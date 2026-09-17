"""Store conversion and experiment orchestration, offline."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import numpy as np
import pytest
import xarray as xr

from conftest import LONGITUDES
from conftest import FakeFetcher
from conftest import probe_day
from conftest import write_netcdf
from gl12 import Area
from gl12 import DailyRequest
from gl12 import Experiment
from gl12 import Gl12Downloader
from gl12 import Gl12ValidationError
from gl12 import NoDataAvailableError
from gl12 import apply_area
from gl12 import files_to_zarr
from gl12 import normalize_dataset
from gl12 import open_gl12_dataset
from gl12 import stamp_day
from gl12 import write_zarr


if TYPE_CHECKING:
    from pathlib import Path


def request(**overrides: object) -> DailyRequest:
    """Build a daily request, overridable per test."""
    fields: dict[str, object] = {"day": probe_day(), "area": None}
    fields.update(overrides)
    return DailyRequest(**fields)  # type: ignore[arg-type]


def sample_grid(tmp_path: Path, day: date | None = None) -> xr.Dataset:
    """Write a synthetic grid and return it normalized with a time axis."""
    path = tmp_path / "sample.nc"
    write_netcdf(path)
    return normalize_dataset(stamp_day(open_gl12_dataset(path), day or probe_day()))


def downloader_for(payload: bytes, **kwargs: object) -> Gl12Downloader:
    """Build a downloader backed by the in-memory fetcher."""
    return Gl12Downloader(FakeFetcher(payload, **kwargs))  # type: ignore[arg-type]


def test_decode_applies_published_scale_and_masks_nodata(tmp_path: Path) -> None:
    """Raw digital numbers become W/m**2 and nodata pixels become NaN."""
    path = tmp_path / "sample.nc"
    write_netcdf(path)
    dataset = open_gl12_dataset(path)
    assert dataset["dswrf"].attrs["units"] == "W m**-2"
    values = dataset["dswrf"].values
    assert np.isnan(values[0, 0])
    assert float(np.nanmax(values)) < 300.0
    assert float(np.nanmin(values)) > 200.0


def test_normalize_adds_canonical_names_and_time_axis(tmp_path: Path) -> None:
    """Decoder coordinates are renamed and time becomes a dimension."""
    normalized = sample_grid(tmp_path)
    assert "lat" in normalized.coords
    assert "lon" in normalized.coords
    assert normalized.sizes["time"] == 1
    assert float(normalized["lon"].min()) >= -180.0


def test_normalize_rejects_out_of_range_longitudes() -> None:
    """The GL1.2 convention is [-180, 180); [0, 360) is refused."""
    dataset = xr.Dataset(
        {"dswrf": (("lat", "lon"), np.zeros((2, 3)))},
        coords={"lat": [-10.0, 10.0], "lon": [200.0, 210.0, 220.0]},
    )
    with pytest.raises(Gl12ValidationError, match="outside"):
        normalize_dataset(dataset)


def test_two_days_concatenate_along_time(tmp_path: Path) -> None:
    """Multiple days land on one time axis, oldest first."""
    first = tmp_path / "a.nc"
    second = tmp_path / "b.nc"
    write_netcdf(first)
    write_netcdf(second)
    groups = (
        (DailyRequest(day=date(2026, 9, 14)), (first,)),
        (DailyRequest(day=date(2026, 9, 15)), (second,)),
    )
    store = files_to_zarr((), tmp_path / "days.zarr", request_sources=groups)
    with xr.open_zarr(store, consolidated=False) as dataset:
        assert dataset.sizes["time"] == 2
        assert "dswrf" in dataset.data_vars
        times = dataset["time"].values
        assert times[0] < times[1]


def test_write_zarr_refuses_to_overwrite_by_default(tmp_path: Path) -> None:
    """A store is never replaced silently."""
    destination = tmp_path / "store.zarr"
    dataset = sample_grid(tmp_path)
    write_zarr(dataset, destination)
    assert destination.exists()
    with pytest.raises(FileExistsError):
        write_zarr(dataset, destination)
    write_zarr(dataset, destination, overwrite=True)


def test_experiment_downloads_and_writes_an_openable_store(
    tmp_path: Path, netcdf_payload: bytes
) -> None:
    """The full offline path produces a store that opens as a dataset."""
    experiment = Experiment(
        name="probe",
        first=request(),
        second=request(day=date(2026, 9, 16)),
        downloader=downloader_for(netcdf_payload),
        root_dir=tmp_path,
    )
    events: list[object] = []
    paths = experiment.download(listener=events.append)
    assert len(paths) == 2
    store = experiment.to_zarr(listener=events.append)
    assert store == experiment.store_path
    with experiment.open() as dataset:
        assert dataset.sizes["time"] == 2
        assert "dswrf" in dataset.data_vars
        assert dataset["dswrf"].attrs["units"] == "W m**-2"
    kinds = {type(event).__name__ for event in events}
    assert {
        "RequestPlanned",
        "ItemResolved",
        "FileResolved",
        "StorePlanned",
        "ItemWritten",
    } <= kinds


def test_download_skips_unpublished_days_when_asked(
    tmp_path: Path, netcdf_payload: bytes
) -> None:
    """A day INPE has not published is skipped, not fatal, when requested."""
    experiment = Experiment(
        name="probe",
        day=request(),
        downloader=downloader_for(netcdf_payload, published=False),
        root_dir=tmp_path,
    )
    with pytest.raises(NoDataAvailableError):
        experiment.download()
    assert experiment.download(skip_missing=True) == ()


def test_experiment_requires_download_before_writing(
    tmp_path: Path, netcdf_payload: bytes
) -> None:
    """Writing a store before downloading is a programming error."""
    experiment = Experiment(
        name="probe",
        day=request(),
        downloader=downloader_for(netcdf_payload),
        root_dir=tmp_path,
    )
    with pytest.raises(RuntimeError, match="download"):
        experiment.to_zarr()
    with pytest.raises(RuntimeError, match="to_zarr"):
        experiment.open()


def test_experiment_cache_key_is_isolated_per_request(tmp_path: Path) -> None:
    """Changing the day yields a different store and cache."""
    base = Experiment(
        name="probe",
        day=request(),
        downloader=downloader_for(b"unused"),
        root_dir=tmp_path,
    )
    other = Experiment(
        name="probe",
        day=request(day=date(2026, 9, 16)),
        downloader=downloader_for(b"unused"),
        root_dir=tmp_path,
    )
    assert base.cache_key != other.cache_key
    assert base.store_path != other.store_path


def test_experiment_rejects_empty_and_mistyped_requests(tmp_path: Path) -> None:
    """Names and request types are validated at construction."""
    with pytest.raises(Gl12ValidationError, match="empty"):
        Experiment(name="  ", day=request(), root_dir=tmp_path)
    with pytest.raises(Gl12ValidationError, match="named request"):
        Experiment(name="probe", root_dir=tmp_path)
    with pytest.raises(Gl12ValidationError, match="DailyRequests"):
        Experiment(
            name="probe",
            day={"not": "a request"},  # type: ignore[arg-type]
            root_dir=tmp_path,
        )


def test_area_crops_latitudes_and_longitudes(tmp_path: Path) -> None:
    """Cropping honours the signed grid and the area bounds."""
    dataset = sample_grid(tmp_path)
    inner = Area(south=-20.0, north=20.0, west=-90.0, east=-50.0)
    cropped = apply_area(dataset, inner)
    assert float(cropped["lat"].min()) >= -20.0
    assert float(cropped["lat"].max()) <= 20.0
    expected = [value for value in LONGITUDES if -90.0 <= value <= -50.0]
    assert set(np.round(cropped["lon"].values, 3)) == set(np.round(expected, 3))
