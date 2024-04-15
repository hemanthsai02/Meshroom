__version__ = "1.0"

from meshroom.core import desc
from meshroom.core.utils import VERBOSE_LEVEL


class MeshRepairing(desc.AVCommandLineNode):
    commandLine = 'aliceVision_meshRepairing {allParams}'
    cpu = desc.Level.NORMAL
    ram = desc.Level.NORMAL

    category = 'Mesh Post-Processing'
    documentation = '''
This node allows to reduce the density of the Mesh.
'''

    inputs = [
        desc.File(
            name="input",
            label="Mesh",
            description="Input mesh in the OBJ format.",
            value="",
            uid=[0],
        ),
        desc.ChoiceParam(
            name="verboseLevel",
            label="Verbose Level",
            description="Verbosity level (fatal, error, warning, info, debug, trace).",
            values=VERBOSE_LEVEL,
            value="info",
            exclusive=True,
            uid=[],
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="Mesh",
            description="Output mesh in the OBJ file format.",
            value=desc.Node.internalFolder + "mesh.obj",
            uid=[],
        ),
    ]
