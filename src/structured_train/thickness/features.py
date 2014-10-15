'''
This is an engine for extracting rotated patches from a depth image.
Each patch is rotated so as to be aligned with the gradient in depth at that point
Patches can be extracted densely or from pre-determined locations
Patches should be able to vary to be constant-size in real-world coordinates
(However, perhaps this should be able to be turned off...)
'''

import numpy as np
import scipy.stats
import scipy.io
import cv2
from numbers import Number

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib as mpl


class CobwebEngine(object):
	'''
	A different type of patch engine, only looking at points in the compass directions
	'''

	def __init__(self, t, fixed_patch_size=False):

		# the stepsize at a depth of 1 m
		self.t = float(t)

		# dimension of side of patch in real world 3D coordinates
		#self.input_patch_hww = input_patch_hww

		# if fixed_patch_size is True:
		#   step is always t in input image pixels
		# else:
		#   step varies linearly with depth. t is the size of step at depth of 1.0 
		self.fixed_patch_size = fixed_patch_size 

	def set_image(self, im):
		self.im = im

	def get_cobweb(self, index):
		'''extracts cobweb for a single index point'''
		row, col = index
		
		start_angle = self.im.angles[row, col]
		start_depth = self.im.depth[row, col]

		if self.fixed_patch_size:
			offset_dist = self.t
		else:
			offset_dist = self.t / start_depth

		# computing all the offsets and angles efficiently
		offsets = offset_dist * np.array([1, 2, 3, 4])
		rad_angles = np.deg2rad(start_angle + np.array(range(0, 360, 45)))

		rows_to_take = (float(row) - np.outer(offsets, np.sin(rad_angles))).astype(int).flatten()
		cols_to_take = (float(col) + np.outer(offsets, np.cos(rad_angles))).astype(int).flatten()

		# defining the cobweb array ahead of time
		cobweb = np.nan * np.zeros((32, )).flatten()

		# working out which indices are within the image bounds
		to_use = np.logical_and.reduce((rows_to_take >= 0, 
										rows_to_take < self.im.depth.shape[0],
										cols_to_take >= 0,
										cols_to_take < self.im.depth.shape[1]))
		rows_to_take = rows_to_take[to_use]
		cols_to_take = cols_to_take[to_use]

		# computing the diff vals and slotting into the correct place in the cobweb feature
		vals = self.im.depth[rows_to_take, cols_to_take] - self.im.depth[row, col]
		cobweb[to_use] = vals
		return np.copy(cobweb.flatten())

	def extract_patches(self, indices):
		return [self.get_cobweb(index) for index in indices]


		#idxs = np.ravel_multi_index((rows_to_take, cols_to_take), dims=self.im.depth.shape, order='C')
		#cobweb = self.im.depth.take(idxs) - self.im.depth[row, col]


class SpiderEngine(object):
	'''
	Engine for computing the spider (compass) features
	'''

	def __init__(self, im):
		'''
		sets the depth image and computes the distance transform
		'''
		dt = DistanceTransforms(im)
		self.distance_transform = dt.get_compass_images()


	def compute_spider_features(self, idxs):
		'''
		computes the spider feature for a given point
		'''
		return self.distance_transform[idxs[0], idxs[1]]


