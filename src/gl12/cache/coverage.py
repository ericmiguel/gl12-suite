"""Coverage summaries for GL1.2 stores.

GL1.2 fragments are daily South America grids, so area is a read-time view
and the coverage axes that matter are time and variables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gl12.decode import CANONICAL_VARIABLE
from gl12.models import DailyRequest


if TYPE_CHECKING:
    from collections.abc import Mapping


GRID_SIGNATURE = "latlon:0.04:south-america"


def summarize_coverage(requests: Mapping[str, object]) -> dict[str, object]:
    """Return the time, variable, and grid coverage of a request set."""
    days: list[str] = []
    for request in requests.values():
        if isinstance(request, DailyRequest):
            days.append(request.day.isoformat())
    return {
        "time": [min(days), max(days)] if days else [],
        "variables": [CANONICAL_VARIABLE],
        "grid": GRID_SIGNATURE,
    }
