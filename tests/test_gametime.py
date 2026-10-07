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


def _c(stage, i):
    return G.COMEBACK_COLUMNS[stage][i]


def test_column_names():
    assert G.COMEBACK_COLUMNS["SNF"] == (
        "Margin overcome (entering SNF)", "Points overcome (entering SNF)",
        "% of own points scored SNF or later", "% of opponent's final points overcome (entering SNF)",
        "Points overcome per player left (entering SNF)", "Margin overcome per player left (entering SNF)",
        "% of opponent's score overcome (SNF or later)", "Comeback size entering SNF (Claude Projection)")
    assert G.COMEBACK_COLUMNS["last game"][2] == "% of own points scored in last game"
    assert G.COMEBACK_COLUMNS["last game"][6] == "% of opponent's score overcome (last game)"
    assert G.TEAM_WEEK_COLUMNS[-1] == "Comeback size (Claude Projection)" and len(G.TEAM_WEEK_COLUMNS) == 3 + 3 * 8 + 1
    # only the scale-preserving renames carry digest history over
    assert G.LEGACY_COLUMNS["Down entering Monday comeback (per player left)"] == \
        "Points overcome per player left (entering Monday)"
    assert not any("%" in old for old in G.LEGACY_COLUMNS)
    # One Comeback size set per projection [per user, 2026-10-07]; the Claude
    # set carries the pre-#481 values, so the digest's boards follow it
    assert G.LEGACY_COLUMNS["Comeback size"] == "Comeback size (Claude Projection)"
    assert G.LEGACY_COLUMNS["Comeback size (entering last game)"] == \
        "Comeback size entering last game (Claude Projection)"
    from lotg_support import digest
    assert digest.migrate_count_column("Comeback size (entering SNF)") == \
        "Comeback size entering SNF (Claude Projection)"
    for x in ("Sleeper", "Claude", "Enhanced"):
        names = G.comeback_names(x)
        assert names[0] == f"Comeback size ({x} Projection)" and len(names) == 4
        assert names[3] == f"Comeback size entering last game ({x} Projection)"
    assert set(G.comeback_names("Claude")) <= set(G.TEAM_WEEK_COLUMNS)
    assert not set(G.PROJECTION_COMEBACK_COLUMNS) & set(G.TEAM_WEEK_COLUMNS)


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
    assert a[_c("SNF", 1)] == 6.0
    assert a[_c("SNF", 0)] == G.NA   # ahead at the time
    assert a[_c("SNF", 3)] == round(6 / 71, 4)
    assert a[_c("Monday", 1)] == 6.0
    assert a[_c("Monday", 0)] == 5.0   # 65 v 70 at the time
    # margin overcome ÷ the opponent's points going in (70)
    assert a[_c("Monday", 6)] == round(5 / 70, 4) and a[_c("SNF", 6)] == G.NA
    # per player left: A had one starter (Tuesday's) still to play at both stages
    assert a[_c("SNF", 4)] == 6.0 and a[_c("Monday", 4)] == 6.0
    assert a[_c("Monday", 5)] == 5.0 and a[_c("SNF", 5)] == G.NA
    # own share from the stage on, every game: A 10 of 75; B 21 of 71 from SNF, 1 from Monday
    assert a[_c("SNF", 2)] == round(10 / 75, 4) and b[_c("SNF", 2)] == round(21 / 71, 4)
    assert b[_c("Monday", 2)] == round(1 / 71, 4)
    # last game = Tuesday's (A's makeup) — the latest kickoff with a starter in it
    assert a["Margin entering last game"] == round(65 - 71, 2)
    assert a[_c("last game", 1)] == 6.0 and a[_c("last game", 0)] == 6.0
    # the loser never has a comeback, but every game has a size
    for stage in ("SNF", "Monday"):
        for i in (0, 1, 3, 4, 5, 6):
            assert b[_c(stage, i)] == G.NA, (stage, i)
        assert isinstance(b[_c(stage, 7)], float) and isinstance(a[_c(stage, 7)], float)
    # A was behind its expected finish entering Monday and won: a real size;
    # it was ahead entering SNF (expected) — 0 from there unless the hole came at SNF
    assert a[_c("Monday", 7)] > 0 and a[G.COMEBACK_SIZE_COLUMN] >= a[_c("Monday", 7)]


