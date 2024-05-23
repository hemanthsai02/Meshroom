# Making Meshroom Plugins

To make a new plugin, make your node inheriting from `meshroom.core.plugins.CondaNode` or `meshroom.core.plugins.DockerNode`.
In your new node class, overwrite the variable `envFile` to point to the environment file (e.g. the `yaml` or `dockerfile`) that sets up your installation. The path to this file should be relative to the path of the node, and within the same folder (or child folder) as the node definition.

Prefixes will be added automatically to your command line to run the node in the right envireonnement.
Several nodes share the same environment as long as they point to the same environment file. 
Changing this file will trigger a rebuild on the environment.

You may install plugin from a git repository or from a local folder. In the later case, you may edit the code directly from your source folder.

By default, Meshroom will look for node definition in `[plugin folder]/meshroomNodes` and new pipelines in `[plugin folder]/meshroomPipelines`.

The environment of the nodes are going to be build the first time it is needed. 

TBA: customised install from meshroomPlugin.json