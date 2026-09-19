"""Canonical filtering and atomic Zarr v3 writing for GL1.2 stores."""

from __future__ import annotations

import logging
from pathlib import Path
from shutil import rmtree
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

from gl12.decode import open_gl12_dataset
from gl12.exceptions import Gl12ValidationError
from gl12.exceptions import MissingCoordinateError


if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence
    from datetime import date

    from gl12.models import Area
    from gl12.models import DailyRequest

#: Decoder coordinate names mapped onto the canonical store vocabulary.
COORDINATE_ALIASES = {"latitude": "lat", "longitude": "lon"}

LOGGER = logging.getLogger(__name__)


def normalize_dataset(dataset: xr.Dataset) -> xr.Dataset:
    """Normalize coordinate names, order, and the time axis.

    GL1.2 keeps the source-native ``[-180, 180)`` longitude convention and
    stamps each daily grid at midnight UTC of its integration day. The scalar
    time of a single-day file is promoted to a dimension so one store serves
    one day or a decade.
    """
    mapping: dict[str, str] = {}
    for source, target in COORDINATE_ALIASES.items():
        if source not in dataset.coords and source not in dataset.dims:
            continue
        if target in dataset.coords or target in dataset.dims:
            raise Gl12ValidationError(
                f"Dataset contains both {source!r} and {target!r}."
            )
        mapping[source] = target
    normalized = dataset.rename(mapping) if mapping else dataset
    normalized = _promote_time(normalized)
    normalized = normalized.drop_vars(
        [name for name in ("step", "valid_time") if name in normalized.coords],
        errors="ignore",
    )
    _require_spatial_coordinates(normalized)
    for coordinate in ("lat", "lon", "time"):
        coordinate_variable = normalized.coords.get(coordinate)
        if coordinate_variable is not None and coordinate_variable.ndim == 1:
            normalized = normalized.sortby(coordinate)
    return normalized


def stamp_day(dataset: xr.Dataset, day: date) -> xr.Dataset:
    """Attach the integration day as a length-one ``time`` dimension."""
    return dataset.expand_dims(time=[np.datetime64(day)])


def _promote_time(dataset: xr.Dataset) -> xr.Dataset:
    """Turn the scalar reference time into a length-one dimension."""
    if "time" in dataset.coords and dataset["time"].ndim == 0:
        return dataset.expand_dims("time")
    return dataset


def apply_area(dataset: xr.Dataset, area: Area) -> xr.Dataset:
    """Crop a normalized dataset to an area on the ``[-180, 180)`` grid."""
    cropped = dataset.sel(lat=slice(area.south, area.north))
    longitude = cropped["lon"]
    if area.east - area.west >= 360:
        return cropped
    if area.west <= area.east:
        mask = (longitude >= area.west) & (longitude <= area.east)
    else:
        mask = (longitude >= area.west) | (longitude <= area.east)
    return cropped.where(mask, drop=True)


