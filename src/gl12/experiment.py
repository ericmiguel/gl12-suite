"""Experiment orchestration for named GL1.2 daily requests."""

from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

import xarray as xr

from gl12.cache import default_namespace
from gl12.cache import legend_payload
from gl12.cache import normalize_dataclass
from gl12.cache import request_fingerprint
from gl12.cache import summarize_coverage
from gl12.chunking import plan_chunks
from gl12.events import FileResolved
from gl12.events import ItemWritten
from gl12.events import PipelineListener
from gl12.events import RequestPlanned
from gl12.events import StorePlanned
from gl12.exceptions import Gl12ValidationError
from gl12.exceptions import NoDataAvailableError
from gl12.models import DailyRequest
from gl12.retrieval import Gl12Downloader
from gl12.root import resolve_project_root
from gl12.zarr import files_to_zarr


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class Experiment:
    """Combine compatible named daily requests into one Zarr v3 store.

    Parameters
    ----------
    name : str
        Experiment name used in progress descriptions and store metadata.
    downloader : Gl12Downloader or None, default=None
        Optional downloader, normally injected with a fake in tests.
    root_dir : pathlib.Path or None, default=None
        Project root used for the hidden cache and data directories. When
        omitted, it is discovered from ``.git``, ``.venv``, or ``README.md``.
    requests : DailyRequest
        One or more named daily requests supplied as keyword arguments.
    """

    def __init__(
        self,
        *,
        name: str,
        downloader: Gl12Downloader | None = None,
        root_dir: Path | None = None,
        **requests: DailyRequest,
    ) -> None:
        if not name.strip():
            raise Gl12ValidationError("Experiment name cannot be empty.")
        if not requests:
            raise Gl12ValidationError("At least one named request is required.")
        if any(not isinstance(request, DailyRequest) for request in requests.values()):
            raise Gl12ValidationError("Experiment requests must be DailyRequests.")
        self.name = name
        self.requests = dict(requests)
        self.root_dir = resolve_project_root(root_dir)
        self._namespace = default_namespace(self.root_dir, name)
        self._fingerprint = request_fingerprint(self.requests)
        self.downloader = downloader or Gl12Downloader()
        self._paths: tuple[Path, ...] = ()
        self._request_paths: dict[str, tuple[Path, ...]] = {}
        self._store_path: Path | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def cache_key(self) -> str:
        """Return the request fingerprint (legacy name kept for callers)."""
        return self._fingerprint

    @property
    def fingerprint(self) -> str:
        """Return the request fingerprint that identifies the store."""
        return self._fingerprint

    @property
    def cache_path(self) -> Path:
        """Return the source-global fragment pool directory."""
        return self._namespace.pool_dir

    @property
    def store_path(self) -> Path:
        """Return the store path for this request fingerprint."""
        return self._namespace.store_path(self._fingerprint)

    def plan(self, request_name: str) -> tuple[str, int, int]:
        """Return ``(name, files, messages)`` for one named request."""
        request = self.requests[request_name]
        plan = plan_chunks(request, self.cache_path, request_name=request_name)
        return (request_name, len(plan.chunks), plan.message_count)

    def download(
        self,
        *,
        listener: PipelineListener | None = None,
        skip_missing: bool = False,
    ) -> tuple[Path, ...]:
        """Download every planned day and return deduplicated paths.

        Parameters
        ----------
        listener : PipelineListener or None, default=None
            Optional subscriber receiving planned, resolved and byte-transfer
            events.
        skip_missing : bool, default=False
            Whether a day INPE has not published yet is skipped with a warning
            instead of raising.

        Returns
        -------
        tuple of pathlib.Path
            Verified GL1.2 files in request and day order.
        """
        paths: list[Path] = []
        seen: set[Path] = set()
        for request_name, request in self.requests.items():
            plan = plan_chunks(request, self.cache_path, request_name=request_name)
            if listener is not None:
                listener(
                    RequestPlanned(
                        name=request_name,
                        files=len(plan.chunks),
                        messages=plan.message_count,
                    )
                )
            request_paths: list[Path] = []
            for chunk in plan.chunks:
                if chunk.path not in seen:
                    try:
                        self.downloader.download_chunk(
                            chunk, listener=listener, skip_missing=skip_missing
                        )
                    except NoDataAvailableError as error:
                        if not skip_missing:
                            raise
                        self._logger.warning("Skipping %s: %s", chunk.label, error)
                        continue
                    paths.append(chunk.path)
                    seen.add(chunk.path)
                request_paths.append(chunk.path)
                if listener is not None:
                    listener(FileResolved(request=request_name, path=chunk.path))
            self._request_paths[request_name] = tuple(request_paths)
        self._paths = tuple(paths)
        self._logger.info("Downloaded %d days for %s.", len(paths), self.name)
        return self._paths

    def to_zarr(
        self,
        *,
        overwrite: bool = False,
        listener: PipelineListener | None = None,
    ) -> Path:
        """Decode, crop, and write the experiment's Zarr store.

        Parameters
        ----------
        overwrite : bool, default=False
            Whether an existing destination may be replaced.
        listener : PipelineListener or None, default=None
            Optional subscriber receiving store-writing events.

        Returns
        -------
        pathlib.Path
            The written Zarr directory.
        """
        if not self._paths:
            raise RuntimeError("Call download() before to_zarr().")
        if listener is not None:
            listener(StorePlanned(items=1))
        groups = tuple(
            (self.requests[name], self._request_paths[name]) for name in self.requests
        )
        destination = files_to_zarr(
            self._paths,
            self.store_path,
            overwrite=overwrite,
            request_sources=groups,
        )
        self._store_path = destination
        if listener is not None:
            listener(ItemWritten(description=str(destination)))
        self._namespace.record_store(
            self._fingerprint,
            requests=_requests_identity(self.requests),
            coverage=summarize_coverage(self.requests),
            provenance=legend_payload(),
            now=_utc_now(),
        )
        self._logger.info("Wrote Zarr store %s.", destination)
        return destination

    def open(self) -> xr.Dataset:
        """Open the experiment's Zarr v3 store lazily."""
        if self._store_path is None:
            raise RuntimeError("Call to_zarr() before open().")
        return xr.open_zarr(self._store_path, consolidated=False)


def _requests_identity(requests: Mapping[str, object]) -> dict[str, object]:
    """Return a JSON-safe description of the named requests."""
    return {
        name: {
            "type": type(request).__qualname__,
            "fields": normalize_dataclass(request),
        }
        for name, request in sorted(requests.items())
    }


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()
