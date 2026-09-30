"""add_drops' post-drop points hold the dropped player's points as scored.

"Dropped avg points", its position-adjusted twin and "Dropped total points"
were stored NEGATED, so "highest" meant the best drop and the digest had to say
"(negated)". They now hold the points the dropped player scored in his next 17
games after the drop — lowest = best drop (a player who went negative, then one
who never played again at 0) — and the email names them "Points / PPG in next
17 games after drop".

Checks:
* last week's snapshot, written negated, is read in today's sign (each place
  negated and moved to the other end) exactly once, and new snapshots are stamped
  so they are never flipped;
* the 5-week rule holds on the new sign: a drop under five NFL weeks old may not
  stand on the LOW (best-drop) end, where the negated column let it stand on the
  high end the week it was made (Chimere Dike, dropped 2026-09-07, was 2nd-best
  drop ever after three weeks);
* the exports hold the un-negated values (data-dependent; skips without exports/).

Run: python tests/test_dropped_points_sign.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import digest as D  # noqa: E402

_EXPORTS = _ROOT / "exports"
_COLS = ("Dropped avg points", "Dropped avg points adjusted by position", "Dropped total points")


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _weeks(**season_weeks):
    """team_week with Year/Week only: _weeks(y2025=17, y2026=3)."""
    yrs, wks = [], []
    for k, n in season_weeks.items():
        yrs += [int(k[1:])] * n
        wks += list(range(1, n + 1))
    return pd.DataFrame({"Year": yrs, "Week": wks})


def _place(column, end, rank, key, value, sheet="add_drops"):
    return {"sheet": sheet, "column": column, "end": end, "rank": rank,
            "key": key, "label": key, "value": value}


def check_old_snapshot_is_read_in_the_new_sign():
    old = {"meta": {"captured_at": "2026-09-29T19:08:20+00:00"}, "event_board": [
        _place("Dropped total points", "high", 1, "toney", 2.4),
        _place("Dropped total points", "low", 1, "gesicki", -343.6),
        _place("Dropped avg points", "high", 1, "never-again", 0.0),
        _place("Net points", "high", 1, "untouched", 50.0),
        _place("Dropped total points", "high", 1, "other-sheet", 9.0, sheet="trades"),
    ]}
    m = D.migrate_snapshot_signs(copy.deepcopy(old))
    got = {(e["sheet"], e["key"]): (e["end"], e["value"]) for e in m["event_board"]}
    ok = _ok("the best drop moves to the low end, as scored",
             got[("add_drops", "toney")] == ("low", -2.4), got[("add_drops", "toney")])
    ok &= _ok("the worst drop moves to the high end",
              got[("add_drops", "gesicki")] == ("high", 343.6), got[("add_drops", "gesicki")])
    ok &= _ok("a 0 stays 0 (not -0.0)", got[("add_drops", "never-again")] == ("low", 0.0)
              and str(got[("add_drops", "never-again")][1]) == "0.0", got[("add_drops", "never-again")])
    ok &= _ok("another add_drops column is untouched",
              got[("add_drops", "untouched")] == ("high", 50.0))
    ok &= _ok("the same name on another sheet is untouched",
              got[("trades", "other-sheet")] == ("high", 9.0))
    ok &= _ok("the migrated snapshot is stamped", m["meta"].get("dropped_points_sign") == "raw", m["meta"])
    again = D.migrate_snapshot_signs(copy.deepcopy(m))
    ok &= _ok("migrating twice is a no-op", again == m)
    return ok


def check_new_snapshots_are_stamped():
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026], "PF": [100.0]})
    snap = D.build_snapshot(pd.DataFrame({"Player": ["p"], "Points": [1.0]}),
                            pd.DataFrame({"Team": ["A"], "PF": [100.0]}), ty,
                            pd.DataFrame({"Year": [2026], "Week": [1], "Team": ["A"]}))
    ok = _ok("build_snapshot stamps the sign", snap["meta"].get("dropped_points_sign") == "raw", snap["meta"])
    snap["event_board"] = [_place("Dropped total points", "low", 1, "toney", -2.4)]
    ok &= _ok("a stamped snapshot is never flipped",
              D.migrate_snapshot_signs(copy.deepcopy(snap)) == snap)
    return ok


def _drops(young_date):
    rows = [("T1", "2021-10-05", 2021, 120.0, 7.0), ("T2", "2022-10-05", 2022, 80.0, 5.0),
            ("T3", "2023-10-05", 2023, 40.0, 3.0), ("T4", "2024-10-05", 2024, 10.0, 1.0),
            ("T5", "2025-10-05", 2025, 0.0, 0.0), ("New", young_date, 2026, -2.0, -0.7)]
    return pd.DataFrame(rows, columns=["Team", "Date", "Season", "Dropped total points",
                                       "Dropped avg points"]).assign(
        **{"Player Added": "", "Player Dropped": "Somebody"})


def check_young_drop_waits_for_the_best_drop_end():
    ad = _drops("2026-09-16")                       # a week-2 drop (Tue-Mon weeks)
    young = {"add_drops": ad, "team_week": _weeks(y2025=17, y2026=3)}
    new = {(h.column, h.end) for h in D.board_highlights(ad, "add_drops", window=3,
                                                         gate=D.BoardGate(young))
           if h.label.startswith("New's")}
    ok = _ok("under five weeks: not the lowest (best-drop) Points in next 17 games",
             ("Dropped total points", "low") not in new, new)
    ok &= _ok("nor the lowest PPG", ("Dropped avg points", "low") not in new, new)
    aged = {"add_drops": ad, "team_week": _weeks(y2025=17, y2026=6)}   # weeks 2-6 played
    new2 = {(h.column, h.end) for h in D.board_highlights(ad, "add_drops", window=3,
                                                          gate=D.BoardGate(aged))
            if h.label.startswith("New's")}
    ok &= _ok("five NFL weeks after the drop, it stands as the best drop",
              ("Dropped total points", "low") in new2 and ("Dropped avg points", "low") in new2, new2)
    ok &= _ok("the email names it plainly",
              D.display_column("Dropped total points", "add_drops") == "Points in next 17 games after drop"
              and "negated" not in D.display_column("Dropped avg points", "add_drops"),
              D.display_column("Dropped avg points", "add_drops"))
    return ok


def check_exports_hold_points_as_scored():
    p = _EXPORTS / "add_drops.csv"
    if not p.exists():
        print("  [SKIP] exports/ absent")
        return True
    ad = pd.read_csv(p, dtype=str, keep_default_na=False)
    ok = True
    for c in _COLS:
        v = pd.to_numeric(ad[c], errors="coerce").dropna()
        v = v[v != 0]
        share = float((v > 0).mean()) if len(v) else 0.0
        # A dropped player's next games are overwhelmingly positive; negated,
        # this share was ~0. A handful of fumble-only runs go negative.
        ok &= _ok(f"{c}: points as scored (mostly positive)", share > 0.9,
                  f"{share:.1%} of {len(v)} non-zero values positive")
    return ok


def run_all():
    ok = True
    for fn in (check_old_snapshot_is_read_in_the_new_sign, check_new_snapshots_are_stamped,
               check_young_drop_waits_for_the_best_drop_end, check_exports_hold_points_as_scored):
        print(f"\n{fn.__name__}:")
        ok &= fn()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_dropped_points_sign():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
