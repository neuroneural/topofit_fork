import os
import numpy as np
import gzip

from surfa import Volume
from surfa import Slice
from surfa import Overlay
from surfa import ImageGeometry
from surfa.core import FramedArray
from surfa.core import pad_vector_length
from surfa.image import FramedImage
from surfa.io import fsio
from surfa.io import protocol
from surfa.io.utils import read_int
from surfa.io.utils import write_int
from surfa.io.utils import read_bytes
from surfa.io.utils import write_bytes
from surfa.io.utils import check_file_readability


def load_volume(filename, fmt=None):
    """
    Load an image `Volume` from a 3D array file.

    Parameters
    ----------
    filename : str
        File path to read.
    fmt : str, optional
        Explicit file format. If None (default), the format is extrapolated
        from the file extension.

    Returns
    -------
    Volume
        Loaded volume.
    """
    return load_framed_array(filename=filename, atype=Volume, fmt=fmt)


def load_slice(filename, fmt=None):
    """
    Load an image `Slice` from a 2D array file.

    Parameters
    ----------
    filename : str
        File path to read.
    fmt : str, optional
        Explicit file format. If None (default), the format is extrapolated
        from the file extension.

    Returns
    -------
    Slice
        Loaded slice.
    """
    return load_framed_array(filename=filename, atype=Slice, fmt=fmt)


def load_overlay(filename, fmt=None):
    """
    Load a surface `Overlay` from a 1D array file.

    Parameters
    ----------
    filename : str
        File path to read.
    fmt : str, optional
        Explicit file format. If None (default), the format is extrapolated
        from the file extension.

    Returns
    -------
    Overlay
        Loaded overlay.
    """
    return load_framed_array(filename=filename, atype=Overlay, fmt=fmt)


def load_framed_array(filename, atype, fmt=None):
    """
    Generic loader for `FramedArray` objects.

    Parameters
    ----------
    filename : str
        File path to read.
    atype : class
        Particular FramedArray subclass to read into.
    fmt : str, optional
        Forced file format. If None (default), file format is extrapolated
        from extension.

    Returns
    -------
    FramedArray
        Loaded framed array. 
    """
    check_file_readability(filename)

    if fmt is None:
        iop = protocol.find_protocol_by_extension(array_io_protocols, filename)
        if iop is None:
            if atype is Overlay:
                # some freesurfer overlays do not have file extensions (another bizarre convention),
                # so let's fallback to the 'curv' format here
                iop = FreeSurferCurveIO
            else:
                raise ValueError(f'cannot determine file format from extension for {filename}')
    else:
        iop = protocol.find_protocol_by_name(array_io_protocols, fmt)
        if iop is None:
            raise ValueError(f'unknown file format {fmt}')

    return iop().load(filename, atype)


def save_framed_array(arr, filename, fmt=None):
    """
    Save a `FramedArray` object to file.

    Parameters
    ----------
    arr : FramedArray
        Object to write.
    filename: str
        Destination file path.
    fmt : str
        Forced file format. If None (default), file format is extrapolated
        from extension.
    """
    if fmt is None:
        iop = protocol.find_protocol_by_extension(array_io_protocols, filename)
        if iop is None:
            raise ValueError(f'cannot determine file format from extension for {filename}')
    else:
        iop = protocol.find_protocol_by_name(array_io_protocols, fmt)
        if iop is None:
            raise ValueError(f'unknown file format {fmt}')
        filename = iop.enforce_extension(filename)

    iop().save(arr, filename)


