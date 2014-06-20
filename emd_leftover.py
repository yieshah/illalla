# vim: set fileencoding=utf-8
"""Modified version of EMD where only a fraction of the total mass must be
moved from one distribution to the other.
The rational behind is that it allow to remove the effect of outlier points."""
import numpy as np
from scipy.spatial.distance import cdist
import scipy.io as sio
MAX_POINTS = 400


def write_matlab_problem(points1, weights1, points2, weights2, idx,
                         fraction=0.8):
    """Write in a file the variables describing the `idx`th problem to be
    solved"""
    if points1.shape[0] > MAX_POINTS or points2.shape[0] > MAX_POINTS:
        return
    costs = cdist(points1, points2)
    vcost = costs.ravel('F')
    i_w = np.kron(np.ones((1, costs.shape[1])), np.eye(costs.shape[0]))
    j_w = np.kron(np.eye(costs.shape[1]), np.ones((1, costs.shape[0])))
    A = np.vstack([i_w, j_w, -1*np.ones((1, i_w.shape[1]))])
    b = np.vstack([weights1.reshape(weights1.size, 1),
                   weights2.reshape(weights2.size, 1), [[-fraction]]])
    sio.savemat('{}/{}_{}'.format('/tmp/mats', 'lpin', idx),
                {'f': vcost, 'A': A, 'b': b}, do_compression=True)


def collect_matlab_output(nb_input, mlab):
    """Call `mlab` to solve the `nb_input` first problems and return the list
    of EMD cost"""
    mlab.run_func('mlinprog.m', {'nb_input': nb_input})
    costs = []
    for idx in range(nb_input):
        try:
            dst = sio.loadmat('{}/{}_{}'.format('/tmp/mats',
                                                'lpout', idx))['dst']
        except IOError:
            dst = 1e15
        costs.append(float(dst))
    return costs
