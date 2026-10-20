"""Parser tests.

The World Bank fixture uses the real field names observed from the live API. The
EPMS, EPADS and table fixtures are RECONSTRUCTIONS of the structure described from the
portals (column names, two-row layout, link patterns), not captured pages. They prove the
parsers' logic; the first discover-mode run on GitHub proves them against the real sites.
"""
from datetime import datetime

from tenderwatch.dates import PKT
from tenderwatch.sources import epads, epms, generic, ungm, worldbank

NOW = datetime(2026, 10, 20, 13, 0, tzinfo=PKT)

WB_NOTICE = {
    "id": "OP00475650",
    "notice_type": "Request for Expression of Interest",
    "noticedate": "16-Oct-2026",
    "notice_status": "Published",
    "submission_deadline_date": "2026-11-13T00:00:00Z",
    "project_ctry_name": "Pakistan",
    "project_name": "Digital Public Services Project",
    "bid_description": "Consultancy services for a national data platform and analytics",
    "procurement_group": "CS",
    "contact_organization": "Planning Department",
    "contact_email": "pmu@example.org",
    "contact_name": "A. Khan",
    "notice_text": "<p><strong>REQUEST FOR EXPRESSIONS OF INTEREST</strong></p><ol><li>Machine learning skills</li></ol>",
}
WB_AWARD_NO_DEADLINE = {
    "id": "OP00475962",
    "notice_type": "Contract Award",
    "noticedate": "14-Oct-2026",
    "project_ctry_name": "Pakistan",
    "bid_description": "Supply of ERP software",
    "procurement_group": "GO",
}


def test_worldbank_parse():
    t = worldbank.parse_notice(WB_NOTICE)
    assert t.uid == "worldbank:OP00475650"
    assert t.kind == "tender" and t.category == "Consulting services"
    assert t.published == "2026-10-16" and t.deadline == "2026-11-13"
    assert "Machine learning" in t.description and "pmu@example.org" in t.contact
    assert t.url.endswith("/procurement-detail/OP00475650")


def test_worldbank_award_with_missing_fields():
    t = worldbank.parse_notice(WB_AWARD_NO_DEADLINE)
    assert t.kind == "award" and t.deadline == "" and t.contact == ""


EPMS_HTML = """
<table><thead><tr><th></th><th>Sr</th><th>Tender No</th><th>Tender Details</th><th>Status</th>
<th>Advertised</th><th>Closing</th><th>Actions</th></tr></thead><tbody>
<tr><td><input type="checkbox"></td><td>1</td><td><b>TS0000016360E</b> Procurement</td>
 <td><b>Development of MIS and data analytics dashboard</b> for monitoring of schemes Consultancy</td>
 <td>Published</td><td>Oct 19, 2026</td><td><b>Dec 08, 2026 09:30 AM</b></td>
 <td><a href="/public/tenders/tender-details/TS0000016360E">View</a>
     <a href="/public/tenders/invoice/TS0000016360E">Invoice</a></td></tr>
<tr><td colspan="8">Organization Ministry of IT Tender Type Tender Notice Procurement Category Consultancy Services
 Sector Information Technology Tender Nature Local Advertised Oct 19, 2026</td></tr>
<tr><td><input type="checkbox"></td><td>2</td><td><b>TS0000016361E</b> Procurement</td>
 <td><b>Supply of office furniture</b> Miscellaneous</td><td>Published Corrigendum</td>
 <td>Oct 18, 2026</td><td><b>Nov 02, 2026 10:00 AM</b></td>
 <td><a href="/public/tenders/tender-details/TS0000016361E">View</a></td></tr>
<tr><td colspan="8">Organization Pakistan Railways Sector Furniture</td></tr>
</tbody></table>
<div>Showing 50 of 2125 tenders  Page 1 of 43</div>
"""


