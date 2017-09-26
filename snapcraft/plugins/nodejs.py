# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2015-2017 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""The nodejs plugin is useful for node/npm based parts.

The plugin uses node to install dependencies from `package.json`. It
also sets up binaries defined in `package.json` into the `PATH`.

This plugin uses the common plugin keywords as well as those for "sources".
For more information check the 'plugins' topic for the former and the
'sources' topic for the latter.

Additionally, this plugin uses the following plugin-specific keywords:

    - node-engine:
      (string)
      The version of nodejs you want the snap to run on.
    - npm-run:
      (list)
      A list of targets to `npm run`.
      These targets will be run in order, after `npm install`
    - node-package-manager
      (string; default: npm)
      The language package manager to use to drive installation
      of node packages. Can be either `npm` (default) or `yarn`.
"""

import collections
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys

import snapcraft
from snapcraft import sources
from snapcraft.file_utils import link_or_copy_tree, link_or_copy
from snapcraft.internal import errors

logger = logging.getLogger(__name__)

_NODEJS_BASE = 'node-v{version}-linux-{arch}'
_NODEJS_VERSION = '6.10.2'
_NODEJS_TMPL = 'https://nodejs.org/dist/v{version}/{base}.tar.gz'
_NODEJS_ARCHES = {
    'i386': 'x86',
    'amd64': 'x64',
    'armhf': 'armv7l',
    'arm64': 'arm64',
}
_YARN_URL = 'https://yarnpkg.com/latest.tar.gz'


class NodePlugin(snapcraft.BasePlugin):

    @classmethod
    def schema(cls):
        schema = super().schema()

        schema['properties']['node-engine'] = {
            'type': 'string',
            'default': _NODEJS_VERSION
        }
        schema['properties']['node-package-manager'] = {
            'type': 'string',
            'default': 'npm',
            'enum': ['npm', 'yarn'],
        }
        schema['properties']['npm-run'] = {
            'type': 'array',
            'minitems': 1,
            'uniqueItems': False,
            'items': {
                'type': 'string'
            },
            'default': []
        }

        if 'required' in schema:
            del schema['required']

        return schema

    @classmethod
    def get_build_properties(cls):
        # Inform Snapcraft of the properties associated with building. If these
        # change in the YAML Snapcraft will consider the build step dirty.
        return ['npm-run']

    @classmethod
    def get_pull_properties(cls):
        # Inform Snapcraft of the properties associated with pulling. If these
        # change in the YAML Snapcraft will consider the build step dirty.
        return ['node-engine', 'node-package-manager']

    def __init__(self, name, options, project):
        super().__init__(name, options, project)
        self._npm_dir = os.path.join(self.partdir, 'npm')
        self._nodejs_tar = sources.Tar(get_nodejs_release(
            self.options.node_engine, self.project.deb_arch), self._npm_dir)
        if self.options.node_package_manager == 'yarn':
            logger.warning(
                'EXPERIMENTAL: use of yarn to manage packages is experimental')
            self._yarn_tar = sources.Tar(_YARN_URL, self._npm_dir)
        self._manifest = collections.OrderedDict()

    def pull(self):
        super().pull()
        os.makedirs(self._npm_dir, exist_ok=True)
        self._nodejs_tar.download()
        if hasattr(self, '_yarn_tar'):
            self._yarn_tar.download()
        # do the install in the pull phase to download all dependencies.
        self._install(rootdir=self.sourcedir)

    def clean_pull(self):
        super().clean_pull()

        # Remove the npm directory (if any)
        if os.path.exists(self._npm_dir):
            shutil.rmtree(self._npm_dir)

    def build(self):
        super().build()
        installed_node_packages = self._install(rootdir=self.builddir)
        lock_file_path = os.path.join(self.sourcedir, 'yarn.lock')

        if os.path.isfile(lock_file_path):
            with open(lock_file_path) as lock_file:
                self._manifest['yarn-lock-contents'] = lock_file.read()

        self._manifest['node-packages'] = [
            '{}={}'.format(name, installed_node_packages[name])
            for name in installed_node_packages
        ]

    def _install(self, rootdir):
        self._nodejs_tar.provision(
            self._npm_dir, clean_target=False, keep_tarball=True)
        self._yarn_tar.provision(
            self._npm_dir, clean_target=False, keep_tarball=True)
        cmd = [os.path.join(self._npm_dir, 'bin',
               self.options.node_package_manager)]
        npm_cmd = [os.path.join(self._npm_dir, 'bin', 'npm')]

        flags = []
        if rootdir == self.builddir:
            flags = ['--offline', '--prod']

        self.run(cmd + ['install'] + flags, rootdir)
        # We run npm regardless of node-package-manager being yarn
        # as yarn isn't doing the right thing.
        self.run(npm_cmd + ['pack'], rootdir)

        # npm pack will create a tarball of the form
        # <package-name>-<package-version>.tgz
        package_json = self._get_package_json(rootdir)
        package_tar_path = '{name}-{version}.tgz'.format(**package_json)

        package_dir = os.path.join(rootdir, 'package')
        package_tar = sources.Tar(package_tar_path, rootdir)
        package_tar.file = package_tar_path
        os.makedirs(package_dir, exist_ok=True)
        package_tar.provision(package_dir)

        # TODO make sure we add support for npm lock files.
        with contextlib.suppress(FileNotFoundError):
            shutil.copy(os.path.join(rootdir, 'yarn.lock'),
                        os.path.join(package_dir, 'yarn.lock'))

        self.run(cmd + ['install'] + flags, package_dir)

        _create_bins(package_json, package_dir)

        for target in self.options.npm_run:
            self.run(cmd + ['run', target], rootdir)

        dependencies = {}
        if rootdir == self.builddir:
            link_or_copy_tree(package_dir, self.installdir)
            dependencies = self._get_installed_node_packages(
                npm_cmd, self.installdir)
            link_or_copy(os.path.join(self._npm_dir, 'bin', 'node'),
                         os.path.join(self.installdir, 'bin', 'node'))

        return dependencies

    def run(self, cmd, rootdir):
        super().run(cmd, env=self._build_environment(), cwd=rootdir)

    def run_output(self, cmd, rootdir):
        return super().run_output(cmd, env=self._build_environment(),
                                  cwd=rootdir)

    def _get_package_json(self, rootdir):
        with open(os.path.join(rootdir, 'package.json')) as json_file:
            return json.load(json_file)

    def _get_installed_node_packages(self, package_manager, cwd):
        cmd = package_manager + ['ls', '--global', '--json']
        try:
            output = self.run_output(cmd, cwd)
        except subprocess.CalledProcessError as error:
            # XXX When dependencies have missing dependencies, an error like
            # this is printed to stderr:
            # npm ERR! peer dep missing: glob@*, required by glob-promise@3.1.0
            # retcode is not 0, which raises an exception.
            output = error.output.decode(sys.getfilesystemencoding()).strip()
        packages = collections.OrderedDict()
        output_json = json.loads(
            output, object_pairs_hook=collections.OrderedDict)
        dependencies = output_json['dependencies']
        while dependencies:
            key, value = dependencies.popitem(last=False)
            # XXX Just as above, dependencies without version are the ones
            # missing.
            if 'version' in value:
                packages[key] = value['version']
            if 'dependencies' in value:
                dependencies.update(value['dependencies'])
        return packages

    def get_manifest(self):
        return self._manifest

    def _build_environment(self):
        env = os.environ.copy()
        npm_bin = os.path.join(self._npm_dir, 'bin')
        if env.get('PATH'):
            new_path = '{}:{}'.format(npm_bin, env.get('PATH'))
        else:
            new_path = npm_bin
        env['PATH'] = new_path
        return env


def _create_bins(package_json, directory):
    binaries = package_json.get('bin')
    if not binaries:
        return

    bin_dir = os.path.join(directory, 'bin')
    os.makedirs(bin_dir, exist_ok=True)

    if type(binaries) == dict:
        for bin_name, bin_path in binaries.items():
            link_target = os.path.join(bin_dir, bin_name)
            link_source = os.path.join('..', bin_path)
            os.symlink(link_source, link_target)
    else:
        raise NotImplementedError(
            'The plugin is not prepared to handle bin entries of '
            'type {!r}'.format(type(binaries)))


def _get_nodejs_base(node_engine, machine):
    if machine not in _NODEJS_ARCHES:
        raise errors.SnapcraftEnvironmentError(
            'architecture not supported ({})'.format(machine))
    return _NODEJS_BASE.format(version=node_engine,
                               arch=_NODEJS_ARCHES[machine])


def get_nodejs_release(node_engine, arch):
    return _NODEJS_TMPL.format(version=node_engine,
                               base=_get_nodejs_base(node_engine, arch))
