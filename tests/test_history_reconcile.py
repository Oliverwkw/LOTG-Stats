"""Top team / Last team reconciliation (lotg_support.history).

Guards the fix for teleported players — a roster carryover with no transaction,
invisible to the tenure table — whose all-time Top/Last team used to be reported
from a stale early-career tenure instead of their real long-term roster. Daniel
Jones is the canonical case (shmuel256/stevenb123 2020 tenures, then
JacobRosenzweig 2021-2025 via teleport).

Run: python tests/test_history_reconcile.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support.history import (  # noqa: E402
    SECONDS_PER_WEEK,
    reconcile_last_team,
    reconcile_top_team,
)

DAY = 24 * 3600


def test_top_team_teleport_wins_via_pw_weeks():
    # Jones: tenure table only has the 2020 stints; his 85 weeks on Jacob live
    # only in player_week. Combined, Jacob must win.
    top = reconcile_top_team(
        pw_top_team="JacobRosenzweig",
        tenure_secs_by_team={"shmuel256": 40 * DAY, "stevenb123": 9 * DAY},
        pw_weeks_by_team={"JacobRosenzweig": 85, "shmuel256": 5, "stevenb123": 1},
    )
    assert top == "JacobRosenzweig", top


def test_top_team_subweek_tenure_still_counts():
    # A <1-week session that never produced a player_week row must still be able
    # to win — the whole reason the tenure signal exists. Team X (20 days tenure,
    # 0 pw weeks) beats team Y (1 pw week).
    top = reconcile_top_team(
        pw_top_team="Y",
        tenure_secs_by_team={"X": 20 * DAY},
        pw_weeks_by_team={"Y": 1},
    )
    assert top == "X", top


def test_top_team_agreement_unchanged():
    top = reconcile_top_team("A", {"A": 100 * DAY}, {"A": 14})
    assert top == "A"
    # No signal at all -> pw fallback.
    assert reconcile_top_team("A", None, None) == "A"


def test_last_team_stale_tenure_loses_to_pw():
    # Jones: last tenure event is 2020 (stevenb123); last rostered season is 2025
    # (Jacob). The stale tenure must not win.
    last = reconcile_last_team(
        pw_last_team="JacobRosenzweig",
        pw_last_fy=2025,
        tenure_last_fy=2020,
        tenure_last_team="stevenb123",
    )
    assert last == "JacobRosenzweig", last


def test_last_team_recent_tenure_wins():
    # A same/later-FY tenure event (e.g. an offseason move) SHOULD win — that's
    # the case the tenure override was built for.
    assert reconcile_last_team("A", 2024, 2025, "B") == "B"
    assert reconcile_last_team("A", 2024, 2024, "B") == "B"
    # No tenure event -> pw fallback.
    assert reconcile_last_team("A", 2024, None, None) == "A"


def test_week_scale_constant():
    assert SECONDS_PER_WEEK == 7 * 24 * 3600


if __name__ == "__main__":
    for fn in (
        test_top_team_teleport_wins_via_pw_weeks,
        test_top_team_subweek_tenure_still_counts,
        test_top_team_agreement_unchanged,
        test_last_team_stale_tenure_loses_to_pw,
        test_last_team_recent_tenure_wins,
        test_week_scale_constant,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all history-reconcile checks passed")
