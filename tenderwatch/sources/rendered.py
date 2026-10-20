from __future__ import annotations

import os
from urllib.parse import urlparse

from ..models import Tender
from .base import ParserError, Source
from .generic import harvest_links, parse_table


def render(url: str, timeout_ms: int = 45_000, wait_selector: str = "") -> str:
    """Load a page in headless Chromium and return the HTML after JavaScript has run."""
    from playwright.sync_api import sync_playwright  # imported lazily: only needed by rendered sources

    exe = os.environ.get("TW_CHROMIUM") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        try:
            page = browser.new_page(user_agent=os.environ.get("TW_USER_AGENT") or None)
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:  # some sites never go idle; what has rendered so far is still useful
                    pass
            return page.content()
        finally:
            browser.close()


class RenderedTableSource(Source):
    """For portals whose list is built by JavaScript (SBP, ADB, AIIB). Same parsing as generic_table.

    The site's robots.txt is still honored, and the page is fetched once per url (no crawling).
    Config: urls, kind, contains, wait_selector.
    """

    type_name = "rendered_table"

    def fetch(self) -> list[Tender]:
        urls = self.cfg.get("urls") or [self.cfg["url"]]
        contains = (self.cfg.get("contains") or "").lower()
        items: list[Tender] = []
        for url in urls:
            if not self.http.allowed(url):
                from ..http import RobotsDisallowed
                raise RobotsDisallowed(url)
            self.http._wait(url)
            html = render(url, wait_selector=self.cfg.get("wait_selector", ""))
            if self.http.discover:
                self._snapshot(url, html)
            batch = parse_table(html, url, self.name, self.cfg.get("kind", "tender"))
            if not batch:
                batch = harvest_links(html, url, self.name, self.cfg.get("link_must_contain", ""))
            if contains:
                batch = [t for t in batch if contains in (t.title + " " + t.description + " " + t.buyer).lower()]
            items.extend(batch)
        if not items and not self.cfg.get("experimental"):
            raise ParserError("rendered page produced no rows")
        return items

    def _snapshot(self, url: str, html: str) -> None:
        folder = self.http.snapshot_dir / self.name
        folder.mkdir(parents=True, exist_ok=True)
        slug = (urlparse(url).path.strip("/").replace("/", "_") or "page")[:60]
        (folder / f"{slug}.txt").write_text(f"URL: {url}\nRENDERED\n\n{html[:800_000]}", "utf-8")
