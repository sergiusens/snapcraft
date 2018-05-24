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
import select
import shlex
import shutil
import socket
import subprocess
import sys
import telnetlib
from time import sleep
from typing import List, Sequence

import paramiko

from snapcraft.internal.build_providers import errors


logger = logging.getLogger(__name__)


def _run(command: List) -> None:
    logger.debug('Running {}'.format(' '.join(command)))
    subprocess.check_call(command)


def _run_output(command: List) -> bytes:
    logger.debug('Running {}'.format(' '.join(command)))
    return subprocess.check_output(command)


def _popen(command: List) -> subprocess.Popen:
    logger.debug('Running {}'.format(' '.join(command)))
    return subprocess.Popen(command)


def _get_qemu_command() -> str:
    # TODO support more architectures.
    return 'qemu-system-x86_64'


class QemuDriver:
    """A driver to interact with qemu virtual machines."""

    provider_name = 'qemu'
    _PROJECT_DEV = 'project_dev'
    _PROJECT_MOUNT = 'project_mount'

    def __init__(self, *, ssh_key_file: str) -> None:
        """Initialize a QemuCommand instance.

        :raises errors.ProviderCommandNotFound:
            if the relevant qemu command is not found.
        """
        provider_cmd = _get_qemu_command()
        if not shutil.which(provider_cmd):
            raise errors.ProviderCommandNotFound(command=provider_cmd)
        self.provider_cmd = provider_cmd
        # TODO detect collisions and make dynamic
        self.telnet_port = 64444
        # TODO detect collisions and make dynamic
        self.ssh_port = 5555
        self._ssh_key_file = ssh_key_file
        self._qemu_proc = None  # type: subprocess.Popen

    def launch(self, *, hda: str, qcow2_drives: Sequence,
               project_9p_dev: str, ram: str=None,
               enable_kvm: bool=True) -> None:
        cmd = [
            'sudo', self.provider_cmd,
            '-m', ram,  # '-nographic',
            '-monitor', 'telnet::{},server,nowait'.format(self.telnet_port),
            '-hda', hda,
            '-fsdev', 'local,id={},path={},security_model=none'.format(
                self._PROJECT_DEV, project_9p_dev),
            '-device', 'virtio-9p-pci,fsdev={},mount_tag={}'.format(
                self._PROJECT_DEV, self._PROJECT_MOUNT),
            '-device', 'e1000,netdev=net0',
            '-netdev', 'user,id=net0,hostfwd=tcp::{}-:22'.format(
                self.ssh_port)]
        for drive in qcow2_drives:
            cmd.append('-drive')
            cmd.append('file={},if=virtio,format=qcow2'.format(drive))
        if enable_kvm:
            cmd.append('-enable-kvm')

        try:
            self._qemu_proc = _popen(cmd)
        except subprocess.CalledProcessError as process_error:
            raise errors.ProviderLaunchError(
                provider_name=self.provider_name,
                exit_code=process_error.returncode) from process_error
        self._wait_for_ssh()

    def stop(self, *, instance_name: str) -> None:
        telnet = telnetlib.Telnet(host='localhost', port=self.telnet_port)
        telnet.read_until('(qemu) '.encode())
        telnet.write('savevm latest\n'.encode())
        telnet.read_until('(qemu) '.encode())
        telnet.write('quit\n'.encode())

        # try:
        #    _run(cmd)
        # except (EOFError, OSError) as telnet_error:
        #    raise errors.ProviderStopError(
        #         provider_name=self.provider_name,
        #         exit_code=None) from telnet_error

    def execute(self, *, command: List[str]) -> None:
        # Properly quote and join the command
        command_string = ' '.join([shlex.quote(c) for c in command])

        # Start up an ssh session
        # TODO startup the session and channel only once to send over
        # multiple commands over the same connection.
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect('localhost', port=self.ssh_port,
                    username='builder', key_filename=self._ssh_key_file)
        channel = ssh.get_transport().open_session()
        channel.get_pty()
        channel.exec_command(command_string)

        channel.settimeout(0.0)
        while True:
            r, w, e = select.select([channel], [], [])
            if channel in r:
                try:
                    x = channel.recv(1024).decode()
                    if len(x) == 0:
                        break
                    sys.stdout.write(x)
                    sys.stdout.flush()
                except socket.timeout:
                    pass
        ssh.close()
        # except subprocess.CalledProcessError as process_error:
        #     raise errors.ProviderExecError(
        #         provider_name=self.provider_name,
        #         command=command,
        #         exit_code=process_error.returncode) from process_error

    def _wait_for_ssh(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = None
        while result != 0:
            sleep(20)
            result = sock.connect_ex(('localhost', self.ssh_port))
            logger.debug('Pinging for ssh availability: port check {}'.format(
                result))
