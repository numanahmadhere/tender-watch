from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import Tender

RETENTION_DAYS = 200


@dataclass
class Diff:
    new: list[Tender] = field(default_factory=list)
    changed: list[Tender] = field(default_factory=list)
    unchanged: list[Tender] = field(default_factory=list)


class State:
    """Remembers which relevant tenders were already reported, in data/state.json."""

    def __init__(self, seen: dict | None = None):
        self.seen: dict[str, dict] = seen or {}

    @classmethod
    def load(cls, path: str | Path) -> "State":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            return cls(json.loads(p.read_text("utf-8")).get("seen", {}))
        except (json.JSONDecodeError, OSError):
            return cls()

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"seen": self.seen}, indent=1, sort_keys=True), "utf-8")

    def diff(self, items: list[Tender], today: str) -> Diff:
        """Classify items as new / changed / unchanged and update the memory."""
        d = Diff()
        for t in items:
            fp = t.fingerprint()
            rec = self.seen.get(t.uid)
            if rec is None:
                t.first_seen = today
                d.new.append(t)
                self.seen[t.uid] = {
                    "first": today,
                    "last": today,
                    "fp": fp,
                    "deadline": t.deadline,
                    "status": t.status,
                    "title": t.title,
                }
                continue
            t.first_seen = rec.get("first", today)
            if rec.get("fp") != fp:
                t.change = _describe_change(rec, t)
                d.changed.append(t)
            else:
                d.unchanged.append(t)
            rec.update(
                {"last": today, "fp": fp, "deadline": t.deadline, "status": t.status, "title": t.title}
            )
        self._prune(today)
        return d

    def _prune(self, today: str) -> None:
        from datetime import date

        try:
            now = date.fromisoformat(today)
        except ValueError:
            return
        stale = []
        for uid, rec in self.seen.items():
            try:
                age = (now - date.fromisoformat(rec.get("last", today))).days
            except ValueError:
                continue
            if age > RETENTION_DAYS:
                stale.append(uid)
        for uid in stale:
            del self.seen[uid]


def _describe_change(rec: dict, t: Tender) -> str:
    notes = []
    if rec.get("deadline") != t.deadline:
        notes.append(f"deadline {rec.get('deadline') or 'none'} to {t.deadline or 'none'}")
    if rec.get("status") != t.status:
        notes.append(f"status {rec.get('status') or 'none'} to {t.status or 'none'}")
    if rec.get("title") != t.title:
        notes.append("title edited")
    return "; ".join(notes) or "details changed"
