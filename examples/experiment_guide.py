"""Guided tour of the gl12-suite library.

This script is the executable documentation for :mod:`gl12`. It walks the
layers of the library in the order you meet them, from describing what you
want to reading the physical field out of a store:

1. requests — describing days and areas (offline)
2. STAC — the vocabulary that resolves a day to a published grid (offline)
3. planning — the exact cache files a window implies (offline)
4. downloader — resolve, fetch, verify, cache (network, a few MB)
5. experiment — one Zarr v3 store from named daily requests (network, a few MB)
6. physics — raw digital numbers, the published scale, and nodata (offline)

Run the lightweight tour, a few MB of traffic::

    uv run examples/experiment_guide.py

Adjust the demonstration window with ``--days`` (default 3). The window ends
two days ago, which is certain to be published. Experiments resolve the
project root from ``.git``, ``.venv``, or ``README.md`` markers; the artifacts
they create live under the gitignored ``.cache/`` and ``data/`` directories of
this repository.
"""

from __future__ import annotations

import argparse
from datetime import date
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from gl12 import CANONICAL_VARIABLE
from gl12 import DSWRF_SCALE
from gl12 import GL12_HISTORY_START
from gl12 import NODATA_DN
from gl12 import Area
from gl12 import BytesTransferred
from gl12 import DailyRequest
from gl12 import Experiment
from gl12 import Gl12Downloader
from gl12 import Gl12ValidationError
from gl12 import ItemResolved
from gl12 import NoDataAvailableError
from gl12 import item_search_url
from gl12 import parse_item
from gl12 import plan_chunks
from gl12 import plan_summary
from gl12 import resolve_project_root


if TYPE_CHECKING:
    from collections.abc import Callable

    from gl12 import PipelineEvent

# The manual-download sections use a cache directory of their own choosing;
# the experiment section uses the library's automatic per-experiment cache.
GUIDE_CACHE = Path(".cache") / "guide"
GUIDE_DAY = date(2026, 9, 15)


def _rule(title: str = "") -> None:
    """Print a plain section separator without a UI dependency."""
    print(f"\n--- {title} ---")


def _report_event(event: PipelineEvent) -> None:
    """Print only the resolved items and completed transfers."""
    if isinstance(event, ItemResolved):
        print(f"    resolved {event.item}")
    elif isinstance(event, BytesTransferred) and event.done:
        print(f"    transferred {event.name}")


def main() -> None:
    """Run the guided tour."""
    args = _parse_args()
    window = _resolve_window(args.days)

    print(f"gl12-suite guided tour · window {window[0]} .. {window[1]}")
    print(f"project root resolved to {resolve_project_root()}")

    section_requests()
    section_stac()
    section_planning(window)
    section_downloader(window)
    section_experiment(window)
    section_physics()

    _rule()
    print(
        "Artifacts on disk (gitignored): the shared guide cache under "
        f"{GUIDE_CACHE}, plus one cache and one store per experiment under "
        ".cache/gl12 and data/gl12."
    )


def _parse_args() -> argparse.Namespace:
    """Parse the tour options."""
    parser = argparse.ArgumentParser(
        description="Executable documentation for the gl12-suite library."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="demonstration window size in days, ending two days ago",
    )
    return parser.parse_args()


def _resolve_window(days: int) -> tuple[date, date]:
    """Return the demonstration window, ending two days ago."""
    end = date.today() - timedelta(days=2)
    start = max(end - timedelta(days=days - 1), GL12_HISTORY_START)
    return start, end


