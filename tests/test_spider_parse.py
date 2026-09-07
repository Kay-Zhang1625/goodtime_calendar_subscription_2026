import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spider_goodtime import parse_ledger_tables  # noqa: E402

HTML = """
<table><thead><tr><th>Date</th><th>Reason</th><th>Change</th><th>User</th></tr></thead>
<tbody>
<tr><td>2026-09-04 21:05:20</td><td>預約課程: 2026-09-15 19:20:00【大安】空中串連 仙女養成班 (4好幣)｜進階 <small>&lt;22471602&gt;</small></td><td>-4 Point</td><td>張某某</td></tr>
<tr><td>2026-08-26 00:37:52</td><td>取消課程:2026-09-01 19:10:00 【民權】空中瑜伽 紮實基本功 （4好幣）＊ <small>&lt;22337794&gt;</small></td><td>+4 Point</td><td>張某某</td></tr>
<tr><td>2026-06-28 10:00:00</td><td>購買方案: 【全區通用】168 好幣</td><td>+168 Point</td><td>張某某</td></tr>
</tbody></table>
<table><tr><td>Remaining Point</td><td>58 Point</td></tr></table>
"""


def test_parse_ledger_tables_maps_by_header_and_skips_user_and_unknown_rows(capsys):
    entries, n_tables, oldest = parse_ledger_tables(HTML)
    assert n_tables == 1
    assert oldest == "2026-06-28 10:00:00"
    assert [e["action"] for e in entries] == ["book", "cancel"]
    assert entries[0]["reservation_id"] == "22471602"
    assert entries[0]["title"] == "【大安】空中串連 仙女養成班 (4好幣)｜進階"
    assert entries[1]["reservation_id"] == "22337794"
    assert all("張" not in str(v) for e in entries for v in e.values())
    out = capsys.readouterr().out
    assert "略過非預約/取消紀錄 ×1" in out
    assert "購買方案" not in out                # skipped rows are counted, never echoed
    assert "張" not in out


def test_parse_ledger_tables_since_cutoff():
    entries, _, oldest = parse_ledger_tables(HTML, since="2026-09-01 00:00:00")
    assert [e["reservation_id"] for e in entries] == ["22471602"]
    assert oldest == "2026-06-28 10:00:00"   # still reported so the caller can stop paging
