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

from datetime import datetime
from typing import Sequence, Type, TypeVar


SnapshotT = TypeVar("SnapshotT", bound="Snapshot")


class Snapshot:
    @classmethod
    def from_cli_output(cls: Type[SnapshotT], output: str) -> SnapshotT:
        # 1         latest                 690M 2018-07-11 15:23:47   00:00:36.444  # noqa
        fields = output.split()
        snapshot_id = fields[0]
        tag = fields[1]
        vm_size = fields[2]
        try:
            date = datetime.strptime(
                "{} {}".format(fields[3], fields[4]), "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            date = datetime.now()
        vm_clock = fields[5]
        return cls(
            snapshot_id=snapshot_id,
            tag=tag,
            vm_size=vm_size,
            date=date,
            vm_clock=vm_clock,
        )

    def __init__(
        self, *, snapshot_id: str, tag: str, vm_size: str, date: datetime, vm_clock: str
    ) -> None:
        self.snapshot_id = snapshot_id
        self.tag = tag
        self.vm_size = vm_size
        self.date = date
        self.vm_clock = vm_clock


def has_tag(snapshots: Sequence[SnapshotT], tag: str) -> bool:
    return any([i.tag == tag for i in snapshots])
