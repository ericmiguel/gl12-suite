"""NetCDF decoding of GL1.2 daily grids.

INPE publishes each daily grid as a small NetCDF-4 file holding a single
``Band1`` float32 layer over ``lat``/``lon`` plus the two coordinate arrays.
The values are raw digital numbers: the STAC item's ``eo:bands`` metadata is
the authority that the physical daily mean irradiance is ``DN * 0.1`` W/m**2
(``min`` 100, ``max`` 5000, nodata 65535). The file itself carries no
``scale_factor``, so the suite applies the published scale explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

from gl12.exceptions import DownloadError


if TYPE_CHECKING:
    from pathlib import Path

#: Raw NetCDF layer holding the daily mean DSWRF digital numbers.
RAW_VARIABLE = "Band1"

#: Canonical name of the physical irradiance field in the store.
CANONICAL_VARIABLE = "dswrf"

#: STAC-published scale factor mapping digital numbers to W/m**2.
DSWRF_SCALE = 0.1

#: STAC-published nodata digital number (raw ``uint16`` full scale).
NODATA_DN = 65535.0

#: Highest plausible daily mean irradiance in W/m**2 (solar constant bound).
MAX_DAILY_IRRADIANCE = 600.0


def open_gl12_dataset(path: Path) -> xr.Dataset:
    """Decode one GL1.2 NetCDF grid into physical units.

    Parameters
    ----------
    path : pathlib.Path
        A GL1.2 daily NetCDF file.

    Returns
    -------
    xarray.Dataset
        Dataset with one ``dswrf`` variable in W/m**2 over ``lat``/``lon``.

    Raises
    ------
    DownloadError
        If the file cannot be decoded or lacks the expected layer.
    """
    try:
        dataset = xr.open_dataset(path, engine="h5netcdf")
    except (OSError, ValueError, ImportError) as error:
        raise DownloadError(f"Could not decode GL1.2 file {path}") from error
    try:
        if RAW_VARIABLE not in dataset:
            raise DownloadError(
                f"GL1.2 file {path.name} has no {RAW_VARIABLE!r} layer."
            )
        raw = dataset[RAW_VARIABLE]
        values = np.asarray(raw.values, dtype="float64")
        values = np.where(values == NODATA_DN, np.nan, values)
        physical = values * DSWRF_SCALE
        coords = {str(dim): dataset[dim] for dim in raw.dims}
        field = xr.DataArray(
            physical,
            dims=raw.dims,
            coords=coords,
            name=CANONICAL_VARIABLE,
        )
    finally:
        dataset.close()
    field.attrs["units"] = "W m**-2"
    field.attrs["long_name"] = (
        "GL1.2 daily mean downward shortwave radiation flux at the surface"
    )
    decoded = xr.Dataset({CANONICAL_VARIABLE: field})
    decoded.attrs["source"] = "INPE GL1.2 (GOES visible channel)"
    decoded.attrs["Conventions"] = "CF-1.5"
    return decoded
