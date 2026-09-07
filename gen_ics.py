import hashlib
from datetime import datetime, timezone, timedelta

from icalendar import Calendar, Event

TZ = timezone(timedelta(hours=8))  # Asia/Taipei, no DST


def _stable_uid(e):
    key = f"{e['date']}|{e['start_time']}|{e['title']}"
    digest = hashlib.md5(key.encode('utf-8')).hexdigest()
    return f"{digest}@goodtime.17fit.com"


def build_calendar(events):
    cal = Calendar()
    cal.add('prodid', '-//My Calendar Product//mxm.dk//')
    cal.add('version', '2.0')
    cal.add('x-wr-calname', 'My Calendar')
    cal.add('x-wr-timezone', 'Asia/Taipei')

    stamp = datetime.now(timezone.utc)
    for e in events:
        event = Event()
        event.add('summary', e['title'])
        start_dt = datetime.strptime(f"{e['date']} {e['start_time']}", '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
        end_dt = datetime.strptime(f"{e['date']} {e['end_time']}", '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('dtstamp', stamp)
        event.add('uid', _stable_uid(e))
        cal.add_component(event)
    return cal


def build_ics(events, ics_path):
    """Rebuild the ICS file from scratch. UIDs are stable, so subscribers see updates, not duplicates."""
    with open(ics_path, 'wb') as f:
        f.write(build_calendar(events).to_ical())
    print(f"ICS 已重建：{ics_path}（{len(events)} 筆事件）")