class DistanceTransforms(object):
	'''
	like the spider feature but aligned with dimensions
	'''
	def __init__(self, im=[]):
		self.set_im(im)


	def set_im(self, im):
		self.im = im

		# parameters for rotating and padding
		self.H, self.W = im.depth.shape
		r = 0.5 * np.sqrt(self.H**2 + self.W**2)
		self.pad_top = (r - self.H/2 + 5).astype(int)
		self.pad_left = (r - self.W/2 + 5).astype(int)


	def straight_dist_transform(self, direction, edges, depth):
		'''
		axis aligned distance transform, going from left to the right
		and top to bottom and vv
		'''

		if direction=='e':
			edge_im = edges
			depth_image = depth
		elif direction=='w':
			edge_im = np.fliplr(edges)
			depth_image = np.fliplr(depth)
		elif direction=='s':
			edge_im = edges.T
			depth_image = depth.T
		elif direction=='n':
			edge_im = np.fliplr(edges.T)
			depth_image = np.fliplr(depth.T)

		pixel_count_im = np.nan * np.copy(edge_im).astype(np.float)
		geodesic_im = np.nan * np.copy(edge_im).astype(np.float)

		u = np.arange(-edge_im.shape[1]/2, edge_im.shape[1]/2)

		# loop over each row...
		for row_idx, row in enumerate(edge_im):
			if np.any(row):
				temp_pixel, temp_geo = self._row_dists(row, depth_image[row_idx, :], u)
				pixel_count_im[row_idx, :] = temp_pixel
				geodesic_im[row_idx, :] = temp_geo

		pixel_count_im[np.isnan(depth_image)] = np.nan
		geodesic_im[np.isnan(depth_image)] = np.nan

		out_stack = [pixel_count_im, geodesic_im]

		if direction=='w':
			out_stack = [np.fliplr(im) for im in out_stack]
		elif direction=='s':
			out_stack = [im.T for im in out_stack]
		elif direction=='n':
			out_stack = [np.fliplr(im).T for im in out_stack]

		# convert the pixel count image to a perpendicular distance
		perpendicular_dist = out_stack[0] * depth / self.im.focal_length

		return [perpendicular_dist, out_stack[1]]

	def enws_distance_transform(self, angle):
		'''
		returns the distance transform in each of the four compass directions,
		offset by the specified angle
		'''
		# no need to pre-rotated
		if angle==0:
			return [self.straight_dist_transform(direction, self.im.edges, self.im.depth) 
					for direction in 'enws']
		else:
			temp_edges = self._pad_and_rotate(self.im.edges, angle) > 0.1
			temp_depth = self._pad_and_rotate(self.im.depth, angle)

			temp_results = []
			for direction in 'enws':
				temp = self.straight_dist_transform(direction, temp_edges, temp_depth)
				temp = [self._rotate_unpad(t, -angle) for t in temp]
				temp_results.append(temp)

			return temp_results


	def _pad_and_rotate(self, image_in, angle):
		'''
		pads image by enough to ensure that when it is rotated 
		it doesn't get cut off at all
		'''

		# padding
		pad_amounts = ((self.pad_top, self.pad_top), (self.pad_left, self.pad_left))
		padded = np.pad(image_in, pad_amounts, mode='constant', constant_values=0).astype(float)

		# now doing the rotation
		return scipy.ndimage.interpolation.rotate(padded, angle, reshape=False, order=1)


	def _rotate_unpad(self, image_in, angle):
		'''
		rotates the image and unpads (crops)
		'''
		# rotating
		rotated_im = scipy.ndimage.interpolation.rotate(image_in, angle, reshape=False, order=1)

		# unpadding
		return rotated_im[self.pad_top:(self.pad_top+self.H), 
						  self.pad_left:(self.pad_left+self.W)]


	def _row_dists(self, edges_row, depth_row, u):
		'''
		U is the left-right position on the image of each point
		Really, I should also include the top-bottom position (ie 'v')
		This should allow for the full reprojection I think.
		'''

		dists = u*depth_row
		dist_diffs = np.abs(np.insert(np.diff(dists), 0, 0))

		pixel_count = np.nan
		geo_dist = np.nan

		pixel_count_row = 0 * np.copy(edges_row).astype(float)
		geodesic_row = 0 * np.copy(edges_row).astype(float)

		for col_idx, pix in enumerate(edges_row):
			
			if pix:
				pixel_count = 0
				geo_dist = 0
			else:
				pixel_count += 1
				geo_dist += dist_diffs[col_idx]

			pixel_count_row[col_idx] = pixel_count
			geodesic_row[col_idx] = geo_dist

		return pixel_count_row, geodesic_row


	def get_compass_images(self):
		compass = []
		for angle in [0, 45]:
			compass.extend(list(self.enws_distance_transform(angle)))

		# flatten the compass into one nice HxWx8 array
		T = np.array(compass).reshape((-1, self.H, self.W))
		print T.shape

		return T
		


class PatchPlot(object):
	'''
	Aim of this class is to plot boxes at specified locations, scales and orientations
	on a background image
	'''

	def __init__(self):
		pass

	def set_image(self, image):
		self.im = im
		plt.imshow(im.depth)

	def plot_patch(self, index, angle, width):
		'''plots a single patch'''
		row, col = index
		bottom_left = (col - width/2, row - width/2)
		angle_rad = np.deg2rad(angle)

		# creating patch
		#print bottom_left, width, angle
		p_handle = patches.Rectangle(bottom_left, width, width, color="red", alpha=1.0, edgecolor='r', fill=None)
		transform = mpl.transforms.Affine2D().rotate_around(col, row, angle_rad) + plt.gca().transData
		p_handle.set_transform(transform)

		# adding to current plot
		plt.gca().add_patch(p_handle)

		# plotting line from centre to the edge
		plt.plot([col, col + width * np.cos(angle_rad)], 
				 [row, row + width * np.sin(angle_rad)], 'r-')


	def plot_patches(self, indices, scale_factor):
		'''plots the patches on the image'''
		
		scales = [scale_factor * self.im.depth[index[0], index[1]] for index in indices]
		
		angles = [self.im.angles[index[0], index[1]] for index in indices]

		plt.hold(True)

		for index, angle, scale in zip(indices, angles, scales):
			self.plot_patch(index, angle, scale)

		plt.hold(False)
		plt.show()


# here should probably write some kind of testing routine
# where an image is loaded, rotated patches are extracted and the gradient of the rotated patches
# is shown to be all mostly close to zero

if __name__ == '__main__':

	'''testing the plotting'''

	import images
	import paths

	# loading the render
	im = images.CADRender()
	im.load_from_cad_set(paths.modelnames[30], 30)
	im.compute_edges_and_angles()

	# sampling indices from the image
	indices = np.array(np.nonzero(~np.isnan(im.depth))).transpose()
	samples = np.random.randint(0, indices.shape[0], 20)
	indices = indices[samples, :]

	# plotting patch
	patch_plotter = PatchPlot()
	patch_plotter.set_image(im.depth)
	patch_plotter.plot_patches(indices, scale_factor=10)
