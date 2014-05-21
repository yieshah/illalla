#! /usr/bin/python2
# vim: set fileencoding=utf-8
"""Match polygonal regions between cities
Input:
    name of two cities
    a list of coordinates that make up a polygon in one city
Output:
    a list of coordinates that make up a polygon in the other city
"""
import cities
import ClosestNeighbor as cn
# import explore as xp
import numpy as np
import utils as u
import itertools as i
import shapely.geometry as geo
# pylint: disable=E1101
# pylint: disable=W0621


def profile(func):
    return func


@profile
def load_surroundings(city):
    """Load projected coordinates and extra field of all venues, checkins and
    photos within `city`, as well as returning city geographical bounds."""
    import persistent as p
    surroundings = [p.load_var('{}_s{}s.my'.format(city, kind))
                    for kind in ['venue', 'checkin', 'photo']]
    venues_pos = np.vstack(surroundings[0].loc)
    city_extent = list(np.min(venues_pos, 0)) + list(np.max(venues_pos, 0))
    return surroundings, city_extent


@profile
def polygon_to_local(city, geojson):
    """Convert a `geojson` geometry to a local bounding box in `city`, and
    return its center, radius and a predicate indicating membership."""
    assert geojson['type'] == 'Polygon'
    coords = np.fliplr(np.array(geojson['coordinates'][0]))
    projected = geo.Polygon(cities.GEO_TO_2D[city](coords))
    minx, miny, maxx, maxy = projected.bounds
    center = list(projected.centroid.coords[0])
    radius = max(maxx - minx, maxy - miny)*0.5
    return center, radius, projected.bounds, projected.contains


@profile
def describe_region(center, radius, belongs_to, surroundings, city_fv,
                    threshold=10):
    """Return the description (X, x, w, ids) of the region defined by
    `center`, `radius` and `belongs_to`, provided that it contains enough
    venues."""
    svenues, scheckins, sphotos = surroundings
    vids, _ = gather_entities(svenues, center, radius, belongs_to,
                              threshold)
    if not vids:
        return None, None, None, None
    vids = filter(city_fv['index'].__contains__, vids)
    if len(vids) < threshold:
        return None, None, None, None
    # _, ctime = gather_entities(scheckins, center, radius, belongs_to)
    # _, ptime = gather_entities(sphotos, center, radius, belongs_to)
    mask = np.where(np.in1d(city_fv['index'], vids))[0]
    assert mask.size == len(vids)
    weights = weighting_venues(city_fv['features'][mask, 1])
    # time_activity = lambda visits: xp.aggregate_visits(visits, 1, 4)[0]
    # activities = np.hstack([xp.to_frequency(time_activity(ctime)),
    #                         xp.to_frequency(time_activity(ptime))])
    activities = np.ones((12, 1))
    return city_fv['features'][mask, :], activities, weights, vids


@profile
def features_support(features):
    """Return a list of intervals representing the support of the probability
    distribution for each dimension."""
    return zip(np.min(features, 0), np.max(features, 0))


@profile
def features_as_density(features, weights, support, bins=10):
    """Turn raw `features` into probability distribution over each dimension,
    with respect to `weights`."""
    @profile
    def get_bins(dim):
        extent = support[dim][1] - support[dim][0]
        size = 1.0/bins
        return [support[dim][0] + j*size*extent for j in xrange(bins+1)]

    return np.vstack([np.histogram(features[:, i], weights=weights,
                                   bins=get_bins(i))[0]
                      for i in range(features.shape[1])])


@profile
def weighting_venues(values):
    """Transform `values` into a list of positive weights that sum up to 1."""
    from sklearn.preprocessing import MinMaxScaler
    scale = MinMaxScaler()
    size = values.size
    scaled = scale.fit_transform(np.power(values, .2).reshape((size, 1)))
    return scaled.ravel()/np.sum(scaled)


@profile
def gather_entities(surrounding, center, radius, belongs_to, threshold=0):
    """Filter points in `surrounding` that belong to the given region."""
    ids, info, locs = surrounding.around(center, radius)
    info = len(ids)*[0, ] if len(info) == 0 else list(info[0])
    if len(ids) < threshold:
        return None, None
    if belongs_to is None:
        return ids, info
    is_inside = lambda t: belongs_to(geo.Point(t[2]))
    res = zip(*(i.ifilter(is_inside, i.izip(ids, info, locs))))
    if len(res) != 3:
        return None, None
    ids[:], info[:], locs[:] = res
    if len(ids) < threshold:
        return None, None
    return ids, info


