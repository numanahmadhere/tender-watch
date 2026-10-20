from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from .dates import days_until, now_pkt
from .digest import build_digest, closing_soon
from .filtering import Scorer
from .http import Http
from .models import Tender
from .publish import build_payload, post
from .sources import build_sources
from .sources.base import Result
from .state import State


def is_current(t: Tender, now, lookback: int) -> bool:
    """Open tenders, or recent notices when the portal gives no deadline."""
    pub = days_until(t.published, now)
    if t.kind == "award":
        return pub is None or pub >= -lookback
    d = days_until(t.deadline, now)
    if d is not None:
        return d >= 0
    if pub is not None:
        return pub >= -lookback
    return True  # neither date known: keep it, we cannot judge


def run_pipeline(cfg: dict, results: list[Result], state: State, now, today: str):
    """Pure part of the run: score, filter, diff against memory. No network."""
    scorer = Scorer(cfg["keywords"])
    lookback = int(cfg.get("lookback_days", 30))
    relevant: list[Tender] = []
    seen_uids: set[str] = set()
    for r in results:
        for t in r.tenders:
            if t.uid in seen_uids:
                continue
            seen_uids.add(t.uid)
            if scorer.evaluate(t) and is_current(t, now, lookback):
                relevant.append(t)
    diff = state.diff(relevant, today)
    new_uids = {t.uid for t in diff.new}
    changed_uids = {t.uid for t in diff.changed}
    soon = closing_soon(relevant, new_uids | changed_uids, now)
    tenders = [t for t in relevant if t.kind == "tender"]
    awards = [t for t in relevant if t.kind == "award"]
    awards_new = [t for t in diff.new if t.kind == "award"]
    return relevant, diff, soon, tenders, awards, awards_new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TenderWatch daily run")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--state", default="data/state.json")
    ap.add_argument("--out", default="output")
    ap.add_argument("--dry-run", action="store_true", help="do not post to the webhook or save state")
    ap.add_argument("--discover", action="store_true", help="save raw page snapshots of each source")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text("utf-8"))
    now = now_pkt()
    today = now.strftime("%Y-%m-%d")
    discover = args.discover or os.environ.get("TW_DISCOVER") == "1"
    http = Http(delay=float(cfg.get("request_delay_seconds", 1.2)), discover=discover,
                snapshot_dir=str(Path(args.out) / "snapshots"))

    results = [s.run() for s in build_sources(cfg, http, now)]
    for r in results:
        print(f"[{r.status:>12}] {r.name}: {r.count} records {r.message}")

    state = State.load(args.state)
    relevant, diff, soon, tenders, awards, awards_new = run_pipeline(cfg, results, state, now, today)
    email = build_digest(
        [t for t in diff.new if t.kind == "tender"], diff.changed, soon, awards_new, results, today, now,
        sheet_url=os.environ.get("SHEET_URL", ""),
    )
    counts = {"new": len(diff.new), "updated": len(diff.changed), "closing_soon": len(soon),
              "sources_ok": sum(r.status == "ok" for r in results),
              "sources_issues": sum(r.status in ("error", "skipped", "experimental") for r in results)}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "digest.html").write_text(email["html"], "utf-8")
    (out / "summary.json").write_text(json.dumps({"counts": counts, "subject": email["subject"]}, indent=1), "utf-8")
    print(email["subject"])

    if args.dry_run:
        print("dry run: nothing posted, state not saved")
        return 0 if counts["sources_ok"] else 1

    url, token = os.environ.get("APPS_SCRIPT_URL", ""), os.environ.get("APPS_SCRIPT_TOKEN", "")
    if not url or not token:
        print("APPS_SCRIPT_URL / APPS_SCRIPT_TOKEN not set: wrote output/digest.html only, state not saved")
        return 0 if counts["sources_ok"] else 1
    try:
        post(url, build_payload(token, today, tenders, awards, results, email, counts))
    except Exception as e:  # keep state untouched so tomorrow re-reports what was missed
        print(f"publish failed: {e}", file=sys.stderr)
        return 2
    state.save(args.state)
    return 0 if counts["sources_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
