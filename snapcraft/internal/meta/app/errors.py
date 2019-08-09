# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2019 Canonical Ltd
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

from snapcraft.internal import errors


class InvalidAppCommandNotExecutable(errors.SnapcraftError):

    fmt = (
        "Failed to generate snap metadata: "
        "The specified command {command!r} defined in the app {app_name!r} "
        "is not executable."
    )

    def __init__(self, command, app_name):
        super().__init__(command=command, app_name=app_name)


class InvalidAppCommandFormatError(errors.SnapcraftError):

    fmt = (
        "Failed to generate snap metadata: "
        "The specified command {command!r} defined in the app {app_name!r} does "
        "not match the pattern expected by snapd.\n"
        "The command must consist only of alphanumeric characters, spaces, and the "
        "following special characters: / . _ # : $ -"
    )

    def __init__(self, command, app_name):
        super().__init__(command=command, app_name=app_name)


class InvalidCommandChainError(errors.SnapcraftError):

    fmt = (
        "Failed to generate snap metadata: "
        "The command-chain item {item!r} defined in the app {app_name!r} does "
        "not exist or is not executable.\n"
        "Ensure that {item!r} is relative to the prime directory."
    )

    def __init__(self, item, app_name):
        super().__init__(item=item, app_name=app_name)


class PrimedCommandNotFoundError(errors.SnapcraftError):
    fmt = (
        "Failed to generate snap metadata: "
        "Specified command {command!r} was not found.\n"
        "Verify the command is correct and for a more "
        "deterministic outcome, specify the relative path "
        "to the command from the prime directory."
    )

    def __init__(self, command: str) -> None:
        super().__init__(command=command)


class ShebangNotFoundError(Exception):
    """Internal exception for when a shebang is not found."""


class ShebangInRoot(Exception):
    """Internal exception for when a shebang is part of the root."""
