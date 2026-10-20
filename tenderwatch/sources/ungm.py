from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..dates import find_dates
from ..models import Tender
from .base import Source

SEARCH = "https://www.ungm.org/Public/Notice/Search"
DETAIL = "https://www.ungm.org/Public/Notice/{id}"
NOTICE_RE = re.compile(r"/Public/Notice/(\d+)")


def parse_results(html: str, source: str, must_contain: str = "pakistan") -> list[Tender]:
    """Best effort parse of the UNGM result fragment. Keeps rows that mention Pakistan."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Tender] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=NOTICE_RE):
        nid = NOTICE_RE.search(a["href"]).group(1)
        if nid in seen:
            continue
        seen.add(nid)
        row = a.find_parent(attrs={"data-noticeid": True}) or a.find_parent("div", class_=re.compile("resultRow|tableRow", re.I)) or a.find_parent("tr") or a.parent
        text = row.get_text(" ", strip=True) if row is not None else a.get_text(" ", strip=True)
        if must_contain and must_contain not in text.lower():
            continue
        dates = find_dates(text)
        title = a.get_text(" ", strip=True) or text[:160]
        out.append(
            Tender(
                source=source,
                source_id=nid,
                title=title,
                published=dates[1][:10] if len(dates) > 1 else "",
                deadline=dates[0] if dates else "",
                url=DETAIL.format(id=nid),
                description=text[:600],
            )
        )
    return out


class UngmSource(Source):
    """UN Global Marketplace notices (experimental).

    UNGM renders its search with JavaScript and has no public API that I could verify.
    This adapter posts the search form payload the page itself appears to use. If the
    response shape differs, it parses nothing and reports 'experimental' with a snapshot
    (run in discover mode) so the parser can be corrected from the real response.
    """

    type_name = "ungm"

    def fetch(self) -> list[Tender]:
        max_pages = int(self.cfg.get("max_pages", 20))
        page_size = int(self.cfg.get("page_size", 100))
        items: list[Tender] = []
        known: set[str] = set()
        for page in range(max_pages):
            payload = {
                "PageIndex": page,
                "PageSize": page_size,
                "Title": "",
                "Description": "",
                "Reference": "",
                "PublishedFrom": "",
                "PublishedTo": "",
                "DeadlineFrom": "",
                "DeadlineTo": "",
                "Countries": [],
                "Agencies": [],
                "UNSPSCs": [],
                "NoticeTypes": [],
                "SortField": "DatePublished",
                "SortAscending": False,
                "isPicker": False,
                "IsSustainable": False,
                "IsActive": True,
                "NoticeDisplayType": None,
                "NoticeSearchTotalLabelId": "noticeSearchTotal",
                "TypeOfCompetitions": [],
            }
            r = self.http.post(SEARCH, json=payload, source=self.name, tag=f"search{page}")
            batch = [t for t in parse_results(r.text, self.name) if t.source_id not in known]
            if not batch and page > 0:
                break
            known.update(t.source_id for t in batch)
            items.extend(batch)
            if not NOTICE_RE.search(r.text):
                break
        return items