class MGHArrayIO(protocol.IOProtocol):
    """
    Array IO protocol for MGH and compressed MGZ files.
    """

    name = 'mgh'
    extensions = ('.mgz', 'mgh', '.mgh.gz')

    def dtype_from_id(self, id):
        """
        Convert a FreeSurfer datatype ID to a numpy datatype.

        Parameters
        ----------
        id : int
            FreeSurfer datatype ID.

        Returns
        -------
        np.dtype
            Converted numpy datatype.
        """
        mgh_types = {
            0:  '>u1',  # uchar
            1:  '>i4',  # int32
            2:  '>i8',  # int64
            3:  '>f4',  # float
            4:  '>i2',  # short
            6:  '>f4',  # tensor
            10: '>u2',  # ushort
        }
        dtype = mgh_types.get(id)
        if dtype is None:
            raise NotImplementedError(f'unsupported MGH data type ID: {id}')
        return np.dtype(dtype)

    def load(self, filename, atype):
        """
        Read array from an MGH/MGZ file.

        Parameters
        ----------
        filename : str
            File path to read.
        atype : class
            FramedArray subclass to load.

        Returns
        -------
        FramedArray
            Array object loaded from file.
        """

        # check if the file is gzipped
        fopen = gzip.open if filename.lower().endswith('gz') else open
        with fopen(filename, 'rb') as file:

            # skip version tag
            file.read(4)

            # read shape and type info
            shape = read_bytes(file, '>u4', 4)
            dtype_id = read_bytes(file, '>u4')
            dof = read_bytes(file, '>u4')

            # read geometry
            geom_params = {}
            unused_header_space = 254
            valid_geometry = bool(read_bytes(file, '>u2'))

            # ignore geometry if flagged as invalid
            if valid_geometry:
                geom_params = dict(
                    voxsize=read_bytes(file, '>f4', 3),
                    rotation=read_bytes(file, '>f4', 9).reshape((3, 3), order='F'),
                    center=read_bytes(file, '>f4', 3),
                )
                unused_header_space -= 60

            # skip empty header space
            file.read(unused_header_space)

            # read data buffer (MGH files store data in fortran order)
            dtype = self.dtype_from_id(dtype_id)
            data = read_bytes(file, dtype, int(np.prod(shape))).reshape(shape, order='F')

            # init array
            arr = atype(data.squeeze())

            # read scan parameters
            scan_params = {
                'tr': read_bytes(file, dtype='>f4'),
                'fa': read_bytes(file, dtype='>f4'),
                'te': read_bytes(file, dtype='>f4'),
                'ti': read_bytes(file, dtype='>f4'),
            }

            # ignore fov
            fov = read_bytes(file, dtype='>f4')
 
            # update image-specific information
            if isinstance(arr, FramedImage):
                arr.geom.update(**geom_params)
                arr.metadata.update(scan_params)

            # read metadata tags
            while True:
                tag, length = fsio.read_tag(file)
                if tag is None:
                    break

                # command history
                elif tag == fsio.tags.history:
                    history = file.read(length).decode('utf-8').rstrip('\x00')
                    if arr.metadata.get('history'):
                        arr.metadata['history'].append(history)
                    else:
                        arr.metadata['history'] = [history]

                # embedded lookup table
                elif tag == fsio.tags.old_colortable:
                    arr.labels = fsio.read_binary_lookup_table(file)

                # phase encode direction
                elif tag == fsio.tags.pedir:
                    pedir = file.read(length).decode('utf-8').rstrip('\x00')
                    if pedir != 'UNKNOWN':
                        arr.metadata['phase-encode-direction'] = pedir

                # field strength
                elif tag == fsio.tags.fieldstrength:
                    arr.metadata['field-strength'] = read_bytes(file, dtype='>f4')

                # skip everything else
                else:
                    file.read(length)

        return arr

    def save(self, arr, filename):
        """
        Write array to a MGH/MGZ file.

        Parameters
        ----------
        arr : FramedArray
            Array to save.
        filename : str
            Target file path.
        """

        # determine whether to write compressed data
        if filename.lower().endswith('gz'):
            fopen = lambda f: gzip.open(f, 'wb', compresslevel=6)
        else:
            fopen = lambda f: open(f, 'wb')

        with fopen(filename) as file:

            # before we map dtypes to MGZ-supported types, smartly convert int64 to int32
            if arr.dtype == np.int64:
                if arr.max() > np.iinfo(np.int32).max or arr.min() < np.iinfo(np.int32).min:
                    raise ValueError('MGH files only support int32 datatypes, but array cannot be ',
                                     'casted since its values exceed the int32 integer limits')
                arr = arr.astype(np.int32)

            # determine supported dtype to save as (order here is very important)
            type_map = {
                np.uint8: 0,
                np.bool8: 0,
                np.int32: 1,
                np.floating: 3,
                np.int16: 4,
                np.uint16: 10,
            }
            dtype_id = next((i for dt, i in type_map.items() if np.issubdtype(arr.dtype, dt)), None)
            if dtype_id is None:
                raise ValueError(f'writing dtype {arr.dtype.name} to MGH format is not supported')

            # sanity check on the array size
            ndim = arr.data.ndim
            if ndim < 1:
                raise ValueError(f'cannot save scalar value to MGH file format')
            if ndim > 4:
                raise ValueError(f'cannot save array with more than 4 dims to MGH format, but got {ndim}D array')

            # shape must always be a length-4 vector, so let's pad with ones
            shape = np.ones(4)
            shape[:ndim] = arr.data.shape

            # begin writing header
            write_bytes(file, 1, '>u4')  # version
            write_bytes(file, shape, '>u4')  # shape
            write_bytes(file, dtype_id, '>u4')  # MGH data type
            write_bytes(file, 1, '>u4')  # DOF

            # write geometry, if valid
            unused_header_space = 254
            is_image = isinstance(arr, FramedImage)
            write_bytes(file, is_image, '>u2')
            if is_image:
                write_bytes(file, arr.geom.voxsize, '>f4')
                write_bytes(file, np.ravel(arr.geom.rotation, order='F'), '>f4')
                write_bytes(file, arr.geom.center, '>f4')
                unused_header_space -= 60

            # fill empty header space
            file.write(bytearray(unused_header_space))

            # write array data
            write_bytes(file, np.ravel(arr.data, order='F'), self.dtype_from_id(dtype_id))

            # write scan parameters
            write_bytes(file, arr.metadata.get('tr', 0.0), '>f4')
            write_bytes(file, arr.metadata.get('fa', 0.0), '>f4')
            write_bytes(file, arr.metadata.get('te', 0.0), '>f4')
            write_bytes(file, arr.metadata.get('ti', 0.0), '>f4')

            # compute FOV
            volsize = pad_vector_length(arr.baseshape, 3, 1)
            fov = max(arr.geom.voxsize * volsize) if is_image else arr.shape[0]
            write_bytes(file, fov, '>f4')

            # write lookup table tag
            if arr.labels is not None:
                fsio.write_tag(file, fsio.tags.old_colortable)
                fsio.write_binary_lookup_table(file, arr.labels)

            # phase encode direction
            pedir = arr.metadata.get('phase-encode-direction', 'UNKNOWN')
            fsio.write_tag(file, fsio.tags.pedir, len(pedir))
            file.write(pedir.encode('utf-8'))

            # field strength
            fsio.write_tag(file, fsio.tags.fieldstrength, 4)
            write_bytes(file, arr.metadata.get('field-strength', 0.0), '>f4')

            # write history tags
            for hist in arr.metadata.get('history', []):
                fsio.write_tag(file, fsio.tags.history, len(hist))
                file.write(hist.encode('utf-8'))


