from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import requests

from ..http import Http, RobotsDisallowed
from ..models import Tender


class ParserError(Exception):
    """The page loaded but nothing could be parsed: the layout probably changed."""


@dataclass
class Result:
    name: str
    status: str  # ok | skipped | error | experimental
    message: str = ""
    tenders: list[Tender] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.tenders)


class Source:
    """Base class. Subclasses implement fetch() and never need to catch their own errors."""

    type_name = ""

    def __init__(self, name: str, cfg: dict, http: Http, now: datetime):
        self.name = name
        self.cfg = cfg
        self.http = http
        self.now = now

    def fetch(self) -> list[Tender]:  # pragma: no cover - interface
        raise NotImplementedError

    def run(self) -> Result:
        experimental = bool(self.cfg.get("experimental"))
        try:
            items = self.fetch()
        except RobotsDisallowed as e:
            return Result(self.name, "skipped", f"robots.txt disallows automated access to {e}")
        except ParserError as e:
            return Result(self.name, "error", f"parser: {e}")
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            return Result(self.name, "error", f"HTTP {code} from {e.request.url if e.request else 'site'}")
        except requests.RequestException as e:
            return Result(self.name, "error", f"network: {type(e).__name__}")
        except Exception as e:  # one broken source must never stop the others
            return Result(self.name, "error", f"{type(e).__name__}: {e}")
        if experimental and not items:
            return Result(self.name, "experimental", "no records parsed yet; run in discover mode and share the snapshot")
        return Result(self.name, "ok", "", items)