def section_requests() -> None:
    """Demonstrate request construction and immediate validation."""
    _rule("1 · requests — describing days and areas")
    print(
        "A request is an immutable, validated value object. The vocabulary is "
        "deliberately small: one integration day plus an optional area. The "
        "day is validated against the published STAC history, which begins "
        f"{GL12_HISTORY_START.isoformat()}."
    )
    request = DailyRequest(day=GUIDE_DAY)
    print(f"  request        : {request.day} · label {request.stamp}")
    print(f"  reference time : {request.reference} UTC (midnight of the day)")

    print("An optional area crops the store, never the download:")
    area = Area(south=-35.0, north=5.0, west=-75.0, east=-35.0)
    cropped = DailyRequest(day=GUIDE_DAY, area=area)
    print(f"  cropped request: {cropped.day} over {area}")
    print(f"  crosses dateline? {area.crosses_dateline}")

    print("Invalid requests fail at construction, never mid-download:")
    rejections: tuple[tuple[str, Callable[[], object]], ...] = (
        ("before the record", lambda: DailyRequest(day=date(2013, 7, 29))),
        ("in a future year", lambda: DailyRequest(day=date(2099, 1, 1))),
        (
            "inverted latitude",
            lambda: Area(south=10.0, north=-10.0, west=-70.0, east=-30.0),
        ),
        (
            "off-grid longitude",
            lambda: Area(south=-5.0, north=5.0, west=300.0, east=310.0),
        ),
    )
    for label, build in rejections:
        try:
            build()
        except Gl12ValidationError as error:
            print(f"  {label} → {error}")


def section_stac() -> None:
    """Demonstrate the STAC vocabulary without touching the network."""
    _rule("2 · STAC — resolving a day to a published grid")
    print(
        "INPE publishes the GL1.2 product as the STAC collection "
        "GOES-GL-DSWRF-Daily-1. Published file names carry a versioned "
        "product id (S11167052 today) that changes on reprocessing, so the "
        "suite never builds URLs by hand: it queries the collection items "
        "for the day and reads the dswrf_daily_mean asset from the response."
    )
    print(f"  items URL : {item_search_url(GUIDE_DAY)}")

    # A minimal but faithful items response, the shape the server returns.
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "GOES_GL_DSWRF_DAILY_202609150000",
                "properties": {"datetime": "2026-09-15T00:00:00.000000Z"},
                "assets": {
                    "dswrf_daily_mean": {
                        "href": (
                            "https://data.inpe.br/bdc/data/GOES-GL-DSWRF-Daily/"
                            "rad_solar/irradiancia_glb_media_diaria_nc/2026/09/"
                            "S11167052_202609150000.nc"
                        ),
                        "bdc:size": 5396686,
                        "checksum:multihash": "1220e6414c625cd366344716072cca7c"
                        "dc7a2235aa16b52902a6b5b4b645a63d6b16",
                    }
                },
            }
        ],
    }
    item = parse_item(payload, GUIDE_DAY)
    print(f"  item id   : {item.item_id}")
    print(f"  asset URL : {item.data_url}")
    print(f"  size      : {item.size:,} bytes")
    print(f"  checksum  : {item.checksum[:16]}… (SHA-256 multihash)")

    print("A day the collection does not publish is not an error state:")
    try:
        parse_item({"type": "FeatureCollection", "features": []}, GUIDE_DAY)
    except NoDataAvailableError as error:
        print(f"  empty response → {error}")


def section_planning(window: tuple[date, date]) -> None:
    """Demonstrate deterministic planning of cache files."""
    _rule("3 · planning — the cache files a window implies")
    print(
        "plan_chunks maps one day to one NetCDF cache file addressed by its "
        "STAC search URL. Planning is pure: no network, no filesystem writes. "
        "A day inside the last two days is marked mutable so its cache is "
        "re-verified on the next run."
    )
    for day in _window_days(window):
        request = DailyRequest(day=day)
        plan = plan_chunks(request, GUIDE_CACHE)
        chunk = plan.chunks[0]
        print(f"  {day} : {plan_summary(plan)} · mutable={chunk.mutable}")
        print(f"    cache {chunk.path}")


