"""plan/phase14_phrasing.csv names only sheets and columns that exist.

The phrasing reference is written by `digest.phrasing_catalog()` but nothing
regenerates it, so it drifted: by the PPG-grid PR it still listed the retired
`transactions` and `picks` sheets, "Number of transactions", "Transaction
skill" and a week-3 on-pace gate. This guard fails on the stale direction — a
row naming a sheet the build no longer writes, or a column that sheet no longer
has — which is stable across data refreshes (completeness is not asserted: which
columns rank can move with the data).

A column counts as current when the plan (plan/LOTG Plan - Sheet1.csv) lists it
for that sheet, or the committed export carries it (the generated per-opponent
and traded-with columns live only there).

Run: python tests/test_phrasing_reference.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PLAN_KEYS = {
    "Player-Week": "player_week", "Player-year": "player_year", "Player-all-time": "player_all_time",
    "team-week": "team_week", "team-year": "team_year", "team-all-time": "team_all_time",
    "league-week": "league_week", "league-year": "league_year", "league-all-time": "league_all_time",
    "add_drops": "add_drops", "player_additions": "player_additions", "trades": "trades",
    "non_rookie_picks": "non_rookie_picks", "rookie_picks": "rookie_picks",
}


def _current_columns() -> dict:
    sys.path.insert(0, str(_ROOT / "lib"))
    from lotg_support.plan import load_plan_catalog  # noqa: E402

    plan = load_plan_catalog(_ROOT / "plan" / "LOTG Plan - Sheet1.csv")
    cols = {sheet: set(plan.get(key, [])) for key, sheet in _PLAN_KEYS.items()}
    for sheet in cols:
        p = _ROOT / "exports" / f"{sheet}.csv"
        if p.exists():
            with p.open(newline="") as fh:
                cols[sheet] |= set(next(csv.reader(fh), []))
    return cols


def test_every_row_names_a_current_sheet_and_column():
    cols = _current_columns()
    with (_ROOT / "plan" / "phase14_phrasing.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "phase14_phrasing.csv is empty"
    bad_sheet = sorted({r["sheet"] for r in rows if r["sheet"] not in cols})
    assert not bad_sheet, f"rows name sheets the build no longer writes: {bad_sheet}"
    stale = sorted({(r["sheet"], r["stat"]) for r in rows if r["stat"] not in cols[r["sheet"]]})
    assert not stale, (f"{len(stale)} rows name columns their sheet no longer has — regenerate with "
                       f"`scripts/build_digest.py --phrasing-csv`: {stale[:10]}")
    print(f"  {len(rows)} rows, all current")


if __name__ == "__main__":
    test_every_row_names_a_current_sheet_and_column()
    print("ok")
