"""
One-off import of an exported Passes point-transaction CSV into ledger.json.

    python import_history.py goodtime_history_2026.csv [--events events.json] [--force]

CSV columns: Date, Reason, Change (export without the User column).
With --events, reservations present in the old events.json but missing from
the CSV are added as synthetic "book" rows (reservation_id null,
source "events.json", txn_datetime set to an epoch sentinel so any real
row scraped later supersedes them).
"""

import argparse
import csv
import json
import os

from ledger import (
    LEDGER_PATH, SYNTHETIC_TXN, active_to_events, apply_new_entries, empty_ledger,
    make_entry, normalize_title, replay, save_ledger,
)


def entries_from_csv(path):
    entries, skipped = [], 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            e = make_entry(row["Date"], row["Reason"], row.get("Change"), source="csv")
            if e is None:
                skipped += 1
                continue
            entries.append(e)
    return entries, skipped


def synthetic_entries_from_events(events_path, active):
    """events.json rows not covered by the replayed ledger -> synthetic book rows."""
    with open(events_path, encoding="utf-8") as f:
        events = json.load(f)
    covered_slots = {(e["class_date"], e["class_start_time"]) for e in active.values()}
    synthetic = []
    for ev in events:
        if (ev["date"], ev["start_time"]) in covered_slots:
            continue
        synthetic.append({
            "txn_datetime": SYNTHETIC_TXN,
            "action": "book",
            "reservation_id": None,
            "class_date": ev["date"],
            "class_start_time": ev["start_time"],
            "title": normalize_title(ev["title"]),
            "points": None,
            "source": "events.json",
        })
    return synthetic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--events", help="old events.json to back-fill reservations missing from the CSV")
    ap.add_argument("--out", default=LEDGER_PATH)
    ap.add_argument("--force", action="store_true", help="overwrite an existing ledger")
    args = ap.parse_args()

    if os.path.exists(args.out) and not args.force:
        raise SystemExit(f"{args.out} 已存在，若要覆寫請加 --force。")

    ledger = empty_ledger()
    entries, skipped = entries_from_csv(args.csv)
    if skipped:
        print(f"略過非預約/取消紀錄 ×{skipped}")
    n = apply_new_entries(ledger, entries)
    print(f"CSV 匯入 {n} 筆（book/cancel），cursor = {ledger['cursor']}")

    if args.events:
        synthetic = synthetic_entries_from_events(args.events, replay(ledger["entries"]))
        for s in synthetic:
            print(f"從 {args.events} 補入: {s['class_date']} {s['class_start_time']} {s['title']}")
        n2 = apply_new_entries(ledger, synthetic)
        print(f"合成 book 列 {n2} 筆（reservation_id = null）")

    save_ledger(args.out, ledger)
    events = active_to_events(replay(ledger["entries"]))
    print(f"已寫入 {args.out}：{len(ledger['entries'])} 筆紀錄，重放後 {len(events)} 筆有效預約。")


if __name__ == "__main__":
    main()
