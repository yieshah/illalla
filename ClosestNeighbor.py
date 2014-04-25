#! /usr/bin/python2
# vim: set fileencoding=utf-8
"""Use feature vector city matrix to perform one to one venue query."""
import itertools
import numpy as np
import sklearn.neighbors as skn
NN = skn.NearestNeighbors
import arguments
# import CommonMongo as cm
import VenueFeature as vf
import pandas as pd
import matplotlib.colors as mcolor
import matplotlib as mpl
import scipy.stats as stats
import random as rd
from collections import namedtuple
LOOP = namedtuple('Loop', 'path dst size')

FEATURES = ['likes', 'users', 'checkins', 'publicness', 'density',
            'category', 'art', 'education', 'food', 'night', 'recreation',
            'shop', 'professional', 'residence', 'transport', 'focus',
            'photogenicity', 'weekend']
for i in range(6, 15):
    FEATURES[i] += ' surrounding'
FEATURES.extend(['activity at ' + t for t in vf.named_ticks('day', 1, 4)])
FEATURES.append('opening')
RESTRICTED = np.array(range(25))  # pylint: disable=E1101
LCATS = {}


def load_matrix(city):
    """Open `city` matrix or compute it."""
    # import os
    filename = city + '_fv.mat'
    # if not os.path.exists(filename):
    #     vf.describe_city(city)
    mat = vf.sio.loadmat(filename)
    # pylint: disable=E1101
    mat['v'][:, 1:3] = np.log(mat['v'][:, 1:3])
    LCATS[city] = (mat['v'][:, 5]/1e5).astype(int)
    mat['v'][:, 5] = np.zeros((mat['v'].shape[0],))
    non_categorical = range(25)
    del non_categorical[non_categorical.index(5)]
    del non_categorical[non_categorical.index(17)]
    mat['v'][:, non_categorical] = stats.zscore(mat['v'][:, non_categorical])
    return mat


def gather_info(city, knn=2, mat=None):
    """Build KD-tree for each categories of venues in `city` that will return
    `knn` results on subsequent call."""
    matrix = load_matrix(city)
    res = {'features': matrix['v'], 'city': city}
    for cat in range(len(vf.CATS)):
        cat *= 1e5
        mask = res['features'][:, 5] == cat
        venues = matrix['i'][mask]
        if len(venues) > 0:
            idx_subset = np.ix_(mask, RESTRICTED)  # pylint: disable=E1101
            algo = NN(knn) if mat is None else NN(knn, metric='mahalanobis',
                                                  V=mat)
            res[int(cat)] = (algo.fit(res['features'][idx_subset]), venues)
    res['index'] = list(matrix['i'])
    return res


def find_closest(vid, origin, dest):
    """Find the closest venues in `dest` to `vid`, which lies in `origin`."""
    try:
        query = origin['index'].index(vid)
        venue = origin['features'][query, :]
        cat = int(venue[5])
        venue = venue[RESTRICTED]
        dst, closest_idx = [r.ravel() for r in dest[cat][0].kneighbors(venue)]
    except (ValueError, KeyError) as oops:
        print(vid)
        print(oops)
        return None, None, None, None, None
    res_ids = dest[cat][1][closest_idx].ravel()
    answer = [dest['index'].index(rid) for rid in res_ids]
    return query, res_ids, answer, dst, len(dest[cat][1])


def make_loop(vid, origin, dest):
    """Compute the loop originating from `vid` in `origin` and going to
    `dest`."""
    smaller_size = int(1e9)

    def forward(id_):
        """Make one step forward from `id_`."""
        qryc, res_id, ansc, dst, size = find_closest(id_, origin, dest)
        same_cat = LCATS[origin['city']][qryc] == LCATS[dest['city']][ansc[0]]
        return res_id[0], dst[0], size, same_cat

    def backward(id_):
        """Make one step backward from `id_`."""
        qryc, res_id, ansc, dst, size = find_closest(id_, dest, origin)
        same_cat = LCATS[dest['city']][qryc] == LCATS[origin['city']][ansc[0]]
        return res_id[0], dst[0], size, same_cat

    go_forward = True
    loop_closed = False
    loop = LOOP([vid], [0], 0)
    matched_cat = 0
    while not loop_closed:
        vid, dst, size, same_cat = (forward if go_forward else backward)(vid)
        matched_cat += int(same_cat)
        loop_closed = vid in loop.path
        loop.path.append(vid)
        loop.dst.append(dst)
        smaller_size = min(smaller_size, size)
        go_forward = not go_forward
    return loop._replace(size=smaller_size), matched_cat


