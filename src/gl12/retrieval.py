"""HTTP retrieval of GL1.2 daily grids from the INPE Big Data Cube.

A day is resolved to its published NetCDF asset through STAC, then streamed
whole. The STAC item's SHA-256 multihash and byte size verify the transfer, and
the decoded grid is checked for physically plausible irradiance before it
replaces a cached file.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

import httpx
import numpy as np
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from gl12.decode import CANONICAL_VARIABLE
from gl12.decode import MAX_DAILY_IRRADIANCE
from gl12.decode import open_gl12_dataset
from gl12.events import BytesTransferred
from gl12.events import ItemResolved
from gl12.exceptions import DownloadError
from gl12.exceptions import NoDataAvailableError
from gl12.stac import parse_item


if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Iterator
    from pathlib import Path

    from gl12.chunking import Chunk
    from gl12.events import PipelineListener
    from gl12.stac import StacItem

LOGGER = logging.getLogger(__name__)


def _log_retry(state: object) -> None:
    """Log a tenacity retry without exposing response contents."""
    LOGGER.warning("Retrying transient INPE BDC request: %s", state)


@dataclass(frozen=True, kw_only=True)
class HeadInfo:
    """Minimal HEAD response information used by the downloader."""

    status_code: int
    headers: Mapping[str, str]


class Fetcher(Protocol):
    """Offline-testable transport protocol for INPE BDC resources."""

    def get_json(self, url: str) -> object:
        """Return the decoded JSON body of a URL."""

    def head(self, url: str) -> HeadInfo:
        """Return status and headers for a URL."""

    def stream_range(self, url: str, start: int, end: int) -> Iterable[bytes]:
        """Yield the bytes of an inclusive range of a remote file."""


class TransientHTTPError(httpx.HTTPError):
    """Internal marker for retryable HTTP status responses."""


class HttpxFetcher:
    """Streaming HTTPS fetcher with explicit timeouts and transient retries."""

    def __init__(
        self,
        *,
        connect_timeout: float = 10.0,
        read_timeout: float = 120.0,
        pool_timeout: float = 10.0,
        write_timeout: float = 120.0,
    ) -> None:
        timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            pool=pool_timeout,
            write=write_timeout,
        )
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def get_json(self, url: str) -> object:
        """Return the JSON body of a STAC or catalog resource."""
        response = self._request_json(url)
        try:
            return response.json()
        except ValueError as error:
            raise DownloadError(f"Invalid JSON from {url}") from error

    def head(self, url: str) -> HeadInfo:
        """Issue a HEAD request with transient retry handling."""
        response = self._request_head(url)
        return HeadInfo(status_code=response.status_code, headers=response.headers)

    def stream_range(self, url: str, start: int, end: int) -> Iterator[bytes]:
        """Stream an inclusive byte range in blocks."""
        response = self._stream_response(url, start, end)
        try:
            yield from response.iter_bytes()
        finally:
            response.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, TransientHTTPError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        before_sleep=_log_retry,
        reraise=True,
    )
    def _request_json(self, url: str) -> httpx.Response:
        """Request JSON and mark only transient statuses for retry."""
        response = self._client.get(url)
        _raise_retryable_status(response)
        response.raise_for_status()
        return response

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, TransientHTTPError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        before_sleep=_log_retry,
        reraise=True,
    )
    def _request_head(self, url: str) -> httpx.Response:
        """Request HEAD and mark only 429/5xx as retryable."""
        response = self._client.head(url)
        _raise_retryable_status(response)
        return response

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, TransientHTTPError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        before_sleep=_log_retry,
        reraise=True,
    )
    def _stream_response(self, url: str, start: int, end: int) -> httpx.Response:
        """Open a ranged response and mark only transient statuses for retry."""
        request = self._client.build_request(
            "GET", url, headers={"Range": f"bytes={start}-{end}"}
        )
        response = self._client.send(request, stream=True)
        try:
            _raise_retryable_status(response)
            response.raise_for_status()
        except httpx.HTTPError:
            response.close()
            raise
        return response

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


def _raise_retryable_status(response: httpx.Response) -> None:
    """Raise retry markers for 429 and server errors only."""
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientHTTPError(f"Transient HTTP status {response.status_code}")


class Gl12Downloader:
    """Resolve, download, cache, and verify GL1.2 daily grids."""

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or HttpxFetcher()

    def download_chunk(
        self,
        chunk: Chunk,
        *,
        listener: PipelineListener | None = None,
        skip_missing: bool = False,
    ) -> Path:
        """Download one daily grid into the cache, atomically.

        Parameters
        ----------
        chunk : Chunk
            Planned day, STAC search URL and cache destination.
        listener : PipelineListener or None, default=None
            Optional subscriber receiving item and byte-transfer events.
        skip_missing : bool, default=False
            Whether an unpublished day is left out instead of failing. Handled
            by the experiment; kept for contract parity.

        Returns
        -------
        pathlib.Path
            The verified NetCDF file.

        Raises
        ------
        NoDataAvailableError
            If the STAC collection publishes no grid for the day.
        DownloadError
            If the transfer or the decoded file cannot be verified.
        """
        del skip_missing  # the experiment handles skipping
        item = self._resolve(chunk)
        object.__setattr__(chunk, "url", item.data_url)
        object.__setattr__(chunk, "size", item.size)
        object.__setattr__(chunk, "checksum", item.checksum)
        if listener is not None:
            listener(
                ItemResolved(
                    request=chunk.request_name, url=item.data_url, item=item.item_id
                )
            )
        if self._cache_is_usable(chunk):
            return chunk.path
        file_size = item.size or self._remote_size(item.data_url)
        chunk.path.parent.mkdir(parents=True, exist_ok=True)
        part = chunk.path.with_name(f".{chunk.path.name}.part")
        part.unlink(missing_ok=True)
        try:
            self._download(chunk, file_size, part, listener=listener)
            self._verify(part, item.checksum)
            part.replace(chunk.path)
        except NoDataAvailableError:
            raise
        except DownloadError:
            raise
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
            raise DownloadError(f"Could not download {item.data_url}") from error
        finally:
            part.unlink(missing_ok=True)
        LOGGER.info("Stored %s (%d bytes).", chunk.path.name, file_size)
        return chunk.path

    def _resolve(self, chunk: Chunk) -> StacItem:
        """Resolve the day's published asset through STAC."""
        try:
            payload = self.fetcher.get_json(chunk.stac_url)
        except (OSError, httpx.HTTPError) as error:
            if _status_code_from_error(error) == 404:
                raise NoDataAvailableError(
                    f"INPE BDC has not published {chunk.cycle}."
                ) from error
            raise DownloadError(f"Could not query {chunk.stac_url}") from error
        return parse_item(payload, chunk.cycle.day)

    def _cache_is_usable(self, chunk: Chunk) -> bool:
        """Verify an existing grid, re-checking recent days."""
        if not chunk.path.is_file():
            return False
        expected_size = chunk.size if chunk.mutable else None
        if expected_size is not None and chunk.path.stat().st_size != expected_size:
            return False
        try:
            self._verify(chunk.path, chunk.checksum)
        except (DownloadError, OSError, ValueError, RuntimeError):
            chunk.path.unlink(missing_ok=True)
            return False
        return True

    def _remote_size(self, url: str) -> int:
        """Return Content-Length and reject all failed HEAD responses."""
        try:
            response = self.fetcher.head(url)
        except (OSError, httpx.HTTPError) as error:
            raise DownloadError(f"HEAD failed for {url}") from error
        status = _status_code(response)
        if status == 404:
            raise NoDataAvailableError(f"INPE BDC has not published {url} yet.")
        if status >= 400:
            raise DownloadError(f"HEAD returned HTTP {status} for {url}")
        value = _headers(response).get("content-length")
        if value is None:
            raise DownloadError(f"HEAD omitted Content-Length for {url}")
        try:
            return int(value)
        except ValueError as error:
            raise DownloadError(f"Invalid Content-Length for {url}") from error

    def _download(
        self,
        chunk: Chunk,
        file_size: int,
        target: Path,
        *,
        listener: PipelineListener | None,
    ) -> None:
        """Stream the whole grid into the target path."""
        if chunk.url is None:
            raise DownloadError("Chunk has no resolved URL.")
        written = 0
        with target.open("wb") as output:
            for block in self.fetcher.stream_range(chunk.url, 0, file_size - 1):
                if not isinstance(block, bytes):
                    raise DownloadError("Fetcher yielded a non-byte block.")
                output.write(block)
                written += len(block)
                if listener is not None:
                    listener(
                        BytesTransferred(
                            name=chunk.label, total=file_size, amount=len(block)
                        )
                    )
        if written != file_size:
            raise DownloadError(
                f"Downloaded {written} of {file_size} advertised bytes for {chunk.url}."
            )
        if listener is not None:
            listener(
                BytesTransferred(name=chunk.label, total=written, amount=0, done=True)
            )

    @staticmethod
    def _verify(path: Path, checksum: str | None) -> None:
        """Verify the transfer checksum and the decoded field plausibility."""
        if not path.is_file() or path.stat().st_size == 0:
            raise DownloadError(f"Downloaded file is empty: {path}")
        expected = _sha256_from_multihash(checksum)
        if expected is not None and _sha256(path) != expected:
            raise DownloadError(f"Checksum mismatch for {path.name}.")
        dataset = open_gl12_dataset(path)
        try:
            field = dataset.data_vars.get(CANONICAL_VARIABLE)
            if field is None:
                raise DownloadError(f"GL1.2 file {path.name} decoded no dswrf.")
            values = np.asarray(field.values, dtype="float64")
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                raise DownloadError(f"GL1.2 file {path.name} has no finite values.")
            if float(np.nanmin(finite)) < 0.0:
                raise DownloadError(f"GL1.2 file {path.name} has negative irradiance.")
            if float(np.nanmax(finite)) > MAX_DAILY_IRRADIANCE:
                raise DownloadError(
                    f"GL1.2 file {path.name} carries implausible irradiance."
                )
        finally:
            dataset.close()


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file, read in blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_from_multihash(value: str | None) -> str | None:
    """Return the hex digest of a SHA-256 multihash, or ``None`` otherwise."""
    if value is None or not value.startswith("1220") or len(value) != 68:
        return None
    return value[4:]


def _status_code(response: object) -> int:
    """Extract an HTTP status from a protocol response."""
    value = getattr(response, "status_code", None)
    if not isinstance(value, int):
        raise DownloadError("Fetcher HEAD response has no integer status code.")
    return value


def _headers(response: object) -> dict[str, str]:
    """Normalize protocol response headers to lowercase strings."""
    raw = getattr(response, "headers", None)
    if not isinstance(raw, Mapping):
        raise DownloadError("Fetcher HEAD response has no headers.")
    return {str(key).lower(): str(value) for key, value in raw.items()}


def _status_code_from_error(error: BaseException) -> int | None:
    """Extract an HTTP status from an exception when one is available."""
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


__all__ = [
    "Fetcher",
    "Gl12Downloader",
    "HeadInfo",
    "HttpxFetcher",
    "TransientHTTPError",
]
