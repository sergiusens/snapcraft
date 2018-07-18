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

import logging
import os
import shutil
import subprocess
import threading
from typing import Sequence

from ._mount_device import MountDevice
from snapcraft.internal.build_providers import errors


logger = logging.getLogger(__name__)


def _popen(command: Sequence[str], **kwargs) -> subprocess.Popen:
    logger.debug("Running {}".format(" ".join(command)))
    return subprocess.Popen(command, **kwargs)


def _get_qemu_command() -> str:
    # TODO support more architectures.
    return "qemu-system-x86_64"


class QemuCommand(threading.Thread):

    provider_name = "qemu"

    def __init__(self, *, ssh_port: int, telnet_port: int) -> None:
        super().__init__()
        qemu_cmd = _get_qemu_command()
        if not shutil.which(qemu_cmd):
            raise errors.ProviderCommandNotFound(command=qemu_cmd)
        self._qemu_cmd = qemu_cmd

        self.ssh_port = ssh_port
        self.telnet_port = telnet_port
        self.proc = None

    def setup(
        self,
        hda: str,
        qcow2_drives: Sequence,
        mount_devices: Sequence[MountDevice],
        ram: str = None,
        loadvm_tag: str = None,
        enable_kvm: bool = True,
    ) -> None:
        self._hda = hda
        self._qcow2_drives = qcow2_drives
        self._mount_devices = mount_devices
        self._ram = ram
        self._enable_kvm = enable_kvm
        self._loadvm_tag = loadvm_tag
        self._log_file_path = os.path.join(os.path.dirname(self._hda), "vm-run.log")

    def run(self):
        if self._hda is None:
            raise RuntimeError("You cannot call run before calling setup.")

        # TODO check for latest snapshot to launch for it instead of a cold
        #      boot.
        # TODO add a spinner.
        cmd = [
            "sudo",
            self._qemu_cmd,
            "-m",
            self._ram,
            "-smp",
            "4",
            "-nographic",
            "-monitor",
            "telnet::{},server,nowait".format(self.telnet_port),
            "-hda",
            self._hda,
            "-device",
            "e1000,netdev=net0",
            "-netdev",
            "user,id=net0,hostfwd=tcp::{}-:22".format(self.ssh_port),
        ]
        for device in self._mount_devices:
            cmd.extend(
                [
                    "-virtfs",
                    "local,id={},path={},security_model=none,mount_tag={}".format(
                        device.dev, device.host_path, device.mount_tag
                    ),
                ]
            )
        for drive in self._qcow2_drives:
            cmd.append("-drive")
            cmd.append("file={},if=virtio,format=qcow2".format(drive))
        if self._loadvm_tag is not None:
            cmd.extend(["-loadvm", self._loadvm_tag])
        if self._enable_kvm:
            cmd.append("-enable-kvm")

        # TODO we might want to spawn another thread here to keep an eye on
        #      the process. This is good enough for now.
        # TODO better encapsulation on setting the log file is needed.
        with open(self._log_file_path, "w") as vm_builder_log:
            self.process = _popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=vm_builder_log,
                stderr=vm_builder_log,
            )

        exit_code = self.process.wait()
        if exit_code != 0:
            raise errors.ProviderLaunchError(
                provider_name=self.provider_name, exit_code=exit_code
            )
