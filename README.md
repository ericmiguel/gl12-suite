# gl12-suite

Data suite (leaf). Resolves and downloads INPE **GL1.2** daily solar
irradiance from the Big Data Cube STAC service, decodes the NetCDF grids, and
materializes a canonical **Zarr v3** store. Package `gl12`.

GL1.2 (Ceballos et al., 2004; Porfirio et al., 2020) infers the surface
downward shortwave radiation flux (DSWRF) from GOES visible-channel imagery.
INPE publishes one 0.04-degree NetCDF grid per day (1800 x 1800) over South
America and adjacent oceans (lat -50..21.96, lon -100..-28.04), with history
from 2013-07-30 in the STAC collection `GOES-GL-DSWRF-Daily-1`.

```python
from datetime import date

from gl12 import DailyRequest, Experiment

experiment = Experiment(
    name="gl12_sep_2026",
    september_15=DailyRequest(day=date(2026, 9, 15)),
    september_16=DailyRequest(day=date(2026, 9, 16)),
)
experiment.download()
experiment.to_zarr()
dataset = experiment.open()  # lazy xarray dataset: time, lat, lon
```

## Data and vocabulary

| concept | values | note |
| --- | --- | --- |
| `Cycle` | one integration day | items are stamped `T00:00:00Z` |
| `DailyRequest` | `day` + optional `Area` | one request is one day; an experiment pairs many days |
| variable | `dswrf` | daily mean downward shortwave radiation flux (W m**-2) |

Each daily grid is a NetCDF-4 file holding one `Band1` float32 layer plus the
`lat`/`lon` coordinate arrays. The layer stores **raw digital numbers**; the
STAC item's `eo:bands` metadata is the authority that the physical daily mean
is `DN * 0.1` W/m**2 (`min` 100, `max` 5000, nodata 65535). The file carries no
`scale_factor`, so the suite applies the published scale explicitly and masks
the nodata digital number to NaN.

Longitude stays source-native `[-180, 180)`; `Area` with `west > east` spans
the dateline and is applied at store time only — never on the server.

## The download economics

File names carry a versioned product id (`S11167052` today) that changes on
reprocessing, so the suite never builds URLs by hand. A day is resolved through
the STAC item endpoint (`.../collections/GOES-GL-DSWRF-Daily-1/items?datetime=
<day>T00:00:00Z/<day>T23:59:59Z`) and the published `dswrf_daily_mean` asset is
streamed whole (~5 MB). The item's SHA-256 multihash and byte size verify the
transfer, and the decoded grid is checked for finite, non-negative irradiance
below 600 W/m**2. A day inside the last two days is re-resolved and re-checked
against the advertised size before its cache is trusted.

## Missing data

A day the STAC collection does not publish is `NoDataAvailableError`; with
`download(skip_missing=True)` it is skipped with a warning, which is how a
rolling range (`days_between(...)`) can include today without failing.

## Store shape

- Coordinates: `time` (midnight UTC of the integration day, the source
  convention), `lat`, `lon`.
- Variable: `dswrf` (W m**-2), daily mean downward shortwave radiation flux.
- Store: `data/gl12/<cache_key>.zarr`; cache: `.cache/gl12/<cache_key>/`, one
  NetCDF file per day. Changing any request field (day, area) yields a new,
  isolated cache key.

## Quality

```bash
uv run ruff check . ; uv run ruff format . --check ; uv run pyrefly check ; uv run pytest ; uv run pytest -m network
```

`examples/experiment_guide.py` is an executable tour of the whole library
(requests, STAC resolution, planning, downloader, experiment, physics):

```bash
uv run examples/experiment_guide.py            # ~3 days, a few MB
uv run examples/experiment_guide.py --days 7
```

The `solar` study in `meteorological-reports` consumes this suite through
`reports/data/gl12.py` and renders `data/gl12/*.zarr` as South America maps.

The network smoke test resolves and downloads a recently published day
(yesterday minus one, which is certain to exist) and verifies a physically
plausible store.