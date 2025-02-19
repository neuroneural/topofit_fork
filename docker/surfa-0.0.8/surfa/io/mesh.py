import os
import numpy as np

from surfa import Mesh
from surfa.transform import ImageGeometry
from surfa.io import fsio
from surfa.io import protocol
from surfa.io.utils import read_bytes
from surfa.io.utils import write_bytes
from surfa.io.utils import read_int
from surfa.io.utils import write_int
from surfa.io.utils import check_file_readability


def load_mesh(filename, fmt=None):
    """
    Load a mesh file into a Mesh object. Supported file formats are:

      - 'fs': Default FreeSurfer surface format.
      - 'gifti': Gifti geometry format.

    Parameters
    ----------
    filename : str
        File path to read.
    fmt : str, optional
        Forced file format. If None (default), file format is extrapolated
        from extension or assumed to be in the extensionless 'fs' surface format.

    Returns
    -------
    Mesh
        A mesh object loaded from file.
    """
    check_file_readability(filename)

    if fmt is None:
        iop = find_mesh_protocol_by_extension(filename)
    else:
        iop = protocol.find_protocol_by_name(mesh_io_protocols, fmt)

    return iop().load(filename)


def save_mesh(mesh, filename, fmt=None):
    """
    Save a Mesh object to file.

    Parameters
    ----------
    mesh : Mesh
        Mesh object to write.
    filename: str
        Destination file path.
    fmt : str
        Forced file format. If None (default), file format is extrapolated
        from extension or assumed to be in the extensionless 'fs' surface format.
    """
    if fmt is None:
        iop = find_mesh_protocol_by_extension(filename)
    else:
        iop = protocol.find_protocol_by_name(mesh_io_protocols, fmt)
        filename = iop.enforce_extension(filename)

    iop().save(mesh, filename)


def find_mesh_protocol_by_extension(filename):
    """
    Find mesh IO protocol from file extension. Since FS mesh files
    have no default extension (sadly), this function wraps and customizes
    `find_protocol_by_name` for mesh files.

    Parameters
    ----------
    filename : str
        File path to read.

    Returns
    -------
    protocol : IOProtocol
        Matched mesh IO protocol class.
    """

    # manually check for common, invalid file types that
    # people might naively try to load as meshes
    bad_formats = ('.mgh', '.mgz', '.nii', '.nii.gz')
    basename = os.path.basename(filename).lower()
    if basename.endswith(bad_formats):
        raise ValueError(f'{basename} is not a valid mesh file type.')

    # find matching protocol
    iop = protocol.find_protocol_by_extension(mesh_io_protocols, filename)

    # assume an unmatched extension is an FS surface
    if iop is None:
        iop = FreesurferSurfaceIO

    return iop


class FreesurferSurfaceIO(protocol.IOProtocol):
    """
    Mesh IO protocol for FreeSurfer-type files.
    """

    name = 'fs'
    extensions = ('.srf', '.surf')

    def load(self, filename):
        """
        Load a FreeSurfer surface file into a Mesh object.

        Parameters
        ----------
        filename : str
            File path to read.

        Returns
        -------
        Mesh
            A Mesh object loaded from file.
        """
        with open(filename, 'rb') as file:

            magic = read_int(file, size=3)
            if magic != -2:
                raise NotImplementedError(f'version {magic} FS surfaces cannot be loaded')

            # skip over two lines (second newline should follow immediately)
            file.readline(200)
            file.readline()

            # read mesh data
            nvertices = read_int(file)
            nfaces = read_int(file)

            vertices = np.fromfile(file, dtype='>f4', count=nvertices * 3).reshape((nvertices, 3))
            faces = np.fromfile(file, dtype='>i4', count=nfaces * 3).reshape((nfaces, 3))

            # create surface object
            mesh = Mesh(vertices, faces)

            # read metadata tags
            while True:
                tag, length = fsio.read_tag(file)
                if tag is None:
                    break

                # command history
                elif tag == fsio.tags.history:
                    history = file.read(length).decode('utf-8').rstrip('\x00')
                    if mesh.metadata.get('history'):
                        mesh.metadata['history'].append(history)
                    else:
                        mesh.metadata['history'] = [history]

                # read surface geometry
                elif tag == fsio.tags.old_surf_geom:
                    # read 8 hardcoded lines
                    string = ''.join([file.readline().decode('utf-8') for _ in range(8)])
                    mesh.geom = fsio.image_geometry_from_string(string)

                # real ras
                elif tag in (fsio.tags.old_real_ras, fsio.tags.real_ras):
                    if read_int(file) != 0:
                        mesh.metadata['real-ras'] = True

                # skip everything else
                else:
                    file.read(length)

        return mesh

    def save(self, mesh, filename):
        """
        Save a Mesh object to a FreeSurfer surface file.

        Parameters
        ----------
        mesh : Mesh
            Mesh to save.
        filename : str
            Destination file path.
        """
        mesh = mesh.convert(space='surface', copy=False)
        
        with open(filename, 'wb') as file:

            # magic and two lines for header
            write_int(file, -2, size=3)
            file.write('\n\n'.encode('utf-8'))

            # write topology
            write_int(file, mesh.nvertices)
            write_int(file, mesh.nfaces)

            # todo ensure contiguous
            mesh.vertices.astype('>f4').tofile(file)
            mesh.faces.astype('>i4').tofile(file)

            # geometry
            fsio.write_tag(file, fsio.tags.old_surf_geom)
            file.write(fsio.image_geometry_to_string(mesh.geom).encode('utf-8'))

            # real ras metadata
            fsio.write_tag(file, fsio.tags.old_real_ras)
            write_int(file, int(mesh.metadata.get('real-ras', False)))

            # history metadata
            for hist in mesh.metadata.get('history', []):
                fsio.write_tag(file, fsio.tags.history, len(hist))
                file.write(hist.encode('utf-8'))


