import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ledger import (  # noqa: E402
    SYNTHETIC_TXN, active_to_events, apply_new_entries, empty_ledger, entry_key,
    make_entry, parse_points, parse_reason, parse_txn_datetime, replay,
)
from import_history import entries_from_csv  # noqa: E402

CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "goodtime_history_2026.csv")


def book(rid, date, time, title, txn, source="passes"):
    return {"txn_datetime": txn, "action": "book", "reservation_id": rid, "class_date": date,
            "class_start_time": time, "title": title, "points": -4, "source": source}


def cancel(rid, date, time, title, txn):
    e = book(rid, date, time, title, txn)
    e.update(action="cancel", points=4)
    return e


# ---------------------------------------------------------------- parsing --

def test_parse_reason_book_with_space_before_id():
    r = parse_reason("預約課程: 2026-09-15 19:20:00【大安】空中串連 仙女養成班 (4好幣)｜進階 <22471602>")
    assert r == {"action": "book", "class_date": "2026-09-15", "class_start_time": "19:20",
                 "title": "【大安】空中串連 仙女養成班 (4好幣)｜進階", "reservation_id": "22471602"}


def test_parse_reason_cancel_no_space_after_colon_and_no_space_before_id():
    r = parse_reason("取消課程:2026-01-12 20:35:00 【中和】低空療癒 失眠救星（4好幣）＊<20120401>")
    assert r["action"] == "cancel"
    assert r["class_start_time"] == "20:35"
    assert r["title"] == "【中和】低空療癒 失眠救星（4好幣）＊"
    assert r["reservation_id"] == "20120401"


def test_parse_reason_fullwidth_digits_and_missing_id():
    r = parse_reason("預約課程：2026-03-31 19:00【民權】空中瑜伽 美力新高度＊（４好幣）")
    assert r["title"] == "【民權】空中瑜伽 美力新高度＊（４好幣）"
    assert r["reservation_id"] is None


def test_parse_reason_unknown_prefix_returns_none():
    assert parse_reason("購買方案: 【全區通用】168 好幣") is None
    assert parse_reason("") is None


def test_parse_txn_datetime_pads_single_digit_hour():
    assert parse_txn_datetime("2026-06-04 0:40:03") == "2026-06-04 00:40:03"
    assert parse_txn_datetime("2026-09-04 21:05:20") == "2026-09-04 21:05:20"


def test_parse_points():
    assert parse_points("-4 Point") == -4
    assert parse_points("+4 Point") == 4
    assert parse_points("") is None


def test_make_entry_never_contains_user():
    e = make_entry("2026-09-04 21:05:20", "預約課程: 2026-09-15 19:20:00 X <1>", "-4 Point", "passes")
    assert "user" not in {k.lower() for k in e}


# ----------------------------------------------------------------- replay --

def test_replay_book_cancel_rebook():
    entries = [
        book("1", "2026-05-09", "14:30", "A", "2026-04-29 00:35:11"),
        cancel("1", "2026-05-09", "14:30", "A", "2026-05-08 20:56:40"),
        book("2", "2026-05-09", "14:30", "A", "2026-05-08 21:00:00"),
    ]
    active = replay(entries)
    assert list(active) == ["rid:2"]


def test_replay_cancel_without_booking_is_ignored():
    assert replay([cancel("9", "2026-01-01", "10:00", "A", "2026-01-01 00:00:00")]) == {}


def test_replay_cancel_matches_by_id_even_if_title_changed():
    entries = [
        book("1", "2026-05-09", "14:30", "A", "2026-04-29 00:35:11"),
        cancel("1", "2026-05-09", "14:30", "A 代課", "2026-05-08 20:56:40"),
    ]
    assert replay(entries) == {}


def test_replay_real_booking_supersedes_synthetic_and_cancel_clears_it():
    synthetic = book(None, "2026-09-01", "19:10", "A", SYNTHETIC_TXN, source="events.json")
    real = book("7", "2026-09-01", "19:10", "A", "2026-08-20 10:00:00")
    assert list(replay([synthetic, real])) == ["rid:7"]
    assert replay([synthetic, real, cancel("7", "2026-09-01", "19:10", "A", "2026-08-26 00:37:52")]) == {}


def test_active_to_events_adds_60_minutes_and_keeps_past():
    active = replay([book("1", "2026-01-05", "19:25", "  A   B ", "2025-12-30 00:00:00")])
    ev = active_to_events(active)
    assert ev == [{"date": "2026-01-05", "start_time": "19:25", "end_time": "20:25", "title": "A B"}]


# ------------------------------------------------------- merge and cursor --

def test_apply_new_entries_dedupes_boundary_rows_and_advances_cursor():
    ledger = empty_ledger()
    first = [book("1", "2026-09-08", "19:10", "A", "2026-08-26 00:42:04")]
    assert apply_new_entries(ledger, first) == 1
    assert ledger["cursor"] == "2026-08-26 00:42:04"
    again = [book("1", "2026-09-08", "19:10", "A", "2026-08-26 00:42:04"),   # same row re-scraped at cursor
             book("2", "2026-09-12", "14:30", "B", "2026-09-04 21:01:17")]
    assert apply_new_entries(ledger, again) == 1
    assert len(ledger["entries"]) == 2
    assert ledger["cursor"] == "2026-09-04 21:01:17"


def test_entry_key_falls_back_to_class_key_without_id():
    e = book(None, "2026-01-05", "19:25", "A", SYNTHETIC_TXN)
    assert entry_key(e) == "cls:2026-01-05|19:25|A|book"


# --------------------------------------------------------------- real CSV --

def test_real_csv_import():
    entries, skipped = entries_from_csv(CSV)
    assert skipped == 0
    assert len(entries) == 49
    ledger = empty_ledger()
    apply_new_entries(ledger, entries)
    assert ledger["cursor"] == "2026-06-24 12:33:52"
    assert len(active_to_events(replay(ledger["entries"]))) == 35
    # every cancel in the CSV refers to a known booking id
    ids = {e["reservation_id"] for e in entries if e["action"] == "book"}
    assert all(e["reservation_id"] in ids for e in entries if e["action"] == "cancel")


# ------------------------------------------------------------------ guard --

def test_guard_fails_when_no_pass_found():
    import pytest
    from ledger import assert_scrape_sane
    with pytest.raises(SystemExit):
        assert_scrape_sane(empty_ledger(), [], passes_found=0)


def test_guard_allows_zero_new_rows_on_incremental_run():
    from ledger import assert_scrape_sane
    ledger = empty_ledger()
    apply_new_entries(ledger, [book("1", "2026-09-08", "19:10", "A", "2026-08-26 00:42:04")])
    assert_scrape_sane(ledger, [], passes_found=1)          # no exception


def test_guard_fails_on_full_resync_without_overlap():
    import pytest
    from ledger import assert_scrape_sane
    ledger = empty_ledger()
    apply_new_entries(ledger, [book("1", "2026-09-08", "19:10", "A", "2026-08-26 00:42:04")])
    foreign = [book("999", "2026-09-09", "10:00", "Z", "2026-08-27 00:00:00")]
    with pytest.raises(SystemExit):
        assert_scrape_sane(ledger, foreign, passes_found=1, full_resync=True)
