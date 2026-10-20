from __future__ import annotations

import os
import random
import re
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROBOTS_TOKEN = "TenderWatch"
OUTAGE_AFTER_FAILED_HOSTS = 5
DEFAULT_UA = "TenderWatch/0.1 (personal research tool; polite, low volume)"


class RobotsDisallowed(Exception):
    """The site's robots.txt does not allow automated access to this URL."""


class Http:
    """Polite HTTP client: honors robots.txt, rate limits per host, retries, and
    optionally saves raw responses as snapshots (discover mode)."""

    def __init__(self, delay: float = 1.2, discover: bool = False, snapshot_dir: str = "snapshots",
                 snapshot_limit: int = 3, timeout: int = 40):
        self.delay = delay
        self.discover = discover
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_limit = snapshot_limit
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "POST"), respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": os.environ.get("TW_USER_AGENT", DEFAULT_UA),
                                     "Accept-Language": "en"})
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._robots_err: dict[str, requests.RequestException] = {}
        self._origins_ok = 0
        self._last_hit: dict[str, float] = {}
        self._snaps: dict[str, int] = {}

    # robots.txt -------------------------------------------------------------
    def _robots_for(self, url: str) -> robotparser.RobotFileParser | None:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        if origin in self._robots_err:
            raise self._robots_err[origin]  # already failed this run: fail fast, do not retry per source
        if self._origins_ok == 0 and len(self._robots_err) >= OUTAGE_AFTER_FAILED_HOSTS:
            # several different hosts failed and none ever answered: the network itself is down
            err = requests.ConnectionError("network outage: no host reachable")
            self._robots_err[origin] = err
            raise err
        rp: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
        # A network failure here propagates so it is reported as a network problem,
        # not mistaken for a robots.txt refusal.
        try:
            r = self.session.get(origin + "/robots.txt", timeout=20)
        except requests.RequestException as e:
            self._robots_err[origin] = e
            raise
        self._origins_ok += 1
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        elif 400 <= r.status_code < 500:
            rp.parse([])  # no robots.txt: everything allowed
        else:
            rp = None  # server error: be conservative and treat as disallowed
        self._robots[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return bool(rp and rp.can_fetch(ROBOTS_TOKEN, url))

    # requests ---------------------------------------------------------------
    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        gap = self.delay + random.uniform(0, 0.6)
        since = time.monotonic() - self._last_hit.get(host, 0.0)
        if since < gap:
            time.sleep(gap - since)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, source: str = "", tag: str = "", **kw) -> requests.Response:
        return self._request("GET", url, source, tag, **kw)

    def post(self, url: str, source: str = "", tag: str = "", **kw) -> requests.Response:
        return self._request("POST", url, source, tag, **kw)

    def _request(self, method: str, url: str, source: str, tag: str, **kw) -> requests.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        self._wait(url)
        kw.setdefault("timeout", self.timeout)
        resp = self.session.request(method, url, **kw)
        self._snapshot(resp, source, tag)
        resp.raise_for_status()
        return resp

    def _snapshot(self, resp: requests.Response, source: str, tag: str) -> None:
        if not self.discover:
            return
        n = self._snaps.get(source, 0)
        if n >= self.snapshot_limit:
            return
        self._snaps[source] = n + 1
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag or urlparse(resp.url).path or "page").strip("_") or "page"
        folder = self.snapshot_dir / (source or "misc")
        folder.mkdir(parents=True, exist_ok=True)
        body = resp.text[:800_000]
        (folder / f"{slug}.txt").write_text(
            f"URL: {resp.url}\nHTTP: {resp.status_code}\nContent-Type: {resp.headers.get('content-type', '')}\n\n{body}",
            "utf-8",
        )
