"""Synthetic in-season week for the injury tracker (data/injury_tracker.csv).

The tracker's first real capture is 2026 week 1, so nothing in the committed
exports exercises it. This drives a whole synthetic week through the REAL code
path the build uses — Sleeper snapshot -> capture_rows -> CSV -> load_status_index
-> apply_overlay — with a fixture NFL schedule in nflverse's own spelling, and
asserts the two rules the sheet has to get right:

  * only a designation that GUARANTEES he did not play flags a week — a game-day
    inactive (Out, Sus) or a reserve list he is ineligible to play from (IR, PUP,
    NFI, COV, DNR) — and not Questionable, Doubtful, Practice Squad or a bare
    0.00, and
  * a player who TOOK THE FIELD is never flagged, however the week ended for him.

The named case is Xavier Worthy, 2025 week 1: hurt on the opening drive, 1
target, 0 catches, 0.0 points, "Out" for the two weeks after. nflverse carries a
week-1 stat line for him and none for weeks 2-3, which is exactly the shape the
overlay has to respect — flagging his week 1 would be inventing an injury week
out of a game he played in.

Run directly (`python tests/test_injury_tracker.py`) to print the week as the
sheet would see it, or via pytest.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import injury_tracker as it  # noqa: E402

UTC = timezone.utc

# --------------------------------------------------------------------------
# Fixture schedule — nflverse spelling ("LA", not Sleeper's "LAR"), which is the
# mismatch that used to put every Rams player on a bye every week of the season.
# Week 1 mirrors the real 2026 schedule: 16 games, nobody on a bye. Week 11 is
# the Rams' real 2026 bye.
# --------------------------------------------------------------------------
_ALL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
]
_BYE_WK11 = {"NE", "GB", "ATL", "CLE", "LA", "SEA"}

_SCHEDULE = {
    1: {"teams": {it.normalize_team(t) for t in _ALL_TEAMS},
        "first": datetime(2026, 9, 9).date(), "last": datetime(2026, 9, 14).date()},
    11: {"teams": {it.normalize_team(t) for t in _ALL_TEAMS if t not in _BYE_WK11},
         "first": datetime(2026, 11, 19).date(), "last": datetime(2026, 11, 23).date()},
}


def _fixture_schedule(season, timeout=30):
    return dict(_SCHEDULE) if int(season) == 2026 else {}


def _fixture_teams_playing(season, week, timeout=30):
    info = _fixture_schedule(season).get(int(week))
    return set(info["teams"]) if info else set()


@contextmanager
def _fixture_nfl_schedule():
    """Swap the live schedule fetch for the fixture, and put back whatever was
    there. Both are restored because a sibling test module patches
    `teams_playing` at import scope and never undoes it — under pytest these
    share a process, so a test that silently inherited that patch would be
    asserting against someone else's schedule."""
    saved = (it._fetch_schedule, it.teams_playing)
    it._fetch_schedule, it.teams_playing = _fixture_schedule, _fixture_teams_playing
    try:
        yield
    finally:
        it._fetch_schedule, it.teams_playing = saved


