from __future__ import annotations

from datetime import datetime
from html import escape

from .dates import days_until
from .models import Tender
from .sources.base import Result

MAX_PER_SECTION = 40


def closing_soon(items: list[Tender], skip_uids: set[str], now: datetime, within_days: int = 7) -> list[Tender]:
    out = []
    for t in items:
        if t.kind != "tender" or t.uid in skip_uids:
            continue
        d = days_until(t.deadline, now)
        if d is not None and 0 <= d <= within_days:
            out.append(t)
    return sorted(out, key=lambda t: t.deadline)


def _by_priority(items: list[Tender]) -> list[Tender]:
    return sorted(items, key=lambda t: (-t.score, t.deadline or "9999"))


def _line(t: Tender, now: datetime) -> str:
    d = days_until(t.deadline, now)
    left = f" ({d} days left)" if d is not None and t.kind == "tender" else ""
    bits = [t.source, t.buyer or "buyer not listed", f"deadline {t.deadline or 'n/a'}{left}"]
    if t.kind == "award" and (t.winner or t.amount):
        bits.append(f"winner {t.winner or 'n/a'} {t.amount}".strip())
    bits.append("matched: " + ", ".join(t.matched[:5]))
    if t.change:
        bits.append("changed: " + t.change)
    return " | ".join(bits)


def _section_html(title: str, items: list[Tender], now: datetime) -> str:
    if not items:
        return ""
    rows = []
    for t in _by_priority(items)[:MAX_PER_SECTION]:
        link = escape(t.url or "#")
        rows.append(
            f'<li style="margin:0 0 10px 0"><a href="{link}" style="color:#0b3d91;font-weight:600;'
            f'text-decoration:none">{escape(t.title[:220])}</a><br>'
            f'<span style="color:#555;font-size:13px">{escape(_line(t, now))}</span></li>'
        )
    extra = len(items) - MAX_PER_SECTION
    more = f'<p style="color:#777">+{extra} more in the sheet</p>' if extra > 0 else ""
    return (
        f'<h3 style="margin:22px 0 8px 0;color:#0b1f3a">{escape(title)} ({len(items)})</h3>'
        f'<ul style="padding-left:18px;margin:0">{"".join(rows)}</ul>{more}'
    )


def _health_html(results: list[Result]) -> str:
    colors = {"ok": "#1a7f37", "skipped": "#9a6700", "experimental": "#9a6700", "error": "#cf222e"}
    rows = []
    for r in results:
        c = colors.get(r.status, "#555")
        rows.append(
            f'<tr><td style="padding:3px 10px 3px 0">{escape(r.name)}</td>'
            f'<td style="padding:3px 10px 3px 0;color:{c};font-weight:600">{escape(r.status)}</td>'
            f'<td style="padding:3px 10px 3px 0">{r.count}</td>'
            f'<td style="padding:3px 0;color:#555">{escape(r.message)}</td></tr>'
        )
    return (
        '<h3 style="margin:26px 0 8px 0;color:#0b1f3a">Source health</h3>'
        '<table style="font-size:13px;border-collapse:collapse"><tr style="color:#777;text-align:left">'
        "<th>Source</th><th>Status</th><th>Records</th><th>Note</th></tr>" + "".join(rows) + "</table>"
    )


def build_digest(new: list[Tender], changed: list[Tender], soon: list[Tender], awards_new: list[Tender],
                 results: list[Result], today: str, now: datetime, sheet_url: str = "") -> dict:
    problems = sum(1 for r in results if r.status == "error")
    subject = (
        f"TenderWatch {today}: {len(new)} new, {len(changed)} updated, {len(soon)} closing soon"
        + (f", {len(awards_new)} awards" if awards_new else "")
        + (f" ({problems} source issue{'s' if problems != 1 else ''})" if problems else "")
    )
    body = [
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:760px;color:#222">',
        f'<h2 style="margin:0 0 4px 0;color:#0b1f3a">TenderWatch, {escape(today)}</h2>',
        '<p style="margin:0;color:#555">AI, data and digital opportunities matched from Pakistani portals, '
        "the World Bank and other sources.</p>",
    ]
    if not (new or changed or soon or awards_new):
        body.append('<p style="margin-top:18px">No new matching tenders today.</p>')
    body.append(_section_html("New tenders", [t for t in new if t.kind == "tender"], now))
    body.append(_section_html("Updated tenders", changed, now))
    body.append(_section_html("Closing within 7 days", soon, now))
    body.append(_section_html("New awards", awards_new, now))
    if sheet_url:
        body.append(f'<p style="margin-top:20px"><a href="{escape(sheet_url)}">Open the full sheet</a></p>')
    body.append(_health_html(results))
    body.append("</div>")
    html = "".join(body)

    lines = [f"TenderWatch {today}", ""]
    for title, items in (("NEW", [t for t in new if t.kind == "tender"]), ("UPDATED", changed),
                         ("CLOSING WITHIN 7 DAYS", soon), ("NEW AWARDS", awards_new)):
        if items:
            lines.append(f"{title} ({len(items)})")
            for t in _by_priority(items)[:MAX_PER_SECTION]:
                lines.append(f"- {t.title[:200]}\n  {_line(t, now)}\n  {t.url}")
            lines.append("")
    lines.append("SOURCES")
    for r in results:
        lines.append(f"- {r.name}: {r.status} ({r.count}) {r.message}".rstrip())
    return {"subject": subject, "html": html, "text": "\n".join(lines)}
