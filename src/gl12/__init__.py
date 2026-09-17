"""Typed access to the INPE GL1.2 daily solar irradiance product.

GL1.2 (Ceballos et al., 2004; Porfirio et al., 2020) infers the surface
downward shortwave radiation flux from GOES visible-channel imagery. INPE's Big
Data Cube publishes one 0.04-degree NetCDF grid per day over South America and
adjacent oceans, indexed by a STAC collection with history from 2013-07-30.

```python
from datetime import date

from gl12 import DailyRequest, Experiment

experiment = Experiment(
    name="gl12_sep_2026",
    day_1=DailyRequest(day=date(2026, 9, 14)),
    day_2=DailyRequest(day=date(2026, 9, 15)),
)
experiment.download()
experiment.to_zarr()
dataset = experiment.open()  # time, lat, lon; dswrf in W/m**2
```
"""

from gl12.cache import experiment_cache_dir
from gl12.cache import experiment_cache_key
from gl12.cache import experiment_store_path
from gl12.chunking import MUTABLE_WINDOW
from gl12.chunking import Chunk
from gl12.chunking import ChunkPlan
from gl12.chunking import plan_chunks
from gl12.chunking import plan_summary
from gl12.decode import CANONICAL_VARIABLE
from gl12.decode import DSWRF_SCALE
from gl12.decode import MAX_DAILY_IRRADIANCE
from gl12.decode import NODATA_DN
from gl12.decode import RAW_VARIABLE
from gl12.decode import open_gl12_dataset
from gl12.events import BytesTransferred
from gl12.events import FileResolved
from gl12.events import ItemResolved
from gl12.events import ItemWritten
from gl12.events import PipelineEvent
from gl12.events import PipelineListener
from gl12.events import RequestPlanned
from gl12.events import StorePlanned
from gl12.exceptions import DownloadError
from gl12.exceptions import Gl12Error
from gl12.exceptions import Gl12ValidationError
from gl12.exceptions import MissingCoordinateError
from gl12.exceptions import NoDataAvailableError
from gl12.exceptions import StacError
from gl12.experiment import Experiment
from gl12.models import GL12_HISTORY_START
from gl12.models import Area
from gl12.models import Cycle
from gl12.models import DailyRequest
from gl12.models import days_between
from gl12.retrieval import Fetcher
from gl12.retrieval import Gl12Downloader
from gl12.retrieval import HttpxFetcher
from gl12.root import resolve_project_root
from gl12.stac import COLLECTION_ID
from gl12.stac import DATA_ASSET
from gl12.stac import STAC_BASE
from gl12.stac import StacItem
from gl12.stac import item_search_url
from gl12.stac import parse_item
from gl12.zarr import apply_area
from gl12.zarr import files_to_zarr
from gl12.zarr import normalize_dataset
from gl12.zarr import stamp_day
from gl12.zarr import write_zarr


__all__ = [
    "CANONICAL_VARIABLE",
    "COLLECTION_ID",
    "DATA_ASSET",
    "DSWRF_SCALE",
    "GL12_HISTORY_START",
    "MAX_DAILY_IRRADIANCE",
    "MUTABLE_WINDOW",
    "NODATA_DN",
    "RAW_VARIABLE",
    "STAC_BASE",
    "Area",
    "BytesTransferred",
    "Chunk",
    "ChunkPlan",
    "Cycle",
    "DailyRequest",
    "DownloadError",
    "Experiment",
    "Fetcher",
    "FileResolved",
    "Gl12Downloader",
    "Gl12Error",
    "Gl12ValidationError",
    "HttpxFetcher",
    "ItemResolved",
    "ItemWritten",
    "MissingCoordinateError",
    "NoDataAvailableError",
    "PipelineEvent",
    "PipelineListener",
    "RequestPlanned",
    "StacError",
    "StacItem",
    "StorePlanned",
    "apply_area",
    "days_between",
    "experiment_cache_dir",
    "experiment_cache_key",
    "experiment_store_path",
    "files_to_zarr",
    "item_search_url",
    "normalize_dataset",
    "open_gl12_dataset",
    "parse_item",
    "plan_chunks",
    "plan_summary",
    "resolve_project_root",
    "stamp_day",
    "write_zarr",
]
