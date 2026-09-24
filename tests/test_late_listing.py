"""Sleeper's late listings come off a finished week (lotg_support.late_listing).

A move completed after a week's last game shows on that week's matchup roster;
the week belongs to whoever held the player when it was played (user rule
2026-09-24). Pure-function tests, no exports needed.

Run: python tests/test_late_listing.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lotg_support.late_listing import undo_late_listings  # noqa: E402

# 2022 week 7's last game was Monday 2022-10-24.
END = "2022-10-24"


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _week():
    return [
        {"roster_id": 4, "starters": ["ryan"], "players": ["ryan", "b1", "doctson"],
         "players_points": {"ryan": 12.0, "b1": 3.0, "doctson": 0.0}},
        {"roster_id": 6, "starters": ["s6"], "players": ["s6", "white"],
         "players_points": {"s6": 9.0, "white": 7.5}},
        {"roster_id": 1, "starters": ["s1"], "players": ["s1"], "players_points": {"s1": 4.0}},
    ]


def test_a_wednesday_waiver_pickup_comes_off_the_week_just_ended():
    # Josh Doctson: Wed 2022-10-26 07:04 UTC waiver, adds Doctson / drops Matt Ryan.
    tx = [{"type": "waiver", "status": "complete", "status_updated": _ms("2022-10-26T07:04:19"),
           "adds": {"doctson": 4}, "drops": {"ryan": 4}}]
    out, chg = undo_late_listings(_week(), tx, END)
    r4 = next(m for m in out if m["roster_id"] == 4)
    assert "doctson" not in r4["players"] and "doctson" not in r4["players_points"]
    assert "ryan" in r4["players"]            # the dropped starter stays, as Sleeper left him
    assert chg == ["-doctson@r4"]


def test_a_tuesday_trade_gives_the_week_back_to_the_old_team():
    # Rachaad White: traded Tue 02:13 ET from roster 6's list... here the
    # receiver (1) was listed with him and his old team (6) was not.
    wk = _week()
    wk[1]["players"].remove("white")
    wk[2]["players"].append("white")
    wk[2]["players_points"]["white"] = 7.5
    wk[1]["players_points"].pop("white")
    tx = [{"type": "trade", "status": "complete", "status_updated": _ms("2022-10-25T06:13:06"),
           "adds": {"white": 1}, "drops": {"white": 6}}]
    out, chg = undo_late_listings(wk, tx, END)
    r1 = next(m for m in out if m["roster_id"] == 1)
    r6 = next(m for m in out if m["roster_id"] == 6)
    assert "white" not in r1["players"]
    assert "white" in r6["players"] and "white" not in r6["starters"]
    assert r6["players_points"]["white"] == 7.5   # Sleeper's own score, carried over
    assert sorted(chg) == ["+white@r6", "-white@r1"]


def test_a_restored_player_with_no_listed_score_uses_the_fallback():
    # 2021: a player dropped after the week left the list entirely (Crowder).
    tx = [{"type": "waiver", "status": "complete", "status_updated": _ms("2022-10-26T07:05:50"),
           "adds": {}, "drops": {"crowder": 1}}]
    out, _ = undo_late_listings(_week(), tx, END, points_fallback=lambda p: 6.2)
    r1 = next(m for m in out if m["roster_id"] == 1)
    assert r1["players_points"]["crowder"] == 6.2
    out, _ = undo_late_listings(_week(), tx, END)
    assert next(m for m in out if m["roster_id"] == 1)["players_points"]["crowder"] == 0.0


def test_moves_inside_the_week_are_left_alone():
    # Monday 19:48 ET (Tue 00:48 UTC) is still the week: Philip Rivers, 2025 wk14.
    tx = [{"type": "free_agent", "status": "complete", "created": _ms("2022-10-24T23:48:00"),
           "status_updated": _ms("2022-10-24T23:48:00"), "adds": {"doctson": 4}, "drops": None}]
    wk = _week()
    out, chg = undo_late_listings(wk, tx, END)
    assert chg == [] and out[0]["players"] == wk[0]["players"]


def test_failed_moves_and_frozen_starters_do_not_change_anything():
    tx = [{"type": "waiver", "status": "failed", "status_updated": _ms("2022-10-26T07:04:19"),
           "adds": {"doctson": 4}},
          {"type": "waiver", "status": "complete", "status_updated": _ms("2022-10-26T07:04:19"),
           "adds": {"ryan": 4}}]           # a starter Sleeper froze into the lineup stays
    out, chg = undo_late_listings(_week(), tx, END)
    assert chg == [] and "doctson" in out[0]["players"] and "ryan" in out[0]["players"]


def test_the_input_is_never_mutated():
    wk = _week()
    tx = [{"type": "waiver", "status": "complete", "status_updated": _ms("2022-10-26T07:04:19"),
           "adds": {"doctson": 4}}]
    undo_late_listings(wk, tx, END)
    assert "doctson" in wk[0]["players"]


if __name__ == "__main__":
    for _fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        _fn()
        print("ok:", _fn.__name__)
