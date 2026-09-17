"""STAC item resolution, offline."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import probe_day
from conftest import stac_payload
from gl12 import COLLECTION_ID
from gl12 import NoDataAvailableError
from gl12 import StacError
from gl12 import item_search_url
from gl12 import parse_item


def test_item_search_url_isolates_one_day() -> None:
    """The search URL filters the collection to the integration day."""
    url = item_search_url(date(2026, 9, 15))
    assert COLLECTION_ID in url
    assert "datetime=2026-09-15T00:00:00Z/2026-09-15T23:59:59Z" in url


def test_parse_item_returns_the_netcdf_asset() -> None:
    """The published href, size and checksum are extracted."""
    payload = stac_payload(probe_day(), b"abc")
    item = parse_item(payload, probe_day())
    assert item.day == probe_day()
    assert item.data_url.endswith(".nc")
    assert item.size == 3
    assert item.checksum is not None and item.checksum.startswith("1220")
    assert item.item_id == "GOES_GL_DSWRF_DAILY_202609150000"


def test_parse_item_without_features_is_no_data() -> None:
    """An empty collection response means the day is unpublished."""
    payload: dict[str, object] = {
        "type": "FeatureCollection",
        "features": list[object](),
    }
    with pytest.raises(NoDataAvailableError, match="no published grid"):
        parse_item(payload, probe_day())


def test_parse_item_ignores_other_days() -> None:
    """An item for a different day is not the requested one."""
    payload = stac_payload(date(2026, 9, 14), b"abc")
    with pytest.raises(NoDataAvailableError, match="no published grid"):
        parse_item(payload, probe_day())


def test_parse_item_without_data_asset_is_stac_error() -> None:
    """A well-formed item missing the NetCDF asset is a library error."""
    payload = stac_payload(probe_day(), b"abc")
    feature = payload["features"][0]  # type: ignore[index]
    feature["assets"] = {}  # type: ignore[index]
    with pytest.raises(StacError, match="dswrf_daily_mean"):
        parse_item(payload, probe_day())


def test_parse_item_rejects_non_collection_payload() -> None:
    """A malformed response fails fast."""
    with pytest.raises(StacError, match="features"):
        parse_item({"type": "Feature"}, probe_day())