def test_epms_listing_two_row_layout():
    items = epms.parse_listing(EPMS_HTML)
    assert [t.source_id for t in items] == ["TS0000016360E", "TS0000016361E"]
    a = items[0]
    assert a.title == "Development of MIS and data analytics dashboard"
    assert a.buyer == "Ministry of IT"
    assert a.published == "2026-10-19" and a.deadline == "2026-12-08T09:30"
    assert "Consultancy Services" in a.category
    assert items[1].status == "Published Corrigendum"
    assert epms.page_count(EPMS_HTML) == 43


EPADS_HTML = """
<table><tr><th>#</th><th>Procurement Title</th><th>Procurement Status</th><th>Type/Procedure</th><th>Details</th></tr>
<tr><td>1</td>
 <td><a href="/opportunities/federal/procurements/9001">Digital transformation of tax services</a>
     <div>Federal Board of Revenue P146550</div></td>
 <td>Published On Wednesday, October 14, 2026 9:00 AM Closing On Wednesday, October 28, 2026 11:00 AM</td>
 <td>Consultancy Services Single Stage-Two Envelope</td>
 <td><a href="/opportunities/federal/procurements/9001">View</a></td></tr>
<tr><td>2</td>
 <td><a href="/opportunities/federal/procurements/9002">Supply of laptops</a><div>Ministry of Defence</div></td>
 <td>Published On Wednesday, October 14, 2026 9:00 AM 1h 49m Left</td>
 <td>Goods Single Stage-One Envelope</td>
 <td><a href="/opportunities/federal/procurements/9002">View</a></td></tr>
</table>
<div>Page 1 of 14</div>
"""


def test_epads_listing():
    items = epads.parse_listing(EPADS_HTML, "epads_federal", NOW)
    assert len(items) == 2
    a, b = items
    assert a.uid == "epads_federal:federal-9001"
    assert a.title == "Digital transformation of tax services"
    assert a.buyer == "Federal Board of Revenue"
    assert a.category == "Consultancy Services"
    assert a.published == "2026-10-14" and a.deadline == "2026-10-28T11:00"
    assert b.deadline == "2026-10-20T14:49"  # resolved from the countdown
    assert epads.page_count(EPADS_HTML) == 14


TABLE_HTML = """
<table><tr><th>S.No</th><th>Tender Title</th><th>Department</th><th>Closing Date</th></tr>
<tr><td>1</td><td><a href="/t/55">Procurement of cloud hosting and ERP software</a></td>
    <td>Health Department</td><td>Nov 10, 2026</td></tr>
<tr><td>2</td><td>short</td><td>X</td><td>Nov 11, 2026</td></tr>
</table>
"""


def test_generic_table_maps_headers_and_skips_junk():
    items = generic.parse_table(TABLE_HTML, "https://portal.example/list", "demo")
    assert len(items) == 1
    t = items[0]
    assert t.title == "Procurement of cloud hosting and ERP software"
    assert t.buyer == "Health Department" and t.deadline == "2026-11-10"
    assert t.url == "https://portal.example/t/55"


def test_generic_harvest_links_fallback():
    html = '<a href="/x/1">A long enough link text describing a tender for data analytics</a><a href="/y">short</a>'
    items = generic.harvest_links(html, "https://p.example/", "demo")
    assert len(items) == 1 and items[0].url == "https://p.example/x/1"


def test_ungm_filters_to_pakistan():
    html = """
    <div data-noticeid="1"><a href="/Public/Notice/101">UNDP data system for Pakistan</a> Pakistan 30-Oct-2026</div>
    <div data-noticeid="2"><a href="/Public/Notice/102">Vehicles for Chad</a> Chad</div>
    """
    items = ungm.parse_results(html, "ungm")
    assert [t.source_id for t in items] == ["101"]


