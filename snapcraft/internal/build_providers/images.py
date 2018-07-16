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
import subprocess
import tempfile
from typing import Dict, Tuple

import requests

from . import errors
from snapcraft.file_utils import calculate_hash
from snapcraft.internal.cache import FileCache
from snapcraft.internal.indicators import download_requests_stream


class _Image:
    def __init__(
        self, *, base: str, snap_arch: str, url: str, checksum: str, algorithm: str
    ) -> None:
        self.base = base
        self.snap_arch = snap_arch
        self.url = url
        self.checksum = checksum
        self.algorithm = algorithm


BuildImageDictT = Dict[Tuple[str, str], _Image]


def _get_build_images() -> BuildImageDictT:
    images = dict()  # type: BuildImageDictT
    images["core", "amd64"] = (
        _Image(
            base="core",
            snap_arch="amd64",
            url="https://cloud-images.ubuntu.com/releases/16.04/release-20180703/ubuntu-16.04-server-cloudimg-amd64-disk1.img",  # noqa: E501
            checksum="79549e87ddfc61b1cc8626a67ccc025cd7111d1af93ec28ea46ba6de70819f8c",  # noqa: E501
            algorithm="sha256",
        ),
    )
    images["core18", "amd64"] = _Image(
        base="core18",
        snap_arch="amd64",
        url="https://cloud-images.ubuntu.com/releases/18.04/release/ubuntu-18.04-server-cloudimg-amd64.img",  # noqa: E501
        checksum="c2d3c8af5ed1ef9c76bc8cfe5c80e78e4b2b27190696068535617ec1dc10378a",  # noqa: E501
        algorithm="sha256",
    )
    return images


class BuildImages:
    def __init__(self) -> None:
        self._image_cache = FileCache("build-images")

    def _cache_hit(self, *, checksum: str, algorithm: str) -> str:
        return self._image_cache.get(hash=checksum, algorithm=algorithm)

    def _cache(self, image: _Image) -> str:
        request = requests.get(image.url, stream=True, allow_redirects=True)
        request.raise_for_status()

        with tempfile.TemporaryDirectory(
            prefix=self._image_cache.file_cache
        ) as tmp_dir:
            download_file = os.path.join(tmp_dir, "{}-vm".format(image.base))
            download_requests_stream(request, download_file)

            calculated_digest = calculate_hash(download_file, algorithm=image.algorithm)
            if image.checksum != calculated_digest:
                raise errors.BuildImageChecksumError(image.checksum, calculated_digest)

            return self._image_cache.cache(
                filename=download_file, algorithm=image.algorithm, hash=image.checksum
            )

    def get(self, *, base: str, deb_arch: str) -> str:
        try:
            image = _get_build_images()[base, deb_arch]
        except KeyError as key_error:
            raise errors.BuildImageForBaseMissing(
                base=base, deb_arch=deb_arch
            ) from key_error

        cached_file = self._cache_hit(
            checksum=image.checksum, algorithm=image.algorithm
        )
        if not cached_file:
            cached_file = self._cache(image)

        return cached_file

    def setup(self, *, base: str, deb_arch: str, size: str, image_path: str) -> None:
        """Setup an instance for base and deb_arch on image_path."""
        cached_file = self.get(base=base, deb_arch=deb_arch)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        subprocess.check_output(
            ["qemu-img", "create", "-f", "qcow2", "-b", cached_file, image_path, size]
        )
