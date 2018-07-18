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

import contextlib
import logging
import select
import shlex
import shutil
import socket
import sys
import telnetlib
import termios
import time
import tty
from typing import Sequence

import paramiko

from ._mount_device import MountDevice
from ._qemu_command import QemuCommand
from ._qemu_img_command import QemuImgCommand
from ._snapshot import has_tag
from snapcraft.internal.build_providers import errors


logger = logging.getLogger(__name__)
# Avoid getting paramiko logs which are overly verbose.
logging.getLogger("paramiko").setLevel(logging.CRITICAL)


class QemuDriver:
    """A driver to interact with qemu virtual machines."""

    provider_name = "qemu"

    def __init__(self, *, ssh_username: str, ssh_key_file: str) -> None:
        """Initialize a QemuDriver instance.

        :raises errors.ProviderCommandNotFound:
            if the relevant qemu command is not found.
        """
        self._ssh_username = ssh_username
        self._ssh_key_file = ssh_key_file
        self._ssh_client = paramiko.SSHClient()
        self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # TODO detect collisions and make dynamic
        self._qemu_cmd = QemuCommand(ssh_port=5555, telnet_port=64444)
        # If set, we will the vm state (savevm)
        self._vm_state_tag = None  # type: str

    def launch(
        self,
        *,
        hda: str,
        qcow2_drives: Sequence,
        mount_devices: Sequence[MountDevice],
        ram: str = None,
        enable_kvm: bool = True
    ) -> None:
        # Setup the tag to save the vm state.
        self._vm_state_tag = "{}-ram".format(ram)
        # Check if we have a snapshot.
        snapshots = QemuImgCommand().snapshot_list(filename=hda)
        # Check if the vm state been saved with this tag before.
        if has_tag(snapshots, self._vm_state_tag):
            tag = self._vm_state_tag
        else:
            tag = None
        self._qemu_cmd.setup(
            hda=hda,
            qcow2_drives=qcow2_drives,
            mount_devices=mount_devices,
            ram=ram,
            loadvm_tag=tag,
            enable_kvm=enable_kvm,
        )
        self._qemu_cmd.start()
        self._wait_for_ssh()
        self._wait_for_cloudinit()

    def stop(self) -> None:
        self._ssh_client.close()
        try:
            telnet = telnetlib.Telnet(host="localhost", port=self._qemu_cmd.telnet_port)
        except socket.gaierror as telnet_error:
            raise errors.ProviderCommunicationError(
                protocol="telnet",
                port=self._qemu_cmd.telnet_port,
                error=telnet_error.strerror,
            ) from telnet_error
        try:
            if self._vm_state_tag is not None:
                telnet.read_until("(qemu) ".encode())
                telnet.write("savevm {}\n".format(self._vm_state_tag).encode())
            telnet.read_until("(qemu) ".encode())
            telnet.write("quit\n".encode())
        except (OSError, EOFError) as telnet_error:
            raise errors.ProviderStopError(
                provider_name=self.provider_name, exit_code=None
            ) from telnet_error
        self._qemu_cmd.join()

    def _get_ssh_shell(self) -> paramiko.Channel:
        term_size = shutil.get_terminal_size()

        channel = self._ssh_client.get_transport().open_session()
        channel.get_pty(width=term_size.columns, height=term_size.lines)
        channel.settimeout(0.0)

        return channel

    def execute(self, *, command: Sequence[str], hide_output=False) -> None:
        # Properly quote and join the command
        command_string = " ".join([shlex.quote(c) for c in command])

        channel = self._get_ssh_shell()
        channel.exec_command(command_string)

        try:
            exit_code = _handle_ssh_output(channel, hide_output=hide_output)
        finally:
            channel.close()

        if exit_code != 0:
            raise errors.ProviderExecError(
                provider_name=self.provider_name, command=command, exit_code=exit_code
            )

    def shell(self, project_dir: str) -> None:
        channel = self._get_ssh_shell()
        channel.invoke_shell()
        try:
            _handle_ssh_shell(channel)
        finally:
            channel.close()

    def push_file(self, *, source: str, destination: str) -> None:
        with self._ssh_client.open_sftp() as sftp:
            sftp.put(source, destination)

    def _wait_for_ssh(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            while True:
                time.sleep(1)
                result = s.connect_ex(("localhost", self._qemu_cmd.ssh_port))
                logger.debug(
                    "Pinging for ssh availability: port check " "{}".format(result)
                )
                if result == 0:
                    break

        while True:
            time.sleep(1)
            try:
                self._ssh_client.connect(
                    "localhost",
                    port=self._qemu_cmd.ssh_port,
                    username=self._ssh_username,
                    key_filename=self._ssh_key_file,
                )
                break
            except paramiko.SSHException as ssh_error:
                logger.debug(
                    "Pinging for ssh using {}: {}".format(
                        self._ssh_key_file, str(ssh_error)
                    )
                )

    def _wait_for_cloudinit(self):
        while True:
            time.sleep(1)
            with contextlib.suppress(errors.ProviderExecError):
                self.execute(command=["test", "-f", "/run/cloud-init/result.json"])
                break


def _handle_ssh_output(channel: paramiko.Channel, *, hide_output: bool) -> int:
    exit_code = None
    while exit_code is None:
        if channel.recv_ready():
            data_stream_b = channel.recv(1024)
            if not hide_output:
                try:
                    data_stream = data_stream_b.decode()
                except UnicodeDecodeError:
                    data_stream = data_stream_b.decode("latin-1", "surrogateescape")
                sys.stdout.write(data_stream)
                sys.stdout.flush()
        if channel.exit_status_ready():
            exit_code = channel.recv_exit_status()

    return exit_code


def _handle_ssh_shell(channel):
    oldtty = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        channel.settimeout(0.0)

        while True:
            r, w, e = select.select([channel, sys.stdin], [], [], 0.2)
            if channel in r:
                try:
                    data_stream_b = channel.recv(1024)
                    try:
                        data_stream = data_stream_b.decode()
                    except UnicodeDecodeError:
                        data_stream = data_stream_b.decode("latin-1", "surrogateescape")
                    if len(data_stream) == 0:
                        break
                    sys.stdout.write(data_stream)
                    sys.stdout.flush()
                except socket.timeout:
                    pass
            if sys.stdin in r:
                x = sys.stdin.read(1)
                channel.send(x)

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, oldtty)
        pass
