"""End-to-end tests of main(): fake sources, a fake webhook, real state file handling."""
import json
from datetime import datetime

import pytest
import requests
import yaml

from tenderwatch import run as run_mod
from tenderwatch.dates import PKT
from tenderwatch.models import Tender
from tenderwatch.sources import REGISTRY
from tenderwatch.sources.base import Source

NOW = datetime.now(PKT)


class FakeOk(Source):
    type_name = "fake_ok"

    def fetch(self):
        return [Tender(source=self.name, source_id="1", title="AI and data analytics platform",
                       deadline=(NOW.date().replace(day=NOW.day)).isoformat(), published=NOW.date().isoformat(),
                       url="https://x/1")]


class FakeNet(Source):
    type_name = "fake_net"

    def fetch(self):
        raise requests.ConnectionError("no route")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "fake_ok", FakeOk)
    monkeypatch.setitem(REGISTRY, "fake_net", FakeNet)
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["sources"] = [{"name": "good", "type": "fake_ok"}, {"name": "down", "type": "fake_net"}]
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("APPS_SCRIPT_URL", "https://script.example/exec")
    monkeypatch.setenv("APPS_SCRIPT_TOKEN", "secret")
    return {"cfg": str(cfg_path), "state": str(tmp_path / "state.json"), "out": str(tmp_path / "out")}


def args(p, *extra):
    return ["--config", p["cfg"], "--state", p["state"], "--out", p["out"], *extra]


def test_happy_path_posts_and_saves_state(project, monkeypatch):
    sent = {}
    monkeypatch.setattr(run_mod, "post", lambda url, payload: sent.update(payload) or {"ok": True})
    assert run_mod.main(args(project)) == 0
    assert sent["token"] == "secret" and len(sent["tenders"]) == 1
    assert {s["name"]: s["status"] for s in sent["sources"]} == {"good": "ok", "down": "error"}
    assert "network: ConnectionError" in json.dumps(sent["sources"])
    assert "good" in json.loads(open(project["state"]).read())["seen"].__str__()

    # next day the same tender is no longer new
    sent.clear()
    run_mod.main(args(project))
    assert sent["run"]["new"] == 0


def test_publish_failure_keeps_state_untouched(project, monkeypatch):
    def boom(url, payload):
        raise RuntimeError("webhook error: unauthorized")

    monkeypatch.setattr(run_mod, "post", boom)
    assert run_mod.main(args(project)) == 2
    import os
    assert not os.path.exists(project["state"])  # nothing saved, so tomorrow re-reports


def test_dry_run_posts_nothing(project, monkeypatch):
    monkeypatch.setattr(run_mod, "post", lambda *a: pytest.fail("must not post in dry run"))
    assert run_mod.main(args(project, "--dry-run")) == 0
    import os
    assert os.path.exists(project["out"] + "/digest.html") and not os.path.exists(project["state"])


def test_all_sources_down_exits_nonzero_but_still_reports(project, monkeypatch):
    cfg = yaml.safe_load(open(project["cfg"]))
    cfg["sources"] = [{"name": "down", "type": "fake_net"}]
    open(project["cfg"], "w").write(yaml.safe_dump(cfg))
    sent = {}
    monkeypatch.setattr(run_mod, "post", lambda url, payload: sent.update(payload) or {"ok": True})
    assert run_mod.main(args(project)) == 1
    assert "source issue" in sent["email"]["subject"]  # you still get an email telling you it broke
