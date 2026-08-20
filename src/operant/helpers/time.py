"""
Timezone-aware clock helpers.

All timestamps in Operant are UTC and ISO-8601 formatted so evidence,
database rows, and API payloads compare and sort consistently.

Import as:

import operant.helpers.time as time
"""

from __future__ import annotations

import datetime
import time as _time
from typing import Optional


def utc_now() -> datetime.datetime:
    """
    Return the current time as an aware UTC ``datetime``.
    """
    now = datetime.datetime.now(tz=datetime.UTC)
    return now


def iso_now() -> str:
    """
    Return the current UTC time in ISO-8601 form.
    """
    now = utc_now().isoformat()
    return now


def monotonic() -> float:
    """
    Return a monotonic clock reading in seconds for deadlines.
    """
    reading = _time.monotonic()
    return reading


def timestamp_slug(moment: Optional[datetime.datetime] = None) -> str:
    """
    Format a moment as ``YYYYmmdd-HHMMSS`` for file and run names.

    :param moment: The moment to format; defaults to now.
    :return: A filesystem-safe timestamp.
    """
    slug = (moment or utc_now()).strftime("%Y%m%d-%H%M%S")
    return slug
