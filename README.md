# TenderWatch

A private, personal radar for AI, data and digital transformation tenders in Pakistan.
It runs once a day on GitHub Actions, updates a Google Sheet, and emails you a digest.

## What it does each day

1. Pulls tenders and notices from every enabled source in `config.yaml`.
2. Scores each one against the keyword groups (AI, data, digital) and drops noise.
3. Compares with `data/state.json` to find what is new, what changed (deadline, status, title) and what closes within 7 days.
4. Posts everything to your Apps Script webhook, which updates the sheet and sends the email.
5. Commits the updated `data/state.json` back to the repo.

## Sources

| Source | Method | Confidence |
|---|---|---|
| `worldbank` | Official public API, Pakistan filter | High: field names and filter verified |
| `epms_tenders` | Federal PPRA EPMS active tenders, `?page=N` | Medium: page structure verified, HTML selectors not |
| `epads_federal`, `epads_kp` | EPADS 2.0 open opportunities, `?jurisdiction=` | Medium: same |
| `epms_awards` | EPMS `/public/contracts` and `/public/evaluations` | Experimental: layout unseen |
| `punjab_eproc`, `kppra`, `sindh_ppms` | Generic table parser | Their robots.txt disallows automated fetching, so they are skipped and reported |
| `balochistan`, `gb_ppra`, `ajk_ppra` | Generic table parser | Experimental |
| `ungm`, `adb` | Search post and generic parser | Disabled: UNGM returns 403, ADB URL gave 404 |
| `wb_pipeline` | World Bank projects API, Pakistan projects still in the pipeline | High: field names verified. Early signal, months before a tender |
| `ted` | EU TED public API, notices in or bought from Pakistan | Experimental: query syntax and field shapes from docs, unverified |
| `contracts_finder` | UK Contracts Finder OCDS API, notices mentioning Pakistan | Experimental |
| `undp` | UNDP procurement notices, rows containing UNDP-PAK | Experimental |
| `news` | RSS feeds (ProPakistani, TechJuice, APP, Dawn, Business Recorder, Tribune), kept only if the item mentions a tender, RFP, ECNEC, funding etc. | Experimental: early signals, not tender notices. Feeds are listed in config.yaml |
| `gb_ppra` | Dedicated parser for GB-PPRA's card layout | Tested on a real captured page |
| `sbp`, `adb`, `aiib` | Headless Chromium (Playwright) for pages built by JavaScript | Experimental |
| `pitb`, `fbr` | Generic table parser on each buyer's tenders page | Experimental: URLs are guesses, fix or disable from the Source health table |

"Experimental" means: if it parses nothing, the email says so in the Source health table instead of failing silently.
The tests use reconstructed HTML for everything except the World Bank fields, so the first real run is the real test.

The pipeline honors `robots.txt`, waits between requests to the same host, and never logs in anywhere.

## One-time setup

### 1. Google Sheet and Apps Script
1. Create a new Google Sheet (any name).
2. Extensions, Apps Script. Paste `apps_script/Code.gs` into the editor.
3. Project Settings: tick "Show appsscript.json manifest file", then replace its contents with `apps_script/appsscript.json`.
4. Project Settings, Script properties, add:
   - `TW_TOKEN`: a long random string you make up
   - `TW_RECIPIENT`: the address that should receive the digest
5. Deploy, New deployment, type Web app, Execute as: Me, Who has access: Anyone. Authorize when asked. Copy the web app URL.
   "Anyone" is needed so GitHub can call it. Requests without the right `TW_TOKEN` are rejected.

### 2. GitHub repo secrets (Settings, Secrets and variables, Actions)
| Secret | Value |
|---|---|
| `APPS_SCRIPT_URL` | the web app URL from step 1 |
| `APPS_SCRIPT_TOKEN` | the same string as `TW_TOKEN` |
| `SHEET_URL` | optional: the sheet link, shown in the email |

### 3. First runs
1. Actions, "TenderWatch daily", Run workflow with `discover` on and `dry_run` on. Nothing is posted. Download the `tenderwatch-output` artifact: `digest.html` and raw page snapshots per source.
2. Check the Source health table. Any source marked error or experimental can be fixed from its snapshot.
3. Run once with both off. The sheet is filled and the first email arrives. The first email lists everything currently open that matches, so it is the longest one.
4. From then on it runs daily at 08:17 Pakistan time.

## Local use

```
pip install -r requirements.txt pytest
python -m pytest            # unit and end-to-end tests, no network needed
python -m tenderwatch.run --dry-run
```

## Tuning

Edit `config.yaml`: keyword groups and weights, exclusion phrases, `min_score`, sources on or off.
If you change the sheet columns (`tenderwatch/publish.py`), delete the old tabs first: the webhook refuses to write into a tab whose header differs.

## Known limits

- GitHub may delay or drop scheduled runs under load. If that happens, trigger the workflow from a Cloudflare Worker cron via `workflow_dispatch`.
- Some provincial portals send tenders only through sign-in pages. Those are out of scope.
- Newspaper-only tenders and non-EPADS buyers (banks, telcos) are not covered yet.
