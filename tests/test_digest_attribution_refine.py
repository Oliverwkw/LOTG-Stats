"""Digest "new data vs edits" refinements (user, 2026-09-30).

1. A past transaction/pick row whose stint is over can't take in new data, so a
   move on it is an edit even when its team made a move this week.
2. An all-time total that is a pure sum of week rows is new data only if this
   week's new rows actually added to it for that entity.

Run: PYTHONPATH=src:lib python tests/test_digest_attribution_refine.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from lotg_support import digest as D              # noqa: E402
from lotg_support import email_summary as DS      # noqa: E402


def test_closed_event_keys():
    fr = {
        "add_drops": pd.DataFrame([
            {"Team": "A", "Date": "2020-12-04 10:00:00", "Player Added": "Kirk Cousins",
             "Player Dropped": "", "Date dropped/traded": "2021-01-02"},
            {"Team": "A", "Date": "2025-09-04 10:00:00", "Player Added": "Still Here",
             "Player Dropped": "", "Date dropped/traded": ""}]),
        "player_additions": pd.DataFrame([
            {"Player": "Rookie Kept", "Team": "B", "Addition type": "Draft", "Date": "2023-06-01",
             "Date dropped/traded": ""},
            {"Player": "Rookie Cut", "Team": "B", "Addition type": "Draft", "Date": "2023-06-01",
             "Date dropped/traded": "2023-10-01"}]),
        "rookie_picks": pd.DataFrame([
            {"Year": 2023, "Number": "1.01", "Player Picked": "Rookie Kept", "Team": "B"},
            {"Year": 2023, "Number": "1.02", "Player Picked": "Rookie Cut", "Team": "B"},
            {"Year": 2028, "Number": "1.??", "Player Picked": "Unknown", "Team": "B"}]),
        "trades": pd.DataFrame([
            {"Team": "C", "Date": "2021-05-01 10:00:00", "Assets retained now": "",
             "Avg PPG of received players on team": 12.0},
            {"Team": "C", "Date": "2025-05-01 10:00:00", "Assets retained now": "",
             "Avg PPG of received players on team": None},
            {"Team": "C", "Date": "2020-05-01 10:00:00", "Assets retained now": "X",
             "Avg PPG of received players on team": 9.0}]),
    }
    closed = D.closed_event_keys(fr, today=dt.date(2026, 9, 30))
    key = lambda s, i: D._board_row_key(s, fr[s].iloc[i])
    assert key("add_drops", 0) in closed and key("add_drops", 1) not in closed
    assert key("player_additions", 1) in closed and key("player_additions", 0) not in closed
    assert key("rookie_picks", 1) in closed
    assert key("rookie_picks", 0) not in closed and key("rookie_picks", 2) not in closed
    assert key("trades", 0) in closed                       # nothing kept, a player came back
    assert key("trades", 1) not in closed                   # picks-only, sent window still open
    assert key("trades", 2) not in closed                   # something still retained


def _nd(**kw):
    base = dict(season=2026, weeks_completed=4, edit_landed=True)
    base.update(kw)
    return DS.NewData(**base)


def test_closed_old_move_is_an_edit_even_when_its_team_moved():
    ev = D.EventCrossing("add_drops", "A's 2020-12-04 move for Kirk Cousins",
                         "Player addition value", "high", 1, 97.9, key="K1")
    open_nd = _nd(tx_teams={"A"}, tx_players={"Someone"})
    closed_nd = _nd(tx_teams={"A"}, tx_players={"Someone"}, closed_keys={"K1"})
    title = "All-time leaderboard moves — add/drops"
    assert DS.attribute(ev, title, open_nd) == "new"        # old behaviour kept for open stints
    assert DS.attribute(ev, title, closed_nd) == "edit"


def test_alltime_sum_needs_new_rows_behind_it():
    cr = D.Crossing("teams", "Hardship", "high", 2, "plehv79", 1300.0)
    title = "All-time leaderboard moves — teams"
    played = dict(new_weeks={(2026, 4)}, teams={"plehv79"}, players=set())
    with_rows = _nd(additive={"teams": {"Hardship"}},
                    contrib={("teams", "plehv79", "Hardship"): 12.5}, **played)
    no_rows = _nd(additive={"teams": {"Hardship"}}, contrib={}, **played)
    not_additive = _nd(additive={"teams": set()}, contrib={}, **played)
    assert DS.attribute(cr, title, with_rows) == "new"
    assert DS.attribute(cr, title, no_rows) == "edit"
    assert DS.attribute(cr, title, not_additive) == "new"   # rates etc.: old rule


def test_additivity_detection():
    tw = pd.DataFrame({"Team": ["A", "A", "B", "B"], "Year": [2026] * 4, "Week": [3, 4, 3, 4],
                       "Hardship": [1.0, 2.0, 3.0, 0.0], "Luck": [0.1, 0.2, 0.3, 0.4]})
    ta = pd.DataFrame({"Team": ["A", "B"], "Hardship": [3.0, 3.0], "Luck": [0.15, 0.35]})
    add, contrib = D.alltime_week_contributions({"team_all_time": ta, "team_week": tw}, {(2026, 4)})
    assert add["teams"] == {"Hardship"}                     # a sum; Luck is an average
    assert contrib == {("teams", "A", "Hardship"): 2.0}     # B added 0 in week 4


if __name__ == "__main__":
    test_closed_event_keys()
    test_closed_old_move_is_an_edit_even_when_its_team_moved()
    test_alltime_sum_needs_new_rows_behind_it()
    test_additivity_detection()
    print("ok")
