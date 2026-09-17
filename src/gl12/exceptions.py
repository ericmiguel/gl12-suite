"""Exceptions raised by :mod:`gl12`."""

from __future__ import annotations


class Gl12Error(Exception):
    """Base class for all GL1.2 errors."""


class Gl12ValidationError(Gl12Error, ValueError):
    """Raised when a request or dataset violates a library contract."""


class StacError(Gl12Error):
    """Raised when the INPE BDC STAC response cannot be interpreted."""


class NoDataAvailableError(Gl12Error):
    """Raised when the STAC collection publishes no item for a planned day."""


class DownloadError(Gl12Error):
    """Raised when an HTTP transfer or a downloaded file cannot be verified."""


class MissingCoordinateError(Gl12ValidationError):
    """Raised when a dataset lacks a required spatial or temporal coordinate."""
