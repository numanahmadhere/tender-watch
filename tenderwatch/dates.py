from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

PKT = timezone(timedelta(hours=5))


def now_pkt() -> datetime:
    return datetime.now(PKT)


_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
)

# e.g. "Wednesday, October 21, 2026 11:00 AM", "Dec 08, 2026 09:30 AM", "Oct 19, 2026"
DATE_RE = re.compile(
    r"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s*)?"
    r"(?:" + _MONTHS + r")\.?\s+\d{1,2},\s+\d{4}(?:\s+\d{1,2}:\d{2}\s*[AP]M)?",
    re.IGNORECASE,
)

_FORMATS = (
    "%d-%b-%Y",
    "%d-%b-%Y %H:%M",
    "%A, %B %d, %Y %I:%M %p",
    "%A, %B %d, %Y",
    "%B %d, %Y %I:%M %p",
    "%b %d, %Y %I:%M %p",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%d-%m-%Y",
)


def parse_date(text: object) -> str:
    """Return 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM', or '' if the text is not a date."""
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip().replace("Sept", "Sep").replace(".", "")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2})?(?:\.\d+)?)?Z?$", s)
    if m:
        day, hh, mm = m.groups()
        if not hh or (hh == "00" and mm == "00"):
            return day
        return f"{day}T{hh}:{mm}"
    for fmt in _FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        has_time = "%H" in fmt or "%I" in fmt
        return dt.strftime("%Y-%m-%dT%H:%M" if has_time else "%Y-%m-%d")
    return ""


def find_dates(text: str) -> list[str]:
    """All date-like substrings of a text blob, parsed, in order of appearance."""
    out = []
    for m in DATE_RE.finditer(text or ""):
        parsed = parse_date(m.group(0))
        if parsed:
            out.append(parsed)
    return out


_REL_RE = re.compile(r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*left", re.IGNORECASE)


def parse_relative(text: str, now: datetime) -> str:
    """Turn '1h 49m Left' into an absolute deadline. Returns '' when there is no countdown."""
    m = _REL_RE.search(text or "")
    if not m or not any(m.groups()):
        return ""
    days, hours, mins = (int(g) if g else 0 for g in m.groups())
    dt = now + timedelta(days=days, hours=hours, minutes=mins)
    return dt.strftime("%Y-%m-%dT%H:%M")


def days_until(iso: str, now: datetime) -> int | None:
    """Whole days from today until the given ISO date. None if unknown."""
    if not iso:
        return None
    try:
        target = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (target - now.date()).days