class NiftiArrayIO(protocol.IOProtocol):
    """
    Array IO protocol for nifti files.
    """
    name = 'nifti'
    extensions = ('.nii.gz', '.nii')

    def __init__(self):
        try:
            import nibabel as nib
        except ImportError:
            raise ImportError('the `nibabel` python package must be installed for nifti IO')
        self.nib = nib

    def load(self, filename, atype):
        """
        Read array from a nifiti file.

        Parameters
        ----------
        filename : str
            File path read.
        atype : class
            FramedArray subclass to load.

        Returns
        -------
        FramedArray
            Array object loaded from file.
        """
        nii = self.nib.load(filename)
        data = nii.get_data()
        arr = atype(data)
        if isinstance(arr, FramedImage):
            matrix = nii.get_affine()
            voxsize = nii.header['pixdim'][1:4]
            arr.geom.update(vox2world=matrix, voxsize=voxsize)
        return arr

    def save(self, arr, filename):
        """
        Write array to a nifti file.

        Parameters
        ----------
        arr : FramedArray
            Array to save.
        filename : str
            Target file path.
        """
        isimage = isinstance(arr, FramedImage)
        matrix = arr.geom.vox2world.matrix if isimage else np.eye(4)
        nii = self.nib.Nifti1Image(arr.data, matrix)
        if is_image:
            nii.header['pixdim'][1:4] = arr.voxsize
        self.nib.save(nii, filename)


