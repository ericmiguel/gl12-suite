"""STAC resolution of one GL1.2 daily grid.

INPE's Big Data Cube exposes the GL1.2 daily DSWRF product as the STAC
collection ``GOES-GL-DSWRF-Daily-1``. File names carry a versioned product id
(``S11167052`` today) that changes on reprocessing, so the suite never builds
URLs by hand: a day is resolved to its published NetCDF asset through the STAC
item endpoint, exactly like the other suites resolve listing names.

The item also advertises the SHA-256 multihash and byte size of the NetCDF,
which the downloader uses to verify a transfer without trusting the transport.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from datetime import datetime

from gl12.exceptions import NoDataAvailableError
from gl12.exceptions import StacError


#: Root of the INPE Big Data Cube STAC API.
STAC_BASE = "https://data.inpe.br/bdc/stac/v1"

#: Collection holding the GL1.2 daily mean DSWRF grids.
COLLECTION_ID = "GOES-GL-DSWRF-Daily-1"

#: Asset key of the NetCDF grid inside each STAC item.
DATA_ASSET = "dswrf_daily_mean"


def item_search_url(day: date) -> str:
    """Return the STAC items URL that isolates one integration day."""
    stamp = day.isoformat()
    return (
        f"{STAC_BASE}/collections/{COLLECTION_ID}/items"
        f"?datetime={stamp}T00:00:00Z/{stamp}T23:59:59Z"
    )


@dataclass(frozen=True, kw_only=True)
class StacItem:
    """The published GL1.2 grid resolved from one STAC item.

    Parameters
    ----------
    item_id : str
        STAC item identifier, e.g. ``GOES_GL_DSWRF_DAILY_202609150000``.
    day : datetime.date
        The integration day the item belongs to.
    data_url : str
        Published NetCDF asset URL.
    size : int or None
        Advertised byte size of the asset, when present.
    checksum : str or None
        Advertised multihash of the asset, when present.
    """

    item_id: str
    day: date
    data_url: str
    size: int | None
    checksum: str | None


def parse_item(payload: object, day: date) -> StacItem:
    """Extract the NetCDF asset of one day from a STAC items response.

    Parameters
    ----------
    payload : object
        Decoded JSON body of a STAC ``FeatureCollection``.
    day : datetime.date
        The integration day requested.

    Returns
    -------
    StacItem
        The resolved asset.

    Raises
    ------
    NoDataAvailableError
        If the collection publishes no item for the day.
    StacError
        If the response is not a well-formed STAC item collection or the item
        lacks the expected data asset.
    """
    collection = _mapping(payload, "STAC response")
    features = collection.get("features")
    if not isinstance(features, list):
        raise StacError("STAC response has no 'features' array.")
    if not features:
        raise NoDataAvailableError(f"GL1.2 has no published grid for {day}.")
    for feature in features:
        candidate = _mapping(feature, "STAC feature")
        properties = _mapping(candidate.get("properties"), "STAC properties")
        found = _parse_datetime(properties.get("datetime"), "item datetime")
        if found.date() != day:
            continue
        assets = _mapping(candidate.get("assets"), "STAC assets")
        asset = assets.get(DATA_ASSET)
        if asset is None:
            raise StacError(f"STAC item for {day} lacks asset {DATA_ASSET!r}.")
        entry = _mapping(asset, "data asset")
        return StacItem(
            item_id=_text(candidate.get("id"), "item id"),
            day=day,
            data_url=_text(entry.get("href"), "asset href"),
            size=_optional_int(entry.get("bdc:size")),
            checksum=_optional_text(entry.get("checksum:multihash")),
        )
    raise NoDataAvailableError(f"GL1.2 has no published grid for {day}.")


def _parse_datetime(value: object, what: str) -> datetime:
    """Parse an ISO-8601 instant that may carry a trailing ``Z``."""
    text = _text(value, what)
    try:
        return datetime.fromisoformat(text.removesuffix("Z"))
    except ValueError as error:
        raise StacError(f"Invalid {what}: {text!r}.") from error


def _mapping(value: object, what: str) -> Mapping[str, object]:
    """Require a JSON object and return it as a string-keyed mapping."""
    if not isinstance(value, Mapping):
        raise StacError(f"{what} is not a JSON object.")
    return value  # type: ignore[return-value]


def _text(value: object, what: str) -> str:
    """Require a non-empty JSON string."""
    if not isinstance(value, str) or not value:
        raise StacError(f"{what} is missing or not a string.")
    return value


def _optional_text(value: object) -> str | None:
    """Return a JSON string or ``None`` when absent."""
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    """Return a JSON number as an int or ``None`` when absent."""
    return int(value) if isinstance(value, (int, float)) else None
