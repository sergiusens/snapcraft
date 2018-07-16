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


class InstallRegistry:
    def __init__(self, registry_directory: str) -> None:
        self._registry_directory = registry_directory

    def _get_filepath(self, snap_name: str, snap_revision: str) -> str:
        return os.path.join(
            self._registry_directory, "{}_{}".format(snap_name, snap_revision)
        )

    def mark(self, *, snap_name: str, snap_revision: str) -> None:
        os.makedirs(self._registry_directory, exist_ok=True)
        open(self._get_filepath(snap_name, snap_revision), "w").close()

    def exists(self, *, snap_name: str, snap_revision: str) -> bool:
        return os.path.exists(self._get_filepath(snap_name, snap_revision))
