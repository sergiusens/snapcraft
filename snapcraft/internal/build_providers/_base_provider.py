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

import abc
import contextlib
import datetime
import os
import shlex
import tempfile
from typing import List

import petname
from xdg import BaseDirectory

from ._snap import SnapInjector


class Provider:

    __metaclass__ = abc.ABCMeta

    _SNAPS_MOUNTPOINT = os.path.join(os.path.sep, "var", "cache", "snapcraft", "snaps")

    def __init__(self, *, project, echoer, is_ephemeral: bool = False) -> None:
        self.project = project
        self.echoer = echoer
        self._is_ephemeral = is_ephemeral

        # Once https://github.com/CanonicalLtd/multipass/issues/220 is
        # closed we can prepend snapcraft- again.
        self.instance_name = "snapcraft-{}".format(project.info.name)
        self.project_dir = shlex.quote(project.info.name)

        if project.info.version:
            self.snap_filename = "{}_{}_{}.snap".format(
                project.info.name, project.info.version, project.deb_arch
            )
        else:
            self.snap_filename = "{}_{}.snap".format(
                project.info.name, project.deb_arch
            )

        self.provider_project_dir = os.path.join(
            BaseDirectory.save_data_path("snapcraft"), "projects", project.info.name
        )

        self.user = "snapcraft"
        # To be used only inside the provider instance
        self.project_dir = "~{}/project".format(self.user)

    def __enter__(self):
        self.create()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.destroy()

    @abc.abstractmethod
    def _run(self, command: Sequence[str], hide_output: bool = False) -> None:
        """Run a command on the instance."""

    @abc.abstractmethod
    def _launch(self):
        """Launch the instance."""

    @abc.abstractmethod
    def _mount(self, *, mountpoint: str, dev_or_path: str) -> None:
        """Mount a path from the host inside the instance."""

    @abc.abstractmethod
    def _umount(self, *, mountpoint: str) -> None:
        """Unmount the mountpoint from the instance."""

    @abc.abstractmethod
    def _mount_snaps_directory(self) -> None:
        """Mount the host directory with snaps into the provider."""

    def _unmount_snaps_directory(self) -> None:
        self._umount(mountpoint=self._SNAPS_MOUNTPOINT)

    @abc.abstractmethod
    def _push_file(self, *, source: str, destination: str) -> None:
        """Push a file into the instance."""

    @abc.abstractmethod
    def create(self) -> None:
        """Provider steps needed to create a fully functioning environment."""

    @abc.abstractmethod
    def destroy(self) -> None:
        """Provider steps needed to ensure the instance is destroyed.

        This method should be safe to call multiple times and do nothing
        if the instance to destroy is already destroyed.
        """

    @abc.abstractmethod
    def provision_project(self, tarball: str) -> None:
        """Provider steps needed to copy project assests to the instance."""

    @abc.abstractmethod
    def mount_project(self) -> None:
        """Provider steps needed to make the project available to the instance.
        """

    @abc.abstractmethod
    def build_project(self) -> None:
        """Provider steps needed build the project on the instance."""

    @abc.abstractmethod
    def retrieve_snap(self) -> str:
        """
        Provider steps needed to retrieve the built snap from the instance.

        :returns: the filename of the retrieved snap.
        :rtype: str
        """

    @abc.abstractmethod
    def shell(self) -> None:
        """Provider steps to provide a shell into the instance."""

    def setup_disk_image(self, *, image_path: str) -> None:
        if os.path.exists(image_path):
            logger.debug("Disk image previously setup.")
            return

        logger.debug("Setting up disk image.")
        images_repo = images.BuildImages()
        images_repo.setup(
            base=self.project.info.base,
            deb_arch=self.project.deb_arch,
            image_path=image_path,
            size="256G",
        )

    def launch_instance(self) -> None:
        self._launch()
        self._setup_snapcraft()
        first_run_file = os.path.join(self.provider_project_dir, "first_run")
        if not os.path.exists(first_run_file):
            self._run(command=["snapcraft", "refresh"])
            open(first_run_file, "w").close()

    def execute_step(self, step: steps.Step) -> None:
        self._run(command=["snapcraft", step.name])

    def pack_project(self) -> None:
        self._run(command=["snapcraft", "snap"])

    def _setup_snapcraft(self) -> None:
        if self._is_ephemeral:
            registry_filepath = None
        else:
            registry_filepath = os.path.join(
                self.provider_project_dir, "snap-registry.yaml"
            )
        snap_injector = SnapInjector(
            snap_dir=self._SNAPS_MOUNTPOINT,
            registry_filepath=registry_filepath,
            runner=self._run,
            snap_dir_mounter=self._mount_snaps_directory,
            snap_dir_unmounter=self._unmount_snaps_directory,
            file_pusher=self._push_file,
        )
        snap_injector.add(snap_name="core", snap_arch=self.project.deb_arch)
        snap_injector.add(snap_name="snapcraft", snap_arch=self.project.deb_arch)

        snap_injector.apply()
