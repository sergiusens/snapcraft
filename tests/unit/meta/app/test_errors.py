# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2017-2019 Canonical Ltd
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

from testtools.matchers import Equals

from snapcraft.internal.meta.app import errors
from tests import unit


class ErrorFormattingTestCase(unit.TestCase):

    scenarios = (
        (
            "InvalidAppCommandNotExecutable",
            {
                "exception": errors.InvalidAppCommandNotExecutable,
                "kwargs": {"command": "test-command", "app_name": "test-app"},
                "expected_message": (
                    "Failed to generate snap metadata: "
                    "The specified command 'test-command' defined in the app "
                    "'test-app' is not executable."
                ),
            },
        ),
        (
            "InvalidAppCommandFormatError",
            {
                "exception": errors.InvalidAppCommandFormatError,
                "kwargs": {"command": "test-command", "app_name": "test-app"},
                "expected_message": (
                    "Failed to generate snap metadata: "
                    "The specified command 'test-command' defined in the app "
                    "'test-app' does not match the pattern expected by snapd.\n"
                    "The command must consist only of alphanumeric characters, spaces, "
                    "and the following special characters: / . _ # : $ -"
                ),
            },
        ),
        (
            "InvalidCommandChainError",
            {
                "exception": errors.InvalidCommandChainError,
                "kwargs": {"item": "test-chain", "app_name": "test-app"},
                "expected_message": (
                    "Failed to generate snap metadata: "
                    "The command-chain item 'test-chain' defined in the app 'test-app' "
                    "does not exist or is not executable.\n"
                    "Ensure that 'test-chain' is relative to the prime directory."
                ),
            },
        ),
        (
            "PrimedCommandNotFoundError",
            {
                "exception": errors.PrimedCommandNotFoundError,
                "kwargs": {"command": "test-command"},
                "expected_message": (
                    "Failed to generate snap metadata: "
                    "Specified command 'test-command' was not found.\n"
                    "Verify the command is correct and for a more deterministic outcome, "
                    "specify the relative path to the command from the prime directory."
                ),
            },
        ),
    )

    def test_error_formatting(self):
        self.assertThat(
            str(self.exception(**self.kwargs)), Equals(self.expected_message)
        )
