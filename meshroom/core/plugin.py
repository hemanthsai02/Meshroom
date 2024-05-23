#!/usr/bin/env python
# coding:utf-8

"""
This file defines the nodes and logic needed for the plugin system in meshroom.
"""

import os
import logging
import urllib
from distutils.dir_util import copy_tree, remove_tree

from meshroom.core.node import Status
from meshroom.core import desc, hashValue
from meshroom.core import pluginsNodesFolder, pluginsPipelinesFolder, defaultCacheFolder

#NOTE: could replace with parsing to avoid dependancy to docker api
import docker

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
        - having a meshroomPlugin.json file at the root of the plugin folder
    """
    logging.info("Installing plugin from "+pluginUrl)
    try:
        isLocal = True

        #if url, clone the repo in cache
        if urllib.parse.urlparse(pluginUrl).scheme in ('http', 'https','git'):
            os.chdir(defaultCacheFolder)
            os.system("git clone "+pluginUrl)
            pluginName = pluginUrl.split('.git')[0].split('/')[-1]
            pluginUrl = os.path.join(defaultCacheFolder, pluginName)
            isLocal = False
        
        if not os.path.isdir(pluginUrl):
            ValueError("Invalid plugin path :"+pluginUrl)

        #get the plugin name from folder
        pluginName = os.path.basename(pluginUrl)
        #default node and pipeline locations
        nodesFolder = os.path.join(pluginUrl, "meshroomNodes")
        pipelineFolder = os.path.join(pluginUrl, "meshroomPipelines")

        #load json for custom install
        if os.path.isfile(os.path.join(pluginUrl, "meshroomPlugin.json")):
            raise NotImplementedError("Install from json not supported yet")
     
        logging.info("Installing "+pluginName+" from "+pluginUrl)
        intallFolder = os.path.join(pluginsNodesFolder, pluginName)

        #check if already installed
        if os.path.isdir(intallFolder):
            logging.warn("Plugin already installed, will overwrite")
            if os.path.islink(intallFolder):
                os.unlink(intallFolder)
            else:
                remove_tree(intallFolder)

        #install via symlink if local, otherwise copy and delete the repo
        if isLocal:
            os.symlink(nodesFolder, intallFolder)
            if os.path.isdir(pipelineFolder):
                os.symlink(pipelineFolder, pluginsPipelinesFolder)
        else:
            copy_tree(nodesFolder, intallFolder)
            if os.path.isdir(pipelineFolder):
                copy_tree(pipelineFolder, pluginsPipelinesFolder)
            os.removedirs(pluginUrl)

    except Exception as ex:
        logging.error(ex)
        return False
        
    return True
    
class PluginNode(desc.CommandLineNode):
    #env file used to build the environement, you may overwrite this to custom the behaviour
    @property
    def envFile(cls):
        raise NotImplementedError("You must specify an env file") #FIXME: automatically look in __file__?

    #env name computed from hash, overwrite this to use a custom env 
    @property
    def _envName(cls):
        """
        Get the env name by hashing the env files
        """
        with open(cls.envFile, 'r') as file:
            envContent = file.read()
        return "MrPlugin_"+hashValue(envContent)

    def build():
        raise RuntimeError("Virtual class must be overloaded")

    def buildCommandLine(self, chunk):
        raise RuntimeError("Virtual class must be overloaded")

def curateEnvCommand():
    """
    Used to unset all rez defined env that messes up with conda.
    """
    cmd=""
    for envVar in os.environ.keys():
        if ((("py" in envVar) or  ("PY" in envVar)) 
            and ("REZ" not in envVar) and ("." not in envVar) and ("-" not in envVar)):
            if envVar.endswith("()"):#function get special treatment
                cmd+='unset -f '+envVar[10:-2]+'; '
            else:
                cmd+='unset '+envVar+'; '
    return cmd

def condaEnvExist(envName):
    """
    Checks if a specified env exists
    """
    cmd = "conda list --name "+envName
    output = os.popen(cmd).read()
    return not output.startswith("EnvironmentLocationNotFound")

class CondaNode(PluginNode):

    def build(cls):
        """
        Build a conda env from a yaml file
        """
        logging.info("Creating conda env "+cls._envName+" from "+cls.envFile)
        makeEnvCommand = (curateEnvCommand()
                            +" conda config --set channel_priority strict; "
                            +" conda env create --name "+cls._envName
                            +" --file "+cls.envFile)
        logging.info("Building...")
        logging.info(makeEnvCommand)
        os.system(makeEnvCommand)
        logging.info("Done")
        
    def buildCommandLine(self, chunk):
        cmdPrefix = ''
        #create the env if not built yet
        if not condaEnvExist(self._envName):
            self.build()

        #add the prefix to the command line
        cmdPrefix = curateEnvCommand()+" conda run --no-capture-output "+self._envName
        cmdSuffix = ''
        if chunk.node.isParallelized and chunk.node.size > 1:
            cmdSuffix = ' ' + self.commandLineRange.format(**chunk.range.toDict())
        return cmdPrefix + chunk.node.nodeDesc.commandLine.format(**chunk.node._cmdVars) + cmdSuffix

    def processChunk(self, chunk):
        try:
            chunk.logManager.start(chunk.node.verboseLevel.value)
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

# %%

def envNameExists(imageName):
    """
    Checks if an image exists with a given name
    """
    client = docker.from_env()
    try:
        client.images.get(imageName)
        return True
    except docker.errors.ImageNotFound:
        return False

class DockerNode(PluginNode):
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
        if not envNameExists(self._envName):
            chunk.node.upgradeStatusTo(Status.BUILD)
            self.build()
            chunk.upgradeStatusTo(Status.NONE)
  
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
            chunk.logManager.start(chunk.node.verboseLevel.value)
            with open(chunk.logFile, 'w') as logF:
                cmd = self.buildCommandLine(chunk)
                chunk.status.commandLine = cmd
                chunk.saveStatusFile()
                print(' - commandLine: {}'.format(cmd))
                print(' - logFile: {}'.format(chunk.logFile))
                #popen doesnt work with docker, also move to node folder
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