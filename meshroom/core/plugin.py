#!/usr/bin/env python
# coding:utf-8

"""
This file defines the nodes and logic needed for the plugin system in meshroom.
"""

import os
import logging
import urllib
from distutils.dir_util import copy_tree
from meshroom.core.node import Status

from meshroom.core import desc, hashValue
from meshroom.core import plugins_folder, defaultCacheFolder

#FIXME: could replace with parsing to avoid dep
import docker

def install_plugin(plugin_url):
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
    logging.info("Installing plugin from "+plugin_url)
    try:
        is_local = True

        #if url, clone the repo in cache
        if urllib.parse.urlparse(plugin_url).scheme in ('http', 'https','git'):
            os.chdir(defaultCacheFolder)
            os.system("git clone "+plugin_url)
            plugin_name = plugin_url.split('.git')[0].split('/')[-1]
            plugin_url = os.path.join(defaultCacheFolder, plugin_name)
            is_local = False
        
        if not os.path.isdir(plugin_url):
            ValueError("Invalid plugin path :"+plugin_url)

        #get the plugin name from folder
        plugin_name = os.path.basename(plugin_url)
        #default node location
        nodesFolder = os.path.join(plugin_url, "meshroomNodes")
        #TODO: pipeline folder
        # pipelineFolder = os.path.join(plugin_url, "meshroomPipelines")

        #load json for custom install
        if os.path.isfile(os.path.join(plugin_url, "meshroomPlugin.json")):
            raise NotImplementedError("Install from json not supported yet")
     
        logging.info("Installing "+plugin_name+" from "+plugin_url)

        #install via symlink if local, otherwise copy and delete the repo
        if is_local:
            os.symlink(nodesFolder, os.path.join(plugins_folder, plugin_name))
        else:
            copy_tree(nodesFolder, os.path.join(plugins_folder, plugin_name))
            os.removedirs(plugin_url)

    except Exception as ex:
        logging.error(ex)
        return False
        
    return True
    
class PluginNode(desc.CommandLineNode):
    #env file used to build the environement, you may overwrite this to custom the behaviour
    @property
    def env_file(cls):
        raise NotImplementedError("You must specify an env file") #FIXME: automatically look in __file__?

    #env name computed from hash, overwrite this to use a custom env 
    @property
    def _env_name(cls):
        """
        Get the env name by hashing the env files
        """
        with open(cls.env_file, 'r') as file:
            env_content = file.read()
        return "mr_plugin_"+hashValue(env_content)

    def build():
        raise RuntimeError("Virtual class must be overloaded")

    def buildCommandLine(self, chunk):
        raise RuntimeError("Virtual class must be overloaded")

#%%

def curate_env_command():
    """
    Used to unset all rez defined env that messes up with conda.
    """
    cmd=""
    for env_var in os.environ.keys():
        if ((("py" in env_var) or  ("PY" in env_var)) 
            and ("REZ" not in env_var) and ("." not in env_var) and ("-" not in env_var)):
            if env_var.endswith("()"):#function get special treatment
                cmd+='unset -f '+env_var[10:-2]+'; '
            else:
                cmd+='unset '+env_var+'; '
    return cmd

def conda_env_exist(env_name):
    """
    Checks if a specified env exists
    """
    cmd = "conda list --name "+env_name
    output = os.popen(cmd).read()
    return not output.startswith("EnvironmentLocationNotFound")

class CondaNode(PluginNode):

    def build(cls):
        """
        Build a conda env from a yaml file
        """
        logging.info("Creating conda env "+cls.env_nam+" from "+cls.env_file)
        make_env_command = (curate_env_command()
                            +" conda config --set channel_priority strict; "
                            +" conda env create --name "+cls._env_name
                            +" --file "+cls.env_file)
        logging.info("Building...")
        logging.info(make_env_command)
        os.system(make_env_command)
        logging.info("Done")
        
    def buildCommandLine(self, chunk):
        cmdPrefix = ''
        #create the env if not built yet
        if not conda_env_exist(self._env_name):
            self.build()

        #add the prefix to the command line
        cmdPrefix = curate_env_command()+" conda run --no-capture-output "+self._env_name
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

def env_name_exists(image_name):
    """
    Checks if an image exists with a given name
    """
    client = docker.from_env()
    try:
        client.images.get(image_name)
        return True
    except docker.errors.ImageNotFound:
        return False

class DockerNode(PluginNode):
    def build(cls):
        #build image 
        logging.info("Creating image "+cls._env_name+" from "+ cls.env_file)
        build_command = "docker build -f "+cls.env_file+" -t "+cls._env_name+" "+os.path.dirname(cls.env_file)
        logging.info("Building with "+build_command+" ...")
        os.system(build_command)
        logging.info("Done")

    def buildCommandLine(self, chunk):
        cmdPrefix = ''
        #if the env was never built
        if not env_name_exists(self._env_name):
            chunk.node.upgradeStatusTo(Status.BUILD)
            self.build()
            chunk.upgradeStatusTo(Status.NONE)
  
        #mount point in the working dir wich is the node dir
        mount_cl = ' --mount type=bind,source="$(pwd)",target=/node_folder '
        #add the prefix to the command line
        cmdPrefix = 'docker run -it --rm --runtime=nvidia --gpus all '+mount_cl+self._env_name+" "
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