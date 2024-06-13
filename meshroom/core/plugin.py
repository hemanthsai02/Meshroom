#!/usr/bin/env python
# coding:utf-8

"""
This file defines the nodes and logic needed for the plugin system in meshroom.
A plugin is a collection of node(s) of any type with their rutime environnement setup file attached.
We use the term 'environement' to abstract a docker container or a conda/virtual environement.
"""

import json
import os, sys
import logging
import urllib
from distutils.dir_util import copy_tree, remove_tree
import subprocess 
import venv

from meshroom.core.node import Status
from meshroom.core import desc, hashValue
from meshroom.core import pluginsNodesFolder, pluginsPipelinesFolder, defaultCacheFolder, pluginCatalogFile

class PluginParams():
    """"
    Class that holds parameters to install one plugin from a folder and optionally from a json structure
    """
    def __init__(self, pluginUrl, jsonData=None):
        #NOTE: other fields? such as other location for the env file, dependencies, extra folder/lib to install
        
        #get the plugin name from folder
        self.pluginName = os.path.basename(pluginUrl)
        #default node and pipeline locations
        self.nodesFolder = os.path.join(pluginUrl, "meshroomNodes")
        self.pipelineFolder = os.path.join(pluginUrl, "meshroomPipelines")

        if jsonData is not None:
            self.pluginName = jsonData["pluginName"]
            #default node and pipeline locations
            self.nodesFolder = os.path.join(pluginUrl, jsonData["nodesFolder"])
            if "pipelineFolder" in jsonData.keys():
                self.pipelineFolder = os.path.join(pluginUrl, jsonData["pipelineFolder"])

def _formatPluginName(pluginName):
    return pluginName.replace(" ", "_")

def installPlugin(pluginUrl):
    """
    Install plugin from an url or local path.
    Regardless of the method, the content will be copied in the plugin folder of meshroom (which is added to the list of directory to load nodes from).
    There are two options :
        - having the following structure :
            - [plugin folder] (will be the plugin name)
                - meshroomNodes
                    - [code for your nodes] that contains relative path to a DockerFile|env.yaml|requirements.txt
                    - [...]
                - meshroomPipelines
                    - [your meshroom templates]
            With this solution, you can only have one environnement for the hole plugin.
        - having a meshroomPlugin.json file at the root of the plugin folder
          With this solution, you may have several envionnements.
    """
    logging.info("Installing plugin from "+pluginUrl)
    try:
        isLocal = True

        #if git repo, clone the repo in cache
        if urllib.parse.urlparse(pluginUrl).scheme in ('http', 'https','git'):
            os.chdir(defaultCacheFolder)
            os.system("git clone "+pluginUrl)
            pluginName = pluginUrl.split('.git')[0].split('/')[-1]
            pluginUrl = os.path.join(defaultCacheFolder, pluginName)
            isLocal = False
        
        #sanity check
        if not os.path.isdir(pluginUrl):
            ValueError("Invalid plugin path :"+pluginUrl)

        #by default only one plugin, and with default file hierachy
        pluginParamList=[PluginParams(pluginUrl)]

        #location of the json file if any
        paramFile=os.path.join(pluginUrl, "meshroomPlugin.json")
        #load json for custom install if any
        if os.path.isfile(paramFile):
            jsonData=json.load(open(paramFile,"r"))
            pluginParamList = [PluginParams(pluginUrl, jsonDataplugin) for jsonDataplugin in jsonData]
        
        #for each plugin, run the 'install'
        for pluginParam in pluginParamList:
            intallFolder = os.path.join(pluginsNodesFolder, _formatPluginName(pluginParam.pluginName))

            logging.info("Installing "+pluginParam.pluginName+" from "+pluginUrl+" in "+intallFolder)

            #check if folder valid
            if not os.path.isdir(pluginParam.nodesFolder):
                raise RuntimeError("Invalid node folder: "+pluginParam.nodesFolder)

            #check if already installed
            if os.path.isdir(intallFolder):
                logging.warn("Plugin already installed, will overwrite")
                if os.path.islink(intallFolder):
                    os.unlink(intallFolder)
                else:
                    remove_tree(intallFolder)

            #install via symlink if local, otherwise copy (usefull to develop)
            if isLocal:
                os.symlink(pluginParam.nodesFolder, intallFolder)
                if os.path.isdir(pluginParam.pipelineFolder):
                    os.symlink(pluginParam.pipelineFolder, os.path.join(pluginsPipelinesFolder, pluginParam.pluginName))
            else:
                copy_tree(pluginParam.nodesFolder, intallFolder)
                if os.path.isdir(pluginParam.pipelineFolder):
                    copy_tree(pluginParam.pipelineFolder, os.path.join(pluginsPipelinesFolder, pluginParam.pluginName))

        #remove repo if was cloned
        if not isLocal:
            os.removedirs(pluginUrl)

        #NOTE: could try to auto load the plugins to avoid restart and test files

    except Exception as ex:
        logging.error(ex)
        return False
        
    return True