class FreeSurferAnnotationIO(protocol.IOProtocol):
    """
    Array IO protocol for 1D mesh annotation files.
    """
    name = 'annot'
    extensions = '.annot'

    def labels_to_mapping(self, labels):
        """
        The annotation file format saves each vertex label value as a
        bit-manipulated int32 value that represents an RGB. But, the label
        lookup table is embedded in the file, so it's kind of a pointless
        format that could be simply replaced by an MGH file with embedded
        labels, like any other volumetric segmentaton. This function builds
        a mapping to convert label RGBs to a lookup of bit-manipulated int32
        values. Using this mapping, we can convert between a classic integer
        segmentation and annotation-style values.
        """
        rgb = np.array([elt.color[:3].astype(np.int32) for elt in labels.values()])
        idx = np.array(list(labels.keys()))
        mapping = np.zeros(idx.max() + 1, dtype=np.int32)
        mapping[idx] = (rgb[:, 2] << 16) + (rgb[:, 1] << 8) + rgb[:, 0]
        return mapping

    def load(self, filename, atype):
        """
        Read overlay from an annot file.

        Parameters
        ----------
        filename : str
            File path read.
        atype : class
            FramedArray subclass to load. When reading annot files, this
            must be Overlay.

        Returns
        -------
        Overlay
            Array object loaded from file.
        """
        if atype is not Overlay:
            raise ValueError('annotation files can only be loaded as 1D overlays')

        with open(filename, 'rb') as file:

            nvertices = read_bytes(file, '>i4')
            data = np.zeros(nvertices, dtype=np.int32)

            value_map = read_bytes(file, '>i4', nvertices * 2)
            vnos = value_map[0::2]
            vals = value_map[1::2]
            data[vnos] = vals

            tag, length = fsio.read_tag(file)
            if tag is None or tag != fsio.tags.old_colortable:
                raise ValueError('annotation file does not have embedded label lookup data')
            labels = fsio.read_binary_lookup_table(file)

        # cache the zero value annotations (unknown labels)
        unknown_mask = data == 0

        # conver annotation values to corresponding label values
        mapping = self.labels_to_mapping(labels)
        ds = np.argsort(mapping)
        pos = np.searchsorted(mapping[ds], data)
        index = np.take(ds, pos, mode='clip')
        mask = mapping[index] != data
        data = np.ma.array(index, mask=mask)

        # all of the unknown labels should be converted to -1
        data[unknown_mask] = -1

        return Overlay(data, labels=labels)

    def save(self, arr, filename):
        """
        Write overlay to an annot file.

        Parameters
        ----------
        arr : Overlay
            Array to save.
        filename : str
            Target file path.
        """
        if not isinstance(arr, Overlay):
            raise ValueError(f'can only save 1D overlays as annotations, but got array type {typle(arr)}')

        if not np.issubdtype(arr.dtype, np.integer):
            raise ValueError(f'annotations must have integer dtype, but overlay has dtype {arr.dtype}')

        if arr.nframes > 1:
            raise ValueError(f'annotations must only have 1 frame, but overlay has {arr.nframes} frames')

        if arr.labels is None:
            raise ValueError('overlay must have label lookup if saving as annotation')

        # 
        unknown_mask = arr.data < 0

        # make sure all indices exist in the label lookup
        cleaned = arr.data[np.logical_not(unknown_mask)]
        found = np.in1d(cleaned, list(arr.labels.keys()))
        if not np.all(found):
            missing = list(np.unique(cleaned[found == False]))
            raise ValueError('cannot save overlay as annotation because it contains the following values '
                            f'that do not exist in its label lookup: {missing}')

        cleaned = arr.data.copy()
        cleaned[unknown_mask] = 0
        colors = self.labels_to_mapping(arr.labels)[arr.data]
        colors[unknown_mask] = 0

        with open(filename, 'bw') as file:
            # write the total number of vertices covered by the overlay
            nvertices = arr.shape[0]
            write_bytes(file, nvertices, '>i4')

            # write the data as sequences of (vertex number, color) for every 'vertex'
            # in the annotation, where color is 
            annot = np.zeros(nvertices * 2, dtype=np.int32)
            annot[0::2] = np.arange(nvertices, dtype=np.int32)
            annot[1::2] = colors
            write_bytes(file, annot, '>i4')

            # include the label lookup information
            fsio.write_tag(file, fsio.tags.old_colortable)
            fsio.write_binary_lookup_table(file, arr.labels)


