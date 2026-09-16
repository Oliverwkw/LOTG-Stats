"""The digest's two halves: moves new data explains, and moves only an edit does.

A week's email used to be one list. The week an edit landed (PR #426 clearing
514 wrong injury weeks), that list carried ~200 moves re-valuing 2020-2025 next
to the handful of real ones, and nothing told a reader which was which. Now every
move new data could explain reads where it always has, and every move only an
edit explains goes in its own labelled section at the bottom. A move BOTH could
explain stays with the news.

What these hold:
  * the split itself, and its tie-break (both -> the news);
  * the evidence it runs on — what arrived since the last digest
    (`new_data_since`) and whether an edit landed (`edit_fingerprint`);
  * that nothing changes without that evidence (the replica, an old caller);
  * that the lede's "re-valued history" count is exactly the edits section.

Run: PYTHONPATH=src:lib python tests/test_digest_attribution.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import digest as D              # noqa: E402
from lotg_support import email_summary as DS      # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


_META = {"season": 2026, "weeks_completed": 1}
_TEAM_SEASONS = "All-time leaderboard moves — team seasons"


def _week_one(**kw):
    """Week 1 of 2026 just completed; an edit may have landed (no fingerprint)."""
    args = dict(season=2026, weeks_completed=1, new_weeks={(2026, 1)},
                players={"Rookie", "Vet"}, teams={"Oliverwkw", "JacobRosenzweig"},
                edit_landed=None)
    args.update(kw)
    return DS.NewData(**args)


def _ev(sheet, label, column, rank=1, value=10.0, passed=("Somebody 2020",), **kw):
    return D.EventCrossing(sheet, label, column, "high", rank, value,
                           passed=tuple(passed), **kw)


def _tag(item, nd, title=_TEAM_SEASONS):
    return DS.attribute(item, title, nd)


# ---------------------------------------------------------------------------
def check_edit_only_moves_render_at_the_bottom():
    new_line = _ev("player_week", "Rookie 2026 week 1", "Points", value=41.0,
                   passed=("Old 2020 week 3",))
    team_now = D.Crossing("teams", "Weeks of injuries", "high", 1, "Oliverwkw", 28.0,
                          passed=("JacobRosenzweig",))
    edit_line = _ev("team_year", "Oldteam 2021", "Hardship", value=1231.3,
                    passed=("Other 2024",))
    html = D.render_digest_html([team_now], [], _META, events=[new_line, edit_line],
                                new_data=_week_one())
    ok = _ok("the edits section is in the email", D.EDIT_SECTION_TITLE in html)
    cut = html.index(D.EDIT_SECTION_TITLE)
    ok &= _ok("new-data lines sit above it",
              html.index("Rookie 2026 week 1") < cut and html.index("Oliverwkw") < cut)
    ok &= _ok("the edit-only line sits below it", html.index("Oldteam 2021") > cut)
    ok &= _ok("it keeps its section title, one level down",
              f">{_TEAM_SEASONS}</h3>" in html[cut:], html[cut:][:400])
    ok &= _ok("and says what the section means", D.EDIT_SECTION_NOTE in html)
    return ok


def check_no_edit_items_means_no_edits_section():
    line = _ev("player_week", "Rookie 2026 week 1", "Points", passed=("Old 2020 week 3",))
    html = D.render_digest_html([], [], _META, events=[line], new_data=_week_one())
    return _ok("nothing to attribute to an edit -> no header",
               D.EDIT_SECTION_TITLE not in html and "Rookie 2026 week 1" in html)


def check_without_evidence_the_email_is_unchanged():
    """The replica and any older caller pass no context: one list, as before."""
    edit_line = _ev("team_year", "Oldteam 2021", "Hardship", passed=("Other 2024",))
    before = D.render_digest_html([], [], _META, events=[edit_line])
    ok = _ok("no context -> no edits section", D.EDIT_SECTION_TITLE not in before)
    ok &= _ok("no context -> everything is new data", _tag(edit_line, None) == "new")
    ok &= _ok("no season -> everything is new data",
              _tag(edit_line, _week_one(season=None)) == "new")
    return ok


def check_both_stays_with_the_news():
    """An all-time total that took in week 1 is new data even if the edit also
    moved it; a past row on a stat week 1 cannot touch stays an edit."""
    nd = _week_one()
    team_total = D.Crossing("teams", "Hardship", "high", 2, "Oliverwkw", 5115.7,
                            passed=("AceMatthew",))
    ok = _ok("an all-time team total that played this week -> news",
             _tag(team_total, nd, "All-time leaderboard moves — teams") == "new")
    rival_only = D.Crossing("teams", "Hardship", "high", 2, "AceMatthew", 5115.7,
                            passed=("JacobRosenzweig",))
    ok &= _ok("a rival it passed took in new data -> news",
              _tag(rival_only, nd, "All-time leaderboard moves — teams") == "new")
    nobody = D.Crossing("players", "Weeks missed due to injury", "high", 5,
                        "Elijah Mitchell", 31.0, passed=("Trey Lance",))
    ok &= _ok("an all-time total nobody named played into -> edit",
              _tag(nobody, nd, "All-time leaderboard moves — players") == "edit")
    past_local = _ev("team_year", "Oliverwkw 2021", "Hardship", passed=("AceMatthew 2024",))
    ok &= _ok("a past season's own stat stays an edit though the team played",
              _tag(past_local, nd) == "edit")
    return ok


def check_open_ended_stats_on_past_rows():
    nd = _week_one()
    still_producing = _ev("rookie_picks", "2023 pick 1.02 (Rookie)",
                          "Player addition value", passed=("2022 pick 1.05 (Gone)",))
    ok = _ok("a past pick still producing, on a stat that accrues -> news",
             _tag(still_producing, nd, "All-time leaderboard moves — rookie draft picks")
             == "new")
    gone = _ev("rookie_picks", "2021 pick 1.04 (Gone)", "Player addition value",
               passed=("2022 pick 1.05 (Retired)",))
    ok &= _ok("the same stat for a player out of the league -> edit",
              _tag(gone, nd, "All-time leaderboard moves — rookie draft picks") == "edit")
    move = _ev("add_drops", "JacobRosenzweig's 2023-10-02 move for Vet", "Player addition value",
               passed=("LWebs53's 2021-12-10 move for Demaryius Thomas",))
    ok &= _ok("an old add of a player who played this week -> news",
              _tag(move, nd, "All-time leaderboard moves — add/drops") == "new")
    return ok


def check_a_settled_streak_is_not_new_data():
    """Streaks are terminal-encoded, so only the run still open can change — the
    last one, from last season. Three 2020-2024 Quiet streak rows moved on the
    2026-09-09 Add/Drop week-attribution change and read as news because their
    teams had made 2026 moves; a 2026 move cannot touch a 2020 week."""
    title = "All-time leaderboard moves — team weeks"
    traded = _week_one(new_weeks=(), weeks_completed=0, players=(), teams=(),
                       tx_teams={"JacobRosenzweig", "Oliverwkw"})
    old = _ev("team_week", "JacobRosenzweig 2020 week 8", "Quiet streak", rank=4,
              value=6.0, joined=True, others=("BROsenzweig 2020 week 13",), passed=())
    ok = _ok("a 2020 Quiet streak of a team that just traded -> edit",
             _tag(old, traded, title) == "edit")
    ok &= _ok("same row in a week with games -> still an edit",
              _tag(old, _week_one(teams={"JacobRosenzweig"}), title) == "edit")
    open_run = _ev("team_week", "Oliverwkw 2025 week 17", "Quiet streak", rank=4,
                   value=6.0, passed=("plehv79 2025 week 17",))
    ok &= _ok("last season's final week, whose run can still be open -> news",
              _tag(open_run, traded, title) == "new")
    with_last = _week_one(new_weeks=(), weeks_completed=0, players=(), teams=(),
                          tx_teams={"Oliverwkw"}, last_weeks={2025: 17})
    ok &= _ok("...and still news when the last week is known",
              _tag(open_run, with_last, title) == "new")
    mid = _ev("team_week", "Oliverwkw 2025 week 10", "Quiet streak", rank=4,
              value=6.0, passed=("plehv79 2025 week 9",))
    ok &= _ok("a mid-season week of last season is settled -> edit",
              _tag(mid, with_last, title) == "edit")
    return ok


def check_a_game_cannot_move_a_transaction_only_stat():
    """A week of games reaches everything about the teams that played it except
    the stats built only from transactions. The Tuesday-Monday week re-dated
    moves and so moved all-time Tanking; in week 1 every team played, and
    without this those edits would have read as news."""
    title = "All-time leaderboard moves — teams"
    games = _week_one()                                   # teams played, no moves
    moves = _week_one(tx_teams={"Oliverwkw"})
    tank = D.Crossing("teams", "Tanking", "high", 1, "Oliverwkw", 12.0,
                      passed=("AceMatthew",))
    ok = _ok("all-time Tanking of a team that only played -> edit",
             _tag(tank, games, title) == "edit")
    ok &= _ok("...of a team that made a move -> news", _tag(tank, moves, title) == "new")
    for col in ("Number of Add/Drops", "Total transactions", "Amount of FAAB spent",
                "Number of waiver adds", "Offseason trades", "Quiet streak"):
        ok &= _ok(f"{col} is transaction-only", DS._transaction_only(col))
    for col in ("Add/Drop skill", "Trade addition value", "Return from trades",
                "Hardship", "Points", "Dropped avg points"):
        ok &= _ok(f"{col} is not", not DS._transaction_only(col))
    both = D.Crossing("teams", "Add/Drop skill", "high", 1, "Oliverwkw", 50.0,
                      passed=("AceMatthew",))
    ok &= _ok("a skill (production too) of a team that played -> news",
              _tag(both, games, title) == "new")
    return ok


def check_pooled_stats_take_in_any_new_week():
    """A pooled tier stat is re-cut by every new week — which reaches this
    season's rows and all-time rows. On a SETTLED week or season one week of
    scores barely moves the cutoffs; what moves it is an edit to the pool (on
    2026-09-15 "2021 week 8 joins a tie for highest % of starters lower quartile"
    came from #426's injury-flag fix, yet read as news)."""
    nd = _week_one()
    past_week = _ev("league_week", "2021 week 8", "% of starters lower quartile",
                    value=27.8, passed=("2020 week 8",))
    ok = _ok("a settled league week's tier share -> edit",
             _tag(past_week, nd, "All-time leaderboard moves — league weeks") == "edit")
    past_season = _ev("player_year", "Retired Guy 2020", "Rostered consistency percentile",
                      value=100.0, passed=("Other Guy 2021",))
    ok &= _ok("a settled season's percentile -> edit", _tag(past_season, nd) == "edit")
    this_week = _ev("league_week", "2026 week 1", "% of starters boom",
                    value=17.5, passed=("2024 week 17",))
    ok &= _ok("this week's tier share -> news",
              _tag(this_week, nd, "All-time leaderboard moves — league weeks") == "new")
    career = D.Crossing("players", "Rostered consistency percentile", "high", 1,
                        "Retired Guy", 100.0, passed=("Other Guy",))
    ok &= _ok("an all-time percentile re-cut by the new week -> news",
              _tag(career, nd, "All-time leaderboard moves — players") == "new")
    ok &= _ok("with no new week an all-time percentile is an edit",
              _tag(career, _week_one(new_weeks=(), weeks_completed=0, players=(), teams=()),
                   "All-time leaderboard moves — players") == "edit")
    return ok


def check_renumber_is_an_edit_even_in_season():
    art = _ev("rookie_picks", "2021 pick 1.10 (Rookie)", "O-Score",
              passed=("2021 pick 1.02 (Rookie)",))
    return _ok("a row passing a renumbered copy of itself -> edit",
               _tag(art, _week_one(), "All-time leaderboard moves — rookie draft picks")
               == "edit")


def check_current_period_items_are_new_data():
    nd = _week_one()
    ok = _ok("a single-week record",
             _tag(D.WeeklyHighlight("teams", "Oliverwkw", "PF", "high", 1, 190.0, week=1),
                  nd) == "new")
    ok &= _ok("a single-season record",
              _tag(D.YearlyRecord("teams", "Oliverwkw", "Times One-man army?", 9.0), nd) == "new")
    ok &= _ok("an on-pace standing",
              _tag(D.Projection("teams", "A", "Hardship", "high", 1, 3, 110.0), nd) == "new")
    ok &= _ok("a league milestone in a week with games",
              _tag(D.Milestone("PF", 51000.0, 50000.0), nd) == "new")
    ok &= _ok("a league milestone with nothing new -> edit",
              _tag(D.Milestone("PF", 51000.0, 50000.0),
                   _week_one(new_weeks=(), weeks_completed=0, players=(), teams=())) == "edit")
    return ok


def check_new_transactions_count_as_new_data():
    """Offseason: no games, but a trade just made reaches both teams' totals."""
    nd = _week_one(new_weeks=(), weeks_completed=0, players=(), teams=(),
                   tx_players={"Kyle Williams"}, tx_teams={"LWebs53", "shmuel256"})
    total = D.Crossing("teams", "Trading skill", "high", 1, "LWebs53", 55.0,
                       passed=("AceMatthew",))
    ok = _ok("an all-time total of a team that just traded -> news",
             _tag(total, nd, "All-time leaderboard moves — teams") == "new")
    quiet = D.Crossing("teams", "Trading skill", "high", 1, "AceMatthew", 55.0,
                       passed=("plehv79",))
    ok &= _ok("a team that did nothing, passing a team that did nothing -> edit",
              _tag(quiet, nd, "All-time leaderboard moves — teams") == "edit")
    games = D.Crossing("teams", "Weeks of starter injuries", "high", 1, "LWebs53", 274.0,
                       passed=("AceMatthew",))
    ok &= _ok("a trade cannot move a game stat: that team's injuries total -> edit",
              _tag(games, nd, "All-time leaderboard moves — teams") == "edit")
    ok &= _ok("a league milestone on a week with only transactions -> news",
              _tag(D.Milestone("Total trades", 600.0, 600.0), nd) == "new")
    return ok


def check_no_edit_landed_keeps_everything_with_the_news():
    """A fingerprint proving the build's inputs did not change: a past row that
    moved did so on upstream data, not an edit, so there is no edits section."""
    edit_line = _ev("team_year", "Oldteam 2021", "Hardship", passed=("Other 2024",))
    nd = _week_one(edit_landed=False)
    html = D.render_digest_html([], [], _META, events=[edit_line], new_data=nd)
    ok = _ok("no edit landed -> the past row is not labelled an edit",
             _tag(edit_line, nd) == "new")
    ok &= _ok("and there is no edits section", D.EDIT_SECTION_TITLE not in html)
    ok &= _ok("a proven edit week still splits",
              _tag(edit_line, _week_one(edit_landed=True)) == "edit")
    return ok


def check_label_entities():
    le = DS._label_entities
    cases = {
        "LWebs53's 2026-09-08 move for Cyrus Allen": {"LWebs53", "Cyrus Allen"},
        "BROsenzweig's 2026-07-07 trade for Chris Olave, 2027 2(AceMatthew)":
            {"BROsenzweig", "Chris Olave", "2027 2(AceMatthew)"},
        "JacobRosenzweig's 2026-09-09 trade for A, B, C +1 more":
            {"JacobRosenzweig", "A", "B", "C"},
        "AceMatthew's 2025-06-18 trade for Bijan Robinson": {"AceMatthew", "Bijan Robinson"},
        "stevenb123's 2023-12-10 waiver pickup of Deneric Prince":
            {"stevenb123", "Deneric Prince"},
        "2023 pick 1.02 (Anthony Richardson)": {"Anthony Richardson", "2023 pick 1.02"},
        "Zamir White 2023 week 6": {"Zamir White"},
        "plehv79 2021": {"plehv79"},
        "the 2021 season": {DS.LEAGUE},
        "2024 week 2": {DS.LEAGUE},
        "Oliverwkw": {"Oliverwkw"},
    }
    ok = True
    for label, want in cases.items():
        got = le(label)
        ok &= _ok(f"entities of {label!r}", want <= got, got)
    return ok


def check_new_data_since():
    tw = pd.DataFrame({"Team": ["A", "B", "A", "B"], "Year": [2026] * 4,
                       "Week": [1, 1, 2, 2]})
    pw = pd.DataFrame({"Player": ["P1", "P2"], "Team": ["A", "B"],
                       "Year": [2026, 2026], "Week": [1, 2]})
    ad = pd.DataFrame({"Team": ["C", "A"], "Date": ["2026-09-20", "2026-08-01"],
                       "Player Added": ["P3", "Old"], "Player Dropped": ["", ""]})
    frames = {"team_week": tw, "player_week": pw, "add_drops": ad}
    old_key = D._board_row_key("add_drops", ad.iloc[1])
    prior = {"meta": {"season": 2026, "weeks_completed": 1, "inputs_fingerprint": "aaa"},
             "row_keys": [old_key]}
    meta = {"season": 2026, "weeks_completed": 2}
    nd = D.new_data_since(prior, meta, frames, "aaa")
    ok = _ok("only the week past the prior count is new", nd.new_weeks == {(2026, 2)},
             nd.new_weeks)
    ok &= _ok("players in that week", nd.players == {"P2"}, nd.players)
    ok &= _ok("teams in that week", nd.teams == {"A", "B"}, nd.teams)
    ok &= _ok("the new add, kept apart", nd.tx_players == {"P3"} and nd.tx_teams == {"C"},
              (nd.tx_players, nd.tx_teams))
    ok &= _ok("a row already in the prior snapshot is not new",
              "Old" not in nd.tx_players and "A" not in nd.tx_teams)
    ok &= _ok("same fingerprint -> no edit landed", nd.edit_landed is False)
    ok &= _ok("different fingerprint -> an edit landed",
              D.new_data_since(prior, meta, frames, "bbb").edit_landed is True)
    no_fp = {"meta": {"season": 2026, "weeks_completed": 1}, "row_keys": [old_key]}
    ok &= _ok("an older snapshot with no fingerprint -> unknown",
              D.new_data_since(no_fp, meta, frames, "bbb").edit_landed is None)
    rollover = {"meta": {"season": 2025, "weeks_completed": 17}}
    ok &= _ok("a new season's weeks are all new",
              D.new_data_since(rollover, meta, frames).new_weeks == {(2026, 1), (2026, 2)})
    ok &= _ok("each season's last week is known", nd.last_weeks == {2026: 2}, nd.last_weeks)
    ok &= _ok("no prior snapshot -> nothing to attribute",
              D.new_data_since(None, meta, frames) is None)
    return ok


def check_fingerprint_follows_build_inputs_only():
    base = [
        "100644 blob aaa\tsrc/lotg.py",
        "100644 blob bbb\tdata/game_day_status.csv",
        "100644 blob ccc\tdata/injury_tracker.csv",
        "100644 blob ddd\tdata/digest/ranks_snapshot.json",
        "100644 blob eee\tlib/lotg_support/digest.py",
        "100644 blob fff\texports/player_week.csv",
        "100644 blob ggg\tconfig/league.yaml",
    ]
    fp = D.edit_fingerprint(base)

    def swap(path, sha):
        return D.edit_fingerprint([f"100644 blob {sha}\t{path}" if e.endswith("\t" + path)
                                   else e for e in base])
    ok = _ok("a hash comes back", bool(fp))
    ok &= _ok("stable", fp == D.edit_fingerprint(list(reversed(base))))
    for path in ("data/injury_tracker.csv", "data/digest/ranks_snapshot.json",
                 "lib/lotg_support/digest.py", "exports/player_week.csv"):
        ok &= _ok(f"a bot/render-only path does not count: {path}", swap(path, "zzz") == fp)
    for path in ("src/lotg.py", "data/game_day_status.csv", "config/league.yaml"):
        ok &= _ok(f"a build input does: {path}", swap(path, "zzz") != fp)
    ok &= _ok("no inputs -> None", D.edit_fingerprint(["100644 blob x\texports/a.csv"]) is None)
    return ok


def check_snapshot_carries_the_fingerprint():
    pat = pd.DataFrame({"Player": ["P"], "Points": [1.0]})
    tat = pd.DataFrame({"Team": ["T"], "PF": [1.0]})
    ty = pd.DataFrame({"Team": ["T"], "Year": [2026]})
    tw = pd.DataFrame({"Team": ["T"], "Year": [2026], "Week": [1]})
    with_fp = D.build_snapshot(pat, tat, ty, tw, inputs_fingerprint="abc123")
    without = D.build_snapshot(pat, tat, ty, tw)
    ok = _ok("stored when known", with_fp["meta"].get("inputs_fingerprint") == "abc123")
    ok &= _ok("absent when not", "inputs_fingerprint" not in without["meta"])
    return ok


def check_the_lede_counts_exactly_the_edits_section():
    nd = _week_one()
    headline = D.Crossing("teams", "Points", "high", 1, "Oliverwkw", 9000.0,
                          passed=("JacobRosenzweig",))
    edits = [_ev("team_year", f"Old{i} 2021", "Hardship", rank=3,
                 passed=(f"Other{i} 2022",)) for i in range(10)]
    secs = [("All-time leaderboard moves — teams", True, [headline]),
            (_TEAM_SEASONS, True, edits)]
    top, bottom = D.split_sections(secs, nd)
    lede = DS.reasoned_summary(secs, season=2026, weeks_completed=1, new_data=nd)
    ok = _ok("10 lines go under edits", sum(len(i) for _t, _g, i in bottom) == 10)
    ok &= _ok("an all-time total that took in week 1 can headline",
              lede.startswith("Oliverwkw"), lede)
    ok &= _ok("and the lede's re-valued count is the edits section",
              "10 of the 10 other moves re-value settled history" in lede, lede)
    old = DS.reasoned_summary(secs, season=2026, weeks_completed=1)
    ok &= _ok("without the evidence the lede reads as it did",
              not old.startswith("Oliverwkw"), old)
    return ok


def run_all() -> bool:
    tests = [
        check_edit_only_moves_render_at_the_bottom,
        check_no_edit_items_means_no_edits_section,
        check_without_evidence_the_email_is_unchanged,
        check_both_stays_with_the_news,
        check_open_ended_stats_on_past_rows,
        check_pooled_stats_take_in_any_new_week,
        check_a_settled_streak_is_not_new_data,
        check_a_game_cannot_move_a_transaction_only_stat,
        check_renumber_is_an_edit_even_in_season,
        check_current_period_items_are_new_data,
        check_new_transactions_count_as_new_data,
        check_no_edit_landed_keeps_everything_with_the_news,
        check_label_entities,
        check_new_data_since,
        check_fingerprint_follows_build_inputs_only,
        check_snapshot_carries_the_fingerprint,
        check_the_lede_counts_exactly_the_edits_section,
    ]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_digest_attribution():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
