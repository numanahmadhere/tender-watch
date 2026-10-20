from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..dates import find_dates
from ..models import Tender
from .base import ParserError, Source

BASE = "https://epms.ppra.gov.pk"
DETAIL_RE = re.compile(r"/public/tenders/tender-details/([A-Za-z0-9]+)")
LABELS = ["Organization", "Tender Type", "Procurement Category", "Sector", "Tender Nature", "Advertised"]
_LABEL_RE = re.compile("(" + "|".join(re.escape(x) for x in LABELS) + r")\s*:?\s*")


def page_count(html: str) -> int:
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", html)
    return int(m.group(1)) if m else 1


def labelled(text: str) -> dict[str, str]:
    """Split 'Organization X Sector Y ...' into {'Organization': 'X', 'Sector': 'Y'}."""
    parts = _LABEL_RE.split(text or "")
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def parse_listing(html: str) -> list[Tender]:
    """Parse one page of the EPMS active-tenders table.

    Each tender spans two rows: the main row (number, details, status, dates, links)
    and a merged sub-row with organization, category and sector.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[Tender] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=DETAIL_RE):
        tid = DETAIL_RE.search(a["href"]).group(1)
        if tid in seen:
            continue
        seen.add(tid)
        tr = a.find_parent("tr")
        if tr is None:
            continue
        cells = tr.find_all("td")
        texts = [c.get_text(" ", strip=True) for c in cells]
        row_text = " ".join(texts)

        # the "Tender Details" cell: found by header when possible, else the longest cell
        details_cell = None
        table = tr.find_parent("table")
        if table is not None:
            heads = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
            if "tender details" in heads and len(heads) == len(cells):
                details_cell = cells[heads.index("tender details")]
        if details_cell is None and cells:
            details_cell = max(cells, key=lambda c: len(c.get_text(" ", strip=True)))
        bold = details_cell.find(["b", "strong"]) if details_cell is not None else None
        details_text = details_cell.get_text(" ", strip=True) if details_cell is not None else row_text
        title = bold.get_text(" ", strip=True) if bold else details_text[:200]

        sub = tr.find_next_sibling("tr")
        sub_text = ""
        if sub is not None and not sub.find("a", href=DETAIL_RE):
            sub_text = sub.get_text(" ", strip=True)
        fields = labelled(sub_text)

        dates = find_dates(row_text)
        status = ""
        m = re.search(r"Published Corrigendum|Published|Cancelled", row_text)
        if m:
            status = m.group(0)

        out.append(
            Tender(
                source="epms",
                source_id=tid,
                title=title,
                buyer=fields.get("Organization", ""),
                category=" / ".join(x for x in [fields.get("Procurement Category", ""), fields.get("Sector", "")] if x),
                notice_type=fields.get("Tender Type", ""),
                published=dates[0][:10] if dates else "",
                deadline=dates[-1] if len(dates) > 1 else "",
                url=f"{BASE}/public/tenders/tender-details/{tid}",
                status=status,
                description=details_text,
            )
        )
    return out


class EpmsTendersSource(Source):
    """Federal PPRA EPMS active tenders (also lists tenders closed in the last 10 days)."""

    type_name = "epms_tenders"

    def fetch(self) -> list[Tender]:
        url = self.cfg.get("url", f"{BASE}/public/tenders/active-tenders")
        first = self.http.get(url, source=self.name, tag="page1")
        items = parse_listing(first.text)
        if not items:
            if len(first.text) > 5000:
                raise ParserError("0 tenders parsed from page 1; the table layout may have changed")
            return []
        pages = min(page_count(first.text), int(self.cfg.get("max_pages", 60)))
        known = {t.source_id for t in items}
        for p in range(2, pages + 1):
            r = self.http.get(url, params={"page": p}, source=self.name, tag=f"page{p}")
            batch = [t for t in parse_listing(r.text) if t.source_id not in known]
            if not batch:
                break
            known.update(t.source_id for t in batch)
            items.extend(batch)
        return items
