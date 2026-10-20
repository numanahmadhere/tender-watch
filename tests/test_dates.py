from datetime import datetime

from tenderwatch.dates import PKT, days_until, find_dates, parse_date, parse_relative

NOW = datetime(2026, 10, 20, 13, 0, tzinfo=PKT)


def test_parse_world_bank_formats():
    assert parse_date("18-Oct-2026") == "2026-10-18"
    assert parse_date("2026-11-13T00:00:00Z") == "2026-11-13"  # midnight means date only
    assert parse_date("2026-11-13T09:30:00Z") == "2026-11-13T09:30"


def test_parse_portal_formats():
    assert parse_date("Wednesday, October 21, 2026 11:00 AM") == "2026-10-21T11:00"
    assert parse_date("Dec 08, 2026 09:30 AM") == "2026-12-08T09:30"
    assert parse_date("Oct 19, 2026") == "2026-10-19"
    assert parse_date("not a date") == ""
    assert parse_date("") == ""


def test_find_dates_in_blob():
    blob = "Published Advertised Oct 19, 2026 Closing Dec 08, 2026 09:30 AM Actions"
    assert find_dates(blob) == ["2026-10-19", "2026-12-08T09:30"]


def test_relative_countdown():
    assert parse_relative("Closing On 1h 49m Left", NOW) == "2026-10-20T14:49"
    assert parse_relative("2d 3h Left", NOW) == "2026-10-22T16:00"
    assert parse_relative("no countdown here", NOW) == ""


def test_days_until():
    assert days_until("2026-10-23", NOW) == 3
    assert days_until("2026-10-19T10:00", NOW) == -1
    assert days_until("", NOW) is None