@profile
def jensen_shannon_divergence(P, Q):
    """Compute JSD(P || Q) as defined in
    https://en.wikipedia.org/wiki/Jensen–Shannon_divergence """
    avg = 0.5*(P + Q)
    avg_entropy = 0.5*(u.compute_entropy(P) + u.compute_entropy(Q))
    return u.compute_entropy(avg) - avg_entropy


@profile
def proba_distance(density1, global1, density2, global2, theta):
    """Compute total distances between all distributions"""
    proba = np.dot(theta, [jensen_shannon_divergence(p, q)
                           for p, q in zip(density1, density2)])
    return proba[0] + np.linalg.norm(global1 - global2)


@profile
def enclose_venues(ids, args):
    """ Get coordinates of all venues and return their bounding box as
    GeoJSON."""
    import CommonMongo as cm
    import json
    venues = cm.connect_to_db('foursquare', args.host, args.port)[0].venue
    positions = [v['loc']['coordinates']
                 for v in venues.find({'_id': {'$in': ids}}, {'loc': 1})]
    bounds = list(np.min(positions, 0)) + list(np.max(positions, 0))
    return json.dumps(geo.mapping(geo.box(*bounds)))


@profile
def brute_search(city_desc, hsize, distance_function):
    """Move a sliding circle over the whole city and keep track of the best
    result."""
    radius = hsize
    city_size, city_support, city_features, city_infos = city_desc
    surroundings, bounds = city_infos
    minx, miny, maxx, maxy = bounds
    nb_x_step = int(2*np.floor(city_size[0]) / hsize + 1)
    nb_y_step = int(2*np.floor(city_size[1]) / hsize + 1)
    best = [1e9, 0, 0, radius]
    res_map = []
    for idx, cx in enumerate(np.linspace(minx+hsize, maxx-hsize, nb_x_step)):
        print('{}/{}'.format(idx, nb_x_step))
        for cy in np.linspace(miny+hsize, maxy-hsize, nb_y_step):
            center = [cx, cy]
            # contains = lambda p: cx - hsize <= p.x <= cx + hsize and \
            #     cy - hsize <= p.y <= cy + hsize
            contains = None
            candidate = describe_region(center, radius, contains,
                                        surroundings, city_features,
                                        threshold)
            features, c_times, weights, c_vids = candidate
            if features is None:
                continue
            # print('found {} candidate venues'.format(len(c_vids)))
            c_density = features_as_density(features, weights, city_support)
            distance = regions_distance(c_density, c_times)
            res_map.append([cx, cy, distance])
            if distance < best[0]:
                best = [distance, c_vids, center, radius]
    return best, res_map

if __name__ == '__main__':
    # pylint: disable=C0103
    import arguments
    args = arguments.two_cities().parse_args()
    origin, dest = args.origin, args.dest
    user_input = {"type": "Polygon",
                  "coordinates": [[[2.35015, 48.85893], [2.35615, 48.85893],
                                   [2.35615, 48.85293], [2.35015, 48.85293],
                                   [2.35015, 48.85893]]]}
    # Load info of the first city
    left = cn.gather_info(args.origin, knn=1)
    left_infos = load_surroundings(origin)
    minx, miny, maxx, maxy = left_infos[1]
    left_city_size = (maxx - minx, maxy - miny)
    left_support = features_support(left['features'])

    # Compute info about the query region
    center, radius, bounds, contains = polygon_to_local(origin, user_input)
    query = describe_region(center, radius, contains, left_infos[0], left)
    features, times, weights, vids = query
    query_num = features_as_density(features, weights, left_support)
    venue_proportion = 1.0*len(vids) / left['features'].shape[0]
    minx, miny, maxx, maxy = bounds
    average_dim = ((maxx - minx)/left_city_size[0] +
                   (maxy - miny)/left_city_size[1])*0.5

    # And use them to define the metric that will be used
    theta = np.ones((1, left['features'].shape[1]))

    @profile
    def regions_distance(r_density, r_global):
        """Return distance of a region from `query_num`."""
        return proba_distance(query_num, times, r_density, r_global, theta)

    # Load info of the target city
    right = cn.gather_info(args.dest, knn=1)
    right_infos = load_surroundings(dest)
    minx, miny, maxx, maxy = right_infos[1]
    right_city_size = (maxx - minx, maxy - miny)
    right_support = features_support(right['features'])

    # given extents, compute treshold and size of candidate
    threshold = 0.7 * venue_proportion * right['features'].shape[0]
    hsize = 600  # TODO function of average_dim and right_city_size
    # city_size, city_support, city_features, surroundings = city_desc
    right_desc = [right_city_size, right_support, right, right_infos]
    res, values = brute_search(right_desc, hsize, regions_distance)
    distance, r_vids, center, radius = res
    print(enclose_venues(r_vids, args))
    print(distance, center)
