"""2026+ two-week-final playoff rule (src/lotg.py pure helpers).

From 2026 the fantasy playoffs open with a one-week Semifinal (week 15, as in
2020) and close with a TWO-week Final: weeks 16 & 17 are one combined round for
the championship and every other bracket, decided by combined points-for. Earlier
seasons keep their one-week final (2020 also starts week 15 but its final is
week 16 only).

These guard the pure decision helpers that gate that behavior:
  * _finals_weeks       -> which week(s) form the final round
  * _matchup_stage      -> SEMIS / FINALS / None per week
  * _is_second_finals_week -> the week-17 leg that additive win stats skip

Run: python tests/test_two_week_final.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

from lotg import (  # noqa: E402
    FIRST_TWO_WEEK_FINAL_SEASON,
    _finals_weeks,
    _is_second_finals_week,
    _matchup_stage,
)


def test_constant_is_2026():
    assert FIRST_TWO_WEEK_FINAL_SEASON == 2026


def test_finals_weeks_pre_2026_single_week():
    # 2021-2025: playoff_start 16 -> single finals week 17.
    assert _finals_weeks(16, 2025) == [17]
    # 2020: playoff_start 15 -> single finals week 16 (NOT two weeks).
    assert _finals_weeks(15, 2020) == [16]


def test_finals_weeks_2026_two_weeks():
    # 2026+: playoff_start 15 -> finals weeks 16 & 17.
    assert _finals_weeks(15, 2026) == [16, 17]
    assert _finals_weeks(15, 2027) == [16, 17]


def test_finals_weeks_no_playoff_start():
    assert _finals_weeks(None, 2026) == []
    assert _finals_weeks(0, 2026) == []


def test_matchup_stage_2026_three_playoff_weeks():
    ps = 15
    assert _matchup_stage(14, ps, 2026) is None          # regular season
    assert _matchup_stage(15, ps, 2026) == "SEMIS"        # semifinal
    assert _matchup_stage(16, ps, 2026) == "FINALS"       # final leg 1
    assert _matchup_stage(17, ps, 2026) == "FINALS"       # final leg 2
    assert _matchup_stage(18, ps, 2026) is None


def test_matchup_stage_2020_single_week_final_unchanged():
    # 2020 also starts week 15, but week 17 is NOT a finals week.
    ps = 15
    assert _matchup_stage(15, ps, 2020) == "SEMIS"
    assert _matchup_stage(16, ps, 2020) == "FINALS"
    assert _matchup_stage(17, ps, 2020) is None


def test_matchup_stage_2025_unchanged():
    ps = 16
    assert _matchup_stage(15, ps, 2025) is None
    assert _matchup_stage(16, ps, 2025) == "SEMIS"
    assert _matchup_stage(17, ps, 2025) == "FINALS"
    assert _matchup_stage(18, ps, 2025) is None


def test_second_finals_week_only_2026_week17():
    ps_by = {2020: 15, 2025: 16, 2026: 15, 2027: 15}
    # 2026 week 17 is the de-dup leg.
    assert _is_second_finals_week(2026, 17, ps_by) is True
    assert _is_second_finals_week(2027, 17, ps_by) is True
    # Week 16 (first finals leg) is NOT skipped.
    assert _is_second_finals_week(2026, 16, ps_by) is False
    # 2020 week 16 is its (single) final — not a second leg.
    assert _is_second_finals_week(2020, 16, ps_by) is False
    assert _is_second_finals_week(2020, 17, ps_by) is False
    # 2025 week 17 is its single-week final — not a two-week second leg.
    assert _is_second_finals_week(2025, 17, ps_by) is False
    # Unknown season / bad input.
    assert _is_second_finals_week(2099, 17, ps_by) is False
    assert _is_second_finals_week(None, 17, ps_by) is False


if __name__ == "__main__":
    for fn in (
        test_constant_is_2026,
        test_finals_weeks_pre_2026_single_week,
        test_finals_weeks_2026_two_weeks,
        test_finals_weeks_no_playoff_start,
        test_matchup_stage_2026_three_playoff_weeks,
        test_matchup_stage_2020_single_week_final_unchanged,
        test_matchup_stage_2025_unchanged,
        test_second_finals_week_only_2026_week17,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all two-week-final checks passed")