# --------------------------------------------------------------------------
# The synthetic week: one Sleeper roster, every designation the sheet can meet.
# (id, name, pos, team, injury_status, status, took_the_field, points,
#  expected (Injury?, Suspension?, Bye?), why)
# --------------------------------------------------------------------------
WEEK = [
    ("worthy", "Xavier Worthy", "WR", "KC", "Out", "Active", True, 0.0,
     (False, False, False), "hurt in the game he played: 0.0 pts but he played"),
    ("hurt_late", "Played Through", "RB", "DAL", "Out", "Active", True, 14.2,
     (False, False, False), "played and scored, then labelled Out"),
    ("fumbler", "Negative Night", "RB", "CHI", "Out", "Active", True, -2.0,
     (False, False, False), "negative points is still a played week"),
    ("out_rb", "Sat Out", "RB", "DEN", "Out", "Inactive", False, 0.0,
     (True, False, False), "Out and never took the field"),
    ("ir_te", "On IR", "TE", "MIA", "IR", "Injured Reserve", False, 0.0,
     (True, False, False), "IR"),
    ("ir_r_te", "IR Return", "TE", "NYJ", "IR-R", "Injured Reserve", False, 0.0,
     (True, False, False), "IR-R designated to return"),
    ("pup_wr", "On PUP", "WR", "TEN", "PUP", "Physically Unable to Perform", False, 0.0,
     (True, False, False), "PUP"),
    ("sus_wr", "Suspended", "WR", "CIN", "Sus", "Suspended", False, 0.0,
     (False, True, False), "suspension, not injury"),
    ("quest_played", "Questionable Played", "RB", "SF", "Questionable", "Active", True, 0.0,
     (False, False, False), "Questionable, played, caught nothing"),
    ("quest_sat", "Questionable Scratched", "WR", "PIT", "Questionable", "Active", False, 0.0,
     (False, False, False), "Questionable is a game-time label, not a miss"),
    ("doubtful", "Doubtful Sort", "WR", "BUF", "Doubtful", "Active", False, 0.0,
     (False, False, False), "Doubtful alone does not flag"),
    ("covid", "Covid List", "TE", "MIN", "COV", "Inactive", False, 0.0,
     (True, False, False), "COV reserve list: ineligible to play"),
    ("nfi", "Non Football", "RB", "NO", "", "Non Football Injury", False, 0.0,
     (True, False, False), "NFI reserve list: ineligible to play"),
    ("dnr", "Did Not Report", "WR", "LV", "DNR", "Active", False, 0.0,
     (True, False, False), "DNR: on the did-not-report list, cannot play"),
    ("na_tag", "Ambiguous NA", "TE", "IND", "NA", "Active", False, 0.0,
     (False, False, False), "NA guarantees nothing — 26 carry it while Active"),
    ("prac_squad", "Practice Squad", "QB", "ATL", "", "Practice Squad", False, 0.0,
     (False, False, False), "practice squad can be elevated and play"),
    ("no_nfl_team", "Cut Loose", "RB", "JAX", "", "Inactive", False, 0.0,
     (False, False, False), "roster status, not a game-day inactive"),
    ("healthy_bench", "Healthy Backup", "QB", "PHI", "", "Active", False, 0.0,
     (False, False, False), "healthy scratch: the old default-to-injury guess"),
    ("rams_star", "Rams Starter", "WR", "LAR", "", "Active", True, 12.4,
     (False, False, False), "LAR vs nflverse LA — must not be a bye"),
    ("rams_zero", "Rams Backup", "RB", "LAR", "", "Active", False, 0.0,
     (False, False, False), "LAR, scoreless, still not a bye and not injured"),
]

# Week 11: the Rams' real 2026 bye, plus a KC player who is not on one.
WEEK11 = [
    ("rams_zero", "Rams Backup", "RB", "LAR", "", "Active", False, 0.0,
     (False, False, True), "real bye, via the normalized team code"),
    ("rams_out", "Rams Injured", "WR", "LAR", "Out", "Inactive", False, 0.0,
     (False, False, True), "bye beats injury"),
    ("out_rb", "Sat Out", "RB", "DEN", "Out", "Inactive", False, 0.0,
     (True, False, False), "no bye for DEN in week 11"),
]


class _MockSleeper:
    """Just the three endpoints capture_rows touches."""

    def __init__(self, week_spec):
        self.spec = {p[0]: p for p in week_spec}

    def players_nfl(self):
        return {pid: {"full_name": n, "position": pos, "team": team,
                      "injury_status": inj, "status": st}
                for (pid, n, pos, team, inj, st, _pl, _pts, _exp, _why) in self.spec.values()}

    def rosters(self):
        return [{"players": list(self.spec), "starters": [], "taxi": [], "reserve": []}]

    def get(self, path):
        p = str(path)
        if "/state/nfl" in p:
            return {"season": "2026", "week": 1, "season_type": "regular"}
        if "/stats/nfl/" in p:
            # Sleeper's live weekly stats: `gp` for everyone who dressed.
            return {pid: {"gp": 1, "off_snp": 21} for pid, s in self.spec.items() if s[6]}
        return None


