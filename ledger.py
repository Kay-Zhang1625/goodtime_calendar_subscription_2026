"""
ledger.py — event store for class reservations.

`ledger.json` is an append-only log of booking / cancellation events scraped
from the Passes point-transaction table, plus a `cursor` (high-water mark)
holding the newest transaction datetime already processed.

    {
      "cursor": "2026-06-24 12:33:52",
      "entries": [ {...}, ... ]        # sorted by txn_datetime ascending
    }

Entry fields: txn_datetime, action ("book" | "cancel"), reservation_id
(str or None), class_date, class_start_time, title, points, source
("csv" | "events.json" | "passes").  The User (name) column is never stored.

All datetimes are naive Asia/Taipei strings; Taiwan has no DST so string
order equals chronological order.
"""

import json
import os
import re
from datetime import datetime, timedelta

LEDGER_PATH = "ledger.json"
DEFAULT_DURATION_MIN = 60
# txn_datetime for rows whose real booking time is unknown (back-filled from
# events.json); sorts before every real row so a real row always supersedes it.
SYNTHETIC_TXN = "1970-01-01 00:00:00"

ACTION_MAP = {"預約課程": "book", "取消課程": "cancel"}

REASON_RE = re.compile(
    r"^\s*(?P<action>預約課程|取消課程)\s*[:：]\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{1,2}:\d{2})(?::\d{2})?\s*"
    r"(?P<title>.*?)\s*(?:<\s*(?P<rid>\d+)\s*>)?\s*$",
    re.S,
)
TXN_DT_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2}):(\d{2})")
POINTS_RE = re.compile(r"([+-])\s*(\d+)\s*Point", re.I)


# ---------------------------------------------------------------- parsing --

def normalize_title(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_reason(text):
    """Parse a Reason cell. Returns a dict or None for non book/cancel rows."""
    m = REASON_RE.match(text or "")
    if not m:
        return None
    hh, mm = m.group("time").split(":")
    return {
        "action": ACTION_MAP[m.group("action")],
        "class_date": m.group("date"),
        "class_start_time": f"{int(hh):02d}:{mm}",
        "title": normalize_title(m.group("title")),
        "reservation_id": m.group("rid"),
    }


def parse_txn_datetime(text):
    """'2026-06-04 0:40:03' -> '2026-06-04 00:40:03' (zero-padded)."""
    m = TXN_DT_RE.search(text or "")
    if not m:
        raise ValueError(f"unrecognised transaction datetime: {text!r}")
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d} {int(h):02d}:{mi}:{s}"


def parse_points(text):
    m = POINTS_RE.search(text or "")
    if not m:
        return None
    sign, n = m.groups()
    return int(n) if sign == "+" else -int(n)


def make_entry(txn_text, reason_text, change_text, source):
    """Build a ledger entry from raw cell texts; None if not a book/cancel row."""
    parsed = parse_reason(reason_text)
    if parsed is None:
        return None
    return {
        "txn_datetime": parse_txn_datetime(txn_text),
        "action": parsed["action"],
        "reservation_id": parsed["reservation_id"],
        "class_date": parsed["class_date"],
        "class_start_time": parsed["class_start_time"],
        "title": parsed["title"],
        "points": parse_points(change_text),
        "source": source,
    }


# ------------------------------------------------------------------- keys --

def class_key(e):
    return f"{e['class_date']}|{e['class_start_time']}|{normalize_title(e['title'])}"


def entry_key(e):
    """Identity of a ledger row: reservation id + action, else class key + action."""
    if e.get("reservation_id"):
        return f"rid:{e['reservation_id']}|{e['action']}"
    return f"cls:{class_key(e)}|{e['action']}"


# ------------------------------------------------------------ persistence --

def empty_ledger():
    return {"cursor": None, "entries": []}


def load_ledger(path=LEDGER_PATH):
    if not os.path.exists(path):
        return empty_ledger()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("cursor", None)
    data.setdefault("entries", [])
    return data


def save_ledger(path, ledger):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _sort_entries(entries):
    entries.sort(key=lambda e: (e["txn_datetime"], e.get("reservation_id") or ""))


def apply_new_entries(ledger, scraped):
    """Append-only merge by entry_key; advance the cursor. Returns number added."""
    known = {entry_key(e) for e in ledger["entries"]}
    added = 0
    for e in scraped:
        k = entry_key(e)
        if k in known:
            continue
        known.add(k)
        ledger["entries"].append(e)
        added += 1
    _sort_entries(ledger["entries"])
    if ledger["entries"]:
        newest = max(e["txn_datetime"] for e in ledger["entries"])
        if ledger["cursor"] is None or newest > ledger["cursor"]:
            ledger["cursor"] = newest
    return added


# ----------------------------------------------------------------- replay --

def replay(entries):
    """
    Fold the log into the set of currently active reservations.

    Active bookings are keyed by reservation_id when present, otherwise by
    class key (synthetic rows imported from events.json).  A real booking
    supersedes a synthetic one for the same class; a cancel removes by
    reservation_id, falling back to class key.
    """
    active = {}          # key -> entry
    by_class = {}        # class_key -> key currently holding that class
    for e in sorted(entries, key=lambda e: e["txn_datetime"]):
        ck = class_key(e)
        rid = e.get("reservation_id")
        if e["action"] == "book":
            key = f"rid:{rid}" if rid else f"cls:{ck}"
            prev = by_class.get(ck)
            if prev and prev != key and prev.startswith("cls:"):
                active.pop(prev, None)          # real booking supersedes synthetic
            active[key] = e
            by_class[ck] = key
        elif e["action"] == "cancel":
            key = f"rid:{rid}" if rid and f"rid:{rid}" in active else by_class.get(ck)
            if key and key in active:
                active.pop(key, None)
                if by_class.get(ck) == key:
                    by_class.pop(ck, None)
    return active


def active_to_events(active):
    """Active reservations -> calendar events (past ones included), sorted."""
    events = []
    for e in active.values():
        start = datetime.strptime(f"{e['class_date']} {e['class_start_time']}", "%Y-%m-%d %H:%M")
        end = start + timedelta(minutes=DEFAULT_DURATION_MIN)
        events.append({
            "date": e["class_date"],
            "start_time": e["class_start_time"],
            "end_time": end.strftime("%H:%M"),
            "title": normalize_title(e["title"]),
        })
    events.sort(key=lambda ev: (ev["date"], ev["start_time"], ev["title"]))
    return events


# ------------------------------------------------------------------ guard --

def assert_scrape_sane(ledger, scraped, passes_found, full_resync=False):
    """Fail loudly instead of silently producing an empty calendar."""
    if passes_found == 0:
        raise SystemExit("找不到任何有效方案，頁面結構或 selector 可能已變更；本次不寫入任何檔案。")
    if full_resync and ledger["entries"] and scraped:
        known = {entry_key(e) for e in ledger["entries"]}
        if not any(entry_key(e) in known for e in scraped):
            raise SystemExit("全量重讀結果與既有 ledger 完全無交集，疑似抓錯頁面；本次不寫入任何檔案。")
