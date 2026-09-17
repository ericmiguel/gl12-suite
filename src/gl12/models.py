"""Typed request objects for the INPE GL1.2 daily solar irradiance product.

GL1.2 (Ceballos et al., 2004; Porfirio et al., 2020) infers the surface
downward shortwave radiation flux (DSWRF) from GOES visible-channel imagery.
INPE publishes one NetCDF grid per day over South America and adjacent oceans
at 0.04 degrees. The suite's vocabulary mirrors the other daily suites: a
*day* and an optional *area*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timedelta
from math import isfinite
from typing import TYPE_CHECKING

from gl12.exceptions import Gl12ValidationError


if TYPE_CHECKING:
    from collections.abc import Iterable

#: The BDC STAC collection publishes daily GL1.2 grids from 2013-07-30.
GL12_HISTORY_START = date(2013, 7, 30)


@dataclass(frozen=True, kw_only=True)
class Cycle:
    """One GL1.2 daily integration cycle.

    Parameters
    ----------
    day : datetime.date
        The UTC day the daily mean irradiance integrates over.
    """

    day: date

    def __post_init__(self) -> None:
        """Reject days outside the published history."""
        if not isinstance(self.day, date):
            raise Gl12ValidationError("Cycle day must be a date.")
        if self.day < GL12_HISTORY_START:
            raise Gl12ValidationError(
                f"GL1.2 history starts {GL12_HISTORY_START.isoformat()}."
            )
        if self.day > date.today():
            raise Gl12ValidationError("Cycle day cannot be in the future.")

    @property
    def stamp(self) -> str:
        """Return the ``YYYYMMDD`` file label."""
        return f"{self.day.year:04d}{self.day.month:02d}{self.day.day:02d}"

    @property
    def reference(self) -> datetime:
        """Return the published instant: midnight UTC of the integration day.

        The STAC item for a daily GL1.2 grid is stamped ``T00:00:00Z`` with the
        integration window ending at ``23:59:59Z``; the store keeps that source
        convention rather than inventing a noon reference.
        """
        return datetime(self.day.year, self.day.month, self.day.day)

    def __str__(self) -> str:
        """Return a compact human label such as ``2026-09-15``."""
        return self.day.isoformat()


@dataclass(frozen=True, kw_only=True)
class Area:
    """A geographic bounding box applied when the store is written.

    GL1.2 grids are whole South America fields; the box is applied locally, at
    store time, and it never changes which bytes are downloaded.

    Parameters
    ----------
    south, north : float
        Latitude bounds in degrees.
    west, east : float
        Longitude bounds in degrees on the source ``[-180, 180)`` convention
        (e.g. Brazil is roughly -74..-34). ``west`` greater than ``east``
        crosses the dateline.
    """

    south: float
    north: float
    west: float
    east: float

    def __post_init__(self) -> None:
        """Validate finite, ordered bounds on the source convention."""
        values = (self.south, self.north, self.west, self.east)
        if not all(isfinite(value) for value in values):
            raise Gl12ValidationError("Area bounds must be finite.")
        if not -90 <= self.south < self.north <= 90:
            raise Gl12ValidationError(
                "Latitude bounds must satisfy -90 <= south < north <= 90."
            )
        if not -180 <= self.west <= 180 or not -180 <= self.east <= 180:
            raise Gl12ValidationError(
                "Longitude bounds must lie in -180 <= bound <= 180."
            )
        if self.west == 0.0 and self.east == 0.0:
            raise Gl12ValidationError("Longitude bounds must span some longitude.")

    @property
    def crosses_dateline(self) -> bool:
        """Return whether the box spans the ``180`` meridian."""
        return self.west > self.east


@dataclass(frozen=True, kw_only=True)
class DailyRequest:
    """Validated parameters for one GL1.2 daily download.

    Parameters
    ----------
    day : date
        The integration day to read.
    area : Area or None, default=None
        Optional spatial subset applied when the store is written.
    """

    day: date
    area: Area | None = None

    def __post_init__(self) -> None:
        """Validate the day against the published history."""
        Cycle(day=self.day)

    @property
    def cycle(self) -> Cycle:
        """Return the validated daily cycle for the request."""
        return Cycle(day=self.day)

    @property
    def stamp(self) -> str:
        """Return the ``YYYYMMDD`` file label."""
        return self.cycle.stamp

    @property
    def reference(self) -> datetime:
        """Return the published instant (midnight UTC of the day)."""
        return self.cycle.reference


def days_between(start: date, end: date) -> Iterable[date]:
    """Yield every day in the inclusive range, oldest first."""
    step = timedelta(days=1)
    day = start
    while day <= end:
        yield day
        day += step
