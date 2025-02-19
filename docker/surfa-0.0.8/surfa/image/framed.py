import os
import numpy as np

from surfa.core.framed import FramedArray
from surfa.core.array import pad_vector_length
from surfa.core.array import check_array
from surfa.transform.geometry import ImageGeometry
from surfa.transform.geometry import cast_image_geometry
from surfa.transform.geometry import image_geometry_equal
from surfa.transform import orientation as otn
from surfa.transform.affine import cast_affine
from surfa.image.slicing import sane_slicing
from surfa.image.slicing import slicing_parameters
from surfa.image.interp import interpolate


class FramedImage(FramedArray):

    def __init__(self, basedim, data, geometry=None, **kwargs):
        """
        Abstract class defining an ND image array with data frames and associated geometry (i.e. data
        elements have a mapable relationship to a world-space coordinate system). This base class includes
        generic support for 3D and 2D FramedArray classes, which are later defined by Volume and Slice classes.

        Parameters
        ----------
        basedim : int
            Array to pad.
        data : array_like
            Internal data array.
        geometry : ImageGeometry
            Image geometry mapping the image data to world coordinates.
        metadata : dict
            Dictionary containing arbitrary array metadata.
        **kwargs
            Extra arguments provided to the FramedArray superclass.
        """
        super().__init__(basedim, data, **kwargs)
        self.geom = geometry

    def new(self, data, geometry=None):
        """
        Return a new instance of the array with updated data. Metadata and geometry is
        preserved unless specified.
        """
        geometry = geometry if geometry is not None else self.geom
        return self.__class__(data=data, geometry=geometry, metadata=self.metadata)

    @property
    def geom(self):
        """
        ImageGeometry object that positions image coordinates in 3D world space.
        """
        return self._geometry

    @geom.setter
    def geom(self, geometry):
        if geometry is None:
            geometry = ImageGeometry(shape=self.baseshape)
        else:
            geometry = cast_image_geometry(geometry).reshape(self.baseshape, copy=True)
        setattr(self, '_geometry', geometry)

    def __geometry__(self):
        """
        By setting this private function, the object can be cast to ImageGeometry.
        """
        return self.geom

    def _shape_changed(self):
        """
        Reshape geometry when the underlying shape changes.
        """
        self._geometry = self._geometry.reshape(self.baseshape)

    def smooth(self, sigma):
        """
        Smooth with Gaussian filter.

        Parameters
        ----------
        sigma : sigmascalar or sequence of scalars
            Standard deviation for Gaussian kernel.

        Returns
        -------
        FramedImage
            Smoothed image.
        """
        if np.isscalar(sigma):
            sigma = (*np.repeat(sigma, self.basdim), 0)
        else:
            sigma = np.asarray(sigma, dtype='float')
            check_array(sigma, ndim=1, shape=[[self.basedim], [self.basedim + 1]], name='sigma')
            sigma = pad_vector_length(sigma, self.basedim + 1, 0, copy=False)
        from scipy.ndimage import gaussian_filter
        return self.new(gaussian_filter(self.framed_data, sigma))

    def __getitem__(self, index_expression):
        """
        Use crop indexing similar to numpy arrays.
        """
        return self._crop(index_expression)

    def _crop(self, index_expression):
        """
        Crop the image array with a given index expression, similar to numpy
        indexing. This cropping takes into account the change in underlying image
        geometry. Certain numpy-style indexing expressions are not allowed, namely
        axis flipping (e.g. `array[::-1]`). To flip an axis, use the `reorient`
        function.

        Parameters
        ----------
        index_expression : tuple
            Numpy-style index expression.

        Returns
        -------
        FramedImage or np.ndarray
            Cropped image with updated geometry or np.ndarray if cropped result
            no longer has valid image dimensionality.
        """

        # check whether the index is valid for images, if not just return the cropped
        # data directly as a numpy ndarray
        try:
            sane_expression = sane_slicing(self.shape, index_expression)[:self.basedim]
        except IndexError:
            return self.data[index_expression]

        # extract the starting coordinate of the cropping
        start, step = slicing_parameters(sane_expression)
        start = pad_vector_length(start, 3, 0)
        step = pad_vector_length(step, 3, 1)

        if np.any(step < 1):
            raise NotImplementedError('axis flipping is not implemented via cropping, use reorient()')

        # use the original index_expression to crop the raw array
        cropped_data = self.data[index_expression]

        # compute target rotation and voxel size
        rotation = self.geom.rotation
        voxsize = self.geom.voxsize * step

        # determine if any axes are to be removed (e.g. in 3D to 2D cropping cases)
        cut_axes = [isinstance(x, int) for x in sane_expression]
        num_axis_cuts = np.count_nonzero(cut_axes)
        if (self.basedim == 2 and num_axis_cuts > 0) or (self.basedim == 3 and num_axis_cuts > 1):
            # if the array will have axes removed making it less than 2D, let's just
            # return the cropped ndarray directly, since the result is no longer an
            # image and geometry information will be invalid. In theory, a 1D array
            # could represent 3D image data along some vector, but let's not get into
            # that crazy territory
            return cropped_data
        elif num_axis_cuts == 1:
            # if we're just cutting one dimension of a 3D image, let's convert to a 2D
            # framed image, but we'll need to update the geometry information appropriately
            # to account for the change in voxel orientation
            cropped_basedim = 2
            cut_index = cut_axes.index(True)
            inter_baseshape = np.insert(cropped_data.shape, cut_index, 1)[:self.basedim]
            if cut_index < 2:
                axis_swap = [1, 2, 0] if cut_index == 0 else [0, 2, 1]
                rotation = rotation[:, axis_swap]
                voxsize = voxsize[axis_swap]
        else:
            # if a dimension is not removed, then we don't need to do much except update
            # the geometry shape and world center coordinate
            cropped_basedim = self.basedim
            inter_baseshape = np.asarray(cropped_data.shape[:self.basedim])

        # compute the new geometry
        inter_baseshape = pad_vector_length(inter_baseshape, 3, 1)
        matrix = self.geom.vox2world.matrix.copy()
        matrix[:3, 3] = self.geom.vox2world.transform(start)
        image_center = np.append(inter_baseshape * step / 2, 1)
        world_center = np.matmul(matrix, image_center)[:3]
        geometry = ImageGeometry(
            shape=cropped_data.shape[:cropped_basedim],
            center=world_center,
            rotation=rotation,
            voxsize=voxsize,
        )

        # construct cropped volume (might be Slice or Volume depending on final dimensionality)
        itype = Slice if cropped_basedim == 2 else Volume
        cropped = itype(cropped_data, geometry=geometry, metadata=self.metadata)
        return cropped

    def bbox(self, margin=None):
        """
        Compute the bounding box of the image data greater than zero. If the image
        has more than one frame, the bounding box will be computed across all frames.

        Parameters
        ----------
        margin : int of sequence of int
            Add a margin to the bounding box in units of voxels. The margin will not
            extend beyond the base image shape.

        Returns
        -------
        tuple of slice
            Bounding box as an index expression.
        """
        mask = self.max(frames=True).data > 0
        if not np.any(mask):
            return tuple([slice(0, s) for s in mask.shape])
        from scipy.ndimage import find_objects
        cropping = find_objects(mask)[0]
        if margin is not None:
            margin = np.repeat(margin, self.basedim) if np.isscalar(margin) else np.asarray(margin)
            check_array(margin, ndim=1, shape=self.basedim, name='bbox margin')
            if not np.issubdtype(margin.dtype, np.integer):
                raise ValueError('only integers can be used for valid bbox margins')
            start = [max(0, c.start - margin[i]) for i, c in enumerate(cropping)]
            stop  = [min(self.baseshape[i], c.stop + margin[i]) for i, c in enumerate(cropping)]
            step  = [c.step for c in cropping]
            cropping = tuple([slice(*s) for s in zip(start, stop, step)])
        return cropping

    def crop_to_bbox(self, margin=None):
        """
        Crop to the bounding box of image data greater than zero.

        Parameters
        ----------
        margin : int of sequence of int
            Add a margin to the bounding box in units of voxels. The margin will not
            extend beyond the base image shape.

        Returns
        -------
        FramedImage
            Cropped image with updated geometry.
        """
        return self[self.bbox(margin=margin)]

    def resize(self, voxsize, method='linear', copy=True):
        """
        Reslice image to a specified voxel size.

        Parameters
        ----------
        voxsize : scalar or float
            Voxel size in millimeters.
        method : {'linear', 'nearest'}
            Image interpolation method.
        copy : bool
            Return copy of image even if target voxel size is already satisfied.

        Returns
        -------
        FramedImage
            Resized image with updated geometry.
        """
        if self.basedim == 2:
            raise NotImplementedError('resize() is not yet implemented for 2D data, contact andrew if you need this')

        if np.isscalar(voxsize):
            # deal with a scalar voxel size input
            voxsize = np.repeat(voxsize, 3).astype('float')
        else:
            # pad to ensure array has length of 3
            voxsize = np.asarray(voxsize, dtype='float')
            check_array(voxsize, ndim=1, shape=3, name='voxsize')
            voxsize = pad_vector_length(voxsize, 3, 1, copy=False)

        # check if anything needs to be done
        if np.allclose(self.geom.voxsize, voxsize, atol=1e-5, rtol=0):
            return self.copy() if copy else self

        baseshape3D = pad_vector_length(self.baseshape, 3, 1, copy=False)
        target_shape = np.asarray(self.geom.voxsize, dtype='float') * baseshape3D / voxsize
        target_shape = tuple(np.ceil(target_shape).astype(int))

        target_geom = ImageGeometry(
            shape=target_shape,
            voxsize=voxsize,
            rotation=self.geom.rotation,
            center=self.geom.center)
        affine = self.geom.world2vox @ target_geom.vox2world
        interped = interpolate(source=self.framed_data, target_shape=target_shape,
                               method=method, affine=affine.matrix)
        return self.new(interped, target_geom)

    def resample_like(self, target, method='linear', copy=True, fill=0):
        """
        Resample to a specified target image geometry.

        Parameters
        ----------
        target : ImageGeometry
            Target image geometry to resample image data into.
        method : {'linear', 'nearest'}
            Image interpolation method.
        copy : bool
            Return copy of image even if target voxel size is already satisfied.
        fill : scalar
            Fill value for out-of-bounds voxels.

        Returns
        -------
        FramedImage
            Resampled image with updated geometry.
        """
        if self.basedim == 2:
            raise NotImplementedError('resample_like() is not yet implemented for 2D data, contact andrew if you need this')

        # cast to geometries
        source_geom = cast_image_geometry(self)
        target_geom = cast_image_geometry(target)
        if image_geometry_equal(source_geom, target_geom):
            return self.copy() if copy else self

        # compute the voxel-to-voxel affine
        affine = self.geom.world2vox @ target_geom.vox2world

        # this is an optimization to avoid interpolation if it's not needed:
        # commonly, such as when conforming images for preprocessing, images are cropped
        # to fit a given size before inputting them to some model. then, the model spits
        # out some result that must be resampled back into the original image space. however,
        # if image reshaping was the only preprocessing modification (ie. no rotation or resizing),
        # then the result does not need to be interpolated back into the target domain, it just
        # needs to be mapped back to a certain region of the grid. this section checks whether
        # that can be done by first testing if the source and target voxel sizes, rotation, and
        # shear match and if the differences in starting voxel coordinates are near-integers.
        if np.allclose(source_geom.voxsize,  target_geom.voxsize,  atol=1e-5, rtol=0.0) and \
           np.allclose(source_geom.rotation, target_geom.rotation, atol=1e-5, rtol=0.0) and \
           np.allclose(source_geom.shear,    target_geom.shear,    atol=1e-5, rtol=0.0):
            # now check if there is a integer-difference between source and target coordinates
            coord = affine.inv().transform((0, 0, 0))
            coord_rounded = coord.round()
            if np.allclose(coord, coord_rounded, atol=1e-5, rtol=0.0):
                # compute the slicing coordinates defining the matching grid regions
                target_start = coord_rounded.astype(np.int)
                source_start = np.array([0, 0, 0])
                target_stop = target_start + source_geom.shape
                source_stop = source_start + source_geom.shape

                # refine the slicing coordinate to ensure they don't exceed the target domain
                delta = np.clip(-target_start, 0, None)
                target_start += delta
                source_start += delta
                delta = np.clip(target_stop - target_geom.shape, 0, None)
                target_stop -= delta
                source_stop -= delta

                # convert to actual array slicings
                target_slicing = tuple([slice(a, b) for a, b in zip(target_start, target_stop)])
                source_slicing = tuple([slice(a, b) for a, b in zip(source_start, source_stop)])

                # place data into target shape
                target_data = np.full((*target_geom.shape, self.nframes), fill, dtype=self.dtype)
                target_data[target_slicing] = self.framed_data[source_slicing]
                return self.new(target_data, target_geom)

        # otherwise just do the standard interpolation with the computed affine
        interped = interpolate(source=self.framed_data, target_shape=target_geom.shape,
                               method=method, affine=affine.matrix, fill=fill)
        return self.new(interped, target_geom)

    def transform(self, affine=None, disp=None, method='linear', rotation='corner', resample=True, fill=0):
        """
        Apply a transform.

        Parameters
        ----------
        affine : Affine
            Affine (linear) transform to apply.
        disp : FramedImage
            Non-linear transform to apply, in the form of a displacement vector field.
        method : {'linear', 'nearest'}
            Image interpolation method if resample is enabled.
        rotation : {'corner', 'center'}
            Apply affine with rotation axis at the image corner or center.
        resample : bool
            If enabled, voxel data will be interpolated and resampled, and geometry will be set
            the target. If disabled, voxel data will not be modified, and only the geometry will
            be updated (this is not possible if a displacement field is provided).
        fill : scalar
            Fill value for out-of-bounds voxels.

        Returns
        -------
        FramedImage
            Transformed image.
        """
        if self.basedim == 2:
            raise NotImplementedError('transform() is not yet implemented for 2D data, contact andrew if you need this')

        if not resample and disp is not None:
            raise ValueError('resampling must be enabled if transforming image with displacement field')

        # if not resampling, just change the image vox2world matrix and return
        if not resample and affine is not None:
            affine = cast_affine(affine)
            if affine.source is None and affine.target is None or affine.space is None:
                raise ValueError('affine must contain source, target, and coordinate space info to transform image header')
            transformed = self.copy()
            transformed.geom.vox2world = affine.convert(space='world', source=self) @ transformed.geom.vox2world
            return transformed

        # sanity check and preprocess the affine if resampling
        matrix = None
        if affine is not None:
            affine = cast_affine(affine)
            target_geom = self.geom
            # TODO it should be assumed that the default affine space is 'voxel' when source and target are set
            if affine.space is not None:
                if affine.source is not None and affine.target is not None:
                    affine = affine.convert(space='voxel', source=self)
                    target_geom = affine.target
                elif affine.space != 'voxel':
                    raise ValueError("affine must contain source and target info if coordinate space is not 'voxel'")
            # make sure the matrix is actually inverted since we want a target to source voxel mapping for resampling
            matrix = affine.inv().matrix

        # get displacement data
        disp_data = disp.data if disp is not None else None

        # do the interpolation
        interped = interpolate(source=self.framed_data, target_shape=target_geom.shape, method=method,
                               affine=matrix, disp=disp_data,  rotation=rotation, fill=fill)
        return self.new(interped, target_geom)

    def reorient(self, orientation, copy=True):
        """
        Realigns image data and world matrix to conform to a specific slice orientation.

        Parameters
        ----------
        orientation : str
            Case-insensitive orientation string.
        copy : bool
            Return copy of image even if target orientation is already satisfied.

        Returns
        -------
        FramedImage
            Reoriented image.
        """
        if self.basedim == 2:
            raise NotImplementedError('reorient() is not yet implemented for 2D data, contact andrew if you need this')

        trg_orientation = orientation.upper()
        src_orientation = otn.rotation_matrix_to_orientation(self.geom.vox2world.matrix)
        if trg_orientation == src_orientation.upper():
            return self.copy() if copy else self

        # extract world axes
        get_world_axes = lambda aff: np.argmax(np.absolute(np.linalg.inv(aff)), axis=0)
        trg_matrix = otn.orientation_to_rotation_matrix(trg_orientation)
        src_matrix = otn.orientation_to_rotation_matrix(src_orientation)
        world_axes_trg = get_world_axes(trg_matrix[:self.basedim, :self.basedim])
        world_axes_src = get_world_axes(src_matrix[:self.basedim, :self.basedim])

        voxsize = np.asarray(self.geom.voxsize)
        voxsize = voxsize[world_axes_src][world_axes_trg]

        # initialize new
        data = self.data.copy()
        affine = self.geom.vox2world.matrix.copy()

        # align axes
        affine[:, world_axes_trg] = affine[:, world_axes_src]
        for i in range(self.basedim):
            if world_axes_src[i] != world_axes_trg[i]:
                data = np.swapaxes(data, world_axes_src[i], world_axes_trg[i])
                swapped_axis_idx = np.where(world_axes_src == world_axes_trg[i])
                world_axes_src[swapped_axis_idx], world_axes_src[i] = world_axes_src[i], world_axes_src[swapped_axis_idx]

        # align directions
        dot_products = np.sum(affine[:3, :3] * trg_matrix[:3, :3], axis=0)
        for i in range(self.basedim):
            if dot_products[i] < 0:
                data = np.flip(data, axis=i)
                affine[:, i] = - affine[:, i]
                affine[:3, 3] = affine[:3, 3] - affine[:3, i] * (data.shape[i] - 1)

        # update geometry
        target_geom = ImageGeometry(
            shape=data.shape[:3],
            vox2world=affine,
            voxsize=voxsize)
        return self.new(data, target_geom)

    def reshape(self, shape, copy=True):
        """
        Returns a volume fit to a given shape. Image will be centered in the conformed volume.

        Parameters
        ----------
        shape : tuple of int
            Target shape.
        copy : bool
            Return copy of image even if target shape is already satisfied.

        Returns
        -------
        FramedImage
            Reshaped image.
        """
        if self.basedim == 2:
            raise NotImplementedError('reshape() is not yet implemented for 2D data, contact andrew if you need this')
        if self.nframes > 1:
            # TODO
            raise NotImplementedError

        if np.array_equal(self.baseshape, shape):
            return self.copy() if copy else self

        delta = (np.array(shape) - np.array(self.baseshape)) / 2
        low = np.floor(delta).astype(int)
        high = np.ceil(delta).astype(int)

        c_low = np.clip(low, 0, None)
        c_high = np.clip(high, 0, None)
        conformed_data = np.pad(self.data.squeeze(), list(zip(c_low, c_high)), mode='constant')

        # note: low and high are intentionally swapped here
        c_low = np.clip(-high, 0, None)
        c_high = conformed_data.shape[:3] - np.clip(-low, 0, None)
        cropping = tuple([slice(a, b) for a, b in zip(c_low, c_high)])
        conformed_data = conformed_data[cropping]

        # compute new affine if one exists
        matrix = np.eye(4)
        matrix[:3, :3] = self.geom.vox2world.matrix[:3, :3]
        p0crs = np.clip(-high, 0, None) - np.clip(low, 0, None)
        p0 = self.geom.vox2world(p0crs)
        matrix[:3, 3] = p0
        pcrs = np.append(np.array(conformed_data.shape[:3]) / 2, 1)
        cras = np.matmul(matrix, pcrs)[:3]
        matrix[:3, 3] = 0
        matrix[:3, 3] = cras - np.matmul(matrix, pcrs)[:3]

        # update geometry
        target_geom = ImageGeometry(
            shape=conformed_data.shape[:3],
            vox2world=matrix,
            voxsize=self.geom.voxsize)
        return self.new(conformed_data, target_geom)

    def conform(self, shape=None, voxsize=1.0, orientation='LIA', method='linear', dtype=None, copy=True):
        """
        Conforms image to a specific shape, type, resolution, and orientation.

        Parameters
        ----------
        shape : tuple of int
            Target shape.
        voxsize : scalar or float
            Voxel size in millimeters.
        orientation : str
            Case-insensitive orientation string.
        method : {'linear', 'nearest'}
            Image interpolation method if resample is enabled.
        dtype : np.dtype
            Target datatype.
        copy : bool
            Return copy of image even if requirements are already satisfied.

        Returns
        -------
        FramedImage
            Conformed image.
        """
        conformed = self.reorient(orientation, copy=False)
        conformed = conformed.resize(voxsize, method=method, copy=False)
        if shape is not None:
            conformed = conformed.reshape(shape, copy=False)
        if dtype is not None:
            conformed = conformed.astype(dtype, copy=False)
        return self.copy() if (copy and conformed is self) else conformed


