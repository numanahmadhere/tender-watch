from __future__ import annotations

import re

from .models import Tender


def _compile(term: str) -> tuple[str, re.Pattern]:
    # Short all-caps acronyms (AI, ERP, MIS, GIS) must match case-sensitively,
    # otherwise "ai" or "mis" would match inside ordinary words.
    letters = term.replace("/", "").replace("-", "")
    case_sensitive = letters.isalpha() and letters.isupper() and len(letters) <= 5
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = r"(?<![A-Za-z0-9&])" + re.escape(term) + r"(?:s|es)?(?![A-Za-z0-9&])"  # "&" glues words: H&AI is not AI
    return term, re.compile(pattern, flags)


class Scorer:
    """Keyword scorer.

    Each group has a weight. Every distinct term that matches adds the weight,
    but at most `max_hits` terms per group count, so repeating synonyms does
    not inflate the score. Exclusion phrases drop a tender unless its score
    reaches the strong threshold.
    """

    def __init__(self, cfg: dict):
        self.groups = []
        for name, g in cfg["groups"].items():
            self.groups.append(
                (name, int(g.get("weight", 1)), int(g.get("max_hits", 2)), [_compile(t) for t in g["terms"]])
            )
        self.exclude = [_compile(t) for t in cfg.get("exclude", [])]
        self.min_score = int(cfg.get("min_score", 3))
        self.strong_score = int(cfg.get("strong_score", 6))

    def score_text(self, text: str) -> tuple[int, list[str]]:
        total = 0
        matched: list[str] = []
        for name, weight, max_hits, terms in self.groups:
            hits = [t for t, rx in terms if rx.search(text)]
            for t in hits[:max_hits]:
                total += weight
            matched.extend(hits[:max_hits])
        return total, matched

    def excluded(self, text: str) -> list[str]:
        return [t for t, rx in self.exclude if rx.search(text)]

    def evaluate(self, t: Tender) -> bool:
        """Score a tender in place. Returns True if it is relevant."""
        text = " ".join([t.title, t.description, t.category])
        t.score, t.matched = self.score_text(text)
        if t.score < self.min_score:
            return False
        if self.excluded(text) and t.score < self.strong_score:
            return False
        return True
