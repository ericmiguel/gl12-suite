"""Typed events emitted by the download and store pipelines.

The library does not depend on a terminal or UI toolkit. Callers subscribe
with a plain callable and decide whether events become progress bars, logs,
metrics, or nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True, kw_only=True)
class RequestPlanned:
    """One named request was planned into its server items."""

    name: str
    files: int
    messages: int


@dataclass(frozen=True, kw_only=True)
class ItemResolved:
    """A planned day was resolved to a published STAC asset."""

    request: str
    url: str
    item: str


@dataclass(frozen=True, kw_only=True)
class FileResolved:
    """One planned chunk reached its final cached state."""

    request: str
    path: Path


@dataclass(frozen=True, kw_only=True)
class BytesTransferred:
    """One streamed block while downloading a file.

    ``total`` is the advertised content length when known. ``done`` marks the
    final event for the file.
    """

    name: str
    total: int | None
    amount: int
    done: bool = False


@dataclass(frozen=True, kw_only=True)
class StorePlanned:
    """The store write was planned."""

    items: int


@dataclass(frozen=True, kw_only=True)
class ItemWritten:
    """The experiment store was written."""

    description: str


type PipelineEvent = (
    RequestPlanned
    | ItemResolved
    | FileResolved
    | BytesTransferred
    | StorePlanned
    | ItemWritten
)
"""Union of every event emitted by the pipeline."""


type PipelineListener = Callable[[PipelineEvent], None]
"""Subscriber receiving pipeline events; plain callables, no framework."""
