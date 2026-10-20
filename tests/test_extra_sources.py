"""Fixtures are reconstructed from API docs; only the WB projects fields were seen live."""
from datetime import datetime

from tenderwatch.dates import PKT
from tenderwatch.sources.extra import ContractsFinderSource, TedSource, WbPipelineSource, _text

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=PKT)


class FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class FakeHttp:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return FakeResp(self.pages.pop(0))

    post = get


def test_wb_pipeline_parses_and_filters():
    data = {"projects": {
        "P181037": {"id": "P181037", "project_name": "Pakistan: Resilient and Accessible Microfinance (RAM) Project",
                    "status": "Pipeline", "pdo": "To support microfinance", "url": "https://wb/P181037",
                    "sector1": {"Name": "", "Percent": 0}},
        "PX": {"id": "PX", "project_name": "Kenya: Roads", "status": "Pipeline", "pdo": "roads"}}}
    out = WbPipelineSource("wb_pipeline", {}, FakeHttp(data), NOW).fetch()
    assert [t.source_id for t in out] == ["P181037"]
    assert out[0].uid == "wb_pipeline:P181037" and "early signal" in out[0].notice_type


def test_contracts_finder_keeps_pakistan_only_and_follows_cursor():
    r1 = {"releases": [
        {"id": "ocds-b5fd17-abc123", "date": "2026-10-18T10:00:00Z", "buyer": {"name": "FCDO"},
         "tender": {"title": "Data analytics support Pakistan", "tenderPeriod": {"endDate": "2026-11-10T12:00:00Z"}}},
        {"id": "ocds-b5fd17-zzz", "tender": {"title": "Road cones, Leeds"}}],
        "links": {"next": "https://cf/next"}}
    r2 = {"releases": []}
    http = FakeHttp(r1, r2)
    out = ContractsFinderSource("contracts_finder", {}, http, NOW).fetch()
    assert len(out) == 1 and out[0].deadline == "2026-11-10" and out[0].buyer == "FCDO"
    assert http.calls[1][0] == "https://cf/next"


def test_ted_multilingual_and_link_fallback():
    assert _text({"eng": "Hello", "fra": "Salut"}) == "Hello"
    assert _text({"fra": ["Salut"]}) == "Salut"
    data = {"notices": [{"publication-number": "123456-2026", "notice-title": {"eng": "AI platform for Pakistan"},
                         "buyer-name": {"eng": ["EU Delegation"]}, "publication-date": "2026-10-15+02:00",
                         "deadline-receipt-tender-date-lot": ["2026-11-20T12:00:00+01:00"]}]}
    out = TedSource("ted", {}, FakeHttp(data), NOW).fetch()
    assert out[0].url.endswith("123456-2026") and out[0].published == "2026-10-15"
    assert out[0].deadline == "2026-11-20" and out[0].buyer == "EU Delegation"
