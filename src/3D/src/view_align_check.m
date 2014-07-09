% a file to load in some of the rendered views and to plot them all
% together to check that they all align
cd ~/projects/shape_sharing/src/3D/src
clear
addpath plotting/
addpath src
addpath transformations/
run ../define_params_3d.m

%% setting up the paths
num = 1;
model = params.model_filelist{num};

%% loading in the views and plotting
num_views = 42;
max_depth = 3;
depths = cell(1, num_views);

for ii = 1:num_views
    % loading the depth
    depth_name = sprintf(paths.basis_models.rendered, model, ii);
    load(depth_name, 'depth');
    
    % plotting depth image
    subplot(6, 7, ii);
    render_depth(depth, max_depth)
    
    depths{ii} = depth;
end
colormap(hot)

%% projecting each depth image into 3d and 3d plotting...
%intrinsics = 
clf
cols = 'rgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcymrgbkcym';
all_xyz_trans = cell(1, 42);

for ii = 1:42
    
    % extracting the xyz points
    this_depth = depths{ii};
    this_xyz = reproject_depth(this_depth, params.half_intrinsics, max_depth);
    this_xyz(:, 2) = -this_xyz(:, 2);
    this_xyz(:, 3) = -this_xyz(:, 3);
    
    
    % extracting the rotation matrix
    rot_name = sprintf('/Users/Michael/projects/shape_sharing/data/3D/basis_models/halo/mat_%d.csv', ii);
    T = csvread(rot_name);
    
    % applying the suitable transformation to get back into canonical view
    this_xyz_trans = apply_transformation_3d(this_xyz, (T));
    all_xyz_trans{ii} = this_xyz_trans;
    
    % adding to the plot in a different colour
    plot3d(this_xyz_trans, cols(ii));
    hold on
    
end

hold off

%% now loading in the voxel grid for this modelclf
clf
voxel_filename = sprintf('/Users/Michael/projects/shape_sharing/data/3D/basis_models/voxelised/%s.mat', model);
vox_struct = load(voxel_filename);
V = vox_struct.vol;
V(V<30) = 0;
V = permute(V, [2, 1, 3]);
R = [-0.5, 0.5];
vol3d('CData', V, 'XData', R, 'YData', R, 'ZData', R)
axis image

hold on
for ii = 1:5:42
    plot3d(all_xyz_trans{ii}, cols(ii));
end
hold off

view(10, -40)

%% alternate viewing system, with proper transformation
[inds] = find(V);
[i, j, k] = ind2sub(size(V), inds);
trans_vox = apply_transformation_3d([i,j,k], params.voxelisation.T_vox);
plot3(trans_vox(:, 1), trans_vox(:, 2), trans_vox(:, 3), '.', 'markersize', 10)

hold on
for ii = 1:5:42
    plot3d(all_xyz_trans{ii}, cols(ii));
end
hold off

view(10, -40)

