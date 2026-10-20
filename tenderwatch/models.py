from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class Tender:
    """One normalized procurement record (a tender notice or an award)."""

    source: str
    source_id: str
    title: str
    kind: str = "tender"  # "tender" or "award"
    buyer: str = ""
    category: str = ""
    notice_type: str = ""
    published: str = ""  # YYYY-MM-DD
    deadline: str = ""  # YYYY-MM-DD or YYYY-MM-DDTHH:MM (Pakistan time)
    url: str = ""
    status: str = ""
    description: str = ""
    contact: str = ""
    winner: str = ""
    amount: str = ""

    # filled in by the pipeline
    score: int = 0
    matched: list[str] = field(default_factory=list)
    first_seen: str = ""
    change: str = ""  # human readable note when a known tender changed

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    def fingerprint(self) -> str:
        """Hash of the fields whose change we want to be told about."""
        raw = "|".join([self.title, self.deadline, self.status, self.notice_type, self.winner, self.amount])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def stable_id(*parts: str) -> str:
    """Deterministic short id for portals that do not expose a tender number."""
    raw = "|".join(p.strip().lower() for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