def interpret(query, answer, feature_order=None):
    """Return a list of criteria explaining distance between `query`
    and `answer`, along with their value for `answer`. If no `feature_order`
    is provided, one is computed to sort features by the proportion they
    contribute to the total distance."""
    query = query[RESTRICTED]
    answer = answer[RESTRICTED]
    diff = (query - answer) * (query - answer)
    # pylint: disable=E1101
    if feature_order is None:
        feature_order = np.argsort(diff)
    percentage = 100*diff/np.sum(diff)
    colormap = mpl.cm.ScalarMappable(mcolor.Normalize(0, 15), 'copper_r')
    get_color = lambda v: mcolor.rgb2hex(colormap.to_rgba(v))
    sendf = lambda x, p: ('{:.'+str(p)+'f}').format(float(x))
    query_info = [{'val': sendf(query[f], 5),
                   'feature': FEATURES[RESTRICTED[f]]}
                  for f in feature_order]
    answer_info = [{'answer': sendf(answer[f], 5),
                    'percentage': sendf(percentage[f], 4),
                    'color': get_color(float(percentage[f]))}
                   for f in feature_order]
    return query_info, answer_info, feature_order


def loop_over_city(origin, dest):
    """Make some loops in all categories."""
    rd.seed(SEED)
    res = {}
    output = []
    matched_cat = []
    nb_venues = []
    for idx, cat in enumerate(vf.CATS):
        res[idx] = ([], [])
        mask = origin['features'][:, 5] == idx*1e5
        venues = list(itertools.compress(origin['index'], mask))
        chosen = rd.sample(venues, len(venues)/7)
        output.append('{} {} venues'.format(len(chosen), cat))
        for venue in chosen:
            loop, matched = make_loop(venue, origin, dest)
            matched_cat.append(matched)
            nb_venues.append(len(loop.path) - 1)
            # NOTE: Actually, loop.size == len(venues)
            ratio = 1.0*(len(loop.dst) - 3)/(2*loop.size + 1 - 3)
            average = np.mean(loop.dst[1:])  # pylint: disable=E1101
            res[idx][0].append(ratio)
            res[idx][1].append(average)
            output.append('{}:\t{}\t{:.5f}\t{:.5f}'.format(venue,
                                                           len(loop.path)-3,
                                                           ratio, average))
    return res, 100.0*sum(matched_cat)/sum(nb_venues), output

SEED = 1234
if __name__ == '__main__':
    # pylint: disable=C0103
    args = arguments.two_cities().parse_args()
    # db, client = cm.connect_to_db('foursquare', args.host, args.port)
    import scipy.io as sio
    learned = sio.loadmat('allthree_A.mat')['A']
    # pylint: disable=E1101
    learned = np.insert(learned, 5, values=0, axis=1)
    learned = np.insert(learned, 5, values=0, axis=0)
    learned[5, 5] = 1.0
    extract = lambda r, i: np.array([one for cats_r in r.itervalues()
                                     for one in cats_r[i]])
    for seed in range(75, 82):
        SEED = seed
        np.random.seed(SEED)
        random_diag = np.diag((22*np.random.random((1, 25))+0.5).ravel())
        mats = [None, random_diag, learned]
        three = []
        for idx, mat in enumerate(mats):
            left = gather_info(args.origin, knn=1, mat=mat)
            right = gather_info(args.dest, knn=1, mat=mat)
            numres, match, txtres = loop_over_city(left, right)
            three.append(numres)
            print(idx, match)
            # outfile = '{}_{}_{}.res'.format(args.origin, args.dest, idx)
            # with open(outfile, 'w') as f:
            #     f.write('\n'.join(txtres))
        rnd = extract(three[0], 0)-extract(three[1], 0)
        itml = extract(three[0], 0)-extract(three[2], 0)
        print(2000*np.sum(itml[np.argsort(itml)[1:]]) -
              2000*np.sum(rnd[np.argsort(rnd)[1:]]))
    # for venue in rd.sample(left['index'], 5):
    #     print(make_loop(venue, left, right))
    # mat = np.eye(matrix['v'].shape[1]) if mat is None else mat

    def explain(query, answer):
        """Explains distance between `query` and `answer` as a data frame."""
        columns = 'feature query percentage answer'.split()
        f, q, p, a = vf.u.xzip(interpret(query, answer), columns)
        return pd.DataFrame(data={'feature': f, 'query': q,
                                  'percentage': p, 'answer': a},
                            columns=columns)
