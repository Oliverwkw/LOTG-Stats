"""lotg_support.position_factor: each season's own position baseline, or the
previous season's until the season has played MIN_WEEKS weeks.

Synthetic data: the offline harness only reaches completed seasons, so the
week-5 switch is pinned here. Run: python tests/test_position_factor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from lotg_support import digest as D  # noqa: E402
from lotg_support import position_factor as PF  # noqa: E402


def _season(year, weeks, qb, te):
    """Starter rows: one QB and one TE per week, scoring `qb` / `te`."""
    rows = []
    for w in range(1, weeks + 1):
        rows.append({"Year": year, "Week": w, "Position": "QB", "Points": qb})
        rows.append({"Year": year, "Week": w, "Position": "TE", "Points": te})
    return rows


def _frame(*seasons):
    return pd.DataFrame([r for s in seasons for r in s])


def test_min_weeks_matches_the_email_gate():
    assert PF.MIN_WEEKS == D.MIN_YEARLY_WEEK, (
        "the position baseline must switch the week the email starts showing a "
        "season's averages")


def test_a_complete_season_uses_its_own_baseline():
    b = PF.season_baselines(_frame(_season(2024, 17, 30.0, 10.0), _season(2025, 17, 20.0, 20.0)))
    assert PF.factor(b, 2024, "QB") == (20.0 / 30.0)
    assert PF.factor(b, 2024, "TE") == (20.0 / 10.0)
    assert PF.factor(b, 2025, "QB") == 1.0          # 2025: QB avg == league avg
    assert b[2] == {2024: 2024, 2025: 2025}


def test_weeks_1_to_4_borrow_the_previous_season_then_switch_at_week_5():
    prior = _season(2025, 17, 30.0, 10.0)            # QB factor 2/3, TE 2
    for played in range(1, PF.MIN_WEEKS):
        b = PF.season_baselines(_frame(prior, _season(2026, played, 10.0, 30.0)))
        assert b[2][2026] == 2025, f"{played} week(s) in: should still use 2025"
        assert PF.factor(b, 2026, "QB") == PF.factor(b, 2025, "QB")
    b = PF.season_baselines(_frame(prior, _season(2026, PF.MIN_WEEKS, 10.0, 30.0)))
    assert b[2][2026] == 2026, "week 5 in: 2026 switches to its own baseline"
    assert PF.factor(b, 2026, "QB") == (20.0 / 10.0)   # retroactive for weeks 1-4 too


def test_a_season_not_yet_kicked_off_uses_the_latest():
    b = PF.season_baselines(_frame(_season(2025, 17, 30.0, 10.0)))
    assert PF.factor(b, 2026, "TE") == PF.factor(b, 2025, "TE") == 2.0
    # ...but a season BEFORE the first on record has no baseline.
    assert PF.factor(b, 2019, "TE") == 1.0


def test_the_first_season_on_record_keeps_its_own_even_when_short():
    b = PF.season_baselines(_frame(_season(2026, 2, 10.0, 30.0)))
    assert b[2][2026] == 2026 and PF.factor(b, 2026, "QB") == 2.0


def test_unknown_position_or_season_is_neutral():
    b = PF.season_baselines(_frame(_season(2025, 17, 30.0, 10.0)))
    assert PF.factor(b, 2025, "K") == 1.0
    assert PF.factor(b, None, "QB") == 1.0
    assert PF.factor(PF.season_baselines(pd.DataFrame()), 2025, "QB") == 1.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("ok")