class FreeSurferCurveIO(protocol.IOProtocol):
    """
    Array IO protocol for 1D FS curv files. This is another silly file format that
    could very well just be replaced by MGH files.
    """
    name = 'curv'
    extensions = ()

    def load(self, filename, atype):
        """
        Read overlay from a curv file.

        Parameters
        ----------
        filename : str
            File path read.
        atype : class
            FramedArray subclass to load. When reading curv files, this
            must be Overlay.

        Returns
        -------
        Overlay
            Array object loaded from file.
        """
        if atype is not Overlay:
            raise ValueError('curve files can only be loaded as 1D overlays')
        with open(filename, 'rb') as file:
            magic = read_int(file, size=3)
            nvertices = read_bytes(file, '>i4')
            read_bytes(file, '>i4')
            read_bytes(file, '>i4')
            data = read_bytes(file, '>f4', nvertices)
        return Overlay(data)

    def save(self, arr, filename):
        """
        Write overlay to a curv file.

        Parameters
        ----------
        arr : Overlay
            Array to save.
        filename : str
            Target file path.
        """
        if arr.nframes > 1:
            raise ValueError(f'curv files must only have 1 frame, but overlay has {arr.nframes} frames')

        with open(filename, 'bw') as file:
            write_int(file, -1, size=3)
            write_bytes(file, arr.shape[0], '>i4')
            write_bytes(file, 0, '>i4')
            write_bytes(file, 1, '>i4')
            write_bytes(file, arr.data, '>f4')


class ImageSliceIO(protocol.IOProtocol):
    """
    Generic array IO protocol for common image formats.
    """

    def __init__(self):
        try:
            from PIL import Image
        except ImportError:
            raise ImportError(f'the `pillow` python package must be installed for {self.name} IO')
        self.Image = Image

    def save(self, arr, filename):
        self.Image.fromarray(arr.data).save(filename)

    def load(self, filename):
        image = np.asarray(self.Image.open(filename))
        return Slice(image)


class JPEGArrayIO(ImageSliceIO):
    name = 'jpeg'
    extensions = ('.jpeg', '.jpg')


class PNGArrayIO(ImageSliceIO):
    name = 'png'
    extensions = '.png'


class TIFFArrayIO(ImageSliceIO):
    name = 'tiff'
    extensions = ('.tif', '.tiff')


# enabled array IO protocol classes
array_io_protocols = [
    MGHArrayIO,
    NiftiArrayIO,
    FreeSurferAnnotationIO,
    FreeSurferCurveIO,
    JPEGArrayIO,
    PNGArrayIO,
    TIFFArrayIO,
]