def getCatalog():
    jsonData=json.load(open(pluginCatalogFile,"r"))
    return jsonData
        
def getInstalledPlugin():
    installedPlugins = [os.path.join(pluginsNodesFolder, f) for f in os.listdir(pluginsNodesFolder)]
    return installedPlugins

def uninstallPlugin(pluginUrl):
    if not os.path.exists(pluginUrl):
        raise RuntimeError("Plugin "+pluginUrl+" is not installed")
    if os.path.islink(pluginUrl):
        os.unlink(pluginUrl)
    else:
        os.removedirs(pluginUrl) 
    
class PluginNode(desc.CommandLineNode):

    #env file used to build the environement, you may overwrite this to custom the behaviour
    @property
    def envFile(cls):
        raise NotImplementedError("You must specify an env file")

    #env name computed from hash, overwrite this to use a custom pre-build env 
    @property
    def _envName(cls):
        """
        Get the env name by hashing the env files
        """
        with open(cls.envFile, 'r') as file:
            envContent = file.read()
        return "meshroom_plugin_"+hashValue(envContent)

    def build():
        raise RuntimeError("Virtual class must be overloaded")

    def buildCommandLine(self, chunk):
        raise RuntimeError("Virtual class must be overloaded")

# def dockerImageExists(imageName):
#     """
#     Checks if an image exists with a given name
#     """
#     client = docker.from_env()
#     try:
#         client.images.get(imageName)
#         return True
#     except docker.errors.ImageNotFound:
#         return False

