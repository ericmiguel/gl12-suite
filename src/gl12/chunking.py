"""Deterministic item planning for the INPE GL1.2 daily product.

One day is one published NetCDF grid. The published file name carries a
versioned product id, so a chunk addresses a day through its STAC search URL
and the downloader resolves the asset from the response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from gl12.stac import item_search_url


if TYPE_CHECKING:
    from gl12.models import Area
    from gl12.models import Cycle
    from gl12.models import DailyRequest

#: A day published within this many days can still be receiving corrections.
MUTABLE_WINDOW = timedelta(days=2)


@dataclass(frozen=True, kw_only=True)
class Chunk:
    """One GL1.2 daily grid and its cache location.

    Parameters
    ----------
    stac_url : str
        STAC items URL that isolates the day.
    path : pathlib.Path
        Cache destination of the downloaded NetCDF.
    request_name : str
        Name of the request the chunk belongs to.
    cycle : Cycle
        The integration day.
    area : Area or None
        Area filter, applied when the store is written.
    url : str or None
        Resolved NetCDF asset URL, filled by the downloader from STAC.
    size : int or None
        Advertised asset size, filled by the downloader from STAC.
    checksum : str or None
        Advertised asset multihash, filled by the downloader from STAC.
    mutable : bool
        Whether the published grid may still be replaced by INPE.
    """

    stac_url: str
    path: Path
    request_name: str
    cycle: Cycle
    area: Area | None = None
    url: str | None = None
    size: int | None = None
    checksum: str | None = None
    mutable: bool = False

    @property
    def label(self) -> str:
        """Return a compact label for events and logs."""
        return f"gl12 {self.cycle}"


@dataclass(frozen=True, kw_only=True)
class ChunkPlan:
    """Immutable deterministic chunks for one request."""

    request: DailyRequest
    cache_dir: Path
    chunks: tuple[Chunk, ...]

    @property
    def message_count(self) -> int:
        """Return how many daily grids the plan addresses."""
        return len(self.chunks)


def plan_chunks(
    request: DailyRequest,
    cache_dir: Path,
    *,
    request_name: str = "request",
    today: date | None = None,
) -> ChunkPlan:
    """Plan the GL1.2 grid for one daily request.

    Parameters
    ----------
    request : DailyRequest
        Validated request.
    cache_dir : pathlib.Path
        Cache directory of the owning experiment.
    request_name : str, default="request"
        Name used in events and logs.
    today : datetime.date, optional
        Reference day for the mutability window; ``date.today()`` when omitted.
    """
    reference_day = today or date.today()
    chunks = [
        Chunk(
            stac_url=item_search_url(request.day),
            path=Path(cache_dir) / f"{request.stamp}.nc",
            request_name=request_name,
            cycle=request.cycle,
            area=request.area,
            mutable=(reference_day - request.day) <= MUTABLE_WINDOW,
        )
    ]
    return ChunkPlan(request=request, cache_dir=Path(cache_dir), chunks=tuple(chunks))


def plan_summary(plan: ChunkPlan) -> str:
    """Return a one-line summary of a chunk plan."""
    return f"{len(plan.chunks)} grids, {plan.message_count} fields"
