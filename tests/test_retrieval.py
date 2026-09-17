"""Retrieval, caching and verification, offline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from conftest import LATITUDES
from conftest import LONGITUDES
from conftest import FakeFetcher
from conftest import probe_day
from conftest import write_netcdf
from gl12 import Chunk
from gl12 import DailyRequest
from gl12 import DownloadError
from gl12 import Gl12Downloader
from gl12 import NoDataAvailableError
from gl12 import plan_chunks


if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path


def build_chunk(tmp_path: Path, day: date | None = None) -> Chunk:
    """Plan a single chunk in an isolated cache directory."""
    request = DailyRequest(day=day or probe_day())
    plan = plan_chunks(request, tmp_path / "cache")
    return plan.chunks[0]


def test_download_verifies_and_caches_the_grid(
    tmp_path: Path, netcdf_payload: bytes
) -> None:
    """The published bytes land in the cache and events are emitted."""
    fetcher = FakeFetcher(netcdf_payload)
    downloader = Gl12Downloader(fetcher)
    chunk = build_chunk(tmp_path)
    events: list[object] = []
    path = downloader.download_chunk(chunk, listener=events.append)
    assert path.read_bytes() == netcdf_payload
    assert any(type(event).__name__ == "ItemResolved" for event in events)
    assert len(fetcher.ranges) == 1


def test_cached_grid_is_not_redownloaded(tmp_path: Path, netcdf_payload: bytes) -> None:
    """A verified cached file short-circuits the transfer."""
    fetcher = FakeFetcher(netcdf_payload)
    downloader = Gl12Downloader(fetcher)
    chunk = build_chunk(tmp_path)
    downloader.download_chunk(chunk)
    downloader.download_chunk(chunk)
    assert len(fetcher.ranges) == 1


def test_invalid_cached_grid_is_replaced(tmp_path: Path, netcdf_payload: bytes) -> None:
    """A corrupt cache entry is discarded and refetched."""
    fetcher = FakeFetcher(netcdf_payload)
    downloader = Gl12Downloader(fetcher)
    chunk = build_chunk(tmp_path)
    chunk.path.parent.mkdir(parents=True, exist_ok=True)
    chunk.path.write_bytes(b"not-a-netcdf")
    downloader.download_chunk(chunk)
    assert chunk.path.read_bytes() == netcdf_payload


def test_unpublished_day_raises(tmp_path: Path, netcdf_payload: bytes) -> None:
    """An empty STAC response is a missing day, not a crash."""
    downloader = Gl12Downloader(FakeFetcher(netcdf_payload, published=False))
    with pytest.raises(NoDataAvailableError):
        downloader.download_chunk(build_chunk(tmp_path))


def test_checksum_mismatch_is_rejected(tmp_path: Path, netcdf_payload: bytes) -> None:
    """A wrong multihash fails the transfer verification."""
    fetcher = FakeFetcher(netcdf_payload, checksum=f"1220{'0' * 64}")
    downloader = Gl12Downloader(fetcher)
    with pytest.raises(DownloadError, match="Checksum"):
        downloader.download_chunk(build_chunk(tmp_path))


def test_verify_rejects_implausible_irradiance(tmp_path: Path) -> None:
    """A decoded field above the plausibility bound is refused."""
    raw = np.full((LATITUDES.size, LONGITUDES.size), 9000.0, dtype="float32")
    path = tmp_path / "implausible.nc"
    write_netcdf(path, raw=raw)
    with pytest.raises(DownloadError, match="implausible"):
        Gl12Downloader._verify(path, None)


def test_verify_rejects_negative_irradiance(tmp_path: Path) -> None:
    """A decoded field below zero is refused."""
    raw = np.full((LATITUDES.size, LONGITUDES.size), -100.0, dtype="float32")
    path = tmp_path / "negative.nc"
    write_netcdf(path, raw=raw)
    with pytest.raises(DownloadError, match="negative"):
        Gl12Downloader._verify(path, None)
