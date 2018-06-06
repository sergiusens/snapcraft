# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2017 Canonical Ltd
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
from typing import cast, Dict, List, Union

from ._env import (  # noqa
    environment_to_replacements,
    snapcraft_global_environment,
    snapcraft_part_environment,
)
from ._schema import Validator  # noqa
from ._parts_config import PartsConfig  # noqa


def load_config(project_options=None):
    from ._config import Config
    return Config(project_options)


def replace_attr(
        attr: Union[List[str], Dict[str, str], str],
        replacements: Dict[str, str]) -> Union[List[str], Dict[str, str], str]:
    if isinstance(attr, str):
        for replacement, value in replacements.items():
            attr = attr.replace(replacement, str(value))
        return attr
    elif isinstance(attr, list) or isinstance(attr, tuple):
        return [cast(str, replace_attr(i, replacements))
                for i in attr]
    elif isinstance(attr, dict):
        return {k: cast(str, replace_attr(attr[k], replacements))
                for k in attr}

    return attr
