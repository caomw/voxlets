'''
classes for extracting voxlets from grids, and for reforming grids from
voxlets.
'''

import numpy as np
import cPickle as pickle
import sys
import os
import time

import paths
import parameters
import voxel_data
import random_forest_structured as srf
import features

# parameters
multiproc = False


class VoxletPredictor(object):
    '''
    Class to predict a full ixjxk voxlet given a feature vector
    Wraps a forest plus a PCA representation of the voxlets themselves.
    The computation of the PCA object is not done here as training voxlets are
    compressed with PCA as soon as they are extracted. This means that this
    class only ever sees the compressed versions.

    COULD make it so all the pca is done inside here - i.e. you keep giving it
    full voxlets before then training the model. Unsure. This would require
    saving the full voxlet version, if I were to keep to the same script
    ordering I have now...
    '''
    def __init__(self):
        pass

    def set_pca(self, pca_in):
        self.pca = pca_in

    def train(self, X, Y, subsample_length=-1):
        '''
        Runs the OMA forest code
        Y is expected to be a PCA version of the shoeboxes
        subsample_length is the maximum number of training examples to use.
        When it is -1, then we use all the training examples
        '''
        if X.shape[0] != Y.shape[0]:
            raise Exception("X and Y should have the same number of rows")

        print "Before removing nans"
        self._print_shapes(X, Y)

        X, Y = self._remove_nans(X, Y)

        if subsample_length > 0 and subsample_length < X.shape[0]:
            X, Y = self._subsample(X, Y, subsample_length)

        print "After subsampling and removing nans..."
        self._print_shapes(X, Y)

        print "Training forest"
        forest_params = srf.ForestParams()
        self.forest = srf.Forest(forest_params)
        tic = time.time()
        self.forest.train(X, Y)
        toc = time.time()
        print "Time to train forest is", toc-tic

        # must save the training data in this class, as the forest only saves
        # an index into the training set...
        self.training_Y = Y

    def _medioid(self, data):
        '''
        similar to numpy 'mean', but returns the medioid data item
        '''
        # finding the distance to the mean
        mu = data.mean(axis=0)
        mu_dist = np.sqrt(((data - mu[np.newaxis, ...])**2).sum(axis=1))

        median_item_idx = mu_dist.argmin()
        return data[median_item_idx]

    def predict(self, X):
        '''
        Returns a voxlet prediction for each row in X
        '''
        # each tree predicts which index in the test set to use...
        # rows = test data (X), cols = tree
        index_predictions = self.forest.test(X).astype(int)

        # must extract original test data from the indices

        print index_predictions[0]

        # this is a horrible line and needs changing...
        Y_pred_compressed = [self._medioid(self.training_Y[pred])
                             for pred in index_predictions]
        Y_pred_compressed = np.array(Y_pred_compressed)

        return self.pca.inverse_transform(Y_pred_compressed)

    def save(self, savepath):
        '''
        Saves the model to specified file.
        I'm doing this as a method of the class so I can do the appropriate
        checks, as performed below
        '''
        if not hasattr(self, 'pca'):
            raise Exception(
                "pca attribute not set - this is important for prediction")

        if not hasattr(self, 'forest'):
            raise Exception("Forest not trained it seems")

        with open(savepath, 'wb') as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

    def _remove_nans(self, X, Y):
        '''
        Removes training entries with nans in feature space
        '''
        to_remove = np.any(np.isnan(X), axis=1)
        X = X[~to_remove, :]
        Y = Y[~to_remove, :]
        return X, Y

    def _subsample(self, X, Y, subsample_length):

        rand_exs = np.sort(np.random.choice(
            X.shape[0],
            np.minimum(subsample_length, X.shape[0]),
            replace=False))
        return X.take(rand_exs, 0), Y.take(rand_exs, 0)

    def _print_shapes(self, X, Y):
        print "X has shape ", X.shape
        print "Y has shape ", Y.shape


