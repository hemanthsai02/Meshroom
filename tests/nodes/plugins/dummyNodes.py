from meshroom.core.plugin import CondaNode, DockerNode, PipNode, VenvNode
import os 

class DummyCondaNode(CondaNode):
    commandLine = 'python -c "import numpy as np"'
    envFile = os.path.join(os.path.dirname(__file__), 'env.yaml')
    outputs = []

class DummyDockerNode(DockerNode):
    commandLine = 'python -c "import numpy as np"'
    envFile = os.path.join(os.path.dirname(__file__), 'Dockerfile')
    outputs = []

class DummyPipNode(PipNode):
    commandLine = 'python -c "import numpy as np"'
    envFile = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    outputs = []

class DummyVenvNode(VenvNode):
    commandLine = 'python -c "import numpy as np"'
    envFile = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    outputs = []