def _run_week(week_spec, week_no):
    """Capture -> CSV -> load -> overlay, returning [(spec, got_triple)]."""
    sc = _MockSleeper(week_spec)
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        rows = it.capture_rows(sc, 2026, week_no)
        it.merge_into_csv(root, rows)
        it.merge_into_csv(root, rows)   # a re-run must replace, not duplicate
        idx = it.load_status_index(root)
        out = []
        for spec in week_spec:
            pid, _n, _pos, _team, _inj, _st, _played, pts = spec[:8]
            entry = idx[(pid, 2026, week_no)]
            # What the build hands the overlay: its own bye read (from the same
            # schedule) and the default-to-injury guess for a scoreless,
            # unplayed, non-bye week — the guess the tracker exists to settle.
            build_bye = entry["bye"] is True
            build_inj = (pts == 0.0) and not build_bye
            got = it.apply_overlay(entry, pts, entry.get("played"),
                                   build_inj, False, build_bye)
            out.append((spec, got, rows))
        return out, {r["player_id"]: r for r in rows}


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_synthetic_week_flags():
    results, _ = _run_week(WEEK, 1)
    for spec, got, _ in results:
        want = spec[8]
        assert got == want, f"{spec[1]} ({spec[9]}): expected {want}, got {got}"


def test_synthetic_bye_week_flags():
    results, _ = _run_week(WEEK11, 11)
    for spec, got, _ in results:
        want = spec[8]
        assert got == want, f"{spec[1]} ({spec[9]}): expected {want}, got {got}"


def test_rams_are_not_on_a_bye_every_week():
    """The LA/LAR mismatch: nflverse spells the Rams 'LA', Sleeper 'LAR'."""
    _, rows = _run_week(WEEK, 1)
    assert rows["rams_star"]["nfl_team"] == "LAR"
    assert rows["rams_star"]["on_bye"] == "false"
    assert rows["rams_zero"]["on_bye"] == "false"
    assert rows["worthy"]["on_bye"] == "false"
    _, rows11 = _run_week(WEEK11, 11)
    assert rows11["rams_zero"]["on_bye"] == "true"    # their real 2026 bye
    assert rows11["out_rb"]["on_bye"] == "false"


def test_participation_is_captured():
    _, rows = _run_week(WEEK, 1)
    assert rows["worthy"]["played"] == "true"
    assert rows["out_rb"]["played"] == ""
    # Sleeper only ever CONFIRMS participation, so a missing/failed feed must
    # not read as "did not play".
    assert {r["played"] for r in rows.values()} <= {"true", ""}


def test_nflverse_fallback_clears_when_sleeper_has_no_participation():
    """Sleeper's stats feed is down; nflverse's played set carries the week."""
    entry = {"status": "out inactive", "bye": False, "played": None}
    assert it.apply_overlay(entry, 0.0, True, True, False, False) == (False, False, False)
    assert it.apply_overlay(entry, 0.0, False, False, False, False) == (True, False, False)
    # Neither source knows yet (the Tuesday build, before nflverse lands).
    assert it.apply_overlay(entry, 0.0, None, False, False, False) == (True, False, False)


def test_designations():
    # Guarantees he did not play: a game-day inactive, or a reserve list he is
    # ineligible to play from.
    for s in ("out", "ir", "ir-r", "pup", "injured reserve", "physically unable to perform",
              "out inactive", "ir injured reserve", "cov", "cov inactive", "covid",
              "reserve/covid-19", "nfi", "non football injury", "dnr", "did not report"):
        assert it.designation(s) == "injury", s
    for s in ("sus", "susp inactive", "suspended"):
        assert it.designation(s) == "suspension", s
    # Guarantees nothing: game-time labels, an elevatable practice squad, a
    # roster status, and Sleeper's ambiguous NA.
    for s in ("", "active", "questionable", "questionable active", "doubtful",
              "doubtful active", "na", "na active", "inactive", "practice squad",
              "practice squad na"):
        assert it.designation(s) is None, s


