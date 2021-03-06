#! /usr/bin/python2
# vim: set fileencoding=utf-8
"""Plot dataset in (reduced) dimension 2 or 3."""
import sys
try:
    # old version of matplotlib on some computers
    del sys.path[sys.path.index('/usr/lib/pymodules/python2.7')]
except ValueError:
    pass
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
import prettyplotlib as ppl
import matplotlib as mpl
from sklearn import manifold, decomposition  # , datasets
import calc_tsne
import scipy.io as sio


def plot_embedding(figure, index, method, run_time, data, classes, dimension):
    """Scatter subplot `data` with colors corresponding to `classes` on
    `figure` at position `index` in `dimension`D. Title is made of `method`
    and `run_time`."""
    common = dict(c=classes, cmap=mpl.cm.Spectral, alpha=0.8, s=45)
    if dimension == 2:
        axe = figure.add_subplot(1, 1, 1 + index)
        ppl.scatter(data[:, 0], data[:, 1], **common)
    elif dimension == 3:
        axe = figure.add_subplot(5, 3, 1 + index, projection="3d")
        ppl.scatter(data[:, 0], data[:, 1], data[:, 2], **common)
    else:
        raise ValueError(dimension)
    plt.title("{} ({:.2g} sec)".format(method, run_time))
    axe.xaxis.set_major_formatter(mpl.ticker.NullFormatter())
    axe.yaxis.set_major_formatter(mpl.ticker.NullFormatter())
    if dimension == 3:
        axe.zaxis.set_major_formatter(mpl.ticker.NullFormatter())
    plt.axis('tight')


def choose_decomposition_method(method, n_components):
    """Return the decomposition corresponding to `method`."""
    if method == 'PCA':
        return decomposition.PCA(n_components)
    elif method == 'Randomized PCA':
        return decomposition.RandomizedPCA(n_components)
    elif method == 'Kernel PCA':
        return decomposition.KernelPCA(n_components, kernel='rbf')
    elif method == 'Sparse PCA':
        return decomposition.SparsePCA(n_components, n_jobs=1)
    elif method == 'SVD':
        return decomposition.TruncatedSVD(n_components)
    elif method == 'Factor Analysis':
        return decomposition.FactorAnalysis(n_components)
    elif method == 'ICA':
        return decomposition.FastICA(n_components)
    raise ValueError('{} is not a known method'.format(method))


def choose_manifold_method(method, n_components, n_neighbors):
    """Return the manifold corresponding to `method`."""
    method = method.lower()
    if method in ['standard', 'ltsa', 'hessian', 'modified']:
        # solver = 'auto' if method != 'standard' else 'dense'
        return manifold.LocallyLinearEmbedding(n_neighbors, n_components,
                                               eigen_solver='dense',
                                               method=method)
    elif method == 'isomap':
        return manifold.Isomap(n_neighbors, n_components)
    elif method == 'mds':
        return manifold.MDS(n_components, max_iter=200, n_init=1)
    elif method == 'spectral':
        return manifold.SpectralEmbedding(n_components=n_components,
                                          n_neighbors=n_neighbors)
    elif method == 't-sne':
        return calc_tsne.tSNE(n_components, perplexity=25, theta=0.3)
    raise ValueError('{} is not a known method'.format(method))


def compute_embedding(high, method, n_components=2, n_neighbors=None):
    """Reduce dimension of `high` to `n_components` using `method`
    (parametrized by `n_neighbors`)"""
    n_neighbors = n_neighbors or (n_components * (n_components + 3) / 2) + 4
    try:
        projector = choose_manifold_method(method, n_components, n_neighbors)
    except ValueError:
        projector = choose_decomposition_method(method, n_components)
    start = time()
    lower = projector.fit_transform(high)
    return lower, time() - start


def join_cities(cities):
    """Concatenate matrix for all `cities` but keep track from which city each
    point come from."""
    features = None
    for idx, city in enumerate(cities):
        mat = load_matrix(city)['v']
        coming_from = idx*np.ones((1, mat.shape[0])).ravel()
        if features is not None:
            features = np.vstack([features, mat])
            origin = np.hstack([origin, coming_from]).ravel()
        else:
            features = mat
            origin = coming_from
    return features, origin


