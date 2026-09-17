"""Live INPE Big Data Cube smoke test.

Excluded by default (``-m network``) because it touches the real STAC service
and data server. It is the only test that exercises the STAC resolution and
NetCDF decode paths end to end on published GL1.2 grids.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np
import pytest

from gl12 import DailyRequest
from gl12 import Experiment
from gl12 import Gl12Downloader
from gl12 import HttpxFetcher
from gl12 import item_search_url


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.network


def recent_day() -> date:
    """Return the most recent day that is certain to be published."""
    return date.today() - timedelta(days=2)


def test_live_stac_resolves_the_day() -> None:
    """The STAC item endpoint answers for a published day."""
    fetcher = HttpxFetcher()
    try:
        payload = fetcher.get_json(item_search_url(recent_day()))
    finally:
        fetcher.close()
    assert isinstance(payload, dict)


def test_live_download_produces_a_physical_store(tmp_path: Path) -> None:
    """One published day decodes to a store with plausible irradiance."""
    fetcher = HttpxFetcher()
    try:
        experiment = Experiment(
            name="live",
            day=DailyRequest(day=recent_day()),
            downloader=Gl12Downloader(fetcher),
            root_dir=tmp_path,
        )
        experiment.download()
        experiment.to_zarr()
        with experiment.open() as dataset:
            assert dataset.sizes["time"] == 1
            assert "dswrf" in dataset.data_vars
            values = dataset["dswrf"].values
            finite = values[np.isfinite(values)]
            assert finite.size > 0
            assert float(np.nanmin(finite)) >= 0.0
            assert float(np.nanmax(finite)) < 600.0
            assert dataset["lat"].min() >= -90.0
            assert dataset["lat"].max() <= 90.0
            assert dataset["lon"].min() >= -180.0
            assert dataset["lon"].max() <= 180.0
    finally:
        fetcher.close()