def write_zarr(
    dataset: xr.Dataset,
    destination: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a normalized dataset to an atomic Zarr v3 directory."""
    destination = Path(destination)
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    backup = destination.with_name(f".{destination.name}.old")
    if temporary.exists():
        _remove_path(temporary)
    if backup.exists():
        _remove_path(backup)
    try:
        normalized = normalize_dataset(dataset)
        normalized.to_zarr(
            temporary,
            mode="w",
            zarr_format=3,
            consolidated=False,
            encoding=_encoding(normalized),
        )
        if destination.exists():
            destination.rename(backup)
        try:
            temporary.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise
        _remove_path(backup)
    finally:
        if temporary.exists():
            _remove_path(temporary)
    return destination


def files_to_zarr(
    sources: Iterable[Path],
    destination: Path,
    *,
    overwrite: bool = False,
    request_sources: Sequence[tuple[DailyRequest, Iterable[Path]]] | None = None,
) -> Path:
    """Decode, crop, combine, and write GL1.2 files as one Zarr store.

    Parameters
    ----------
    sources : iterable of pathlib.Path
        GL1.2 NetCDF files, used when no request grouping is supplied.
    destination : pathlib.Path
        Directory of the Zarr v3 store.
    overwrite : bool, default=False
        Whether an existing store may be replaced.
    request_sources : sequence of tuple, optional
        ``(request, paths)`` pairs. The request's day is stamped onto the file's
        time axis and its own area filter is applied before the files combine.
    """
    groups = tuple(request_sources or ())
    if not groups:
        paths = tuple(sources)
        if not paths:
            raise ValueError("At least one GL1.2 file is required.")
        return write_zarr(_combine(_decode(paths)), destination, overwrite=overwrite)
    datasets: list[xr.Dataset] = []
    for request, paths in groups:
        request_paths = tuple(paths)
        if not request_paths:
            LOGGER.warning(
                "Skipping GL1.2 request for %s: no published grid.", request.day
            )
            continue
        for path in request_paths:
            dataset = stamp_day(open_gl12_dataset(path), request.day)
            cropped = (
                apply_area(dataset, request.area)
                if request.area is not None
                else dataset
            )
            datasets.append(normalize_dataset(cropped))
    return write_zarr(_combine(tuple(datasets)), destination, overwrite=overwrite)


def _decode(paths: Iterable[Path]) -> tuple[xr.Dataset, ...]:
    """Decode every GL1.2 grid, normalized."""
    decoded = tuple(normalize_dataset(open_gl12_dataset(path)) for path in paths)
    if not decoded:
        raise ValueError("At least one GL1.2 grid is required.")
    return decoded


def _combine(datasets: Sequence[xr.Dataset]) -> xr.Dataset:
    """Combine decoded days along the time axis, then by variables.

    GL1.2 days are independent files carrying the same variable, so datasets
    with the same variable signature are concatenated along ``time`` and the
    resulting cubes are merged.
    """
    if not datasets:
        raise ValueError("At least one GL1.2 grid is required.")
    if len(datasets) == 1:
        return datasets[0]
    groups: dict[tuple[str, ...], list[xr.Dataset]] = {}
    for dataset in datasets:
        signature = tuple(sorted(str(name) for name in dataset.data_vars))
        groups.setdefault(signature, []).append(dataset)
    combined: list[xr.Dataset] = []
    for members in groups.values():
        if len(members) == 1:
            combined.append(members[0])
            continue
        stacked = xr.concat(
            members,
            dim="time",
            compat="override",
            coords="minimal",
            combine_attrs="override",
        )
        combined.append(stacked.sortby("time"))
    if len(combined) == 1:
        return combined[0]
    return xr.merge(combined, compat="override", combine_attrs="override")


def _require_spatial_coordinates(dataset: xr.Dataset) -> None:
    """Require one-dimensional canonical latitude and longitude coordinates."""
    for name, minimum, maximum in (("lat", -90, 90), ("lon", -180, 180)):
        if name not in dataset.coords:
            raise MissingCoordinateError(f"Dataset is missing {name!r} coordinate.")
        coordinate = dataset[name]
        if coordinate.ndim != 1:
            raise Gl12ValidationError(f"Coordinate {name!r} must be one-dimensional.")
        if float(coordinate.min()) < minimum or float(coordinate.max()) > maximum:
            raise Gl12ValidationError(
                f"Coordinate {name!r} is outside the GL1.2 longitude convention."
            )


def _encoding(dataset: xr.Dataset) -> dict[str, dict[str, tuple[int, ...]]]:
    """Derive conservative time and spatial chunk sizes."""
    chunks: dict[str, int] = {}
    for raw_dimension, size in dataset.sizes.items():
        dimension = str(raw_dimension)
        if dimension in {"lat", "lon"}:
            chunks[dimension] = size or 1
        elif dimension == "time":
            chunks[dimension] = 1
        else:
            chunks[dimension] = min(size, 8) or 1
    return {
        str(name): {
            "chunks": tuple(chunks[str(dimension)] for dimension in variable.dims)
        }
        for name, variable in dataset.data_vars.items()
        if variable.dims
    }


def _remove_path(path: Path) -> None:
    """Remove a temporary or replaced Zarr path."""
    if path.is_dir():
        rmtree(path)
    else:
        path.unlink(missing_ok=True)
