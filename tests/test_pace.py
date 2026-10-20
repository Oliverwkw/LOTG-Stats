"""On-pace projection rules (lotg_support.pace; user rules, 2026-10-13).

Each case is one the 2026 week-5 email got wrong: Tanking scaled as a count,
distinct counts past their caps, offseason trades still "on pace", front-loaded
pickups and FAAB, a suspension that ignored the bye, "Change in points from
career" scaled whole. Plus the email's every-4-weeks resend, its "no longer on
pace" list and the player-team season-to-date columns.

Run: python tests/test_pace.py   (or pytest tests/)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import digest as D  # noqa: E402
from lotg_support import pace as P  # noqa: E402


def test_each_flagged_column_gets_its_rule():
    want = {
        ("teams", "Tanking"): P.ASIS,
        ("teams", "Future draft capital"): P.SKIP,
        ("teams", "Offseason trades"): P.ACTUAL,
        ("teams", "Offseason roster turnover"): P.ACTUAL,
        ("teams", "Total number of picks made"): P.ACTUAL,
        ("teams", "Number of first round picks made"): P.ACTUAL,
        ("teams", "Inseason roster turnover"): P.ACTUAL,
        ("teams", "Number of QB started"): P.ACTUAL,
        ("teams", "Number of TE rostered"): P.ACTUAL,
        ("teams", "Number of cuffs rostered"): P.ACTUAL,
        ("teams", "Number of NFL teams among rostered players"): P.ACTUAL,
        ("teams", "Most number of QBs rostered from same NFL team"): P.ACTUAL,
        ("league", "Highest starter score"): P.ACTUAL,
        ("players", "Number of teams"): P.ACTUAL,
        ("teams", "Number of Add/Drops"): P.CALENDAR,
        ("teams", "Number of waiver adds"): P.CALENDAR,
        ("teams", "Amount of FAAB spent"): P.CALENDAR,
        ("teams", "Total transactions"): P.CALENDAR,
        ("players", "Number of drops"): P.CALENDAR,
        ("players", "Number of trades"): P.CALENDAR,
        ("teams", "Weeks suspensions"): P.SUSPENSION,
        ("players", "Weeks missed due to suspension"): P.BYE,
        ("players", "Points"): P.BYE,
        ("players", "Change in points from career"): P.BASE,
        ("players", "Change in points from previous season"): P.BASE,
        ("players", "Weeks rostered"): P.LINEAR,
        ("teams", "Stacks"): P.SHAPE,
        ("teams", "Points from TEs"): P.SHAPE,
        ("teams", "Average weekly roster turnover"): P.ASIS,
        ("teams", "Times Highest score?"): P.SKIP,
    }
    got = {k: D.pace_mode(*k) for k in want}
    bad = {k: (got[k], v) for k, v in want.items() if got[k] != v}
    assert not bad, bad


def _ctx(**kw):
    base = dict(season=2026, played=5, horizon=17)
    base.update(kw)
    return P.PaceContext(**base)


def test_a_bye_is_neither_a_game_nor_a_suspended_week():
    # Josh Jacobs: suspended weeks 1-5 of 5, GB's bye still ahead -> 16, Calvin
    # Ridley's 2022 record (17 weeks less his bye).
    ctx = _ctx(byes={"GB": {8}}, nfl_team={"Josh Jacobs": "GB"})
    assert ctx.project("players", "Josh Jacobs", "Weeks missed due to suspension",
                       5, P.BYE) == 16
    # A bye already taken: 4 games in 5 weeks, 12 games to come.
    ctx = _ctx(byes={"KC": {5}}, nfl_team={"Patrick Mahomes": "KC"})
    assert ctx.project("players", "Patrick Mahomes", "Points", 80.0, P.BYE) == 80.0 + 20.0 * 12


def test_change_from_a_baseline_projects_the_points_not_the_difference():
    # Puka Nacua 2026: 77.8 points, 452.6 the season before (change -374.8). The
    # old pace scaled -374.8 to -1,274; now 77.8 is projected and 452.6 taken off.
    ctx = _ctx(byes={"LAR": {10}}, nfl_team={"Puka Nacua": "LAR"})
    got = ctx.project("players", "Puka Nacua", "Change in points from previous season",
                      -374.8, P.BASE, row={"Points (full season)": 77.8})
    assert abs(got - (77.8 * 16 / 5 - 452.6)) < 1e-9, got


def test_running_averages_and_levels_are_not_scaled():
    ctx = _ctx()
    assert ctx.project("teams", "plehv79", "Tanking", 1.0748, D.pace_mode("teams", "Tanking")) == 1.0748


def test_not_projectable_columns_are_not_on_pace_but_are_records():
    # A team that rosters 9 QBs by week 5 when no season had more than 8: a
    # record now, not "on pace for 30".
    hist = [{"Team": f"T{i}", "Year": y, "Number of QB rostered": 5 + i % 4,
             "Tanking": 0.1 * i} for y in (2023, 2024, 2025) for i in range(8)]
    cur = [{"Team": "A", "Year": 2026, "Number of QB rostered": 9, "Tanking": 0.05}]
    ty = pd.DataFrame(hist + cur)
    proj = D._project_frame("teams", ty, "Team", _ctx(), 5)
    assert not [p for p in proj if p.column == "Number of QB rostered"], proj
    recs = D._records_for_frame("teams", ty, "Team", 2026)
    assert [(r.entity, r.column, r.value) for r in recs] == [("A", "Number of QB rostered", 9.0)], recs


def test_transactions_follow_the_league_calendar():
    # Half of every past season's add/drops came by week 5: 10 so far is on pace
    # for 20, not 10 x 17/5 = 34.
    rows = []
    for y in (2023, 2024, 2025):
        for k in range(10):   # weeks 1-5 (offseason moves count in week 1)
            rows.append({"Season": y, "Date": f"{y}-08-{10 + k:02d}", "Player Added": "x",
                         "Player Dropped": "y", "type of add/drop (waiver/free agency)": "waiver"})
        for k in range(10):   # weeks 6-17
            rows.append({"Season": y, "Date": f"{y}-11-{1 + k:02d}", "Player Added": "x",
                         "Player Dropped": "y", "type of add/drop (waiver/free agency)": "waiver"})
    shares = P.calendar_shares(pd.DataFrame(rows), None, 2026, 5)
    assert abs(shares["adddrop"] - 0.5) < 1e-9, shares
    ctx = _ctx(calendar=shares)
    assert ctx.project("teams", "A", "Number of Add/Drops", 10, P.CALENDAR) == 20


def test_resend_weeks_and_final():
    weeks = [w for w in range(1, 18) if D.pace_resend_week(w, 17)]
    assert weeks == [9, 13, 17], weeks
    assert "every standing" in D.pace_resend_sentence(2026, 9, False)
    assert "over" in D.pace_resend_sentence(2026, 17, True)


def test_no_longer_on_pace():
    prior = {"players": {"Points": {"Josh Allen": "high:2", "Jahmyr Gibbs": "high:1"}},
             "league": {"PF": {"2026.0": "high:2"}}}
    now = [D.Projection("players", "Jahmyr Gibbs", "Points", "high", 1, 100, 500.0),
           D.Projection("league", "2026", "PF", "high", 2, 10, 20000.0)]
    got = [d.sentence() for d in D.pace_dropouts(prior, now)]
    # The league's old "2026.0" key is the same season as "2026": no dropout.
    assert got == ["Josh Allen is no longer on pace for a top-5 Points (was 2nd-highest)."], got
    assert D.part_of(D.pace_dropouts(prior, now)[0]) == D.PACE_DROPOUT_TITLE


def test_a_pace_rule_change_is_told_as_an_edit():
    items = [D.Projection("teams", "A", "Tanking", "high", 1, 50, 1.0),
             D.PaceDropout("teams", "B", "Offseason trades", "high", 1)]
    old = {"meta": {}}
    assert D.mark_pace_rule_change(old, items) == 2 and all(i.rule_release for i in items)
    same = {"meta": {D.PACE_RULES_KEY: D.PACE_RULES_VERSION}}
    fresh = [D.Projection("teams", "A", "Tanking", "high", 1, 50, 1.0)]
    assert D.mark_pace_rule_change(same, fresh) == 0 and not fresh[0].rule_release
    assert D.mark_pace_rule_change(None, fresh) == 0


def test_player_team_season_columns_ride_on_pace_and_lock_when_he_leaves():
    rows = [{"Player": f"P{i}", "Team": "X", "Year": 2025, "Week": 17,
             "PPG as team starter this season": 10.0 + i} for i in range(6)]
    rows += [{"Player": "Gone", "Team": "Y", "Year": 2026, "Week": 2,
              "PPG as team starter this season": 40.0},
             {"Player": "Here", "Team": "Z", "Year": 2026, "Week": 5,
              "PPG as team starter this season": 30.0}]
    pw = pd.DataFrame(rows)
    got = {(p.entity, p.rank) for p in D._project_stints(pw, _ctx(), 5)}
    assert ("Gone (Y)", 1) in got and ("Here (Z)", 2) in got, got
    assert D.is_stint_season_column("player_week", "PPG as team starter this season")
    assert not D.high_on_board("player_week", "% of team points on team this season")
    assert D.high_on_board("player_week", "Total times highest starter on team this season")


def test_a_faller_names_only_who_holds_its_place():
    prev = {"players": {"X": [{"entity": "W", "value": 20.0}, {"entity": "M", "value": 18.0},
                              {"entity": "R", "value": 17.0}, {"entity": "Z", "value": 1.0}]}}
    curr = {"players": {"X": [{"entity": "W", "value": 16.0}, {"entity": "M", "value": 18.0},
                              {"entity": "R", "value": 17.0}, {"entity": "Z", "value": 1.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)
           if getattr(c, "passed_by", False)]
    assert got == ["W was passed by M for highest X (18.00), falling to 16.00 (3rd-highest)."], got


def test_an_idle_row_on_a_relative_column_moved_nobody():
    # D'Ernest Johnson, no games since 2023, "joined the tie for highest Floor
    # percentile, passing Emanuel Wilson" because Wilson's floor fell. Told from
    # Wilson's side.
    prev = {"players": {"Floor percentile": [
        {"entity": "Wilson", "value": 100.0}, {"entity": "Sanders", "value": 100.0},
        {"entity": "Johnson", "value": 99.3}, {"entity": "Q", "value": 50.0}]}}
    curr = {"players": {"Floor percentile": [
        {"entity": "Wilson", "value": 95.0}, {"entity": "Sanders", "value": 100.0},
        {"entity": "Johnson", "value": 100.0}, {"entity": "Q", "value": 50.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev, curr,
                                                  active={"players": {"Wilson", "Sanders"}})]
    assert not any(s.startswith("Johnson") for s in got), got
    assert any(s.startswith("Wilson was passed by Johnson and Sanders") for s in got), got


def test_the_rookie_class_addition_rows_wait_for_week_8():
    pa = pd.DataFrame({"Player": ["Rookie", "Vet"], "Team": ["A", "B"],
                       "Date": ["2026-07-12", "2026-07-12"],
                       "Points above expectation (rate)": [-9.0, -8.0]})
    pw = pd.DataFrame({"Player": ["Rookie", "Vet"], "Year": [2026, 2026],
                       "Rookie?": [True, False]})
    yrs = [2025] * 17 + [2026] * 5
    tw = pd.DataFrame({"Year": yrs, "Week": list(range(1, 18)) + list(range(1, 6))})
    gate = D.BoardGate({"team_week": tw, "player_week": pw,
                        "team_year": pd.DataFrame({"Year": [2026]})})
    held = gate.restricted(pa, "player_additions", "Points above expectation (rate)")
    assert held.tolist() == [True, False], held.tolist()


def test_on_completed_seasons_the_league_shares_reach_one():
    """Data: every completed season's calendar and weekly shape come to 1 by
    its last week (no move is left out of its season)."""
    ex = _ROOT / "exports"
    if not (ex / "add_drops.csv").exists():
        return
    ad = pd.read_csv(ex / "add_drops.csv", low_memory=False)
    tr = pd.read_csv(ex / "trades.csv", low_memory=False)
    tw = pd.read_csv(ex / "team_week.csv", low_memory=False)
    shares = P.calendar_shares(ad, tr, 2026, 17)
    assert shares and all(0.9 <= v <= 1.0 for v in shares.values()), shares
    assert abs(P.shape_share(tw, "PF", 2026, 17, 17) - 1.0) < 1e-9


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)


def test_no_longer_on_pace_sits_above_the_edits():
    """Its own part after the on-pace parts and above "Changes from edits",
    even when a pace-rule release alone explains it (user, 2026-10-20)."""
    pace4 = D.Projection("teams", "A", "Luck", "high", 4, 3, 2.0)
    gone = D.PaceDropout("teams", "B", "Offseason trades", "high", 1, rule_release=True)
    edit = D.Projection("teams", "C", "Hardship", "high", 2, 3, 9.0)
    edit.rule_release = True
    nd = D.NewData(season=2026, weeks_completed=6, new_weeks=[6], edit_landed=True)
    html = D.render_digest_html([], [pace4, edit], {"season": 2026, "weeks_completed": 6},
                                new_data=nd, dropouts=[gone])
    pace_b = html.find(f">{D.PACE_BOARDS_TITLE}</h2>")
    drop = html.find(f">{D.PACE_DROPOUT_TITLE}</h2>")
    edits = html.find(f">{D.EDIT_SECTION_TITLE}</h2>")
    assert 0 < pace_b < drop < edits, (pace_b, drop, edits)
    assert "no longer on pace" in html[drop:edits] and "no longer on pace" not in html[edits:]
    assert "Hardship" in html[edits:]
    assert html.count(D.PACE_DROPOUT_TITLE) == 1, "one heading, not a part + section pair"
