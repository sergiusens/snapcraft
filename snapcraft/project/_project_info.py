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

import codecs
import os
from types import MappingProxyType

import yaml
import yaml.reader

from . import errors


class ProjectInfo:
    """Information gained from the snap's snapcraft.yaml file."""

    def __init__(self) -> None:
        self.snapcraft_yaml_file_path = get_snapcraft_yaml()
        self.raw_snapcraft_yaml = _load_yaml(
            yaml_file_path=self.snapcraft_yaml_file_path)

        self.name = self.raw_snapcraft_yaml['name']
        self.version = self.raw_snapcraft_yaml.get('version')
        self.summary = self.raw_snapcraft_yaml.get('summary')
        self.description = self.raw_snapcraft_yaml.get('description')
        self.confinement = self.raw_snapcraft_yaml.get('confinement')
        self.grade = self.raw_snapcraft_yaml.get('grade')
        self.base = self.raw_snapcraft_yaml.get('base')


def _load_yaml(*, yaml_file_path: str) -> MappingProxyType:
    with open(yaml_file_path, 'rb') as fp:
        bs = fp.read(2)

    if bs == codecs.BOM_UTF16_LE or bs == codecs.BOM_UTF16_BE:
        encoding = 'utf-16'
    else:
        encoding = 'utf-8'

    try:
        with open(yaml_file_path, encoding=encoding) as fp:  # type: ignore
            yaml_contents = yaml.safe_load(fp)               # type: ignore
    except yaml.scanner.ScannerError as e:
        raise errors.YamlValidationError('{} on line {} of {}'.format(
            e.problem, e.problem_mark.line + 1, yaml_file_path)) from e
    except yaml.reader.ReaderError as e:
        raise errors.YamlValidationError(
            'Invalid character {!r} at position {} of {}: {}'.format(
                chr(e.character), e.position + 1, yaml_file_path,
                e.reason)) from e

    return MappingProxyType(yaml_contents)


def get_snapcraft_yaml(base_dir=None):
    possible_yamls = [
        os.path.join('snap', 'snapcraft.yaml'),
        'snapcraft.yaml',
        '.snapcraft.yaml',
    ]

    if base_dir:
        possible_yamls = [os.path.join(base_dir, x) for x in possible_yamls]

    snapcraft_yamls = [y for y in possible_yamls if os.path.exists(y)]

    if not snapcraft_yamls:
        raise errors.MissingSnapcraftYamlError(
            snapcraft_yaml='snap/snapcraft.yaml')
    elif len(snapcraft_yamls) > 1:
        raise errors.DuplicateSnapcraftYamlError(
            snapcraft_yaml_file_path=snapcraft_yamls[0],
            other_snapcraft_yaml_file_path=snapcraft_yamls[1])

    return snapcraft_yamls[0]
