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
import enum
import logging
import os
import tempfile
from collections import namedtuple
from typing import List, Sequence

import petname
from xdg import BaseDirectory

from . import errors, images
from ._install_registry import InstallRegistry
from snapcraft.internal import repo, steps


logger = logging.getLogger(__name__)


_STORE_ASSERTION_KEY = (
    "BWDEoaqyr25nF5SNCvEv2v7QnM9QsfCc0PBMYD_i2NGSQ32EF2d4D0hqUel3m8ul"
)


class _Ops(enum.Enum):

    NOP = 0
    INJECT = 1
    INSTALL = 2
    REFRESH = 3


_SnapOp = namedtuple("_SnapOp", ["snap_name", "op"])


class Provider:

    __metaclass__ = abc.ABCMeta

    _SNAPS_MOUNTPOINT = os.path.join(os.path.sep, "var", "cache", "snapcraft", "snaps")

    def __init__(self, *, project, echoer, instance_name: str = None) -> None:
        self.project = project
        self.echoer = echoer
        # Once https://github.com/CanonicalLtd/multipass/issues/220 is
        # closed we can prepend snapcraft- again.
        if project.info is not None and project.info.name is not None:
            self.instance_name = "snapcraft-{}".format(project.info.name)
        else:
            # This is just a safe fallback.
            self.instance_name = petname.Generate(2, "-")

        if project.info.version:
            self.snap_filename = "{}_{}_{}.snap".format(
                project.info.name, project.info.version, project.deb_arch
            )
        else:
            self.snap_filename = "{}_{}.snap".format(
                project.info.name, project.deb_arch
            )

        self.provider_project_dir = os.path.join(
            BaseDirectory.xdg_cache_home, "snapcraft", "projects", project.info.name
        )

        self._install_registry = InstallRegistry(
            os.path.join(self.provider_project_dir, "snaps")
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
    def _mount_snaps_directory(self) -> str:
        """Mount the host directory with snaps into the provider."""

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

    def execute_step(self, step: steps.Step) -> None:
        self._run(command=["sudo", "snapcraft", step.name])

    def pack_project(self) -> None:
        self._run(command=["sudo", "snapcraft", "snap"])

    def _disable_and_wait_for_refreshes(self):
        # Disable autorefresh for 15 minutes,
        # https://github.com/snapcore/snapd/pull/5436/files
        now_plus_15 = datetime.datetime.now() + datetime.timedelta(minutes=15)
        self._run(
            [
                "sudo",
                "snap",
                "set",
                "core",
                "refresh.hold={}Z".format(now_plus_15.isoformat()),
            ]
        )
        # Auto refresh may have kicked in while setting the hold.
        logger.debug("Waiting for pending snap auto refreshes.")
        with contextlib.suppress(errors.ProviderExecError):
            self._run(
                ["sudo", "snap", "watch", "--last=auto-refresh"], hide_output=True
            )

    def setup_snapcraft(self) -> None:
        # Pre check if need need any setup
        snap_ops = []  # type: List[_SnapOp]
        # Order is important, first comes the base, then comes snapcraft.
        for snap_name in ["core", "snapcraft"]:
            snap_op = _SnapOp(snap_name, self._get_required_op(snap_name))
            snap_ops.append(snap_op)

        # Return early if there is nothing to do.
        if all([snap_op.op == _Ops.NOP for snap_op in snap_ops]):
            return

        # Make the snaps available to the provider if we need to inject a snap.
        if any([snap_op.op == _Ops.INJECT for snap_op in snap_ops]):
            self._mount_snaps_directory()

        # Disable refreshes so they do not interfere with installation ops.
        self._disable_and_wait_for_refreshes()

        # Add the store assertion, common to all snaps.
        self._inject_assertions(
            [["account-key", "public-key-sha3-384={}".format(_STORE_ASSERTION_KEY)]]
        )

        # snap_ops should be in the correct order per the above logic.
        for snap_op in snap_ops:
            self._install_snap(snap_op)

        # Finally unmount the snaps directory if it was mounted.
        if any([snap_op.op == _Ops.INJECT for snap_op in snap_ops]):
            self._umount(mountpoint=self._SNAPS_MOUNTPOINT)

    def _inject_assertions(self, assertions: List[List[str]]):
        with tempfile.NamedTemporaryFile() as assertion_file:
            for assertion in assertions:
                assertion_file.write(repo.snaps.get_assertion(assertion))
                assertion_file.write(b"\n")
            assertion_file.flush()

            self._push_file(source=assertion_file.name, destination=assertion_file.name)
            self._run(["sudo", "snap", "ack", assertion_file.name])

    def _get_required_op(self, snap_name: str) -> _Ops:
        # TODO find a better way to do this.
        snap = repo.snaps.SnapPackage(snap_name)
        # This means we are not running from the snap.
        if not snap.installed:
            try:
                self._run(["snap", "info", snap.name])
                return _Ops.REFRESH
            except errors.ProviderExecError:
                return _Ops.INSTALL

        snap_info = snap.get_local_snap_info()

        if self._install_registry.exists(
            snap_name=snap_name, snap_revision=snap_info["revision"]
        ):
            return _Ops.NOP
        else:
            return _Ops.INJECT

    def _install_snap(self, snap_op: _SnapOp) -> None:
        if snap_op.op == _Ops.NOP:
            return

        snap = repo.snaps.SnapPackage(snap_op.snap_name)

        cmd = ["sudo", "snap"]

        if snap_op.op == _Ops.INJECT:
            cmd.append("install")
            snap_info = snap.get_local_snap_info()
            snap_revision = snap_info["revision"]

            if snap_info["revision"].startswith("x"):
                cmd.append("--dangerous")
            else:
                self._inject_assertions(
                    [
                        ["snap-declaration", "snap-name={}".format(snap.name)],
                        [
                            "snap-revision",
                            "snap-revision={}".format(snap_info["revision"]),
                            "snap-id={}".format(snap_info["id"]),
                        ],
                    ]
                )

            if snap_info["confinement"] == "classic":
                cmd.append("--classic")

            # https://github.com/snapcore/snapd/blob/master/snap/info.go
            # MountFile
            snap_file_name = "{}_{}.snap".format(snap.name, snap_revision)
            cmd.append(os.path.join(self._SNAPS_MOUNTPOINT, snap_file_name))
        elif snap_op.op == _Ops.INSTALL or snap_op == _Ops.REFRESH:
            cmd.append(snap_op.op.name.lower())
            snap_info = snap.get_store_snap_info()
            # TODO support other channels
            snap_revision = snap_info["channels"]["latest/stable"]["revision"]
            confinement = snap_info["channels"]["latest/stable"]["confinement"]
            if confinement == "classic":
                cmd.append("--classic")
            cmd.append(snap.name)
        else:
            raise RuntimeError("The operation {!r} is not supported".format(snap_op.op))

        self._run(cmd)
        self._install_registry.mark(snap_name=snap.name, snap_revision=snap_revision)
