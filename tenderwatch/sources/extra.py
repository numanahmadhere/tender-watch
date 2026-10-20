from __future__ import annotations

import json
from datetime import timedelta

from ..dates import parse_date
from ..models import Tender
from .base import ParserError, Source

PROJECTS_API = "https://search.worldbank.org/api/v2/projects"
CF_API = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
CF_NOTICE = "https://www.contractsfinder.service.gov.uk/Notice/{id}"
TED_API = "https://api.ted.europa.eu/v3/notices/search"
TED_NOTICE = "https://ted.europa.eu/en/notice/-/detail/{id}"


class WbPipelineSource(Source):
    """Early signal: World Bank projects for Pakistan that are still in the pipeline.

    These show up months before any procurement notice, so you can approach the
    client department early. Uses the public projects API (field names verified).
    """

    type_name = "wb_pipeline"

    def fetch(self) -> list[Tender]:
        statuses = self.cfg.get("statuses") or ["Pipeline"]
        out: list[Tender] = []
        for status in statuses:
            params = {"format": "json", "countrycode_exact": "PK", "status_exact": status, "rows": 100,
                      "fl": "id,project_name,status,pdo,url,boardapprovaldate,sector1,lendinginstr"}
            data = self.http.get(PROJECTS_API, params=params, source=self.name, tag=status).json()
            projects = data.get("projects") or {}
            if isinstance(projects, dict):
                projects = list(projects.values())
            for p in projects:
                pid = p.get("id")
                name = (p.get("project_name") or "").strip()
                if not pid or not name:
                    continue
                if not name.lower().startswith("pakistan") and "pakistan" not in (p.get("pdo") or "").lower():
                    continue  # safety net if the server-side country filter is ignored
                out.append(Tender(
                    source=self.name, source_id=pid, title=name, kind="tender",
                    buyer="World Bank (borrower: Government of Pakistan)",
                    category=(p.get("sector1") or {}).get("Name", "") if isinstance(p.get("sector1"), dict) else "",
                    notice_type="Pipeline project (early signal, no tender yet)",
                    published=parse_date(p.get("boardapprovaldate")) or "",
                    url=p.get("url") or f"https://projects.worldbank.org/en/projects-operations/project-detail/{pid}",
                    status=p.get("status", status),
                    description=(p.get("pdo") or "").strip(),
                ))
        return out


class ContractsFinderSource(Source):
    """UK Contracts Finder (OCDS, no key). Keeps notices that mention Pakistan (FCDO, British Council etc.)."""

    type_name = "contracts_finder"

    def fetch(self) -> list[Tender]:
        days = int(self.cfg.get("lookback_days", 14))
        max_pages = int(self.cfg.get("max_pages", 8))
        needle = (self.cfg.get("contains") or "pakistan").lower()
        since = (self.now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
        url, params = CF_API, {"publishedFrom": since, "stages": "tender", "limit": 100}
        out: list[Tender] = []
        for page in range(max_pages):
            data = self.http.get(url, params=params, source=self.name, tag=f"p{page}").json()
            releases = data.get("releases")
            if releases is None:
                raise ParserError("response has no 'releases' list")
            for r in releases:
                if needle not in json.dumps(r, ensure_ascii=False).lower():
                    continue
                t = r.get("tender") or {}
                rid = str(r.get("id") or r.get("ocid") or "")
                if not rid or not t.get("title"):
                    continue
                uuid = rid.split("-", 3)[-1] if rid.startswith("ocds-") else rid
                out.append(Tender(
                    source=self.name, source_id=rid, title=t["title"].strip(), kind="tender",
                    buyer=(r.get("buyer") or {}).get("name", ""),
                    category=t.get("mainProcurementCategory", ""),
                    notice_type="UK tender notice",
                    published=parse_date((r.get("date") or "")[:10]) or "",
                    deadline=((t.get("tenderPeriod") or {}).get("endDate") or "")[:10],
                    url=CF_NOTICE.format(id=uuid),
                    status=t.get("status", ""),
                    description=(t.get("description") or "")[:1500],
                ))
            nxt = (data.get("links") or {}).get("next")
            if not nxt or not releases:
                break
            url, params = nxt, None
        return out


def _text(v) -> str:
    """TED returns multilingual values as {lang: text|[text]}; take English if present, else the first string."""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        for x in v:
            s = _text(x)
            if s:
                return s
        return ""
    if isinstance(v, dict):
        for key in ("eng", "ENG", "en"):
            if key in v:
                return _text(v[key])
        for x in v.values():
            s = _text(x)
            if s:
                return s
    return ""


class TedSource(Source):
    """EU Tenders Electronic Daily (public API, no key): notices performed in or bought from Pakistan."""

    type_name = "ted"

    def fetch(self) -> list[Tender]:
        days = int(self.cfg.get("lookback_days", 30))
        since = (self.now - timedelta(days=days)).strftime("%Y%m%d")
        query = self.cfg.get("query") or (
            f"(place-of-performance-country-lot=PAK OR buyer-country=PAK) AND publication-date>={since}")
        fields = ["publication-number", "notice-title", "buyer-name", "publication-date",
                  "deadline-receipt-tender-date-lot", "notice-type", "links"]
        out: list[Tender] = []
        for page in range(1, int(self.cfg.get("max_pages", 5)) + 1):
            body = {"query": query, "fields": fields, "page": page, "limit": 100}
            data = self.http.post(TED_API, json=body, source=self.name, tag=f"p{page}").json()
            notices = data.get("notices")
            if notices is None:
                raise ParserError("response has no 'notices' list")
            for n in notices:
                num = n.get("publication-number")
                title = _text(n.get("notice-title")).strip()
                if not num or not title:
                    continue
                link = _text((n.get("links") or {}).get("htmlDirect")) or TED_NOTICE.format(id=num)
                out.append(Tender(
                    source=self.name, source_id=str(num), title=title, kind="tender",
                    buyer=_text(n.get("buyer-name")),
                    notice_type=_text(n.get("notice-type")),
                    published=parse_date(_text(n.get("publication-date"))[:10]) or "",
                    deadline=_text(n.get("deadline-receipt-tender-date-lot"))[:10],
                    url=link,
                ))
            if len(notices) < 100:
                break
        return out
