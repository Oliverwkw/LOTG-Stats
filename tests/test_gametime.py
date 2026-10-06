"""Guards for `lotg_support.gametime` — player_week "Game slot" and the team_week
margins / comebacks entering SNF, Monday and the matchup's last game.

The synthetic checks pin the rules [per user, 2026-10-05]: the semifinal +5
counts toward every margin, a comeback is measured against the opponent's
FINAL score (so a team ahead going in can still have one), 2020's Tuesday /
Wednesday makeups are part of Monday, and "last game" is N/A when both sides
were done by Sunday afternoon. The data checks run the same functions over the
committed exports and the cached schedule, completed seasons only, and — once a
build has written the columns — require the export to equal the recompute.

Run: python tests/test_gametime.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import gametime as G  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_week.csv").exists()
_HAVE_SCHEDULE = (_ROOT / ".cache" / "nfldata_games.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _games(rows):
    return pd.DataFrame(rows, columns=["season", "week", "game_type", "gameday", "gametime",
                                       "away_team", "home_team"])


# A week with every kind of slot: Thursday, a London morning game, 1 pm, 4 pm,
# SNF, a Monday doubleheader, and a Tuesday makeup.
_WEEK = _games([
    (2020, 5, "REG", "2020-10-08", "20:20", "TB", "CHI"),
    (2020, 5, "REG", "2020-10-11", "09:30", "NYG", "DAL"),
    (2020, 5, "REG", "2020-10-11", "13:00", "MIA", "SF"),
    (2020, 5, "REG", "2020-10-11", "16:25", "IND", "CLE"),
    (2020, 5, "REG", "2020-10-11", "20:20", "MIN", "SEA"),
    (2020, 5, "REG", "2020-10-12", "19:05", "LAC", "NO"),
    (2020, 5, "REG", "2020-10-12", "20:50", "ATL", "GB"),
    (2020, 5, "REG", "2020-10-13", "19:00", "BUF", "TEN"),
])


def test_game_slots():
    s = G.load_schedule(_WEEK)
    want = {"CHI": "Thursday", "DAL": "Sunday morning", "SF": "Sunday early", "CLE": "Sunday late",
            "SEA": "SNF", "NO": "MNF", "GB": "MNF", "TEN": "Tuesday", "KC": "Bye"}
    for team, slot in want.items():
        assert G.player_slot(s, 2020, 5, team) == slot, (team, G.player_slot(s, 2020, 5, team))
    assert G.player_slot(s, 2020, 5, "NFL") == G.NA
    # a Christmas Wednesday before Sunday is a Wednesday, not a Monday stage
    xmas = G.load_schedule(_games([(2024, 17, "REG", "2024-12-25", "13:00", "KC", "PIT"),
                                   (2024, 17, "REG", "2024-12-29", "13:00", "MIA", "CLE")]))
    assert G.player_slot(xmas, 2024, 17, "PIT") == "Wednesday"
    assert xmas.stage_start(2024, 17, "Monday") is None


def test_stage_starts():
    s = G.load_schedule(_WEEK)
    assert s.stage_start(2020, 5, "SNF") == datetime(2020, 10, 11, 20, 20)
    assert s.stage_start(2020, 5, "Monday") == datetime(2020, 10, 12, 19, 5)
    assert s.stage_start(2020, 5, "Sunday late") == datetime(2020, 10, 11, 16, 25)
    assert s.stage_start(2020, 6, "SNF") is None


def test_struck_bills_bengals_game_is_monday_night():
    s = G.load_schedule(_games([(2022, 17, "REG", "2023-01-01", "13:00", "NE", "MIA")]))
    assert G.player_slot(s, 2022, 17, "BUF") == "MNF"
    assert G.player_slot(s, 2022, 17, "CIN") == "MNF"
    assert s.stage_start(2022, 17, "Monday") == datetime(2023, 1, 2, 20, 30)
    # put back once, and only where it is missing
    g = G.restore_struck_games(_games([(2022, 17, "REG", "2023-01-01", "13:00", "NE", "MIA")]))
    assert len(g) == 2 and len(G.restore_struck_games(g)) == 2


def _tw(rows):
    return pd.DataFrame(rows, columns=["Team", "Year", "Week", "Week Name", "Opponent", "Win?",
                                       "PF", "Points against"])


def _pw(rows):
    return pd.DataFrame(rows, columns=["Team", "Year", "Week", "Starter/Bench", "NFL team", "Points"])


def test_margins_and_comebacks():
    s = G.load_schedule(_WEEK)
    # A: 60 Sunday early, 10 Tuesday (a makeup: Monday stage), +5 semifinal bonus -> PF 75.
    # B: 50 Sunday early, 20 SNF, 1 on MNF                                        -> PF 71.
    tw = _tw([("A", 2020, 5, "Semifinal", "B", True, 75.0, 71.0),
              ("B", 2020, 5, "Semifinal", "A", False, 71.0, 75.0)])
    pw = _pw([("A", 2020, 5, "Starter", "SF", 60.0), ("A", 2020, 5, "Starter", "TEN", 10.0),
              ("A", 2020, 5, "Bench", "SEA", 99.0),
              ("B", 2020, 5, "Starter", "SF", 50.0), ("B", 2020, 5, "Starter", "SEA", 20.0),
              ("B", 2020, 5, "Starter", "NO", 1.0)])
    c = G.team_week_columns(tw, pw, s).set_index("Team")
    a, b = c.loc["A"], c.loc["B"]
    # entering SNF: A 65 (60 + the bonus) v B 50
    assert a["Margin entering SNF"] == 15.0 and b["Margin entering SNF"] == -15.0
    # entering Monday: A 65 v B 70
    assert a["Margin entering Monday"] == -5.0
    # A was AHEAD entering SNF, but B's final (71) was above A's 65: still a comeback, of 6
    assert a["Down entering SNF comeback (points overcome)"] == 6.0
    assert a["Down entering SNF comeback (margin overcome)"] == G.NA   # ahead at the time
    assert a["Down entering SNF comeback (% of points going in)"] == round(6 / 65 * 100, 1)
    assert a["Down entering SNF comeback (% of opponent's final)"] == round(6 / 71 * 100, 1)
    assert a["Down entering Monday comeback (points overcome)"] == 6.0
    assert a["Down entering Monday comeback (margin overcome)"] == 5.0   # 65 v 70 at the time
    # per player left: A had one starter (Tuesday's) still to play at both stages
    assert a["Down entering SNF comeback (per player left)"] == 6.0
    assert a["Down entering Monday comeback (per player left)"] == 6.0
    # last game = Tuesday's (A's makeup) — the latest kickoff with a starter in it
    assert a["Margin entering last game"] == round(65 - 71, 2)
    assert a["Down entering last game comeback (points overcome)"] == 6.0
    assert a["Down entering last game comeback (margin overcome)"] == 6.0
    # the loser never has a comeback
    for col in G.COMEBACK_COLUMNS["SNF"] + G.COMEBACK_COLUMNS["Monday"]:
        assert b[col] == G.NA, col


def test_last_game_needs_sunday_night_or_later():
    s = G.load_schedule(_WEEK)
    tw = _tw([("A", 2020, 5, "Week 5", "B", True, 30.0, 20.0),
              ("B", 2020, 5, "Week 5", "A", False, 20.0, 30.0)])
    pw = _pw([("A", 2020, 5, "Starter", "CLE", 30.0), ("B", 2020, 5, "Starter", "SF", 20.0)])
    c = G.team_week_columns(tw, pw, s).set_index("Team")
    assert c.loc["A", "Margin entering last game"] == G.NA
    assert c.loc["A", "Down entering last game comeback (points overcome)"] == G.NA
    # SNF / Monday are league-wide: they exist although neither side played in them
    assert c.loc["A", "Margin entering SNF"] == 10.0 and c.loc["A", "Margin entering Monday"] == 10.0
    assert c.loc["A", "Down entering SNF comeback (points overcome)"] == G.NA   # never trailed the final
    assert c.loc["A", "Down entering SNF comeback (margin overcome)"] == G.NA


# --------------------------------------------------------------------------- #
def _data():
    tw, pw = Q.load_sheet("team_week"), Q.load_sheet("player_week")
    done = set(Q.completed_seasons())
    tw = tw[Q.numeric(tw, "Year").isin(done)]
    pw = pw[Q.numeric(pw, "Year").isin(done)]
    return tw, pw, G.load_schedule(Q.schedule())


def test_every_scoring_starter_has_a_game():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE):
        return _skip("no exports or schedule cache")
    _tw_, pw, s = _data()
    st = pw[pw["Starter/Bench"].astype(str) == "Starter"]
    slot = [G.player_slot(s, y, w, t) for y, w, t in zip(st["Year"], st["Week"], st["NFL team"])]
    bad = st[pd.Series(slot, index=st.index).isin(["Bye", G.NA]) & (Q.numeric(st, "Points").fillna(0) != 0)]
    assert bad.empty, bad[["Player", "Year", "Week", "NFL team", "Points"]].to_string()


def test_points_going_in_are_ordered():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE):
        return _skip("no exports or schedule cache")
    tw, pw, s = _data()
    snf, mon, last = (G.stage_rows(tw, pw, s, st).set_index(["Team", "Year", "Week"]) for st in G.STAGES)
    both = snf.join(mon, rsuffix="_m").join(last, rsuffix="_l")
    ok = both.dropna(subset=["Points going in", "Points going in_m"])
    assert (ok["Points going in"] <= ok["Points going in_m"] + 1e-9).all()
    assert (ok["Points going in_m"] <= ok["PF"] + 1e-9).all()
    l = both.dropna(subset=["Points going in_l"])
    assert (l["Points going in"] <= l["Points going in_l"] + 1e-9).all()
    print(f"  {len(ok)} team-weeks with SNF + Monday, {len(l)} with a late last game")


def test_known_monday_comeback():
    # LWebs53 v Oliverwkw, 2021 week 2: 129.14 going into MNF against a 192.92 final
    # (Oliverwkw had nobody left), won 217.54 with 3 starters on Monday night.
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE):
        return _skip("no exports or schedule cache")
    tw, pw, s = _data()
    r = G.stage_rows(tw, pw, s, "Monday").set_index(["Team", "Year", "Week"]).loc[("LWebs53", 2021, 2)]
    assert (r["Margin overcome"], r["Points overcome"], r["Comeback (% of points going in)"], r["Comeback (% of opponent's final)"],
            r["Players left"], r["Comeback (per player left)"]) == (63.78, 63.78, 49.4, 33.1, 3, 21.26), r


def test_exports_match_the_recompute():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE):
        return _skip("no exports or schedule cache")
    tw, pw, s = _data()
    if G.TEAM_WEEK_COLUMNS[0] not in tw.columns or G.GAME_SLOT_COLUMN not in pw.columns:
        return _skip("exports predate the game-time columns")
    want = G.team_week_columns(tw, pw, s).set_index(["Team", "Year", "Week"])
    have = tw.assign(Year=Q.numeric(tw, "Year").astype(int), Week=Q.numeric(tw, "Week").astype(int)) \
        .set_index(["Team", "Year", "Week"])
    for col in G.TEAM_WEEK_COLUMNS:
        h = have[col].astype(str).replace({"": G.NA, "nan": G.NA})
        w = want[col].reindex(have.index).astype(str)
        diff = [(k, a, b) for k, a, b in zip(have.index, h, w)
                if a != b and not (a != G.NA and b != G.NA and abs(float(a) - float(b)) < 0.006)]
        assert not diff, (col, diff[:5])
    slot = [G.player_slot(s, y, w, t) for y, w, t in zip(pw["Year"], pw["Week"], pw["NFL team"])]
    # the export writes every N/A as a blank cell
    assert list(pw[G.GAME_SLOT_COLUMN].astype(str).replace({"": G.NA, "nan": G.NA})) == slot


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("ok")
