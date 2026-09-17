"""Request validation for the GL1.2 daily product."""

from __future__ import annotations

from datetime import date
from datetime import datetime

import pytest

from gl12 import GL12_HISTORY_START
from gl12 import Area
from gl12 import Cycle
from gl12 import DailyRequest
from gl12 import Gl12ValidationError
from gl12 import days_between


def test_cycle_rejects_days_before_history() -> None:
    """The STAC collection starts 2013-07-30."""
    with pytest.raises(Gl12ValidationError, match="history"):
        Cycle(day=GL12_HISTORY_START.replace(day=GL12_HISTORY_START.day - 1))


def test_cycle_rejects_future_days() -> None:
    """A day after today cannot have been published."""
    with pytest.raises(Gl12ValidationError, match="future"):
        Cycle(day=date.today().replace(year=date.today().year + 1))


def test_cycle_stamp_and_reference_follow_the_source() -> None:
    """The label is YYYYMMDD and the instant is midnight UTC."""
    cycle = Cycle(day=date(2026, 9, 15))
    assert cycle.stamp == "20260915"
    assert cycle.reference == datetime(2026, 9, 15, 0, 0)
    assert str(cycle) == "2026-09-15"


def test_daily_request_exposes_cycle_fields() -> None:
    """A request mirrors its cycle's label and reference."""
    request = DailyRequest(day=date(2026, 9, 15))
    assert request.stamp == "20260915"
    assert request.reference == datetime(2026, 9, 15)


def test_area_rejects_disordered_or_non_finite_bounds() -> None:
    """Latitude and longitude bounds are validated at the boundary."""
    with pytest.raises(Gl12ValidationError, match="Latitude"):
        Area(south=10.0, north=-10.0, west=-70.0, east=-30.0)
    with pytest.raises(Gl12ValidationError, match="Longitude"):
        Area(south=-10.0, north=10.0, west=-200.0, east=-30.0)
    with pytest.raises(Gl12ValidationError, match="finite"):
        Area(south=-10.0, north=10.0, west=float("nan"), east=-30.0)


def test_area_crosses_dateline_flag() -> None:
    """``west > east`` marks the 180-degree seam."""
    assert Area(south=-10.0, north=10.0, west=170.0, east=-170.0).crosses_dateline
    assert not Area(south=-10.0, north=10.0, west=-70.0, east=-30.0).crosses_dateline
    with pytest.raises(Gl12ValidationError, match="span"):
        Area(south=-10.0, north=10.0, west=0.0, east=0.0)


def test_days_between_is_inclusive_and_ordered() -> None:
    """A rolling range yields each day, oldest first."""
    days = list(days_between(date(2026, 9, 14), date(2026, 9, 16)))
    assert days == [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)]
