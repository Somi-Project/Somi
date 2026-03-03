from __future__ import annotations

import re
from typing import Optional

from routing.types import TimeAnchor

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

_DATE_ISO = re.compile(r"\b(19\d{2}|20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
_RANGE = re.compile(r"\b(?:from\s+)?(19\d{2}|20\d{2})\s*(?:-|–|to)\s*(19\d{2}|20\d{2})\b", re.I)
_MONTH_YEAR = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\s+(19\d{2}|20\d{2})\b", re.I)
_MONTH_DAY_YEAR = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\s+([0-3]?\d)(?:st|nd|rd|th)?(?:,)?\s+(19\d{2}|20\d{2})\b", re.I)
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def extract_time_anchor(text: str) -> Optional[TimeAnchor]:
    t = str(text or "")
    m = _DATE_ISO.search(t)
    if m:
        return TimeAnchor(kind="date", year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)), date=m.group(0), label=m.group(0))

    m = _MONTH_DAY_YEAR.search(t)
    if m:
        month = _MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        date = f"{year:04d}-{month:02d}-{day:02d}"
        return TimeAnchor(kind="date", year=year, month=month, day=day, date=date, label=f"{m.group(1)} {day} {year}")

    m = _RANGE.search(t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        start_year, end_year = (a, b) if a <= b else (b, a)
        return TimeAnchor(kind="range", start_year=start_year, end_year=end_year, label=f"{start_year}-{end_year}")

    m = _MONTH_YEAR.search(t)
    if m:
        month = _MONTHS[m.group(1).lower()]
        year = int(m.group(2))
        return TimeAnchor(kind="month_year", year=year, month=month, label=f"{m.group(1)} {year}")

    m = _YEAR.search(t)
    if m:
        y = int(m.group(1))
        return TimeAnchor(kind="year", year=y, label=str(y))

    return None