def section_downloader(window: tuple[date, date]) -> None:
    """Resolve, download, verify, and cache through the downloader layer."""
    _rule("4 · downloader — resolve, fetch, verify, cache")
    print(
        "Gl12Downloader resolves the day through STAC, streams the whole "
        "NetCDF (~5 MB at 0.04°), verifies the transfer against the item's "
        "SHA-256 multihash and byte size, then verifies the decoded field is "
        "physically plausible before the file replaces its cache entry."
    )
    downloader = Gl12Downloader()
    for day in _window_days(window):
        chunk = plan_chunks(DailyRequest(day=day), GUIDE_CACHE).chunks[0]
        try:
            path = downloader.download_chunk(chunk, listener=_report_event)
        except NoDataAvailableError as error:
            print(f"  {day} → not published yet · {error}")
        else:
            print(f"  {day} → {path.name} ({path.stat().st_size:,} bytes)")

    print("A second pass is idempotent: verified cache entries are trusted.")
    for day in _window_days(window):
        chunk = plan_chunks(DailyRequest(day=day), GUIDE_CACHE).chunks[0]
        downloader.download_chunk(chunk)
        print(f"  {day} → cached")


def section_experiment(window: tuple[date, date]) -> None:
    """Run the complete experiment pipeline on a small window."""
    _rule("5 · experiment — one Zarr v3 store")
    print(
        "Named daily requests combine into one Zarr v3 store: download, "
        "to_zarr, open. The cache and the store are keyed by a hash of the "
        "experiment name plus the request definitions, so every experiment "
        "is isolated — change a day or an area and you get a brand-new cache "
        "and store. skip_missing tolerates days not published yet."
    )
    requests = {
        f"day_{day:%Y%m%d}": DailyRequest(day=day) for day in _window_days(window)
    }
    experiment = Experiment(
        name="guide-daily",
        downloader=Gl12Downloader(),
        **requests,
    )
    paths = experiment.download(skip_missing=True, listener=_report_event)
    print(f"  resolved {len(paths)} files under {experiment.cache_path}")
    if not paths:
        print("  no day was published yet; nothing to store")
        return

    # The definition is fixed, so re-running the tour rewrites the same store.
    store = experiment.to_zarr(overwrite=True)
    print(f"  store written : {store}")

    dataset = experiment.open()
    variables = sorted(str(name) for name in dataset.data_vars)
    print(f"  variables     : {variables}")
    print(f"  sizes         : {dict(dataset.sizes)}")
    print(
        f"  time axis     : {str(dataset.time.values[0])[:10]}"
        f" .. {str(dataset.time.values[-1])[:10]}"
    )
    print(f"  units         : {dataset[CANONICAL_VARIABLE].attrs['units']}")
    print(
        f"  chunks        : {dataset[CANONICAL_VARIABLE].encoding.get('chunks')}"
        " (one day per time chunk)"
    )


def section_physics() -> None:
    """Explain the raw-DN to W/m**2 transform and nodata handling."""
    _rule("6 · physics — raw digital numbers and the published scale")
    print(
        "Each published NetCDF holds a single Band1 float32 layer of raw "
        "digital numbers plus the lat/lon arrays, and no scale_factor of its "
        "own. The STAC item's eo:bands metadata is the authority for the "
        f"physics: physical irradiance is DN x {DSWRF_SCALE} W/m**2."
    )
    print(f"  canonical variable : {CANONICAL_VARIABLE} (W m**-2, daily mean)")
    print(f"  scale factor       : {DSWRF_SCALE}")
    print(f"  nodata digital no. : {int(NODATA_DN)} → NaN")
    print(
        "The suite applies the scale at decode, so a store read back always "
        "carries W/m**2. Daily means below ~500 W/m**2 are physical; the "
        "verification bound rejects anything above 600."
    )
    print("Daily means form a south-to-north gradient, e.g. a synthetic field:")
    latitudes = np.array([-50.0, -30.0, -10.0, 10.0, 20.0])
    raw = np.array([1500, 2100, 2600, 2900, 3000], dtype="float64")
    for latitude, digital in zip(latitudes, raw, strict=True):
        print(
            f"    lat {latitude:6.1f}° · DN {int(digital):5d} → {digital * DSWRF_SCALE:6.1f} W/m**2"
        )


def _window_days(window: tuple[date, date]) -> list[date]:
    """Return every day of the demonstration window, oldest first."""
    start, end = window
    step = timedelta(days=1)
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += step
    return days


if __name__ == "__main__":
    main()
