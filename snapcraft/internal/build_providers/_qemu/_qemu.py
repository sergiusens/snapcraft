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
import tempfile
from distutils import util
from textwrap import dedent
from typing import Sequence

import yaml

from ._qemu_driver import MountDevice, QemuDriver
from ._keys import SSHKey
from snapcraft.file_utils import get_tool_path
from snapcraft.internal.build_providers import errors
from snapcraft.internal.build_providers._base_provider import Provider


logger = logging.getLogger(__name__)


class Qemu(Provider):
    """A multipass provider for snapcraft to execute its lifecycle."""

    @classmethod
    def _get_provider_name(cls) -> str:
        return "qemu"

    @classmethod
    def get_requires_sudo(cls) -> bool:
        return True

    def _run(self, command: Sequence[str], hide_output: bool = False) -> None:
        self._qemu_driver.execute(command=command, hide_output=hide_output)

    def _launch(self) -> None:
        self.setup_disk_image(image_path=self._hda_img)
        self._setup_cloud_img()
        mount_devices = [self._snaps_dir_device_mount, self._project_device_mount]

        try:
            enable_kvm = util.strtobool(os.getenv("SNAPCRAFT_ENABLE_KVM", "yes"))
        except ValueError:
            enable_kvm = True

        self._qemu_driver.launch(
            hda=self._hda_img,
            qcow2_drives=[self._cloud_img],
            # TODO RAM adjustments (downscaling).
            ram="2048",
            mount_devices=mount_devices,
            enable_kvm=enable_kvm,
        )

    def _mount(self, *, mountpoint: str, dev_or_path: str) -> None:
        self._qemu_driver.execute(
            command=[
                "sudo",
                "sh",
                "-c",
                "mkdir -p {mountpoint}; "
                "mount {dev} {mountpoint} -t 9p -o trans=virtio,noauto".format(
                    mountpoint=mountpoint, dev=dev_or_path
                ),
            ]
        )

    def _umount(self, *, mountpoint: str) -> None:
        self._qemu_driver.execute(
            command=["sudo", "sh", "-c", "umount {}".format(mountpoint)]
        )

    def _mount_snaps_directory(self) -> None:
        # https://github.com/snapcore/snapd/blob/master/dirs/dirs.go
        # CoreLibExecDir
        self._mount(
            mountpoint=self._SNAPS_MOUNTPOINT,
            dev_or_path=self._snaps_dir_device_mount.mount_tag,
        )

    def _unmount_snaps_directory(self):
        self._umount(mountpoint=self._SNAPS_MOUNTPOINT)

    def _push_file(self, *, source: str, destination: str) -> None:
        self._qemu_driver.push_file(source=source, destination=destination)

    def provision_project(self):
        raise NotImplementedError()

    def build_project(self):
        raise NotImplementedError()

    def retrieve_snap(self) -> str:
        raise NotImplementedError()

    def shell(self) -> None:
        self._qemu_driver.shell()

    def __init__(self, *, project, echoer) -> None:
        super().__init__(project=project, echoer=echoer)

        self._hda_img = os.path.join(self.provider_project_dir, "builder.qcow2")
        self._cloud_img = os.path.join(self.provider_project_dir, "cloud.qcow2")

        self._project_device_mount = MountDevice(
            host_path=self.project._project_dir,
            dev="project_device",
            mount_tag="project_mount",
        )
        self._snaps_dir_device_mount = MountDevice(
            host_path=os.path.join("/", "var", "lib", "snapd", "snaps"),
            dev="snaps_dir_device",
            mount_tag="snaps_dir_mount",
        )

        try:
            ssh_key = SSHKey(root_dir=self.provider_project_dir)
        except errors.SSHKeyFileNotFoundError:
            logger.debug(
                "No SSH keys found. Generating SSH keys to access the environment."
            )
            ssh_key = SSHKey.new_key(root_dir=self.provider_project_dir)
        self._ssh_key = ssh_key

        self._qemu_driver = QemuDriver(
            ssh_username="snapcraft", ssh_key_file=self._ssh_key.private_key_file_path
        )

    def create(self) -> None:
        """Create the qemu instance and setup the build environment."""
        self.launch_instance()

    def destroy(self) -> None:
        """Destroy the instance, trying to stop it first."""
        self._umount(mountpoint=self.project._project_dir)
        self._qemu_driver.stop()

    def mount_project(self) -> None:
        self._mount(
            mountpoint=self.project._project_dir,
            dev_or_path=self._project_device_mount.mount_tag,
        )

    def clean_project(self) -> None:
        shutil.rmtree(self.provider_project_dir)

    def _setup_cloud_img(self):
        if os.path.exists(self._cloud_img):
            return

        public_key = self._ssh_key.get_public_key()

        with tempfile.TemporaryDirectory() as cloud_dir:
            cloud_meta = os.path.join(cloud_dir, "meta-data")
            with open(cloud_meta, "w") as cloud_meta_file:
                print(
                    dedent(
                        """\
                    local-hostname: {project_name}
                    manage_etc_hosts: true
                """
                    ).format(project_name=self.project.info.name),
                    file=cloud_meta_file,
                )
            cloud_config = os.path.join(cloud_dir, "user-data")
            cloud_config_default = self._get_cloud_user_data()
            with open(cloud_config_default) as default_cloud_config_file:
                data = yaml.load(default_cloud_config_file)
                data["users"] = [
                    {
                        "name": "snapcraft",
                        "gecos": "snap build user",
                        "shell": "/bin/bash",
                        "sudo": "ALL=(ALL) NOPASSWD:ALL",
                        "lock_passwd": True,
                        "ssh-authorized-keys": [public_key],
                    }
                ]
                with open(cloud_config, "w") as cloud_config_file:
                    print("#cloud-config", file=cloud_config_file)
                    yaml.dump(data, stream=cloud_config_file)

            cloud_img = os.path.join(cloud_dir, "cloud.img")
            genisoimage_cmd = get_tool_path("genisoimage")
            subprocess.check_output(
                [
                    genisoimage_cmd,
                    "-volid",
                    "cidata",
                    "-joliet",
                    "-rock",
                    "-quiet",
                    "-output",
                    cloud_img,
                    cloud_config,
                    cloud_meta,
                ]
            )
            os.makedirs(os.path.dirname(self._cloud_img), exist_ok=True)
            subprocess.check_call(
                ["qemu-img", "convert", cloud_img, "-O", "qcow2", self._cloud_img]
            )