def split_cities(cities, reduced, origin, features):
    """Save a 2d representation (given by `reduced`) from each city of
    `cities`."""
    for idx, city in enumerate(cities):
        autochthons = origin == idx
        original = sio.loadmat(city+'_fv')
        coords = reduced[autochthons, :]
        cats = features[autochthons, 5] * 8e5
        newv = np.hstack([coords, coords, cats.reshape((coords.shape[0], 1))])
        sio.savemat(city+'_tsne', {'i': original['i'],
                                   'c': original['c'],
                                   'stat': original['stat'],
                                   'v': newv})

if __name__ == '__main__':
    from timeit import default_timer as time
    from ClosestNeighbor import load_matrix
    import numpy as np
    # pylint: disable=C0103
    city = sys.argv[1].strip().lower()
    nb_dim = 2 if len(sys.argv) <= 2 else int(sys.argv[2])
    features = None
    origin = None
    cities = ['stockholm', 'prague', 'paris', 'barcelona', 'rome', 'berlin',
              'london', 'helsinki', 'amsterdam', 'moscow']
    cities = ['amsterdam', 'atlanta', 'barcelona', 'berlin', 'chicago',
              'helsinki', 'houston', 'indianapolis', 'london', 'losangeles',
              'moscow', 'newyork', 'paris', 'prague', 'rome', 'sanfrancisco',
              'seattle', 'stlouis', 'stockholm', 'washington']
    cities = ['paris', 'barcelona', 'rome', 'berlin', 'barcelona',
              'sanfrancisco', 'washington', 'newyork']

    # cities = ['helsinki']
    if len(cities) > 1:
        features, origin = join_cities(cities)
    else:
        features = load_matrix(city)['v']
        origin = features.shape[0] * [0, ]
    # sio.savemat('tmp', {'A': features}, do_compression=True)
    # sys.exit()
    features[:, 5] = features[:, 5] / 8e5
    # to_keep = set(range(6, 15))
    # to_keep = set(range(18, 24)+range(25, 31))
    # to_keep = set(range(0, 5))
    cats = (8*features[:, 5]).astype(int)
    features[:, 5] = 0
    # to_delete = set(range(features.shape[1])).difference(to_keep)
    # features = np.delete(features, list(to_delete), axis=1)
    # print(features.shape)
    # features[:, 5] *= 0.0
    # print(np.sum(features[:, 5]))
    Axes3D
    # n_points = 300
    # X, color = datasets.samples_generator.make_s_curve(n_points,
    # features, cats = datasets.samples_generator.make_swiss_roll(n_points,
    #                                                             noise=0.1,
    #                                                           random_state=0)
    fig = plt.figure(figsize=(25, 18))
    # title = "{} venues of {} projected to {} dimensions"
    # title = title.format(features.shape[0], city.title(), nb_dim)
    # print(title)
    # plt.suptitle(title, fontsize=14)
    # ax = fig.add_subplot(241, projection='3d')
    # plt.scatter(X[:, 0], X[:, 1], X[:, 2], c=color, cmap=mpl.cm.Spectral)

    methods = ['Standard', 'LTSA', 'Hessian', 'Modified', 'Isomap', 'MDS',
               'Spectral', 't-SNE', 'PCA', 'Randomized PCA', 'Kernel PCA',
               'Sparse PCA', 'SVD', 'Factor Analysis', 'ICA']
    methods = ['t-SNE']

    # for i, method in enumerate(methods):
    #     reduced, how_long = compute_embedding(features, method, nb_dim)
    #     sio.savemat('tsne_'+city, {'cl': cats, 'data': reduced})
    #     plot_embedding(fig, i, method, how_long, reduced, cats, nb_dim)
    #     print("{}: {:.3f} sec".format(method, how_long))
    # outfile = '{}_DR_{}.png'.format(city, nb_dim)
    # plt.savefig(outfile, frameon=False, bbox_inches='tight',
    #             pad_inches=0.05)
    reduced, how_long = compute_embedding(features, 't-SNE', 2)
    split_cities(cities, reduced, origin, features)
    # city_name = np.array(map(lambda x: cities[int(x)], origin))
    # to_export = np.hstack([reduced, cats.reshape((reduced.shape[0], 1)),
    #                        city_name.reshape((reduced.shape[0], 1))])
    # np.savetxt('allCities.tsv', to_export, comments='', delimiter='\t', fmt='%s',
    #            header='posx posy cat city'.replace(' ', '\t'))
