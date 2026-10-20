from datetime import datetime
from pathlib import Path

import yaml

from tenderwatch.dates import PKT
from tenderwatch.digest import build_digest
from tenderwatch.http import Http, RobotsDisallowed
from tenderwatch.models import Tender
from tenderwatch.publish import COLUMNS, build_payload, to_row
from tenderwatch.run import is_current, run_pipeline
from tenderwatch.sources.base import ParserError, Result, Source
from tenderwatch.state import State

NOW = datetime(2026, 10, 20, 13, 0, tzinfo=PKT)
TODAY = "2026-10-20"
CFG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text())


def tender(i, title, deadline="2026-10-24", kind="tender", source="epms"):
    return Tender(source=source, source_id=str(i), title=title, deadline=deadline, kind=kind,
                  published="2026-10-15", url=f"https://x/{i}")


def results():
    return [
        Result("epms", "ok", "", [
            tender(1, "Machine learning platform for revenue analytics"),
            tender(2, "Supply of furniture"),                                   # irrelevant
            tender(3, "Data warehouse and dashboards", deadline="2026-10-01"),  # already closed
        ]),
        Result("worldbank", "ok", "", [
            tender(4, "ERP software implementation", source="worldbank", deadline="2026-10-30"),
            tender(5, "Contract award: AI chatbot", kind="award", deadline="", source="worldbank"),
        ]),
        Result("kppra", "skipped", "robots.txt disallows automated access"),
    ]


def test_pipeline_filters_scores_and_diffs():
    state = State()
    relevant, diff, soon, tenders, awards, awards_new = run_pipeline(CFG, results(), state, NOW, TODAY)
    ids = {t.source_id for t in relevant}
    assert ids == {"1", "4", "5"}          # furniture and the closed tender are gone
    assert len(diff.new) == 3 and len(awards) == 1 and len(awards_new) == 1
    assert [t.source_id for t in soon] == []  # new items are not repeated under "closing soon"

    # second day: nothing new, tender 1 now falls in the closing-soon window
    relevant, diff, soon, *_ = run_pipeline(CFG, results(), state, NOW, "2026-10-21")
    assert not diff.new and [t.source_id for t in soon] == ["1"]


def test_digest_content():
    state = State()
    relevant, diff, soon, tenders, awards, awards_new = run_pipeline(CFG, results(), state, NOW, TODAY)
    d = build_digest([t for t in diff.new if t.kind == "tender"], diff.changed, soon, awards_new,
                     results(), TODAY, NOW)
    assert "2 new" in d["subject"] and "awards" in d["subject"]
    assert "Machine learning platform" in d["html"] and "kppra" in d["html"]
    assert "—" not in d["html"] and "—" not in d["text"]
    assert "skipped" in d["text"]


def test_empty_day_digest():
    d = build_digest([], [], [], [], [Result("epms", "ok")], TODAY, NOW)
    assert "No new matching tenders" in d["html"]


def test_payload_shape_matches_columns():
    t = tender(1, "AI platform")
    t.first_seen = TODAY
    row = to_row(t, TODAY)
    assert len(row) == len(COLUMNS) and row[COLUMNS.index("Status")] == "New"
    p = build_payload("tok", TODAY, [t], [], results(), {"subject": "s", "html": "h", "text": "t"}, {"new": 1})
    assert p["columns"] == COLUMNS and p["tenders"][0] == row
    assert {s["name"] for s in p["sources"]} == {"epms", "worldbank", "kppra"}


def test_is_current_rules():
    assert is_current(tender(1, "x", deadline="2026-10-20"), NOW, 30)      # closes today
    assert not is_current(tender(1, "x", deadline="2026-10-19"), NOW, 30)  # closed yesterday
    undated = Tender(source="s", source_id="1", title="x", published="2026-10-10")
    assert is_current(undated, NOW, 30)
    old = Tender(source="s", source_id="1", title="x", published="2026-08-01")
    assert not is_current(old, NOW, 30)


class Boom(Source):
    def __init__(self, exc):
        super().__init__("boom", {}, None, NOW)
        self.exc = exc

    def fetch(self):
        raise self.exc


def test_source_failures_are_contained():
    assert Boom(RobotsDisallowed("https://x")).run().status == "skipped"
    assert Boom(ParserError("0 rows")).run().status == "error"
    assert Boom(ValueError("bad")).run().status == "error"


class FakeResp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def robots_http(status, text=""):
    h = Http()
    h.session.get = lambda *a, **k: FakeResp(status, text)
    return h


def test_robots_rules():
    h = robots_http(200, "User-agent: *\nDisallow: /private\n")
    assert h.allowed("https://a.example/public/page") and not h.allowed("https://a.example/private/x")
    assert robots_http(404).allowed("https://b.example/anything")      # no robots.txt: allowed
    assert not robots_http(503).allowed("https://c.example/anything")  # server error: conservative
    assert not robots_http(200, "User-agent: *\nDisallow: /\n").allowed("https://d.example/x")
