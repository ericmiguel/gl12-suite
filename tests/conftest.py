"""Shared offline fixtures: a synthetic GL1.2 grid and a fake fetcher."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import parse_qs
from urllib.parse import urlparse

import h5netcdf
import numpy as np
import pytest

from gl12.retrieval import HeadInfo


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


LATITUDES = np.array([-45.0, -15.0, 0.0, 15.0, 45.0])
LONGITUDES = np.array([-100.0, -80.0, -60.0, -40.0])

#: Raw digital number the STAC metadata flags as nodata.
NODATA_DN = 65535.0


def probe_day() -> date:
    """Return a fixed, valid day for tests."""
    return date(2026, 9, 15)


def raw_values() -> np.ndarray:
    """Return a synthetic raw digital-number layer, with one nodata pixel."""
    values = np.arange(LATITUDES.size * LONGITUDES.size, dtype="float32").reshape(
        LATITUDES.size, LONGITUDES.size
    )
    values = 2400.0 + values
    values[0, 0] = NODATA_DN
    return values


def write_netcdf(path: Path, *, raw: np.ndarray | None = None) -> None:
    """Write a synthetic NetCDF-4 grid in the published GL1.2 layout."""
    with h5netcdf.File(path, "w") as handle:
        handle.dimensions = {"lat": LATITUDES.size, "lon": LONGITUDES.size}
        handle.create_variable("lat", ("lat",), dtype="f8", data=LATITUDES)
        handle.create_variable("lon", ("lon",), dtype="f8", data=LONGITUDES)
        handle.create_variable(
            "Band1",
            ("lat", "lon"),
            dtype="f4",
            data=raw if raw is not None else raw_values(),
        )
        handle.variables["lat"].attrs["units"] = "degrees_north"
        handle.variables["lon"].attrs["units"] = "degrees_east"
        handle.variables["Band1"].attrs["long_name"] = "GDAL Band Number 1"


@pytest.fixture
def netcdf_payload(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """Return the bytes of a synthetic GL1.2 NetCDF file."""
    path = tmp_path_factory.mktemp("gl12") / "sample.nc"
    write_netcdf(path)
    return path.read_bytes()


def multihash(payload: bytes) -> str:
    """Return the SHA-256 multihash of a payload, as STAC advertises it."""
    return f"1220{hashlib.sha256(payload).hexdigest()}"


def stac_payload(
    day: date,
    payload: bytes,
    *,
    href: str = "https://data.inpe.br/bdc/data/sample.nc",
    include_checksum: bool = True,
    include_size: bool = True,
    checksum: str | None = None,
) -> dict[str, object]:
    """Build a STAC items response with one NetCDF asset for a day."""
    asset: dict[str, object] = {"href": href}
    if include_size:
        asset["bdc:size"] = len(payload)
    if include_checksum:
        asset["checksum:multihash"] = checksum or multihash(payload)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"GOES_GL_DSWRF_DAILY_{day.strftime('%Y%m%d')}0000",
                "properties": {"datetime": f"{day.isoformat()}T00:00:00.000000Z"},
                "assets": {"dswrf_daily_mean": asset},
            }
        ],
    }


def day_from_url(url: str) -> date:
    """Recover the integration day from a STAC items URL."""
    query = parse_qs(urlparse(url).query)
    return date.fromisoformat(query["datetime"][0][:10])


class FakeFetcher:
    """In-memory transport that answers STAC queries and serves one payload."""

    def __init__(
        self,
        payload: bytes,
        *,
        published: bool = True,
        include_checksum: bool = True,
        checksum: str | None = None,
        status: int = 200,
    ) -> None:
        self.payload = payload
        self.published = published
        self.include_checksum = include_checksum
        self.checksum = checksum
        self.status = status
        self.json_calls: list[str] = []
        self.heads: list[str] = []
        self.ranges: list[tuple[str, int, int]] = []

    def get_json(self, url: str) -> object:
        """Return a STAC response for the day named in the URL."""
        self.json_calls.append(url)
        if not self.published:
            empty: list[object] = []
            return {"type": "FeatureCollection", "features": empty}
        return stac_payload(
            day_from_url(url),
            self.payload,
            include_checksum=self.include_checksum,
            checksum=self.checksum,
        )

    def head(self, url: str) -> HeadInfo:
        """Return the configured status and the payload length."""
        self.heads.append(url)
        return HeadInfo(
            status_code=self.status,
            headers={"content-length": str(len(self.payload))},
        )

    def stream_range(self, url: str, start: int, end: int) -> Iterable[bytes]:
        """Yield the requested slice of the payload and record it."""
        self.ranges.append((url, start, end))
        yield self.payload[start : end + 1]
