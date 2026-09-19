"""Tests for the cache namespace, fingerprint, and manifest contract."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from gl12.cache import ExperimentNamespace
from gl12.cache import request_fingerprint
from gl12.cache import validate_slug
from gl12.exceptions import Gl12ValidationError
from gl12.models import DailyRequest


if TYPE_CHECKING:
    from pathlib import Path


def _request(day: date = date(2026, 9, 1)) -> DailyRequest:
    return DailyRequest(day=day)


def test_fingerprint_excludes_name_and_tracks_fields() -> None:
    same = request_fingerprint({"daily": _request()})
    assert same == request_fingerprint({"daily": _request()})
    assert same != request_fingerprint({"daily": _request(date(2026, 9, 2))})
    assert same != request_fingerprint({"surface": _request()})


def test_slug_validation() -> None:
    assert validate_slug("gl12-sep") == "gl12-sep"
    for bad in ("", " ", "../escape", "a/b", ".hidden"):
        with pytest.raises(Gl12ValidationError):
            validate_slug(bad)


def test_namespace_paths(tmp_path: Path) -> None:
    namespace = ExperimentNamespace(tmp_path, "gl12", "solar")
    assert namespace.pool_dir == tmp_path / ".cache" / "fragments" / "gl12" / "v2"
    assert namespace.store_path("abc") == (
        tmp_path / ".cache" / "stores" / "gl12" / "solar" / "abc.zarr"
    )


def test_pool_is_shared_across_namespaces(tmp_path: Path) -> None:
    first = ExperimentNamespace(tmp_path, "gl12", "solar")
    second = ExperimentNamespace(tmp_path, "gl12", "precip")
    assert first.pool_dir == second.pool_dir
    assert first.data_dir != second.data_dir


def test_store_path_tracks_fingerprint(tmp_path: Path) -> None:
    namespace = ExperimentNamespace(tmp_path, "gl12", "solar")
    first = request_fingerprint({"daily": _request()})
    second = request_fingerprint({"daily": _request(date(2026, 9, 2))})
    assert namespace.store_path(first) != namespace.store_path(second)


def test_manifest_round_trip(tmp_path: Path) -> None:
    namespace = ExperimentNamespace(tmp_path, "gl12", "solar")
    assert namespace.load_manifest() is None
    namespace.record_store(
        "fp1",
        requests={"daily": {"type": "DailyRequest"}},
        coverage={"time": ["2026-09-01", "2026-09-01"]},
        provenance={"0": "published"},
        now="2026-09-18T12:00:00+00:00",
    )
    manifest = namespace.load_manifest()
    assert manifest is not None
    assert manifest.current == "fp1"
    assert manifest.stores["fp1"].coverage["time"] == ["2026-09-01", "2026-09-01"]
    assert manifest.stores["fp1"].provenance == {"0": "published"}