def test_win_z_and_comeback_size():
    # 10 behind, nobody left on either side: certain loss, capped
    assert G.win_z(50, 60, [], []) == -G.Z_CAP
    # 10 behind, one own player expected 16 (spread c·√16 = 4c) -> z = 6 / 4c
    z = G.win_z(50, 60, [(None, 0, 16.0)], [])
    assert abs(z - 6 / (4 * G.SD_PER_ROOT_POINT)) < 1e-9
    # never behind its expected finish -> 0, win or lose
    assert G.comeback_size([0.5, 1.2, 3.0], 1.0) == 0.0
    assert G.comeback_size([0.5, 1.0, 0.4], 0.0) == 0.0
    # a sliver behind, then ahead again before losing: a sliver of a comeback
    assert G.comeback_size([0.5, -0.1, 0.4], 0.0) == round(0.1 * G._phi(0.4), 2)
    # a win from 1.5 SDs down scores the whole depth
    assert G.comeback_size([-0.3, -1.5, -0.2], 1.0) == 1.5
    # a loss scores the comeback it was on course for at its best moment:
    # 1.5 deep, later at z = 0 (a coin flip) -> 0.75
    assert G.comeback_size([-1.5, 0.0, -2.0], 0.0) == 0.75
    # a blowout from the first game on: deep but never close -> ~0
    assert G.comeback_size([-4.0, -5.0, -6.0], 0.0) <= 0.01
    # a stage's version only counts the hole at the stage itself
    assert G.comeback_size([-0.2, -1.5], 1.0, from_first=True) == 0.2
    assert G.comeback_size([], 1.0) == 0.0


def test_a_hold_counts_but_small():
    # (z, own points over expectation still to come, opponent's shortfall still to come)
    # 1.2 SDs down; the team's own players then beat expectation by 20, the
    # opponent's matched theirs: all its own doing -> the whole depth.
    assert G.comeback_size([(-1.2, 20.0, 0.0)], 1.0) == 1.2
    # Same hole, nobody left on its side: the lead survived because the
    # opponent's late players fell 15 short -> a quarter [per user].
    assert G.comeback_size([(-1.2, 0.0, 15.0)], 1.0) == round(1.2 * G.HOLD_SHARE, 2)
    # Half and half -> 1/4 + 3/4 x 1/2
    assert G.comeback_size([(-1.2, 10.0, 10.0)], 1.0) == round(1.2 * (G.HOLD_SHARE + (1 - G.HOLD_SHARE) / 2), 2)
    # Own players fell short too, the opponent's fell shorter: a hold
    assert G.comeback_size([(-1.2, -5.0, 25.0)], 1.0) == round(1.2 * G.HOLD_SHARE, 2)
    # The share is of the turnaround BETWEEN the two points: a later point's
    # remaining over/short is taken off (here 10 own v 0 opponent -> all own).
    assert G.comeback_size([(-1.0, 12.0, 8.0), (0.5, 2.0, 8.0)], 0.0) == round(1.0 * G._phi(0.5), 2)


def test_overlapping_games_are_one_window():
    # 4:05 and 4:25 overlap, as do a Monday doubleheader's 7:15 and 8:15: no
    # moment has the first done and the second not started.
    d = lambda h, m=0, day=11: datetime(2020, 10, day, h, m)
    own = [(d(13), 10.0, 10.0, False), (d(16, 5), 10.0, 10.0, False), (d(19, 15, 12), 5.0, 9.0, False)]
    opp = [(d(16, 25), 20.0, 10.0, False), (d(20, 20), 9.0, 9.0, False), (d(20, 15, 12), 3.0, 9.0, False)]
    assert G.windows(own, opp) == [d(13), d(16, 5), d(20, 20), d(19, 15, 12)]
    # ...so "entering last game" is entering the doubleheader's first kickoff
    s = G.load_schedule(_WEEK)
    rows = [(d(19, 5, 12), 1.0, 1.0, False), (d(20, 50, 12), 1.0, 1.0, False)]
    assert G.last_game_start(s, 2020, 5, rows[:1], rows[1:]) == d(19, 5, 12)


