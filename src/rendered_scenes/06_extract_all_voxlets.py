'''
Extracts all the shoeboxes from all the training images
'''
import numpy as np
import cPickle as pickle
import sys
import os
from time import time
import scipy.io
import logging
logging.basicConfig(level=logging.DEBUG)

sys.path.append(os.path.expanduser('~/projects/shape_sharing/src/'))
from common import scene, voxlets, features

import paths
import parameters

# features_iso_savepath = paths.RenderedData.voxlets_dictionary_path + 'features_iso.pkl'
# with open(features_iso_savepath, 'rb') as f:
#     features_iso = pickle.load(f)

pca_savepath = paths.RenderedData.voxlets_dictionary_path + 'shoeboxes_pca.pkl'
with open(pca_savepath, 'rb') as f:
    pca = pickle.load(f)

mask_pca_savepath = paths.RenderedData.voxlets_dictionary_path + 'masks_pca.pkl'
with open(mask_pca_savepath, 'rb') as f:
    mask_pca = pickle.load(f)

features_pca_savepath = paths.RenderedData.voxlets_dictionary_path + 'features_pca.pkl'
with open(features_pca_savepath, 'rb') as f:
    features_pca = pickle.load(f)


print "PCA components is shape ", pca.components_.shape
print "Features PCA components is shape ", features_pca.components_.shape

if not os.path.exists(paths.RenderedData.voxlets_data_path):
    os.makedirs(paths.RenderedData.voxlets_data_path)

cobwebengine = features.CobwebEngine(0.01, mask=True)

def decimate_flatten(sbox):
    return sbox.V[::2, ::2, ::2].flatten()


def pca_flatten(sbox):
    """Applied to the GT shoeboxes after extraction"""
    return pca.transform(sbox.V.flatten())


def sample_sbox(sbox):
    return sbox.flatten()[parameters.VoxletTraining.voxlet_samples]


def sbox_flatten(sbox):
    """Applied to the GT shoeboxes after extraction"""
    return sbox.V.flatten()


def process_sequence(sequence):

    logging.info("Processing " + sequence['name'])

    sc = scene.Scene(parameters.RenderedVoxelGrid.mu, voxlets.voxlet_class_to_dict(parameters.Voxlet))
    sc.load_sequence(sequence, frame_nos=0, segment_with_gt=True,
        save_grids=False, load_implicit=parameters.VoxletTraining.use_implicit)
    # sc.santity_render(save_folder='/tmp/')

    # just using reconstructor for sampling the points...
    rec = voxlets.Reconstructer(
        reconstruction_type='kmeans_on_pca', combine_type='modal_vote')
    rec.set_scene(sc)
    rec.sample_points(parameters.VoxletTraining.number_points_from_each_image,
                      parameters.VoxletPrediction.sampling_grid_size,
                      additional_mask=sc.gt_im_label != 0)
    idxs = rec.sampled_idxs

    logging.debug("Extracting shoeboxes and features...")
    t1 = time()
    gt_shoeboxes = [sc.extract_single_voxlet(
        idx, extract_from='gt_tsdf', post_transform=sbox_flatten) for idx in idxs]

    cobwebengine.set_image(sc.im)
    np_cobweb = np.array(cobwebengine.extract_patches(idxs))

    np_sboxes = np.vstack(gt_shoeboxes)

    # Doing the mask trick...
    np_masks = np.isnan(np_sboxes).astype(np.float16)
    np_sboxes[np_masks == 1] = np.nanmax(np_sboxes)

    if parameters.use_binary:
        np_sboxes = (np_sboxes > 0).astype(np.float16)

    # must do the pca now after doing the mask trick
    np_sboxes = pca.transform(np_sboxes)
    np_masks = mask_pca.transform(np_masks)

    '''replace all the nans in the shoeboxes from the image view'''
    logging.debug("...Shoeboxes are shape " + str(np_sboxes.shape))

    print "Took %f s" % (time() - t1)
    t1 = time()

    savepath = paths.RenderedData.voxlets_data_path + \
        sequence['name'] + '.mat'
    logging.debug("Saving to " + savepath)
    D = dict(shoeboxes=np_sboxes, masks=np_masks, cobweb=np_cobweb)
    scipy.io.savemat(savepath, D, do_compression=True)


if parameters.multicore:
    # need to import these *after* pool_helper has been defined
    import multiprocessing
    pool = multiprocessing.Pool(parameters.cores)
    mapper = pool.map
else:
    mapper = map


if __name__ == "__main__":

    tic = time()
    mapper(process_sequence, paths.RenderedData.train_sequence())
    print "In total took %f s" % (time() - tic)
