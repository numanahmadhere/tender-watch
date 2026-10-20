from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import find_dates, parse_date
from ..models import Tender, stable_id
from .base import ParserError, Source

# header text (regex) -> field. First match wins, so order matters.
HEADER_MAP = [
    ("winner", r"contractor|winner|awarded to|successful|supplier"),
    ("amount", r"amount|contract value|price|cost"),
    ("id", r"tender (no|number)|\bref|reference|ad no|contract (no|number)|\bid\b"),
    ("title", r"title|details|description|subject|name of work|particulars|tender name|work"),
    ("buyer", r"organi[sz]ation|department|procuring|authority|agency|entity|office"),
    ("deadline", r"clos|deadline|due|last date|submission|opening"),
    ("published", r"advertis|publish|posted|issue|date"),
    ("category", r"category|type|sector|nature"),
]


AWARD_ID_RE = re.compile(r"\b(EVL\d+|PCN-\d+)\b")
AWARD_NOISE = [
    re.compile(r"\b(EVL\d+|PCN-\d+|TS\d+E)\b"),
    re.compile(r"Tender Ref#:?\s*\S+"),
    re.compile(r"\bPPRA Contract No\b|\bRef:\s*\S+"),
    re.compile(r"\d+\s+Bids?\b.*$", re.I),
    re.compile(r"\bLowest:.*$", re.I),
    re.compile(r"\bNational Tender:.*$", re.I),
]


def clean_text(s: str) -> str:
    """Unescape HTML entities (twice: some portals double-escape) and drop zero-width characters."""
    s = htmllib.unescape(htmllib.unescape(s or ""))
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s).strip()


def clean_award_title(s: str) -> str:
    """Awards pages are not header-labelled: strip ids, bid counts and winner text from the work title."""
    for rx in AWARD_NOISE:
        s = rx.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip(" -:,")


def _classify(header: str) -> str | None:
    h = header.lower()
    for field, pattern in HEADER_MAP:
        if re.search(pattern, h):
            return field
    return None


def parse_table(html: str, base_url: str, source: str, kind: str = "tender") -> list[Tender]:
    """Parse the largest table on the page, mapping columns by header text."""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return []
    table = max(tables, key=lambda t: len(t.find_all("tr")))
    rows = table.find_all("tr")
    headers: list[str] = []
    start = 0
    for i, tr in enumerate(rows[:3]):
        ths = tr.find_all("th")
        if ths:
            headers = [th.get_text(" ", strip=True) for th in ths]
            start = i + 1
            break
    if not headers and rows:
        first = [c.get_text(" ", strip=True) for c in rows[0].find_all(["td"])]
        if first and all(len(x) < 40 for x in first):
            headers, start = first, 1
    mapping = [_classify(h) for h in headers]
    out: list[Tender] = []
    for tr in rows[start:]:
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        vals = [clean_text(c.get_text(" ", strip=True)) for c in cells]
        rec: dict[str, str] = {}
        for i, v in enumerate(vals):
            field = mapping[i] if i < len(mapping) else None
            if field and field not in rec and v:
                rec[field] = v
        title = rec.get("title") or max(vals, key=len)
        award_id = ""
        if kind == "award":
            m = AWARD_ID_RE.search(" ".join(vals))
            award_id = m.group(1) if m else ""
            title = clean_award_title(title)
        if len(title) < 8:
            continue
        a = tr.find("a", href=True)
        link = urljoin(base_url, a["href"]) if a else base_url
        row_text = " ".join(vals)
        dates = find_dates(row_text)
        published = parse_date(rec.get("published", "")) or (dates[0][:10] if dates else "")
        deadline = parse_date(rec.get("deadline", "")) or (dates[-1] if len(dates) > 1 else "")
        sid = award_id or rec.get("id") or stable_id(title, published or deadline)
        if kind == "award" and not award_id and len(sid) > 40:
            sid = stable_id(title, published or deadline)
        out.append(
            Tender(
                source=source,
                source_id=sid[:60],
                title=title,
                kind=kind,
                buyer=rec.get("buyer", ""),
                category=rec.get("category", ""),
                published=published,
                deadline=deadline,
                url=link,
                description="" if kind == "award" else (row_text if row_text != title else ""),  # awards: score the work title only, winner text is noise
                winner=rec.get("winner", ""),
                amount=rec.get("amount", ""),
            )
        )
    return out


def harvest_links(html: str, base_url: str, source: str, must_contain: str = "") -> list[Tender]:
    """Fallback for pages without a table: long link texts are treated as tender titles."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Tender] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if len(text) < 30 or text in seen:
            continue
        if must_contain and must_contain.lower() not in text.lower():
            continue
        seen.add(text)
        href = urljoin(base_url, a["href"])
        out.append(Tender(source=source, source_id=stable_id(text, href), title=text, url=href))
    return out


class GenericTableSource(Source):
    """Header-mapped table scraper for portals without a dedicated adapter.

    Config: urls (list), kind (tender|award), max_pages (follows ?page=N; page_base 0 when page 2 is ?page=1), contains
    (keep only rows whose text contains this, e.g. 'Pakistan'), harvest_links (fallback).
    """

    type_name = "generic_table"

    def fetch(self) -> list[Tender]:
        urls = self.cfg.get("urls") or [self.cfg["url"]]
        kind = self.cfg.get("kind", "tender")
        max_pages = int(self.cfg.get("max_pages", 1))
        contains = (self.cfg.get("contains") or "").lower()
        items: list[Tender] = []
        for url in urls:
            known: set[str] = set()
            for p in range(1, max_pages + 1):
                params = {"page": p - 1 + int(self.cfg.get("page_base", 1))} if p > 1 else None
                r = self.http.get(url, params=params, source=self.name, tag=f"{url.rsplit('/', 1)[-1]}_p{p}")
                batch = parse_table(r.text, url, self.name, kind)
                if not batch and self.cfg.get("harvest_links", True):
                    batch = harvest_links(r.text, url, self.name, self.cfg.get("link_must_contain", ""))
                batch = [t for t in batch if t.uid not in known]
                if contains:
                    batch = [t for t in batch if contains in (t.title + " " + t.description + " " + t.buyer).lower()]
                if not batch:
                    break
                known.update(t.uid for t in batch)
                items.extend(batch)
        if not items and not self.cfg.get("experimental"):
            raise ParserError("no table rows or links could be parsed; run in discover mode to capture the page")
        return items
