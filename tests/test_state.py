from tenderwatch.models import Tender
from tenderwatch.state import State


def mk(deadline="2026-11-01", status="Published", title="Data platform"):
    return Tender(source="epms", source_id="TS1", title=title, deadline=deadline, status=status)


def test_new_then_unchanged_then_changed(tmp_path):
    s = State()
    d1 = s.diff([mk()], "2026-10-20")
    assert len(d1.new) == 1 and not d1.changed

    d2 = s.diff([mk()], "2026-10-21")
    assert len(d2.unchanged) == 1 and not d2.new
    assert d2.unchanged[0].first_seen == "2026-10-20"

    d3 = s.diff([mk(deadline="2026-11-15")], "2026-10-22")
    assert len(d3.changed) == 1
    assert "deadline 2026-11-01 to 2026-11-15" in d3.changed[0].change


def test_roundtrip_and_prune(tmp_path):
    s = State()
    s.diff([mk()], "2026-01-01")
    p = tmp_path / "state.json"
    s.save(p)
    s2 = State.load(p)
    assert "epms:TS1" in s2.seen
    s2.diff([], "2026-10-20")  # more than 200 days later: pruned
    assert "epms:TS1" not in s2.seen


def test_missing_or_corrupt_state_file(tmp_path):
    assert State.load(tmp_path / "nope.json").seen == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert State.load(bad).seen == {}
