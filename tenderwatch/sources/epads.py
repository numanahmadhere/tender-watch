from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..dates import find_dates, parse_relative
from ..models import Tender
from .base import ParserError, Source

BASE = "https://epads.gov.pk"
DETAIL_RE = re.compile(r"/opportunities/(\w+)/(procurements|frameworks|disposals)/([A-Za-z0-9\-]+)")
CATEGORIES = ("Non-Consultancy Services", "Consultancy Services", "Goods", "Works")  # order matters
REF_RE = re.compile(r"\bP\d{5,7}\b")
NOISE = ("Grievance Raised", "View")


def page_count(html: str) -> int:
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", html)
    return int(m.group(1)) if m else 1


def parse_listing(html: str, source: str, now: datetime) -> list[Tender]:
    """Parse the EPADS 2.0 open-opportunities table.

    Columns (as observed): Procurement Title (link, procuring entity, project reference),
    Procurement Status (Published On, Closing On or a countdown like '1h 49m Left'),
    Type/Procedure, Details (a View link to /opportunities/<jurisdiction>/procurements/<id>).
    """
    soup = BeautifulSoup(html, "lxml")
    groups: dict[str, list] = {}
    for a in soup.find_all("a", href=DETAIL_RE):
        pid = DETAIL_RE.search(a["href"]).group(3)
        groups.setdefault(pid, []).append(a)

    out: list[Tender] = []
    for pid, anchors in groups.items():
        link = max(anchors, key=lambda x: len(x.get_text(" ", strip=True)))
        title = link.get_text(" ", strip=True)
        row = link.find_parent("tr") or link.find_parent("li") or link.find_parent("div")
        row_text = row.get_text(" ", strip=True) if row is not None else title
        cell = link.find_parent("td")
        cell_text = cell.get_text(" ", strip=True) if cell is not None else ""

        buyer = cell_text.replace(title, " ", 1) if cell_text else ""
        buyer = REF_RE.sub(" ", buyer)
        for n in NOISE:
            buyer = buyer.replace(n, " ")
        buyer = re.sub(r"\s+", " ", buyer).strip(" -|,")

        dates = find_dates(row_text)
        published = dates[0][:10] if dates else ""
        deadline = ""
        if len(dates) > 1:
            deadline = dates[1]
        else:
            deadline = parse_relative(row_text, now)

        category = next((c for c in CATEGORIES if c.lower() in row_text.lower()), "")
        m = DETAIL_RE.search(link["href"])
        href = link["href"] if link["href"].startswith("http") else BASE + link["href"]
        out.append(
            Tender(
                source=source,
                source_id=f"{m.group(1)}-{pid}",
                title=title,
                buyer=buyer,
                category=category,
                notice_type=m.group(2).rstrip("s").capitalize(),
                published=published,
                deadline=deadline,
                url=href,
                status="Grievance raised" if "Grievance Raised" in row_text else "Published",
                description=title,
            )
        )
    return out


class EpadsSource(Source):
    """EPADS 2.0 public open opportunities, one jurisdiction per source (federal, kp)."""

    type_name = "epads"

    def fetch(self) -> list[Tender]:
        jurisdiction = self.cfg.get("jurisdiction", "federal")
        base_params = {"jurisdiction": jurisdiction}
        first = self.http.get(BASE + "/", params=base_params, source=self.name, tag="page1")
        items = parse_listing(first.text, self.name, self.now)
        if not items:
            if len(first.text) > 5000:
                raise ParserError("0 opportunities parsed from page 1; the table layout may have changed")
            return []
        known = {t.source_id for t in items}
        pages = min(page_count(first.text), int(self.cfg.get("max_pages", 30)))
        for p in range(2, pages + 1):
            r = self.http.get(BASE + "/", params={**base_params, "page": p}, source=self.name, tag=f"page{p}")
            batch = [t for t in parse_listing(r.text, self.name, self.now) if t.source_id not in known]
            if not batch:
                break
            known.update(t.source_id for t in batch)
            items.extend(batch)
        return items