def test_projection_band_for_a_team_behind_on_the_scoreboard():
    # [per user, 2026-10-07] Steve (stevenb123) 2026 wk 4 entering SNF: down
    # 57.38 with 4 starters left, opponent done. Projected 69.4 (+12): not a
    # comeback. Projected 58 or 60 (+0.6 / +2.6): inside the band -> one. The
    # band is 2.5·√n on the Claude projection: 5.0 for 4 left.
    band = G.BAND_PER_ROOT_STARTER * 2
    assert abs(band - 5.0) < 1e-9
    def hole(projected):
        left = [(None, 0.0, projected / 4, False)] * 4
        return G.win_z(76.50, 133.88, left, [], G.projection_band(76.50, 133.88, left, []))
    assert hole(69.4) > 0                    # still ahead after the band: depth 0
    assert hole(60.0) < 0 and hole(58.0) < 0   # behind once the band is applied
    # ahead (or level) on the scoreboard: no band
    assert G.projection_band(80.0, 70.0, [(None, 0, 10.0, False)], []) == 0.0
    # known outs carry no projection error
    assert G.projection_band(60.0, 70.0, [(None, 0, 10.0, True)], []) == 0.0
    # the band deepens the hole; the later win chance stays unbanded
    pts = [(0.2, 10.0, 0.0, -0.3)]
    assert G.comeback_size(pts, 1.0) == 0.3


def test_each_projection_has_its_own_model():
    # [per user, 2026-10-07: "fix band to match each"] the band is how far that
    # projection and Sleeper's disagree on the final margin (75th percentile per
    # √starters left, 2020-26 trailing windows): Claude 2.42 -> 2.5, Enhanced
    # 1.60, Sleeper 0 (it is what the league sees). Spreads: Claude 2.0,
    # Enhanced 1.8 (log loss refit); Sleeper reads the app-style win %.
    M = G.COMEBACK_MODELS
    assert (M["Claude"].win, M["Claude"].sd, M["Claude"].band) == ("calibrated", 2.0, 2.5)
    assert (M["Enhanced"].win, M["Enhanced"].sd, M["Enhanced"].band) == ("calibrated", 1.8, 1.6)
    assert (M["Sleeper"].win, M["Sleeper"].band) == ("app", 0.0)
    assert G.comeback_model("calibrated") is M["Claude"] and G.comeback_model("app") is M["Sleeper"]
    # 10 down on the scoreboard, 4 starters left projecting +12: the band takes
    # 5.0 / 3.2 / 0 off the projected margin
    left = [(None, 0.0, 3.0, False)] * 4
    for x, want in (("Claude", 5.0), ("Enhanced", 3.2), ("Sleeper", 0.0)):
        assert abs(G.projection_band(50.0, 60.0, left, [], M[x].band) - want) < 1e-9, x
    # the spread scales the z: 16 expected points left, 6 ahead after them
    for x in ("Claude", "Enhanced"):
        z = G.win_z(50, 60, [(None, 0, 16.0)], [], sd=M[x].sd)
        assert abs(z - 6 / (4 * M[x].sd)) < 1e-9


def test_known_outs_expect_nothing():
    # A starter known to be out (dead start) adds no expectation and no spread.
    out = (None, 0.0, 15.0, True)
    assert G.win_z(50, 60, [out], []) == -G.Z_CAP
    z = G.win_z(50, 60, [(None, 0.0, 16.0, False), out], [])
    assert abs(z - 6 / (G.SD_PER_ROOT_POINT * 4)) < 1e-9


def test_expected_points_use_only_earlier_weeks():
    s = G.load_schedule(_games([(2021, w, "REG", f"2021-09-{11 + w:02d}", "13:00", "KC", "CLE")
                                for w in (1, 2, 3)]
                               + [(2020, 5, "REG", "2020-10-11", "13:00", "KC", "LV")]))
    pw = pd.DataFrame([
        ("X", "1", "A", 2020, 5, "Bench", "WR", "KC", 30.0),     # last season: 30 a game
        ("X", "1", "A", 2021, 1, "Starter", "WR", "KC", 10.0),
        ("X", "1", "A", 2021, 2, "Starter", "WR", "KC", 20.0),
        ("X", "1", "A", 2021, 3, "Starter", "WR", "KC", 99.0),
        ("Y", "2", "B", 2021, 1, "Starter", "TE", "CLE", 5.0),
    ], columns=["Player", "Player ID", "Team", "Year", "Week", "Starter/Bench", "Position", "NFL team", "Points"])
    mu = G.expected_points(pw, s)
    seed = G.POSITION_SEED
    wr0 = seed["WR"]   # no WR start before 2020 wk 5... nor before 2021 wk 1 (the 2020 row is bench)
    k, c = G.EXPECT_POSITION_GAMES, G.EXPECT_LAST_SEASON_GAMES
    assert abs(mu[1] - (c * 30 + k * wr0) / (c + k)) < 1e-9
    # week 3: two games this season (10, 20), last season, the WR average of 2 starts so far
    m0 = (30 + G.POSITION_PRIOR_STARTS * wr0) / (2 + G.POSITION_PRIOR_STARTS)
    assert abs(mu[3] - (30 + c * 30 + k * m0) / (2 + c + k)) < 1e-9
    # the week's own 99 never leaks in; bench rows get no expectation
    assert mu[0] != mu[0]
    assert abs(mu[4] - seed["TE"]) < 1e-9


