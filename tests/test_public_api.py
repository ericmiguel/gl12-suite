"""The package surface stays importable and complete."""

from __future__ import annotations

import gl12


def test_every_public_name_is_importable() -> None:
    """All documented exports exist on the package."""
    for name in gl12.__all__:
        assert hasattr(gl12, name), name


def test_contract_names_are_present() -> None:
    """The shared suite contract is exposed."""
    for name in (
        "Experiment",
        "DailyRequest",
        "Area",
        "Gl12Downloader",
        "Fetcher",
        "PipelineEvent",
        "NoDataAvailableError",
        "GL12_HISTORY_START",
        "DSWRF_SCALE",
    ):
        assert name in gl12.__all__
