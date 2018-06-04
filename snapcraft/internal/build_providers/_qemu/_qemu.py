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

import os
import shutil
import subprocess
import tempfile
from textwrap import dedent

from ._qemu_driver import QemuDriver
from snapcraft.internal.build_providers._base_provider import Provider


class Qemu(Provider):
    """A multipass provider for snapcraft to execute its lifecycle."""

    def _run(self, command) -> None:
        self._qemu_driver.execute(command=command)

    def _launch(self) -> None:
        hda_img = self._get_developer_vm_for_base('')
        cloud_img = self._create_cloud_img()
        self._qemu_driver.launch(
            hda=hda_img, qcow2_drives=[cloud_img], ram='1024',
            project_9p_dev=os.path.abspath('.'))

    def __init__(self, *, project, echoer) -> None:
        super().__init__(project=project, echoer=echoer)
        self._qemu_driver = QemuDriver(
            ssh_username='builder',
            ssh_key_file='/home/sergiusens/.ssh/id_rsa')

    def create(self) -> None:
        """Create the qemu instance and setup the build environment."""
        self.launch_instance()
        self.refresh_snapcraft()

    def destroy(self) -> None:
        """Destroy the instance, trying to stop it first."""
        self._qemu_driver.stop()

    def mount_project(self) -> None:
        self._qemu_driver.execute(command=[
            'sudo', 'sh', '-c',
            'mkdir /{0}; '
            'mount project_mount /{0} -t 9p -o trans=virtio,noauto'.format(
                self.project_dir)])

    def build_project(self) -> None:
        # TODO add instance check.
        # Use the full path as /snap/bin is not in PATH.
        snapcraft_cmd = 'cd /{}; /snap/bin/snapcraft'.format(self.project_dir)
        self._qemu_driver.execute(command=['sudo', 'sh', '-c', snapcraft_cmd])

    def _get_developer_vm_for_base(self, base: str) -> str:
        # TODO implement correctly
        base = '/home/sergiusens/Downloads/base-builder.qcow2'
        builder_img_qcow2 = os.path.join(
            '/home/sergiusens/test-vm/builder.qcow2')
        shutil.copyfile(base, builder_img_qcow2)
        return builder_img_qcow2

    def _create_cloud_img(self) -> str:
        with tempfile.TemporaryDirectory() as cloud_dir:
            cloud_meta = os.path.join(cloud_dir, 'meta-data')
            with open(cloud_meta, 'w') as cloud_meta_file:
                print('local-hostname: base-builder',
                      file=cloud_meta_file)
            cloud_config = os.path.join(cloud_dir, 'user-data')
            with open(cloud_config, 'w') as cloud_config_file:
                print(dedent("""\
                    #cloud-config
                    package_update: true
                    package_upgrade: true
                    users:
                        - name: builder
                          gecos: snap build user
                          shell: /bin/bash
                          sudo: ALL=(ALL) NOPASSWD:ALL
                          lock_passwd: true
                          ssh-authorized-keys:
                            - ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC69cR5d1juYmUYqB8khseKzjIfbomBORmEIyFPaieVG86ioW3CI4c2bHbD6yowED8mseKozpTIT3Xh2mepRqihY1h1wE7yEnQnLBMcE8ADJe5ah5HKOXboS2geMeEROGz9jzqbx62nL4+Yo46JOgqhUiJb3zPH3HPljeHThJhJBIOEEy3SpBC9EMs+YQpkYsQ64cu4ZSejzHTZ+DOSB0bHLaHTpU3lS8Tkp8MyAF/chmvlQKUOhAIzBraGEhtyLSj4ze6Cc+xi0SiTFj6++GG9c6MC16QQSO3Gj9avRYRcVe6RJw5OV5GR3XEwOsCBj+EcdmG7xd9JRKPJAQP3MMM3
                """), file=cloud_config_file)  # noqa: E501

            cloud_img = os.path.join(cloud_dir, 'cloud.img')
            subprocess.check_call(['cloud-localds', cloud_img,
                                   cloud_config, cloud_meta])
            cloud_img_qcow2 = os.path.join('/home/sergiusens/test-vm',
                                           'cloud.qcow2')
            subprocess.check_call(['qemu-img', 'convert', cloud_img,
                                   '-O', 'qcow2', cloud_img_qcow2])
        return cloud_img_qcow2
