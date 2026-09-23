"""Every commissioner pick-trade row names a real trade by its COMPLETION time.

data/commissioner_pick_trades.csv injects off-platform pick legs into existing
trades, matched by the exact timestamp in `trade_completed_utc`. Trades are
dated by completion (Sleeper's status_updated; a trade sharing its completion
second with earlier-proposed ones one second later per such trade), so a row
still carrying a proposal time would silently match nothing and its pick would
vanish from the trade (it happened mid-branch: two 2023 Oliverwkw trades lost
their 2028 picks). 2020 rows name ESPN trades by their trade-email time, which
the snapshot does not hold; they are left to the build's unmatched-row log.

Runs off the committed Sleeper snapshot; skips without it.
Run: python tests/test_commissioner_overlay_match.py
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _completions() -> set:
    out = set()
    for sd in sorted(glob.glob(str(_ROOT / "exports/snapshot/season_*"))):
        trades = {}
        for f in glob.glob(sd + "/weeks/week_*/transactions.json"):
            for t in json.load(open(f)):
                if t.get("type") == "trade":
                    trades[t["transaction_id"]] = t
        by_sec = defaultdict(list)
        for t in trades.values():
            if t.get("status_updated"):
                by_sec[int(t["status_updated"]) // 1000].append(t)
        for ts in by_sec.values():
            ts.sort(key=lambda x: (int(x.get("created") or 0), str(x.get("transaction_id"))))
            for k, t in enumerate(ts):
                ms = int(t["status_updated"]) + 1000 * k
                out.add(dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    return out


def test_every_sleeper_overlay_row_names_a_completed_trade():
    if not glob.glob(str(_ROOT / "exports/snapshot/season_2021")):
        print("  SKIP — no Sleeper snapshot")
        return
    done = _completions()
    rows = [r for r in csv.reader(open(_ROOT / "data/commissioner_pick_trades.csv", encoding="utf-8"))
            if r and r[0].strip() and not r[0].lstrip().startswith("#")]
    assert rows[0][5] == "trade_completed_utc", rows[0]
    missing = [(r[0], r[5], r[6] if len(r) > 6 else "") for r in rows[1:] if int(r[5][:4]) >= 2021 and r[5] not in done]
    assert not missing, f"overlay rows matching no trade completion: {missing}"


if __name__ == "__main__":
    test_every_sleeper_overlay_row_names_a_completed_trade()
    print("ok: every Sleeper-season overlay row names a completed trade")