def test_a_real_bye_survives_an_injury_designation():
    """Bye wins: an Out player whose team was idle is a bye week, not an injury."""
    entry = {"status": "out inactive", "bye": True, "played": None}
    assert it.apply_overlay(entry, 0.0, None, False, False, False) == (False, False, True)
    # ...and a bye the BUILD derived is never overwritten by the tracker.
    entry2 = {"status": "out inactive", "bye": None, "played": None}
    assert it.apply_overlay(entry2, 0.0, None, False, False, True) == (False, False, True)


def test_team_normalization():
    assert it.normalize_team("LA") == "LAR" and it.normalize_team("LAR") == "LAR"
    assert it.normalize_team("OAK") == "LV" and it.normalize_team("SD") == "LAC"
    assert it.normalize_team("WSH") == "WAS" and it.normalize_team("") == ""


def test_week_is_derived_from_the_schedule_not_sleeper_state():
    with _fixture_nfl_schedule():
        # The Tuesdays before kickoff: no regular-season week has started.
        assert it.week_from_schedule(2026, datetime(2026, 9, 1, 5, 0, tzinfo=UTC)) is None
        assert it.week_from_schedule(2026, datetime(2026, 9, 8, 5, 0, tzinfo=UTC)) is None
        # The capture that closes week 1 — hours after a Monday night game that ran
        # past midnight UTC.
        assert it.week_from_schedule(2026, datetime(2026, 9, 15, 5, 0, tzinfo=UTC)) == 1
        # Still week 1 through the rest of that week; week 11 once it kicks off.
        assert it.week_from_schedule(2026, datetime(2026, 9, 16, 5, 0, tzinfo=UTC)) == 1
        assert it.week_from_schedule(2026, datetime(2026, 11, 24, 5, 0, tzinfo=UTC)) == 11
        assert it.week_from_schedule(2027, datetime(2027, 9, 15, 5, 0, tzinfo=UTC)) is None


def test_missing_weeks_and_dedup():
    sc = _MockSleeper(WEEK)
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.merge_into_csv(root, it.capture_rows(sc, 2026, 1))
        it.merge_into_csv(root, it.capture_rows(sc, 2026, 3))
        it.merge_into_csv(root, it.capture_rows(sc, 2026, 3))   # replace, not append
        assert it.weeks_present(root, 2026) == {1, 3}
        assert it.missing_weeks(root, 2026, 4) == [2, 4]
        assert len(it.load_status_index(root)) == 2 * len(WEEK)


def test_season_from_date():
    assert it.season_from_date(datetime(2026, 9, 15).date()) == 2026
    assert it.season_from_date(datetime(2027, 1, 5).date()) == 2026   # week 18 tail


# --------------------------------------------------------------------------
def _render():
    """Print the synthetic week as the sheet would see it."""
    for week_no, spec in ((1, WEEK), (11, WEEK11)):
        results, rows = _run_week(spec, week_no)
        print(f"\n=== SYNTHETIC 2026 WEEK {week_no} "
              f"({'16 games, no byes' if week_no == 1 else 'LAR/SEA/NE/GB/ATL/CLE on bye'}) ===")
        print(f"{'Player':<24}{'Tm':<5}{'Sleeper':<24}{'Pts':>7}{'Plyd':>6}"
              f"{'Inj':>7}{'Susp':>6}{'Bye':>6}   why")
        for (pid, name, _pos, team, inj_st, st, _pl, pts, want, why), got, _ in results:
            mark = "" if got == want else "   <-- MISMATCH"
            print(f"{name:<24}{team:<5}{(inj_st + '/' + st)[:23]:<24}{pts:>7}"
                  f"{rows[pid]['played'] or '-':>6}"
                  f"{str(got[0]):>7}{str(got[1]):>6}{str(got[2]):>6}   {why}{mark}")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    _render()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
