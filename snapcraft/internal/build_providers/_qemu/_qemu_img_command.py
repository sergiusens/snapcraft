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
import shutil
import subprocess
from typing import List, Sequence

from ._snapshot import Snapshot
from snapcraft.internal.build_providers import errors


logger = logging.getLogger(__name__)


def _popen(command: Sequence[str], **kwargs) -> subprocess.Popen:
    logger.debug("Running {}".format(" ".join(command)))
    return subprocess.Popen(command, **kwargs)


def _run_output(command: Sequence) -> bytes:
    logger.debug("Running {}".format(" ".join(command)))
    return subprocess.check_output(command)


class QemuImgCommand:
    def __init__(self) -> None:
        qemu_img_cmd = "qemu-img"
        if not shutil.which(qemu_img_cmd):
            raise errors.ProviderCommandNotFound(command=qemu_img_cmd)
        self._qemu_img_cmd = qemu_img_cmd

    def snapshot_list(self, *, filename: str) -> List[Snapshot]:
        output_b = _run_output([self._qemu_img_cmd, "snapshot", "-l", filename])
        output = output_b.decode()
        # Snapshot list:
        # ID        TAG                 VM SIZE                DATE       VM CLOCK  # noqa
        # 1         latest                 690M 2018-07-11 15:23:47   00:00:36.444  # noqa
        valid_output = [i for i in output.splitlines() if len(i.split()) == 6]
        return [Snapshot.from_cli_output(i) for i in valid_output]
