"""ESPN's injury timelines: what counts as season-ending, the date -> NFL week
mapping, the daily file and its change log, and what the forecast does with them.

Why (2026-11-15): Sleeper says a player is hurt but never for how long, so a
torn ACL returned on the same curve as a sprained ankle until someone wrote a
research row by hand. ESPN's public API dates every listed player's return; the
daily workflow (.github/workflows/espn_injuries.yml) captures it without Claude.
The trap these tests pin: ESPN's after-season date (2027-02-15 for 2026) is used
for "no timeline" too (Jayden Reed), so the date alone must never end a season.

Pure-logic tests need no data; the rest SKIP without exports/ or the capture.

Run: python tests/test_espn_injuries.py
"""
from __future__ import annotations

import csv
import dataclasses
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import espn_injuries as E  # noqa: E402
from lotg_support import forecast as F  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import ir_status as IR  # noqa: E402

_HAVE_SCHEDULE = (_ROOT / ".cache" / "nfldata_games.csv").exists()
_HAVE_DATA = ((_ROOT / "exports" / "team_week.csv").exists()
              and (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists())


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _item(status="Injured Reserve", ret="2027-02-15", short="", long="", type_="Knee", detail=""):
    return {"status": status, "shortComment": short, "longComment": long,
            "details": {"returnDate": ret, "type": type_, "detail": detail}}


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_the_after_season_date_alone_does_not_end_a_season():
    reed = _item(type_="Neck", short="Reed remains without a clear timeline for a return.")
    assert E.classify(reed, 2026) == (False, "")


def test_season_ending_needs_the_date_and_a_reason():
    words = _item(short="Noel will miss the remainder of the season.", type_="Toe")
    assert E.classify(words, 2026)[0]
    acl = _item(short="The Dolphins placed Achane (knee) on injured reserve Monday.", detail="ACL")
    assert E.classify(acl, 2026) == (True, "acl tear")
    # the same words with an in-season date: an estimate, not the end
    assert not E.classify(_item(ret="2026-12-13", short="haven't ruled out season-ending surgery"), 2026)[0]
    # a Questionable player is never season-ending, whatever the date
    assert not E.classify(_item(status="Questionable", short="season-ending"), 2026)[0]


def test_after_season_is_february_of_the_next_year():
    assert E.after_season(date(2027, 2, 15), 2026)
    assert not E.after_season(date(2027, 1, 17), 2026)


def test_a_reset_returns_him_on_the_first_week_hazard():
    """Held out 3 weeks by an estimated date: in week 4 he comes back at the
    curve's first-week rate, not the much lower rate for a 3-week absence."""
    model = F.InjuryModel(recovery=(0.6, 0.3, 0.1, 0.05), tail=0.02, mean_duration=3.0,
                          spells=1, seasons=())
    args = (np.random.default_rng(5), 4000, 5, np.array([0.9, 0.9]), np.zeros(2, dtype=bool),
            np.array([0, 0]), model)
    paths = F._injury_paths(*args, lock=np.array([3, 3]), reset=np.array([True, False]))
    assert not paths[:, :3, :].any()
    dated, held = paths[:, 3, 0].mean(), paths[:, 3, 1].mean()
    assert abs(dated - 0.6) < 0.03, dated
    assert held < 0.1, held


def test_a_reset_on_ir_uses_the_first_eligible_game():
    irm = IR.IRReturnModel(recovery=(0.4, 0.1), tail=0.02, runs=1, returned=1, seasons=())
    model = F.InjuryModel(recovery=(0.5,) * 8, tail=0.5, mean_duration=3.0, spells=1, seasons=())
    paths = F._injury_paths(np.random.default_rng(6), 4000, 8, np.array([0.9]), np.zeros(1, dtype=bool),
                            np.array([1]), model, ir_games=np.array([1]), ir_model=irm, year=2026,
                            lock=np.array([6]), reset=np.array([True]))
    assert not paths[:, :6, 0].any()
    assert abs(paths[:, 6, 0].mean() - 0.4) < 0.03, paths[:, 6, 0].mean()


def test_the_log_records_changes_only():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        row = {c: "" for c in E.CURRENT_COLUMNS} | {
            "season": 2026, "sleeper_id": "1", "espn_id": "9", "player": "A B", "position": "WR",
            "status": "Out", "return_date": "2026-11-22", "return_week": 11,
            "season_ending": "false", "captured_at_utc": "2026-11-15T14:30:00+00:00"}
        assert E.write([row], root) == (1, 1)
        assert E.write([row | {"captured_at_utc": "2026-11-16T14:30:00+00:00"}], root) == (1, 0)
        assert E.write([row | {"status": "Injured Reserve", "return_date": "2026-12-20",
                               "return_week": 15}], root) == (1, 1)
        other = row | {"sleeper_id": "2", "captured_at_utc": "2026-11-18T14:30:00+00:00"}
        assert E.write([other], root) == (1, 2), "player 1 left the list: logged as Active"
        with E.log_path(root).open() as f:
            log = list(csv.DictReader(f))
        assert [r["status"] for r in log] == ["Out", "Injured Reserve", "Out", "Active"]
        assert log[-1]["sleeper_id"] == "1" and log[-1]["first_seen_utc"].startswith("2026-11-18")
        assert set(E.current(2026, root)) == {"2"}


# ---------------------------------------------------------------------------
# Against the league's data
# ---------------------------------------------------------------------------
def test_return_dates_map_to_nfl_weeks():
    if not _HAVE_SCHEDULE:
        return _skip("no .cache/nfldata_games.csv")
    assert E.week_of(date(2026, 11, 29), 2026) == 12       # a Sunday
    assert E.week_of(date(2026, 11, 25), 2026) == 12       # the Wednesday before Thanksgiving
    last = E._week_ends(2026, str(_ROOT))[-1][0]
    assert E.week_of(date(2027, 1, 17), 2026) == last + 1, "a January date is past every week"
    assert E.week_of(date(2027, 2, 15), 2026) is None


def test_the_committed_capture_is_mapped_by_id():
    if not (_HAVE_DATA and E.current_path(_ROOT).exists()):
        return _skip("no capture / exports")
    with E.current_path(_ROOT).open() as f:
        rows = list(csv.DictReader(f))
    assert rows, "empty capture"
    ids = [r["sleeper_id"] for r in rows]
    assert len(ids) == len(set(ids)), "a player listed twice"
    players = Q.players()
    for r in rows:
        assert r["position"] in E.FANTASY_POSITIONS, r
        assert Q._normalize(r["player"]) == Q._normalize(players.name(r["sleeper_id"])), r
        if r["season_ending"] == "true":
            assert r["evidence"] and not r["return_week"], r
    share_id = sum(r["matched_by"] == "id" for r in rows) / len(rows)
    assert share_id > 0.9, f"only {share_id:.0%} matched by id"


def test_a_live_forecast_holds_espn_players_out():
    if not (_HAVE_DATA and E.current_path(_ROOT).exists()):
        return _skip("no capture / exports")
    live = [y for y in Q.snapshot_seasons() if not Q.season_meta(y).is_complete]
    if not live or not Q.played_weeks(max(live)):
        return _skip("no live season under way")
    year = max(live)
    rows, note = F._espn_timelines(year, 1, F.AvailabilityModel().espn_max_age_days)
    if not rows:
        return _skip(note or "capture is for another season")
    fc = F.forecast(year, sims=300, availability=dataclasses.replace(F.AvailabilityModel(), draws=150))
    assert fc.espn_timelines, "a live capture applied to nobody"
    start = fc.availability_from_week
    for pid, label in fc.espn_timelines.items():
        v, es = fc.player_availability[pid], rows[pid]
        if es.season_ending:
            assert not any(v), (label, v)
        else:
            assert not any(v[:es.return_week - start]), (label, v)
    # a research row wins over ESPN
    for pid in F.research_overrides(year):
        assert pid not in fc.espn_timelines or F.research_overrides(year)[pid].out_through_week is None


def test_the_build_does_not_import_espn_injuries():
    hits = []
    for path in list((_ROOT / "src").rglob("*")) + [_ROOT / ".github" / "workflows" / "build.yml"]:
        if path.is_file() and "espn_injuries" in path.read_text(errors="ignore"):
            hits.append(str(path.relative_to(_ROOT)))
    assert not hits, hits


TESTS = [
    test_the_after_season_date_alone_does_not_end_a_season,
    test_season_ending_needs_the_date_and_a_reason,
    test_after_season_is_february_of_the_next_year,
    test_a_reset_returns_him_on_the_first_week_hazard,
    test_a_reset_on_ir_uses_the_first_eligible_game,
    test_the_log_records_changes_only,
    test_return_dates_map_to_nfl_weeks,
    test_the_committed_capture_is_mapped_by_id,
    test_a_live_forecast_holds_espn_players_out,
    test_the_build_does_not_import_espn_injuries,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall ESPN injury checks passed")