class Slice(FramedImage):

    def __init__(self, data, **kwargs):
        super().__init__(basedim=2, data=data, **kwargs)


class Volume(FramedImage):

    def __init__(self, data, **kwargs):
        super().__init__(basedim=3, data=data, **kwargs)


def cast_image(obj, allow_none=True, copy=False):
    """
    Cast object to `FramedImage` type.

    Parameters
    ----------
    obj : any
        Object to cast.
    allow_none : bool
        Allow for `None` to be successfully passed and returned by cast.
    copy : bool
        Return copy if object is already the correct type.

    Returns
    -------
    FramedImage or None
        Casted image.
    """
    if obj is None and allow_none:
        return obj

    if isinstance(obj, FramedImage):
        return obj.copy() if copy else obj

    if getattr(obj, '__array__', None) is not None:
        return Volume(np.array(obj))

    # as a final test, check if the input is possibly a nibabel image
    # we don't want nibabel to be required though, so ignore import errors
    try:
        import nibabel as nib
        if isinstance(obj, nib.spatialimages.SpatialImage):
            data = obj.get_data().copy()
            geometry = ImageGeometry(data.shape[:3], vox2world=obj.affine)
            return Volume(data, geometry=geometry)
    except ImportError:
        pass

    raise ValueError('cannot convert type %s to image' % type(obj).__name__)
