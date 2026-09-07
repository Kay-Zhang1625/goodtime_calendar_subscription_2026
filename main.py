import argparse

from gen_ics import build_ics
from ledger import (
    LEDGER_PATH, active_to_events, apply_new_entries, assert_scrape_sane,
    load_ledger, replay, save_ledger,
)
from spider_goodtime import PASSWORD, USERNAME, create_driver, fetch_pass_ledger, login

ICS_FILE = "mycalendar.ics"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full-resync", action="store_true",
                    help="ignore the cursor and re-read every row of every active pass")
    args = ap.parse_args()

    ledger = load_ledger(LEDGER_PATH)
    since = None if args.full_resync else ledger["cursor"]

    wd = create_driver()
    try:
        login(wd, USERNAME, PASSWORD)
        scraped, passes_found = fetch_pass_ledger(wd, since=since)
    finally:
        wd.quit()

    assert_scrape_sane(ledger, scraped, passes_found, full_resync=args.full_resync)

    n_new = apply_new_entries(ledger, scraped)
    save_ledger(LEDGER_PATH, ledger)

    events = active_to_events(replay(ledger["entries"]))
    build_ics(events, ICS_FILE)
    print(f"新增 {n_new} 筆 ledger 紀錄，ICS 共 {len(events)} 筆事件，cursor = {ledger['cursor']}")


if __name__ == "__main__":
    main()