def test_last_game_needs_sunday_night_or_later():
    s = G.load_schedule(_WEEK)
    tw = _tw([("A", 2020, 5, "Week 5", "B", True, 30.0, 20.0),
              ("B", 2020, 5, "Week 5", "A", False, 20.0, 30.0)])
    pw = _pw([("A", 2020, 5, "Starter", "CLE", 30.0), ("B", 2020, 5, "Starter", "SF", 20.0)])
    c = G.team_week_columns(tw, pw, s).set_index("Team")
    assert c.loc["A", "Margin entering last game"] == G.NA
    assert c.loc["A", _c("last game", 1)] == G.NA
    assert c.loc["A", _c("last game", 7)] == G.NA
    # SNF / Monday are league-wide: they exist although neither side played in them
    assert c.loc["A", "Margin entering SNF"] == 10.0 and c.loc["A", "Margin entering Monday"] == 10.0
    assert c.loc["A", _c("SNF", 1)] == G.NA   # never trailed the final
    assert c.loc["A", _c("SNF", 0)] == G.NA
    assert c.loc["A", _c("SNF", 2)] == 0.0   # nobody left after Sunday afternoon


# --------------------------------------------------------------------------- #
def _data():
    tw, pw = Q.load_sheet("team_week"), Q.load_sheet("player_week")
    done = set(Q.completed_seasons())
    tw = tw[Q.numeric(tw, "Year").isin(done)]
    pw = pw[Q.numeric(pw, "Year").isin(done)]
    return tw, pw, G.load_schedule(Q.schedule())


_EXPECTED = []


def _expected():
    """The Claude projections for every completed season (the build's input to
    Comeback size (Claude Projection)), once per run."""
    if not _EXPECTED:
        _EXPECTED.append(G.claude_expectations(Q.load_sheet("player_week")))
    return _EXPECTED[0]


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
    assert (r["Margin overcome"], r["Points overcome"], r["% of opponent's final overcome"],
            r["Players left"], r["Points overcome per player left"], r["Margin overcome per player left"],
            r["% of opponent's score overcome"]) == (63.78, 63.78, 0.3306, 3, 21.26, 21.26, 0.3306), r
    assert r["% of own points scored after"] == round(88.4 / 217.54, 4)
    # 63.78 down on the scoreboard: the projection band deepens the hole (1.70)
    assert 0.5 < r["Comeback size"] < 2.0, r["Comeback size"]


def test_exports_match_the_recompute():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE):
        return _skip("no exports or schedule cache")
    if not _have_enhanced():
        return _skip("exports predate the projection columns")
    tw, pw, s = _data()
    if not set(G.TEAM_WEEK_COLUMNS) <= set(tw.columns) or G.GAME_SLOT_COLUMN not in pw.columns:
        return _skip("exports predate the game-time columns")
    want = G.team_week_columns(tw, pw, s, _expected()).set_index(["Team", "Year", "Week"])
    have = tw.assign(Year=Q.numeric(tw, "Year").astype(int), Week=Q.numeric(tw, "Week").astype(int)) \
        .set_index(["Team", "Year", "Week"])
    for col in G.TEAM_WEEK_COLUMNS:
        h = have[col].astype(str).replace({"": G.NA, "nan": G.NA})
        w = want[col].reindex(have.index).astype(str)
        diff = [(k, a, b) for k, a, b in zip(have.index, h, w)
                if a != b and not (a != G.NA and b != G.NA and abs(float(a) - float(b)) < 0.006)]
        assert not diff, (col, diff[:5])
    # the Sleeper and Enhanced Comeback size sets, once the exports carry them
    if set(G.PROJECTION_COMEBACK_COLUMNS) <= set(tw.columns):
        for x in ("Sleeper", "Enhanced"):
            want = G.projection_comeback_columns(tw, pw, s, x).assign(
                Year=lambda d: Q.numeric(d, "Year").astype(int), Week=lambda d: Q.numeric(d, "Week").astype(int)
            ).set_index(["Team", "Year", "Week"])
            for col in G.comeback_names(x):
                h = have[col].astype(str).replace({"": G.NA, "nan": G.NA})
                w = want[col].reindex(have.index).astype(str)
                diff = [(k, a, b) for k, a, b in zip(have.index, h, w)
                        if a != b and not (a != G.NA and b != G.NA and abs(float(a) - float(b)) < 0.006)]
                assert not diff, (col, diff[:5])
    slot = [G.player_slot(s, y, w, t) for y, w, t in zip(pw["Year"], pw["Week"], pw["NFL team"])]
    # the export writes every N/A as a blank cell
    assert list(pw[G.GAME_SLOT_COLUMN].astype(str).replace({"": G.NA, "nan": G.NA})) == slot


