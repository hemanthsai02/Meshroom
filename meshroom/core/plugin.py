#!/usr/bin/env python
# coding:utf-8

"""
This file defines the nodes and logic needed for the plugin system in meshroom.
"""

import os
import logging
import urllib
from distutils.dir_util import copy_tree

from meshroom.core import desc, hashValue
from meshroom.core import plugins_folder

#FIXME: could replace with parsing to avoid dep
import docker

def install_plugin(plugin_url, run_all_build=False):
    """
    Install plugin from an url or local path.
    Regardless of the method, the content will be copied in the plugin folder of meshroom (which is added to the list of directory to load nodes from).
    There are two options :
        - having the following structure :
            - [plugin folder] (will be the plugin name)
                - meshroomNodes
                    - [code for your nodes] that contains relative path to a DockerFile|env.yaml|requirements.txt
        - having a meshroomPlugin.json file at the root of the plugin folder
    """
    logging.info("Installing plugin rom "+plugin_url)
    try:
        #if url, clone the repo
        if urllib.parse.urlparse(plugin_url).scheme in ('http', 'https','git'):
            os.chdir(plugins_folder)
            os.system("git clone "+plugin_url)
            plugin_name = plugin_url.split("/")[-1] #FIXME: eee
            plugin_root_path = os.path.join(plugins_folder, plugin_name)
        #else copy directory  to folder
        elif os.path.isdir(plugin_url):
            plugin_name = os.path.basename(plugin_url)
            plugin_root_path = os.path.join(plugins_folder, plugin_name)
            copy_tree(plugin_url, plugin_root_path)#FIXME: symlink instead? easier for dev
        else:
            ValueError("Invalid plugin path :"+plugin_url)

        logging.info("Installing "+plugin_name+" in "+plugin_root_path)

        #default values
        nodesFolder = os.path.join(plugin_root_path, "meshroomNodes") #FIXME: add to env vars

        #load json for custom install
        if os.path.isfile(os.path.join(plugin_root_path), "meshroomPlugin.json"):
            raise NotImplementedError("Install from json not supported yet")

        #load and build each node?
        if run_all_build:
            raise NotImplementedError("Prebuild not implemented yet")
    
    except Exception as ex:
        print(ex)
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
        cls._env_name=hashValue(env_content)
        return cls._env_name

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
        logging.info("Creating image "+cls.env_name+" from "+ cls.env_file)
        build_command = "docker build "+cls.env_file+" -t "+cls._env_name
        logging.info("Building...")
        os.system(build_command)
        logging.info("Done")

    def buildCommandLine(self, chunk):
        cmdPrefix = ''

        if not env_name_exists(self._env_name):
            self.build()
  
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