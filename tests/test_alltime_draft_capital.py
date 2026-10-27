"""team_all_time 'All-time draft capital' counts every rookie pick exactly once.

It is the round-weighted value of the rookie picks a team has made plus the
future picks it holds now [per user, 2026-10-27], replacing the sum of
season-end 'Future draft capital', which counted a pick once for every season
it was held. rookie_picks lists both halves — a made pick under the team that
made it, a future pick ("1.??") under its holder today — so the column must
equal the weights summed over each team's rookie_picks rows up to the 5-draft
horizon, and the league total must equal every pick's weight once.

Run: python tests/test_alltime_draft_capital.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_EXPORTS = _ROOT / "exports"
_WEIGHTS = {1: 0.25, 2: 0.09, 3: 0.03, 4: 0.01}
_HORIZON = 5


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _rookie_pick_weights():
    rp = pd.read_csv(_EXPORTS / "rookie_picks.csv", low_memory=False)
    num = rp["Number"].astype(str).str.strip()
    made = num.str.match(r"^\d+\.\d+$") & ~rp["Player Picked"].astype(str).str.strip().isin(("", "Unknown", "nan"))
    last_held = int(pd.to_numeric(rp.loc[made, "Year"], errors="coerce").max())
    rp = rp[pd.to_numeric(rp["Year"], errors="coerce") <= last_held + _HORIZON]
    rnd = rp["Number"].astype(str).str.extract(r"^(\d+)")[0].astype(int)
    rnd = rnd.where(rnd != 5, 4)  # a 5.0X FAAB pick counts as a 4th (2.09 already reads as round 2)
    return rp.assign(_w=rnd.map(_WEIGHTS).fillna(0.0))


def check_each_team_is_its_made_plus_held_picks() -> bool:
    if not (_EXPORTS / "team_all_time.csv").exists() or not (_EXPORTS / "rookie_picks.csv").exists():
        return _skip("exports/ absent")
    ta = pd.read_csv(_EXPORTS / "team_all_time.csv")
    if "All-time draft capital" not in ta.columns:
        return _skip("exports/ predate 'All-time draft capital'")
    want = _rookie_pick_weights().groupby("Team")["_w"].sum()
    ok = True
    for team, got in zip(ta["Team"], pd.to_numeric(ta["All-time draft capital"], errors="coerce")):
        exp = float(want.get(team, 0.0))
        good = abs(float(got) - exp) < 1e-6
        ok &= good
        print(f"  {'ok ' if good else 'BAD'} {team}: {got:.4f} vs rookie_picks {exp:.4f}")
    return ok


def check_the_league_total_counts_each_pick_once() -> bool:
    if not (_EXPORTS / "team_all_time.csv").exists() or not (_EXPORTS / "rookie_picks.csv").exists():
        return _skip("exports/ absent")
    ta = pd.read_csv(_EXPORTS / "team_all_time.csv")
    if "All-time draft capital" not in ta.columns:
        return _skip("exports/ predate 'All-time draft capital'")
    got = float(pd.to_numeric(ta["All-time draft capital"], errors="coerce").sum())
    exp = float(_rookie_pick_weights()["_w"].sum())
    print(f"  league total {got:.4f} vs every pick once {exp:.4f}")
    return abs(got - exp) < 1e-6


def run_all() -> bool:
    all_ok = True
    for t in (check_each_team_is_its_made_plus_held_picks,
              check_the_league_total_counts_each_pick_once):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_alltime_draft_capital():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