def test_award_rows_get_clean_ids_and_titles():
    from tenderwatch.sources.generic import parse_table
    html = ("<table><tr><td>EVL00000004120 TS0000013971E Tender Ref#: SLIC/H&amp;#38;AI/RO/I "
            "SUPPLY OF AI SERVER MACHINES 5 Bids Equipments State Life Insurance</td><td>x</td></tr></table>")
    t = parse_table(html, "https://x.test/", "epms_awards", "award")[0]
    assert t.source_id == "EVL00000004120"
    assert "Bids" not in t.title and "EVL" not in t.title and "&#" not in t.title
    assert t.description == ""


def test_pitb_style_table_and_page_base():
    from tenderwatch.sources.generic import parse_table
    html = ("<table><tr><th>Title</th><th>File</th><th>Release Date</th><th>Closing Date</th></tr>"
            "<tr><td>HR outsourcing, scanning, and data entry (EGOV-21)</td>"
            "<td><a href='/system/files/BD_EGOV_21.pdf'>pdf</a></td><td>Oct 15, 2026</td><td>Oct 30, 2026</td></tr></table>")
    t = parse_table(html, "https://pitb.gov.pk/tendernotices", "pitb")[0]
    assert t.published == "2026-10-15" and t.deadline == "2026-10-30"
    assert t.url == "https://pitb.gov.pk/system/files/BD_EGOV_21.pdf"


def test_gb_ppra_cards_real_fixture():
    from pathlib import Path
    from tenderwatch.sources.gb import parse_cards
    html = (Path(__file__).parent / "fixtures" / "gb_ppra_cards.html").read_text("utf-8")
    items = parse_cards(html, "gb_ppra")
    assert len(items) >= 3
    t = items[0]
    assert t.source_id.startswith("TSE-") and t.title and t.buyer
    assert t.published.startswith("2026-") and t.deadline.startswith("2026-")
    assert t.url.startswith("https://www.gbppra.gov.pk/procurementde")
    assert "View" not in t.title


def test_feed_filters_tender_signals():
    from tenderwatch.sources.feed import parse_feed
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>ProPakistani</title>
    <item><title>ECNEC approves digital land records project</title><link>https://x.test/a</link>
    <pubDate>Tue, 20 Oct 2026 12:19:14 +0000</pubDate><description>&lt;p&gt;AI and digitization&lt;/p&gt;</description></item>
    <item><title>Cricket team wins</title><link>https://x.test/b</link><pubDate>Tue, 20 Oct 2026 12:00:00 +0000</pubDate></item>
    </channel></rss>"""
    out = parse_feed(rss, "news")
    assert len(out) == 1 and out[0].published == "2026-10-20" and out[0].buyer == "ProPakistani"
    assert "<p>" not in out[0].description


def test_moitt_style_table():
    """Layout reconstructed from a description of moitt.gov.pk/Tenders (columns and link style)."""
    from tenderwatch.sources.generic import parse_table
    html = ("<table><tr><th>Title</th><th>Type</th><th>Status</th><th>Advertisement Date</th>"
            "<th>Closing Date</th><th>Download</th></tr>"
            "<tr><td><a href='/TenderDetail/abc123'>Selection of Training Company / Consortium for AI Capacity Building in Pakistan</a></td>"
            "<td>RFP</td><td>Open</td><td>14 May 2026</td><td>08 June 2026</td>"
            "<td><a href='/SiteImage/Tenders/x.pdf'>Download</a></td></tr></table>")
    t = parse_table(html, "https://moitt.gov.pk/Tenders", "moitt")[0]
    assert t.title.startswith("Selection of Training Company")
    assert t.category == "RFP" and t.published == "2026-05-14" and t.deadline == "2026-06-08"
    assert t.url == "https://moitt.gov.pk/TenderDetail/abc123"

    from tenderwatch.filtering import Scorer
    import yaml
    cfg = yaml.safe_load(open("config.yaml"))["keywords"]
    assert Scorer(cfg).evaluate(t)  # "AI" in the title is enough to be reported
