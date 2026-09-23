"""No player is ever on a team without a player_additions row that put him there.

User rule (2026-09-23): every week a player sits on a team's roster
(player_week) falls inside one of that team's tenures for him on
player_additions (Date .. Date dropped/traded). A week counts as inside when it
overlaps the tenure: its first game is before the exit day, and the pickup was
no later than the Wednesday after its last game (Sleeper lists a Tuesday or
Wednesday-waiver pickup on the week that just ended).

Run 531 had 166 team-weeks outside every tenure, in two families: moves across
the 2020 ESPN -> 2021 Sleeper seam whose synthesized arrival was dated the day
before a drop years later (Darrell Henderson, Devin Singletary, Kenyan Drake,
Jonnu Smith), and 2024 trades undone off the log (K.J. Osborn, Hunter Henry).

Data-dependent; skips cleanly without exports/.
Run: python tests/test_player_history_coverage.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_EXPORTS = _ROOT / "exports"


def _week_bounds():
    """(season, week) -> (first game day, last game day), from the schedule the
    build caches; None when it is absent (the check then uses Thu..Mon)."""
    g = _ROOT / ".cache" / "nfldata_games.csv"
    if not g.exists():
        return None
    df = pd.read_csv(g, low_memory=False, usecols=["season", "week", "game_type", "gameday"])
    df = df[df["game_type"] == "REG"]
    grp = df.groupby(["season", "week"])["gameday"]
    return {k: (str(a)[:10], str(b)[:10]) for (k, a), (_, b) in zip(grp.min().items(), grp.max().items())}


def _uncovered():
    pw = pd.read_csv(_EXPORTS / "player_week.csv", dtype=str, keep_default_na=False,
                     usecols=["Team", "Player", "Year", "Week"])
    pa = pd.read_csv(_EXPORTS / "player_additions.csv", dtype=str, keep_default_na=False)
    ten = defaultdict(list)
    for t, p, d, dr in zip(pa["Team"], pa["Player"], pa["Date"], pa["Date dropped/traded"]):
        ten[(t, p)].append((d[:10], (dr or "9999")[:10]))
    bounds = _week_bounds()
    out = []
    # usecols keeps the FILE's column order; name the order explicitly
    for t, p, y, w in pw[["Team", "Player", "Year", "Week"]].drop_duplicates().itertuples(index=False):
        y, w = int(y), int(w)
        if bounds and (y, w) in bounds:
            sd, ed = bounds[(y, w)]
        else:       # fallback: the Thursday of week 1 is the first Thursday of September
            first_thu = date(y, 9, 1) + timedelta(days=(3 - date(y, 9, 1).weekday()) % 7)
            sd = (first_thu + timedelta(weeks=w - 1)).isoformat()
            ed = (first_thu + timedelta(weeks=w - 1, days=4)).isoformat()
        # Sleeper lists a Tuesday or Wednesday pickup (the 3am ET waiver run) on
        # the week that just ended: Dylan Laube (LWebs53, Tue 2024-10-08) shows
        # on week 5, Nico Collins (LWebs53, Wed 2022-10-19 03:04) on week 6. A
        # tenure starting by that Wednesday covers the week.
        wed = (date.fromisoformat(ed) + timedelta(days=2)).isoformat()
        if not any(s0 <= wed and e0 > sd for s0, e0 in ten.get((t, p), [])):
            out.append((t, p, y, w))
    return out


def test_every_rostered_week_has_a_player_additions_tenure():
    if not ((_EXPORTS / "player_week.csv").exists() and (_EXPORTS / "player_additions.csv").exists()):
        print("  SKIP — exports/ absent")
        return
    bad = _uncovered()
    seasons = sorted({(t, p, y) for t, p, y, _ in bad})
    assert not bad, (f"{len(bad)} rostered team-weeks with no player_additions tenure "
                     f"({len(seasons)} team/player/seasons), e.g. {seasons[:8]}")


if __name__ == "__main__":
    test_every_rostered_week_has_a_player_additions_tenure()
    print("ok: every rostered week sits inside a player_additions tenure")