def dockerImageExists(image_name, tag='latest'): 
    try: 
        result = subprocess.run( ['docker', 'images', image_name, '--format', '{{.Repository}}:{{.Tag}}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True )
        if result.returncode != 0: 
            return False 
        #check if the desired image:tag exists 
        images = result.stdout.splitlines() 
        image_tag = f"{image_name}:{tag}" 
        return image_tag in images 
    except Exception as e: 
        print(f"An error occurred: {e}") 
        return False 
        
class DockerNode(PluginNode):
    """
    Node that build a docker container from a dockerfile and run all the commands in it.
    """
    def build(cls):
        #build image 
        logging.info("Creating image "+cls._envName+" from "+ cls.envFile)
        buildCommand = "docker build -f "+cls.envFile+" -t "+cls._envName+" "+os.path.dirname(cls.envFile)
        logging.info("Building with "+buildCommand+" ...")
        os.system(buildCommand)
        logging.info("Done")

    def buildCommandLine(self, chunk):
        cmdPrefix = ''
        #if the env was never built
        if not dockerImageExists(self._envName):
            chunk.upgradeStatusTo(Status.BUILD)
            self.build()
            chunk.upgradeStatusTo(Status.RUNNING)
  
        #mount point in the working dir wich is the node dir
        mountCl = ' --mount type=bind,source="$(pwd)",target=/node_folder '
        #add the prefix to the command line
        cmdPrefix = 'docker run -it --rm --runtime=nvidia --gpus all '+mountCl+self._envName+" "
        cmdSuffix = ''
        if chunk.node.isParallelized and chunk.node.size > 1:
            cmdSuffix = ' ' + self.commandLineRange.format(**chunk.range.toDict())
        return cmdPrefix + chunk.node.nodeDesc.commandLine.format(**chunk.node._cmdVars) + cmdSuffix

    def processChunk(self, chunk):
        try:
            with open(chunk.logFile, 'w') as logF:
                cmd = self.buildCommandLine(chunk)
                chunk.status.commandLine = cmd
                chunk.saveStatusFile()
                print(' - commandLine: {}'.format(cmd))
                print(' - logFile: {}'.format(chunk.logFile))
                #popen doesnt work with docker, also move to node folder is necessary
                chunk.status.returnCode = os.system("cd "+chunk.node.internalFolder+" && "+cmd)
                logContent=""

            if chunk.status.returnCode != 0:
                with open(chunk.logFile, 'r') as logF:
                    logContent = ''.join(logF.readlines())
                raise RuntimeError('Error on node "{}":\nLog:\n{}'.format(chunk.name, logContent))
        except:
            chunk.logManager.end()
            raise
        chunk.logManager.end()


def curateEnvCommand():
    """
    Used to unset all rez defined env that messes up with conda.
    """
    cmd=""
    for envVar in os.environ.keys():
        if ((("py" in envVar) or  ("PY" in envVar)) 
            and ("REZ" not in envVar) and ("." not in envVar) and ("-" not in envVar)):
            if envVar.endswith("()"):
                cmd+='unset -f '+envVar[10:-2]+'; '
            else:
                cmd+='unset '+envVar+'; '
    return cmd

def condaEnvExist(envName):
    """
    Checks if a specified env exists
    """
    cmd = "conda list --name "+envName
    result = subprocess.run( cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True )
    return result.returncode == 0

class CondaNode(PluginNode):
    """
    Node that build conda environement from a yaml file and run all the commands in it.
    """
    def build(cls):
        """
        Build a conda env from a yaml file
        """
        logging.info("Creating conda env "+cls._envName+" from "+cls.envFile)
        makeEnvCommand = (curateEnvCommand()
                            +" conda config --set channel_priority strict; "
                            +" conda env create --name "+cls._envName
                            +" --file "+cls.envFile+" ")
        logging.info("Building...")
        logging.info(makeEnvCommand)
        return_status = os.system(makeEnvCommand)
        if return_status != 0:
            raise RuntimeError("Build failed!")
        logging.info("Done")
        
    def buildCommandLine(self, chunk):
        cmdPrefix = ''
        #create the env if not built yet
        if not condaEnvExist(self._envName):
            chunk.upgradeStatusTo(Status.BUILD)
            self.build()
            chunk.upgradeStatusTo(Status.RUNNING)
        else:
            logging.info("Reusing env "+self._envName)

        #add the prefix to the command line
        cmdPrefix = curateEnvCommand()+" conda run --no-capture-output "+self._envName+" "
        cmdSuffix = ''
        if chunk.node.isParallelized and chunk.node.size > 1:
            cmdSuffix = ' ' + self.commandLineRange.format(**chunk.range.toDict())
        return cmdPrefix + chunk.node.nodeDesc.commandLine.format(**chunk.node._cmdVars) + cmdSuffix

    def processChunk(self, chunk):
        try:
            with open(chunk.logFile, 'w') as logF:
                cmd = self.buildCommandLine(chunk)
                chunk.status.commandLine = cmd
                chunk.saveStatusFile()
                print(' - commandLine: {}'.format(cmd))
                print(' - logFile: {}'.format(chunk.logFile))
                #unset doesnt work with subprocess, and removing the variables from the env dict does not work either
                chunk.status.returnCode = os.system(cmd)
                logContent=""

            if chunk.status.returnCode != 0:
                with open(chunk.logFile, 'r') as logF:
                    logContent = ''.join(logF.readlines())
                raise RuntimeError('Error on node "{}":\nLog:\n{}'.format(chunk.name, logContent))
        except:
            chunk.logManager.end()
            raise
        chunk.logManager.end()

class PipNode(desc.Node):
    """
    Node than runs in the same python as meshroom, but install extra packages first
    """
    def build(cls):
        #install packages in the same python as meshroom
        logging.info("Installing packages from "+ cls.envFile)
        buildCommand = sys.executable+" -m pip install "+ cls.envFile
        logging.info("Building with "+buildCommand+" ...")
        os.system(buildCommand)
        logging.info("Done")

def create_venv(venv_path):
    """
    Create venv and return python executable
    """
    #builder that saves context once built
    class _EnvBuilder(venv.EnvBuilder):
        def __init__(self, *args, **kwargs):
            self.context = None
            super().__init__(*args, **kwargs)
        def post_setup(self, context):
            self.context = context
    venv_builder = _EnvBuilder(with_pip=True)
    venv_builder.create(venv_path)
    env_exe = venv_builder.context.env_exe
    return env_exe

class VenvNode(desc.CommandLineNode):
    """
    Node that build a python virtual env and install pip packages from a requirement.txt.
    """
    def build(cls):
        """
        Build a virtual env from a requirement.txt file-
        """
        logging.info("Creating virtual env "+os.path.join(defaultCacheFolder, cls._envName)+" from "+cls.envFile)
        cls.env_exe = create_venv(os.path.join(defaultCacheFolder, cls._envName))
        os.system(cls.env_exe+" -m pip install "+ cls.envFile)
        logging.info("Done")
        
    def buildCommandLine(self, chunk):
        cmdPrefix = ''
        #create the env if not built yet
        if not os.path.isdir(os.path.join(defaultCacheFolder, self._envName)):
            self.build()

        #add the prefix to the command line
        cmdPrefix = "cls.env_exe "
        cmdSuffix = ''
        if chunk.node.isParallelized and chunk.node.size > 1:
            cmdSuffix = ' ' + self.commandLineRange.format(**chunk.range.toDict())
        return cmdPrefix + chunk.node.nodeDesc.commandLine.format(**chunk.node._cmdVars) + cmdSuffix

