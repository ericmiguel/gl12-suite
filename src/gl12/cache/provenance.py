"""Provenance ranks for GL1.2 fragments.

INPE publishes one operational daily grid per day, so the store carries a
single provenance variant.
"""

from __future__ import annotations


PUBLISHED = 0

LEGEND: dict[int, str] = {
    PUBLISHED: "published",
}


def legend_payload() -> dict[str, str]:
    """Return the manifest-ready provenance legend."""
    return {str(code): label for code, label in LEGEND.items()}
