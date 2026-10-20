from __future__ import annotations

import re
from datetime import datetime

import feedparser
from bs4 import BeautifulSoup

from ..models import Tender
from .base import ParserError, Source

# A news item is only an opportunity signal when it talks about buying or funding something.
DEFAULT_MUST_MATCH = (r"tender|\bRFPs?\b|request for proposal|expression of interest|\bEOIs?\b|"
                      r"invit\w* (?:for )?bids?|bids? invit\w*|procurement|procures?\b|ECNEC|PSDP|"
                      r"contract (?:award|signed)|awarded|call for|funding|grant\b")


def parse_feed(content: bytes | str, source: str, must_match: str = DEFAULT_MUST_MATCH) -> list[Tender]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ParserError("not a readable RSS/Atom feed")
    rx = re.compile(must_match, re.I)
    out: list[Tender] = []
    for e in parsed.entries:
        title = (e.get("title") or "").strip()
        link = e.get("link") or ""
        if not title or not link:
            continue
        summary = BeautifulSoup(e.get("summary", ""), "lxml").get_text(" ", strip=True)[:500]
        if not rx.search(title + " " + summary):
            continue
        pub = e.get("published_parsed") or e.get("updated_parsed")
        out.append(Tender(
            source=source, source_id=link, title=title, kind="tender",
            buyer=(parsed.feed.get("title") or "").strip(), notice_type="News signal (not a tender notice)",
            published=datetime(*pub[:3]).strftime("%Y-%m-%d") if pub else "",
            url=link, description=summary,
        ))
    return out


class FeedSource(Source):
    """RSS/Atom news feeds as early signals: ECNEC approvals, funded programmes, RFP announcements."""

    type_name = "feed"

    def fetch(self) -> list[Tender]:
        urls = self.cfg.get("urls") or [self.cfg["url"]]
        must = self.cfg.get("must_match") or DEFAULT_MUST_MATCH
        items: list[Tender] = []
        seen: set[str] = set()
        errors: list[Exception] = []
        for url in urls:
            try:
                r = self.http.get(url, source=self.name, tag=re.sub(r"\W+", "_", url.split("//")[-1])[:40])
                batch = parse_feed(r.content, self.name, must)
            except Exception as e:  # one dead feed must not hide the others
                errors.append(e)
                continue
            for t in batch:
                if t.uid not in seen:
                    seen.add(t.uid)
                    items.append(t)
        if errors and len(errors) == len(urls):
            raise errors[0]
        return items
