"""Max PF position pins: the build's ceiling agrees with Sleeper's own.

Sleeper keeps a season max-points total per roster (`rosters[].settings.ppts`),
computed with the position(s) each player was listed at that season. The build
computes `team_week."Max PF"` from Sleeper's current single label, so a player
Sleeper has since relabelled moves the ceiling. `MAX_PF_POSITION_PINS` records
the listings that mattered: Taysom Hill QB in 2021 and QB/TE from 2022,
Cordarrelle Patterson RB/WR in 2021. A player listed at several positions is
eligible at each. With them all 40 completed team-seasons (2021-2025)
reconcile: 38 match `ppts` to the cent, and the other two differ by exactly the
Sleeper-side errors in SLEEPER_SIDE_GAPS, where the build's lineup is legal and
Sleeper's frozen total is the one that is off.

The data test asserts against the snapshot only — Sleeper's numbers and the
build's own routine — so it holds before and after CI regenerates exports/.
`test_replay.test_ceiling_model_reproduces_the_built_max_pf` and
`test_draft_capital` tie the same routine to the shipped column.

Run: python tests/test_max_pf_pins.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support.lineup import compute_optimal_lineup  # noqa: E402
from lotg_support.position_pins import max_pf_positions  # noqa: E402

_HAVE_DATA = (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists()

HILL, PATTERSON = "4381", "1535"

# Team-seasons where Sleeper's `ppts` is itself wrong, with the exact gap
# (build minus Sleeper). Pinned to the cent, so any change on either side shows.
#   stevenb123 2024: Sleeper's `fpts` for the team and the opponent's
#     `fpts_against` are off by the same 1.00 — a stat correction to a starter
#     (week 6 or 13, the two meetings with Shmuel256) that landed after Sleeper
#     froze its season totals. Not a position.
#   LWebs53 2024: week 11, where Hill (41.52 on the bench, matching nflverse
#     under league scoring) sits in the optimum at TE, a legal slot for a QB/TE.
#     Sleeper's total is 3.54 lower: stale points or a one-week QB-only label.
#     Copying it would put Max PF below a lineup the team could have set.
SLEEPER_SIDE_GAPS = {(2024, "stevenb123"): 1.00, (2024, "LWebs53"): 3.54}


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_pin_lookup_by_season():
    assert max_pf_positions(HILL, 2021) == ("QB",)
    assert max_pf_positions(HILL, 2022) == ("QB", "TE")
    assert max_pf_positions(HILL, "2026") == ("QB", "TE")     # open-ended, string input
    assert max_pf_positions(PATTERSON, 2021) == ("RB", "WR")
    assert max_pf_positions(PATTERSON, 2022) is None          # RB-only from 2022
    assert max_pf_positions("no-such-player", 2021) is None


def test_pins_apply_only_with_a_week_and_dual_takes_the_better_slot():
    # As a TE Hill takes the TE slot and the real TE drops to FLEX; as a QB he
    # takes the superflex instead and the backup QB sits.
    pts = {HILL: 20.0, "qb": 30.0, "qb2": 10.0, "te": 5.0}
    pos = {HILL: "TE", "qb": "QB", "qb2": "QB", "te": "TE"}
    as_te = compute_optimal_lineup(pts, pos, 2021)
    assert as_te == 30.0 + 20.0 + 5.0 + 10.0    # QB, TE=Hill, FLEX=te, SF=qb2
    as_qb = compute_optimal_lineup(pts, pos, 2021, week=13)
    assert as_qb == 30.0 + 5.0 + 20.0           # QB-only in 2021: SF=Hill, qb2 sits
    # QB/TE from 2022: the better of the two.
    assert compute_optimal_lineup(pts, pos, 2022, week=13) == max(as_te, as_qb)


# ---------------------------------------------------------------------------
# Against the committed snapshot
# ---------------------------------------------------------------------------
def test_regular_season_max_pf_matches_sleeper_ppts():
    if not _HAVE_DATA:
        return _skip("no committed snapshot")
    positions = Q.players().positions()
    problems, checked = [], 0
    for season in Q.completed_seasons():
        meta = Q.season_meta(season)
        rosters_path = Q.snapshot_dir() / f"season_{season}" / "rosters.json"
        if not meta.has_snapshot or not rosters_path.exists():
            continue
        teams = Q.teams(season)
        built = {}
        for wk in Q.played_weeks(season):
            if wk >= meta.playoff_week_start:
                continue
            for rid, row in Q.week(season, wk).items():
                built[rid] = built.get(rid, 0.0) + compute_optimal_lineup(
                    {p: row.players_points.get(p, 0.0) for p in row.players},
                    positions, season, week=wk)
        for r in json.loads(rosters_path.read_text()):
            s = r.get("settings") or {}
            sleeper = float(s.get("ppts", 0)) + float(s.get("ppts_decimal", 0)) / 100
            rid = int(r["roster_id"])
            gap = round(built.get(rid, 0.0) - sleeper, 2)
            want = SLEEPER_SIDE_GAPS.get((season, teams.get(rid, "")), 0.0)
            checked += 1
            if abs(gap - want) > 0.005:
                problems.append(f"{season} {teams.get(rid, rid)}: build - Sleeper = {gap:+.2f}"
                                f" (expected {want:+.2f})")
    if not checked:
        return _skip("no completed season with a snapshot")
    assert not problems, problems


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  [FAIL] {name} — {exc}")
    sys.exit(1 if fails else 0)
