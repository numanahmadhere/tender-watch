from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..dates import parse_date
from ..models import Tender
from .base import ParserError, Source


def parse_cards(html: str, source: str, base: str = "https://www.gbppra.gov.pk/viewall") -> list[Tender]:
    """GB-PPRA lists procurements as cards (div.job-post-item), not as a table."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Tender] = []
    for card in soup.select("div.job-post-item"):
        heads = [h.get_text(" ", strip=True) for h in card.select("h2")]
        if len(heads) < 2:
            continue
        ref = re.sub(r"[\[\]\s]", "", heads[0])
        title = heads[1]
        badge = card.select_one(".badge")
        buyer_a = card.select_one(".fa-university")
        buyer = buyer_a.parent.get_text(" ", strip=True) if buyer_a else ""
        pub = card.select_one(".text-success")
        dead = card.select_one(".text-danger")
        link = card.select_one("a.btn")
        out.append(Tender(
            source=source, source_id=ref or title[:60], title=title, kind="tender",
            buyer=buyer, notice_type=badge.get_text(" ", strip=True) if badge else "",
            published=parse_date(pub.get_text(" ", strip=True)) if pub else "",
            deadline=parse_date(dead.get_text(" ", strip=True)) if dead else "",
            url=link["href"] if link and link.get("href") else base,
        ))
    return out


class GbPpraSource(Source):
    """Gilgit-Baltistan PPRA 'view all' listing (10 cards per page, newest first, ?page=N)."""

    type_name = "gb_ppra"

    def fetch(self) -> list[Tender]:
        url = self.cfg.get("url", "https://www.gbppra.gov.pk/viewall")
        items: list[Tender] = []
        known: set[str] = set()
        for p in range(1, int(self.cfg.get("max_pages", 6)) + 1):
            params = {"page": p} if p > 1 else None
            r = self.http.get(url, params=params, source=self.name, tag=f"p{p}")
            batch = [t for t in parse_cards(r.text, self.name, url) if t.uid not in known]
            if not batch:
                if p == 1:
                    raise ParserError("no procurement cards found; run discover and share the snapshot")
                break
            known.update(t.uid for t in batch)
            items.extend(batch)
        return items