def _have_enhanced() -> bool:
    return "Claude Projection" in Q.load_sheet("player_week").columns


def test_win_chance_is_calibrated():
    # The comeback-size model's win chances, at every kickoff but the first of
    # every completed-season matchup, against what happened. Expectations are
    # the Claude projections (0.393 log loss over 2020-25 at a 2.0 spread, vs 0.398
    # for the season-average fallback); a change that breaks the projections or
    # the spread shows up here first.
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE):
        return _skip("no exports or schedule cache")
    if not _have_enhanced():
        return _skip("exports predate the projection columns")
    import math
    tw, pw, s = _data()
    plays = G.starter_plays(pw, s, _expected())
    ps, ys = [], []
    for team, opp, y, w, pf, pa, won in zip(tw["Team"], tw["Opponent"], Q.numeric(tw, "Year"),
                                            Q.numeric(tw, "Week"), Q.numeric(tw, "PF"),
                                            Q.numeric(tw, "Points against"), tw["Win?"]):
        own, op = plays.get((team, int(y), int(w)), []), plays.get((opp, int(y), int(w)), [])
        for k in G.windows(own, op)[1:]:
            ps.append(min(max(G._phi(G.checkpoint_z(own, op, pf, pa, k)), 1e-6), 1 - 1e-6))
            ys.append(1.0 if G._won(won) else 0.0)
    ll = -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(ps, ys)) / len(ps)
    lo = [(p, y) for p, y in zip(ps, ys) if p < 0.1]
    hi = [(p, y) for p, y in zip(ps, ys) if p > 0.9]
    print(f"  {len(ps)} kickoff windows, log loss {ll:.4f}; under 10%: predicted "
          f"{sum(p for p, _ in lo) / len(lo):.3f} v won {sum(y for _, y in lo) / len(lo):.3f}")
    assert ll < 0.40, ll
    assert abs(sum(p for p, _ in lo) / len(lo) - sum(y for _, y in lo) / len(lo)) < 0.03
    assert abs(sum(p for p, _ in hi) / len(hi) - sum(y for _, y in hi) / len(hi)) < 0.03


def test_comeback_size_bounds():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE):
        return _skip("no exports or schedule cache")
    if not _have_enhanced():
        return _skip("exports predate the projection columns")
    tw, pw, s = _data()
    c = G.team_week_columns(tw, pw, s, _expected()).replace(G.NA, float("nan"))
    size = pd.to_numeric(c[G.COMEBACK_SIZE_COLUMN], errors="coerce")
    assert size.notna().all() and (size >= 0).all()
    for st in G.STAGES:
        stage = pd.to_numeric(c[G.COMEBACK_COLUMNS[st][7]], errors="coerce")
        both = stage.notna()
        # the whole week's hole is at least as deep as any one stage's
        assert (size[both] >= stage[both] - 1e-9).all(), st
        # every comeback (won from behind entering the stage) has a size above 0
        mo = pd.to_numeric(c[G.COMEBACK_COLUMNS[st][0]], errors="coerce")
        assert (stage[mo.notna()] >= 0).all()
    print(f"  Comeback size: median {size.median():.2f}, max {size.max():.2f}; "
          f"{int((size == 0).sum())} of {len(size)} at 0")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("ok")
