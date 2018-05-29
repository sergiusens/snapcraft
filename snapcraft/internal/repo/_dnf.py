# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2018 Canonical Ltd
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

import subprocess
from typing import Dict, Set, List, Tuple  # noqa: F401

from ._base import BaseRepo


class Dnf(BaseRepo):

    @classmethod
    def get_package_libraries(cls, package_name):
        return []

    @classmethod
    def get_packages_for_source_type(cls, source_type):
        return set()

    @classmethod
    def install_build_packages(cls, package_names: List[str]) -> List[str]:
        """Install packages on the host required to build.

        :param package_names: a list of package names to install.
        :type package_names: a list of strings.
        :return: a list with the packages installed and their versions.
        :rtype: list of strings.
        :raises snapcraft.repo.errors.BuildPackageNotFoundError:
            if one of the packages was not found.
        :raises snapcraft.repo.errors.PackageBrokenError:
            if dependencies for one of the packages cannot be resolved.
        :raises snapcraft.repo.errors.BuildPackagesNotInstalledError:
            if installing the packages on the host failed.
        """
        if package_names:
            subprocess.check_call(['sudo', 'dnf', '--assumeyes', 'install'] +
                                  list(package_names))
        return []

    @classmethod
    def build_package_is_valid(cls, package_name):
        return True

    @classmethod
    def is_package_installed(cls, package_name):
        pass

    @classmethod
    def get_installed_packages(cls):
        return []

    def is_valid(self, package_name):
        return True

    def get(self, package_names) -> None:
        pass

    def unpack(self, unpackdir) -> None:
        pass