class Reconstructer(object):
    '''
    does the final prediction
    '''

    def __init__(self, reconstruction_type, combine_type):
        self.reconstruction_type = reconstruction_type
        self.combine_type = combine_type

    def set_model(self, model):
        self.model = model

    def set_test_im(self, test_im):
        self.im = test_im

    def sample_points(self, num_to_sample):
        '''
        sampling points from the test image
        '''
        self.sampled_idxs = self.im.random_sample_from_mask(num_to_sample)

    def _initialise_voxlet(self, index):
        '''
        given a point in an image, creates a new voxlet at an appropriate
        position and rotation in world space
        '''
        assert(index.shape[0] == 2)

        # getting the xyz and normals in world space
        world_xyz = self.im.get_world_xyz()
        world_norms = self.im.get_world_normals()

        # convert to linear idx
        point_idx = index[0] * self.im.mask.shape[1] + index[1]

        # creating the voxlet
        shoebox = voxel_data.ShoeBox(parameters.Voxlet.shape)  # grid size
        shoebox.set_p_from_grid_origin(parameters.Voxlet.centre)  # m
        shoebox.set_voxel_size(parameters.Voxlet.size)  # m
        shoebox.initialise_from_point_and_normal(world_xyz[point_idx],
                                                 world_norms[point_idx],
                                                 np.array([0, 0, 1]))
        return shoebox

    def initialise_output_grid(self, gt_grid=None):
        '''defaulting to initialising from the ground truth grid...'''
        self.accum = voxel_data.UprightAccumulator(gt_grid.V.shape)
        self.accum.set_origin(gt_grid.origin)
        self.accum.set_voxel_size(gt_grid.vox_size)

    def fill_in_output_grid_oma(self):
        '''
        doing the final reconstruction
        '''

        "extract features from test image"
        ce = features.CobwebEngine(t=5, fixed_patch_size=False)
        ce.set_image(self.im)
        np_features = np.array(ce.extract_patches(self.sampled_idxs))

        "classify according to the forest"
        voxlet_predictions = self.model.predict(np_features)
        print "Forest predictons has shape " + str(voxlet_predictions.shape)

        "for each forest prediction, do something sensible"
        for count, (idx, voxlet) in enumerate(
                zip(self.sampled_idxs, voxlet_predictions)):

            # adding the shoebox into the result
            transformed_voxlet = self._initialise_voxlet(idx)
            transformed_voxlet.V = voxlet.reshape(parameters.Voxlet.shape)
            self.accum.add_voxlet(transformed_voxlet)

            print "Added shoebox " + str(count)

        return self.accum

# def pool_helper(index, im, vgrid):

#     world_xyz = im.get_world_xyz()
#     world_norms = im.get_world_normals()

#     # convert to linear idx
#     point_idx = index[0] * im.mask.shape[1] + index[1]

#     shoebox = voxel_data.ShoeBox(parameters.Voxlet.shape)  # grid size
#     shoebox.set_p_from_grid_origin(parameters.Voxlet.centre)  # m
#     shoebox.set_voxel_size(parameters.Voxlet.size)  # m
#     shoebox.initialise_from_point_and_normal(
#         world_xyz[point_idx], world_norms[point_idx], np.array([0, 0, 1]))

#     # convert the indices to world xyz space
#     shoebox.fill_from_grid(vgrid)
#     return shoebox.V.flatten()

# # need to import these *after* the pool helper has been defined
# if multiproc:
#     import multiprocessing
#     import functools
#     pool = multiprocessing.Pool(parameters.cores)


# class VoxletExtractor(object):
#     '''
#     extracts voxlets from a voxel grid and a depth image
#     '''
#     def __init__(self):
#         pass

#     def set_voxel_grid(self, vgrid):
#         self.voxel_grid = vgrid

#     def set_image(self, im):
#         self.im = im

#     def extract_voxlets(self, num_to_extract):
#         self