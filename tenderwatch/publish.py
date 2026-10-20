from __future__ import annotations

import requests

from .models import Tender
from .sources.base import Result

COLUMNS = [
    "UID", "First seen", "Last seen", "Status", "Source", "Title", "Buyer", "Category", "Notice type",
    "Published", "Deadline", "Days left", "Score", "Matched", "Winner", "Amount", "Link",
]
DATE_COLUMNS = ["First seen", "Last seen", "Published", "Deadline"]


def to_row(t: Tender, today: str) -> list:
    if t.kind == "award":
        status = "Award"
    elif t.change:
        status = "Updated"
    elif t.first_seen == today:
        status = "New"
    else:
        status = "Open"
    values = {
        "UID": t.uid,
        "First seen": t.first_seen or today,
        "Last seen": today,
        "Status": status,
        "Source": t.source,
        "Title": t.title,
        "Buyer": t.buyer,
        "Category": t.category,
        "Notice type": t.notice_type,
        "Published": t.published,
        "Deadline": t.deadline,
        "Days left": "",  # computed by a sheet formula
        "Score": t.score,
        "Matched": ", ".join(t.matched),
        "Winner": t.winner,
        "Amount": t.amount,
        "Link": t.url,
    }
    return [values[c] for c in COLUMNS]


def build_payload(token: str, today: str, tenders: list[Tender], awards: list[Tender], results: list[Result],
                  email: dict, counts: dict) -> dict:
    return {
        "token": token,
        "run": {"date": today, **counts},
        "columns": COLUMNS,
        "dateColumns": DATE_COLUMNS,
        "tenders": [to_row(t, today) for t in tenders],
        "awards": [to_row(t, today) for t in awards],
        "sources": [{"name": r.name, "status": r.status, "count": r.count, "message": r.message} for r in results],
        "email": email,
    }


def post(url: str, payload: dict) -> dict:
    """POST to the Apps Script web app. Raises RuntimeError unless it reports ok."""
    r = requests.post(url, json=payload, timeout=180)  # Apps Script replies via a redirect; requests follows it
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"webhook returned non-JSON (HTTP {r.status_code}): {r.text[:200]!r}")
    if not data.get("ok"):
        raise RuntimeError(f"webhook error: {data.get('error', data)}")
    return data