class GiftiIO(protocol.IOProtocol):
    """
    Mesh IO protocol for gifti files.
    """

    name = 'gifti'
    extensions = ('.gii', '.gii.gz')

    def __init__(self):
        try:
            import nibabel as nib
        except ImportError:
            raise ImportError('the nibabel python package must be installed for GIFTI surface IO')
        self.nib = nib

    def load(self, filename):
        """
        Load a gifti mesh file into a Mesh object.

        Parameters
        ----------
        filename : str
            File path to read.

        Returns
        -------
        mesh : Mesh
            A Mesh object loaded from file.
        """
        gii = self.nib.load(filename)

        # extract mesh data
        vertices = gii.agg_data('pointset')
        faces = gii.agg_data('triangle')

        # ensure data exists
        if not vertices:
            raise RuntimeError('cannot load mesh since GIFTI file does not contain pointset data')
        if not faces:
            raise RuntimeError('cannot load mesh since GIFTI file does not contain triangle data')

        # extract geometry metadata
        metadata = gii.get_arrays_from_intent('pointset')[0].metadata
        shape = [
            metadata.get('VolGeomWidth'),
            metadata.get('VolGeomHeight'),
            metadata.get('VolGeomDepth'),
        ]
        voxsize = [
            metadata.get('VolGeomXsize'),
            metadata.get('VolGeomYsize'),
            metadata.get('VolGeomZsize'),
        ]
        rotation = [
            metadata.get('VolGeomX_R'),
            metadata.get('VolGeomY_R'),
            metadata.get('VolGeomZ_R'),
            metadata.get('VolGeomX_A'),
            metadata.get('VolGeomY_A'),
            metadata.get('VolGeomZ_A'),
            metadata.get('VolGeomX_S'),
            metadata.get('VolGeomY_S'),
            metadata.get('VolGeomZ_S'),
        ]
        center = [
            metadata.get('VolGeomC_R'),
            metadata.get('VolGeomC_A'),
            metadata.get('VolGeomC_S'),
        ]

        # assume that any missing geometry fields means invalid geometry
        if None in center + rotation + voxsize + shape:
            geometry = None
        else:
            shape = [int(i) for i in shape]
            voxsize = [float(i) for i in voxsize]
            rotation = np.reshape([float(i) for i in rotation], (3, 3))
            center = [float(i) for i in center]
            geometry = ImageGeometry(shape=shape, voxsize=voxsize, rotation=rotation, center=center)

        return Mesh(vertices, faces, geometry=geometry)

    def save(self, mesh, filename):
        """
        Save a Mesh object to a giti mesh file.

        Parameters
        ----------
        mesh : Mesh
            Mesh to save.
        filename : str
            Destination file path.
        """
        mesh = mesh.convert(space='surface', copy=False)

        gii = self.nib.GiftiImage()

        if mesh.geom is not None:
            meta = {
                'VolGeomWidth': '%d' % mesh.geom.shape[0],
                'VolGeomHeight': '%d' % mesh.geom.shape[1],
                'VolGeomDepth': '%d' % mesh.geom.shape[2],
                'VolGeomXsize': '%.15e' % mesh.geom.voxsize[0],
                'VolGeomYsize': '%.15e' % mesh.geom.voxsize[1],
                'VolGeomZsize': '%.15e' % mesh.geom.voxsize[2],
                'VolGeomX_R': '%.15e' % mesh.geom.rotation[0, 0],
                'VolGeomY_R': '%.15e' % mesh.geom.rotation[0, 1],
                'VolGeomZ_R': '%.15e' % mesh.geom.rotation[0, 2],
                'VolGeomX_A': '%.15e' % mesh.geom.rotation[1, 0],
                'VolGeomY_A': '%.15e' % mesh.geom.rotation[1, 1],
                'VolGeomZ_A': '%.15e' % mesh.geom.rotation[1, 2],
                'VolGeomX_S': '%.15e' % mesh.geom.rotation[2, 0],
                'VolGeomY_S': '%.15e' % mesh.geom.rotation[2, 1],
                'VolGeomZ_S': '%.15e' % mesh.geom.rotation[2, 2],
                'VolGeomC_R': '%.15e' % mesh.geom.center[0],
                'VolGeomC_A': '%.15e' % mesh.geom.center[1],
                'VolGeomC_S': '%.15e' % mesh.geom.center[2],
            }
        else:
            meta = None

        vertices = self.nib.gifti.GiftiDataArray(mesh.vertices, 'pointset', meta=meta)
        faces = self.nib.gifti.GiftiDataArray(mesh.faces, 'triangle')

        gii.add_gifti_data_array(vertices)
        gii.add_gifti_data_array(faces)
        self.nib.gifti.write(gii, filename)


# enabled mesh IO protocol classes
mesh_io_protocols = [
    FreesurferSurfaceIO,
    GiftiIO,
]
