from __future__ import annotations

from bs4 import BeautifulSoup

from ..dates import days_until, parse_date
from ..models import Tender
from .base import Source

API = "https://search.worldbank.org/api/v2/procnotices"
DETAIL = "https://projects.worldbank.org/en/projects-operations/procurement-detail/{id}"

GROUPS = {"CW": "Works", "GO": "Goods", "NC": "Non-consulting services", "CS": "Consulting services"}


def _clean_html(html: str, limit: int = 1500) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)[:limit]


def parse_notice(n: dict) -> Tender | None:
    nid = n.get("id")
    if not nid:
        return None
    ntype = n.get("notice_type", "")
    group = n.get("procurement_group", "")
    title = n.get("bid_description") or n.get("project_name") or ""
    text = _clean_html(n.get("notice_text", ""))
    contact_bits = [n.get("contact_name"), n.get("contact_email"), n.get("contact_phone_no")]
    return Tender(
        source="worldbank",
        source_id=nid,
        title=title.strip(),
        kind="award" if ntype == "Contract Award" else "tender",
        buyer=n.get("contact_organization", "") or "",
        category=GROUPS.get(group, group),
        notice_type=ntype,
        published=parse_date(n.get("noticedate")),
        deadline=parse_date(n.get("submission_deadline_date")),
        url=DETAIL.format(id=nid),
        status=n.get("notice_status", ""),
        description=" ".join(x for x in [n.get("project_name", ""), text] if x),
        contact=" | ".join(b for b in contact_bits if b),
    )


class WorldBankSource(Source):
    """Official World Bank procurement notices API (no key). Filtered to Pakistan."""

    type_name = "worldbank"

    def fetch(self) -> list[Tender]:
        rows = int(self.cfg.get("rows", 100))
        max_pages = int(self.cfg.get("max_pages", 120))
        cutoff_days = int(self.cfg.get("lookback_days", 45))
        out: list[Tender] = []
        sorted_desc = None
        for page in range(max_pages):
            params = {
                "format": "json",
                "rows": rows,
                "os": page * rows,
                "project_ctry_name_exact": "Pakistan",
                "srt": "noticedate",
                "order": "desc",
            }
            data = self.http.get(API, params=params, source=self.name, tag=f"page{page}").json()
            batch = data.get("procnotices") or []
            if isinstance(batch, dict):  # some responses key notices by id
                batch = list(batch.values())
            if not batch:
                break
            dates = []
            for n in batch:
                if n.get("project_ctry_name") != "Pakistan":
                    continue  # safety net in case the server-side filter is ignored
                t = parse_notice(n)
                if t:
                    out.append(t)
                    dates.append(t.published)
            if sorted_desc is None and len(dates) > 3:
                sorted_desc = dates == sorted(dates, reverse=True)
            # stop early once a whole page is older than the lookback window,
            # but only when we have verified that results come newest first
            if sorted_desc and dates and all((days_until(d, self.now) or 0) < -cutoff_days for d in dates if d):
                break
            if (page + 1) * rows >= int(data.get("total") or 0):
                break
        return out
