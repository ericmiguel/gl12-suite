"""Experiment cache identity and namespace construction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields
from dataclasses import is_dataclass
from datetime import date
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from gl12.models import DailyRequest

CACHE_SCHEMA_VERSION = 1
CACHE_SOURCE = "gl12"


def experiment_cache_key(
    name: str,
    requests: Mapping[str, DailyRequest],
) -> str:
    """Return a stable key for an experiment name and request definitions."""
    identity = {
        "schema": CACHE_SCHEMA_VERSION,
        "source": CACHE_SOURCE,
        "name": name,
        "requests": {
            request_name: {
                "type": type(request).__qualname__,
                "fields": _normalize_dataclass(request),
            }
            for request_name, request in sorted(requests.items())
        },
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def experiment_cache_dir(cache_root: Path, cache_key: str) -> Path:
    """Return the isolated cache directory for one GL1.2 experiment."""
    return Path(cache_root) / CACHE_SOURCE / cache_key


def experiment_store_path(data_root: Path, cache_key: str) -> Path:
    """Return the canonical Zarr v3 path for one GL1.2 experiment."""
    return Path(data_root) / CACHE_SOURCE / f"{cache_key}.zarr"


def _normalize_dataclass(value: object) -> dict[str, object]:
    """Convert a request dataclass into JSON-compatible identity data."""
    if not is_dataclass(value):
        raise TypeError("Cache identity requires a dataclass request.")
    return {
        field.name: _normalize_value(getattr(value, field.name))
        for field in fields(value)
    }


def _normalize_value(value: object) -> object:
    """Normalize nested request values for canonical JSON serialization."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _normalize_dataclass(value)
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_value(item)
            for key, item in sorted(value.items(), key=str)
        }
    if isinstance(value, (tuple, list)):
        return [_normalize_value(item) for item in value]
    return value
