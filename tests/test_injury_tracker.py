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

# Week 1's real 2026 gamedays: a WEDNESDAY opener, then Thu / Sun / Mon.
_SCHEDULE = {
    1: {"teams": {it.normalize_team(t) for t in _ALL_TEAMS},
        "days": {datetime(2026, 9, d).date() for d in (9, 10, 13, 14)},
        "first": datetime(2026, 9, 9).date(), "last": datetime(2026, 9, 14).date()},
    11: {"teams": {it.normalize_team(t) for t in _ALL_TEAMS if t not in _BYE_WK11},
         "days": {datetime(2026, 11, d).date() for d in (19, 22, 23)},
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
        it.merge_into_csv(root, rows)   # a --force re-run must replace, not duplicate
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


def test_a_curated_flag_is_never_cleared_or_reclassified():
    """data/suspensions.csv and data/injuries.csv are hand-written because no
    feed reports the fact — nflverse's game-status report does not list suspended
    players at all, and Sleeper carries "Sus" for ten players league-wide and only
    while it is current. So an all-clear tracker week must leave a curated week
    exactly as the human wrote it, or the next commissioner-added suspension
    silently stops existing the moment the tracker covers its weeks."""
    clear = {"status": "active", "bye": False, "played": None}
    # Rashee Rice 2025 wks 1-6 is the live shape: curated suspension, Sleeper Active.
    assert it.apply_overlay(clear, 0.0, None, False, True, False, curated=True) == (False, True, False)
    assert it.apply_overlay(clear, 0.0, None, True, False, False, curated=True) == (True, False, False)
    # ...and the tracker may not RECLASSIFY it either (curated suspension, Sleeper IR).
    ir = {"status": "ir injured reserve", "bye": False, "played": None}
    assert it.apply_overlay(ir, 0.0, None, False, True, False, curated=True) == (False, True, False)
    # Uncurated is unchanged: the tracker still decides those outright.
    assert it.apply_overlay(clear, 0.0, None, True, False, False, curated=False) == (False, False, False)
    assert it.apply_overlay(clear, 0.0, None, False, True, False, curated=False) == (False, False, False)
    # A bye still outranks a curated week, exactly as it does everywhere else.
    on_bye = {"status": "active", "bye": True, "played": None}
    assert it.apply_overlay(on_bye, 0.0, None, False, True, False, curated=True) == (False, False, True)
    # A player who took the field is still not flagged, curated or not — but the
    # curated week is left alone rather than overwritten with a guess.
    assert it.apply_overlay(clear, 0.0, True, False, True, False, curated=True) == (False, True, False)
    # curated defaults to False, so every existing caller keeps its behaviour.
    assert it.apply_overlay(clear, 0.0, None, True, False, False) == (False, False, False)


def test_the_tracker_is_forward_only():
    """2025 and earlier were built by the nflverse/meta process and keep its
    flags. A row for one of those seasons is dropped on load, so no capture — a
    mistaken `--season 2024`, a hand-edited CSV — can reach back into a season
    that is already published."""
    sc = _MockSleeper(WEEK)
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        rows = it.capture_rows(sc, 2026, 1)
        old = [dict(r, season=2025) for r in rows] + [dict(r, season=2020) for r in rows]
        it.merge_into_csv(root, old + rows)
        idx = it.load_status_index(root)
        assert {k[1] for k in idx} == {2026}, sorted({k[1] for k in idx})
        assert len(idx) == len(WEEK)
    assert it.TRACKER_FIRST_SEASON == 2026


def test_the_schedule_stops_at_the_regular_season():
    """games.csv carries the postseason as weeks 19-22 (WC/DIV/CON/SB). Filing
    those would put four junk blocks a season in the CSV — and `on_bye` for a
    playoff week marks every eliminated team as being on a bye."""
    import types
    csv_text = (
        "season,game_type,week,gameday,away_team,home_team\n"
        "2026,REG,1,2026-09-10,LA,SEA\n"
        "2026,REG,18,2027-01-10,SEA,LA\n"
        "2026,WC,19,2027-01-16,LA,SEA\n"
        "2026,DIV,20,2027-01-23,LA,SEA\n"
        "2026,CON,21,2027-01-30,LA,SEA\n"
        "2026,SB,22,2027-02-13,LA,SEA\n"
    )
    fake = types.SimpleNamespace(
        get=lambda url, timeout=30: types.SimpleNamespace(
            text=csv_text, raise_for_status=lambda: None))
    saved_mod, saved_cache = sys.modules.get("requests"), dict(it._SCHEDULE_CACHE)
    sys.modules["requests"] = fake
    it._SCHEDULE_CACHE.clear()
    try:
        sched = it._fetch_schedule(2026)
        assert sorted(sched) == [1, 18], sorted(sched)
        assert sched[1]["days"] == {datetime(2026, 9, 10).date()}
        # Read off _fetch_schedule's own return rather than the module-global
        # teams_playing, which another test module is free to have replaced.
        assert sched[1]["teams"] == {"LAR", "SEA"}   # nflverse "LA" normalised
        # January, after week 18: the week does not creep into the playoffs.
        assert it.week_from_schedule(2026, datetime(2027, 1, 12, 5, 0, tzinfo=UTC)) == 18
        assert it.week_from_schedule(2026, datetime(2027, 1, 19, 5, 0, tzinfo=UTC)) == 18
        assert it.week_from_schedule(2026, datetime(2027, 2, 2, 5, 0, tzinfo=UTC)) == 18
    finally:
        it._SCHEDULE_CACHE.clear()
        it._SCHEDULE_CACHE.update(saved_cache)
        if saved_mod is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = saved_mod


def test_sleeper_state_only_shouts_at_a_real_disagreement():
    """Sleeper's state rolls to the next week some time after the Monday night
    game, so on a Tuesday capture it is normally one ahead. Warning on that every
    week would train us to ignore the one week it means something."""
    assert it.state_week_drift(5, 5) == "agree"
    assert it.state_week_drift(6, 5) == "rolled"     # the ordinary Tuesday picture
    assert it.state_week_drift(4, 5) == "drift"      # lagging: real
    assert it.state_week_drift(7, 5) == "drift"      # two ahead: real
    assert it.state_week_drift(None, 5) == "unknown"
    assert it.state_week_drift(5, None) == "unknown"


def test_sleepers_empty_roster_slot_is_not_a_player():
    """Sleeper pads `starters` with the string "0" for an unfilled slot (9 of them
    across the 2026 rosters). Capturing it writes a nameless, teamless row."""
    class _WithSentinel(_MockSleeper):
        def rosters(self):
            return [{"players": list(self.spec) + ["0"], "starters": ["0", "0"],
                     "taxi": [], "reserve": [None, ""]}]
    with _fixture_nfl_schedule():
        rows = it.capture_rows(_WithSentinel(WEEK), 2026, 1)
    assert {r["player_id"] for r in rows} == set(p[0] for p in WEEK)
    assert len(rows) == len(WEEK)


def test_the_committed_tracker_header_matches_the_schema():
    """The seed file is what the first capture merges into; a header that has
    drifted from TRACKER_COLUMNS is a schema disagreement sitting in the repo."""
    path = it.tracker_path(_ROOT)
    if not path.exists():
        return
    assert path.open().readline().strip().split(",") == it.TRACKER_COLUMNS


def test_a_gameday_sweep_merges_with_the_final_capture():
    """The J2 case, end to end. A player is Out for Sunday's game and the team
    clears the tag on Monday; the Tuesday capture sees nothing. The sweep taken on
    the gameday keeps the designation, and the final capture keeps participation —
    neither is allowed to wipe the other."""
    sunday = [("cleared_mon", "Cleared Monday", "RB", "DEN", "Out", "Inactive", False, 0.0,
               (True, False, False), "Out at kick-off, tag gone by Tuesday")]
    tuesday = [("cleared_mon", "Cleared Monday", "RB", "DEN", "", "Active", False, 0.0,
                (True, False, False), "Sleeper shows him Active two days later")]
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.merge_capture(root, it.capture_rows(_MockSleeper(sunday), 2026, 1), final=False)
        idx = it.load_status_index(root)
        assert it.designation(idx[("cleared_mon", 2026, 1)]["status"]) == "injury"

        it.merge_capture(root, it.capture_rows(_MockSleeper(tuesday), 2026, 1), final=True)
        entry = it.load_status_index(root)[("cleared_mon", 2026, 1)]
        # The designation the sweep saw survives the final capture...
        assert it.designation(entry["status"]) == "injury", entry
        assert it.apply_overlay(entry, 0.0, entry["played"], False, False, False) \
            == (True, False, False)
        # ...and the week is recorded as finalized, with both captures folded in.
        assert it.weeks_finalized(root, 2026) == {1}
        assert max(it.sweep_counts(root, 2026, 1)) == 2


def test_the_merge_never_lets_one_capture_wipe_another():
    """Column by column: designation from the strongest capture, participation
    from any capture that saw him play, identity from the newest."""
    # A sweep runs BEFORE the games, so its `played` is empty. Merging must not
    # let it erase the final capture's participation, or fix #1 stops working.
    played_final = [("worthy", "Xavier Worthy", "WR", "KC", "Out", "Active", True, 0.0,
                     (False, False, False), "")]
    sweep_only = [("worthy", "Xavier Worthy", "WR", "KC", "Out", "Active", False, 0.0,
                   (False, False, False), "")]
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.merge_capture(root, it.capture_rows(_MockSleeper(sweep_only), 2026, 1), final=False)
        it.merge_capture(root, it.capture_rows(_MockSleeper(played_final), 2026, 1), final=True)
        e = it.load_status_index(root)[("worthy", 2026, 1)]
        assert e["played"] is True, "the sweep wiped the final capture's participation"
        # Worthy: Out on the sheet AND played -> still not flagged.
        assert it.apply_overlay(e, 0.0, e["played"], True, False, False) == (False, False, False)

    # ...and the reverse: a final capture that lost the participation feed must
    # not erase a `played` an in-game sweep did see.
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.merge_capture(root, it.capture_rows(_MockSleeper(played_final), 2026, 1), final=False)
        it.merge_capture(root, it.capture_rows(_MockSleeper(sweep_only), 2026, 1), final=True)
        assert it.load_status_index(root)[("worthy", 2026, 1)]["played"] is True

    # Suspension outranks injury outranks clear, whichever order they arrive in.
    def _one(inj_st, st):
        return [("p", "P", "RB", "KC", inj_st, st, False, 0.0, (False, False, False), "")]
    for first, second, want in ((("", "Active"), ("Sus", "Active"), "suspension"),
                                (("Sus", "Active"), ("", "Active"), "suspension"),
                                (("Out", "Active"), ("", "Active"), "injury"),
                                (("", "Active"), ("Out", "Active"), "injury"),
                                (("Out", "Active"), ("Sus", "Active"), "suspension"),
                                (("Sus", "Active"), ("Out", "Active"), "suspension"),
                                (("", "Active"), ("", "Active"), None)):
        with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
            root = Path(d)
            it.merge_capture(root, it.capture_rows(_MockSleeper(_one(*first)), 2026, 1), final=False)
            it.merge_capture(root, it.capture_rows(_MockSleeper(_one(*second)), 2026, 1), final=True)
            got = it.designation(it.load_status_index(root)[("p", 2026, 1)]["status"])
            assert got == want, f"{first} then {second}: expected {want}, got {got}"

    # A player dropped mid-week is still in the week the sweep saw him in, and a
    # player added mid-week is added rather than replacing the block.
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.merge_capture(root, it.capture_rows(_MockSleeper(_one("Out", "Inactive")), 2026, 1), final=False)
        later = [("q", "Q", "WR", "SF", "", "Active", False, 0.0, (False, False, False), "")]
        it.merge_capture(root, it.capture_rows(_MockSleeper(later), 2026, 1), final=True)
        idx = it.load_status_index(root)
        assert {k[0] for k in idx} == {"p", "q"}, sorted(idx)
        assert it.designation(idx[("p", 2026, 1)]["status"]) == "injury"

    # --force still REPLACES, discarding what the sweeps saw. That is the point.
    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.merge_capture(root, it.capture_rows(_MockSleeper(_one("Out", "Inactive")), 2026, 1), final=False)
        it.merge_into_csv(root, it.capture_rows(_MockSleeper(_one("", "Active")), 2026, 1))
        assert it.designation(it.load_status_index(root)[("p", 2026, 1)]["status"]) is None


def test_a_sweep_runs_only_on_a_gameday():
    """The whole cost argument. The cron fires daily and the script decides, so
    the Wednesday opener and a rescheduled Tuesday game need no cron edit."""
    with _fixture_nfl_schedule():
        # The fixture's week 1 gamedays.
        assert it.gameday_week(2026, datetime(2026, 9, 10, 16, 0, tzinfo=UTC)) == 1
        assert it.gameday_week(2026, datetime(2026, 9, 13, 16, 0, tzinfo=UTC)) == 1
        # A Tuesday, and the week's off days: nothing to sweep.
        assert it.gameday_week(2026, datetime(2026, 9, 15, 16, 0, tzinfo=UTC)) is None
        assert it.gameday_week(2026, datetime(2026, 9, 16, 16, 0, tzinfo=UTC)) is None
        assert it.gameday_week(2026, datetime(2026, 11, 19, 16, 0, tzinfo=UTC)) == 11
        assert it.gameday_week(2027, datetime(2027, 9, 12, 16, 0, tzinfo=UTC)) is None
        # A night game that runs past midnight UTC belongs to its own gameday.
        assert it.gameday(datetime(2026, 9, 15, 3, 30, tzinfo=UTC)) == datetime(2026, 9, 14).date()
        assert it.gameday(datetime(2026, 9, 14, 16, 0, tzinfo=UTC)) == datetime(2026, 9, 14).date()


def test_a_midweek_nfl_trade_cannot_invent_a_bye():
    """on_bye is the one column the merge takes from the EARLIEST capture.

    A bye belongs to the team the player was on when the games were played. Every
    other column takes the newest capture, and this one must not: a trade landing
    between two captures of the same week makes the newest name the wrong team,
    and a bye is an outright override — it beats the build's own (correct)
    answer, and it drops the week from the played-week denominators, so the week
    does not read wrong, it disappears."""
    playing = {"KC", "SF", "BUF"}

    def _sched(season, timeout=30):
        return {5: {"teams": set(playing), "days": set(), "first": None, "last": None}}

    def _teams(season, week, timeout=30):
        return set(playing)

    class _Trade:
        def __init__(self, team, played=False, tag=("", "Active")):
            self.team, self.played, self.tag = team, played, tag

        def players_nfl(self):
            return {"x": {"full_name": "Traded Man", "position": "WR", "team": self.team,
                          "injury_status": self.tag[0], "status": self.tag[1]}}

        def rosters(self):
            return [{"players": ["x"], "starters": [], "taxi": [], "reserve": []}]

        def get(self, path):
            return {"x": {"gp": 1}} if ("/stats/nfl/" in str(path) and self.played) else None

    def _week(kickoff_team, tuesday_team, played, tag=("", "Active")):
        saved = (it._fetch_schedule, it.teams_playing)
        it._fetch_schedule, it.teams_playing = _sched, _teams
        try:
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                it.merge_capture(root, it.capture_rows(_Trade(kickoff_team, tag=tag), 2026, 5),
                                 final=False)
                it.merge_capture(root, it.capture_rows(
                    _Trade(tuesday_team, played=played, tag=tag), 2026, 5), final=True)
                entry = it.load_status_index(root)[("x", 2026, 5)]
        finally:
            it._fetch_schedule, it.teams_playing = saved
        build_bye = kickoff_team not in playing        # the build reads the kick-off team
        pl = True if entry["played"] is True else None
        return entry, it.apply_overlay(entry, 0.0, pl, False, False, build_bye)

    # Traded FROM a team that was idle TO one that played: he really was on a bye,
    # and the tracker says so on its own rather than leaning on the build.
    e, got = _week("LAR", "KC", played=False)
    assert e["bye"] is True and got == (False, False, True), (e, got)

    # Traded the other way: he PLAYED for the old team, and the Tuesday capture
    # names a team that was idle. This must not become a bye.
    e, got = _week("KC", "LAR", played=False)
    assert e["bye"] is False, e
    assert got == (False, False, False), got
    # ...and with a designation on him, the (correct) injury must survive too.
    e, got = _week("KC", "LAR", played=False, tag=("Out", "Inactive"))
    assert got == (True, False, False), got
    # Participation clears it either way.
    _e, got = _week("KC", "LAR", played=True)
    assert got == (False, False, False), got

    # No trade: both directions unchanged.
    assert _week("KC", "KC", played=False)[1] == (False, False, False)
    assert _week("LAR", "LAR", played=False)[1] == (False, False, True)


def test_an_empty_tracker_is_a_starting_state_not_damage():
    """The committed tracker is header-only until the first capture ever runs, so
    "no rows" must stay ordinary — it is what week 1 writes into.

    This is the other side of the NUL guard: that guard cannot key on "parsed to
    zero rows", because the real file does exactly that. It keys on the HEADER,
    which is also why csv no longer raising on NUL bytes (Python 3.11 dropped
    that error, and the workflows pin 3.11) does not put a truncated file back
    on the accepted path."""
    new = {c: "" for c in it.TRACKER_COLUMNS}
    new.update({"season": 2026, "week": 1, "player_id": "p1", "captures": 1,
                "captured_at_utc": "t", "status": "Active"})
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.tracker_path(root).parent.mkdir(parents=True)
        # 1. no file at all
        assert it._read_existing(it.tracker_path(root)) == ([], None)
        # 2. header only, exactly as committed
        it.tracker_path(root).write_text(",".join(it.TRACKER_COLUMNS) + "\n")
        rows, note = it._read_existing(it.tracker_path(root))
        assert rows == [] and note is None, (rows, note)
        it.merge_capture(root, [new], final=True)               # must not refuse
        assert ("p1", 2026, 1) in it.load_status_index(root)
        # 3. a completely empty file is not damage either
        it.tracker_path(root).write_text("")
        it.merge_capture(root, [new], final=True)

    # 4. a file that parses cleanly but is not a tracker must NOT be written over
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.tracker_path(root).parent.mkdir(parents=True)
        it.tracker_path(root).write_text("some,other,csv\n1,2,3\n")
        try:
            it.merge_capture(root, [new], final=True)
        except it.TrackerUnreadable:
            pass
        else:
            raise AssertionError("wrote over a file that is not the tracker")


def test_a_damaged_csv_costs_its_damaged_lines_and_nothing_else():
    """The readers degrade to empty on a corrupt file, which is right for them —
    a build with no overlay is still a build. The WRITERS cannot: every writer
    rewrites the whole file, so "no rows" would replace the season's history with
    the one week being captured. Nor can they simply propagate the error, because
    Sleeper keeps no injury history and a failed capture is a permanent gap."""
    good = ",".join(it.TRACKER_COLUMNS) + "\n" + "\n".join(
        f"2026,{w},keep{i},N,WR,KC,Out,,Inactive,false,,1,t,t"
        for w in (1, 2) for i in range(5)) + "\n"
    new = {c: "" for c in it.TRACKER_COLUMNS}
    new.update({"season": 2026, "week": 9, "player_id": "fresh", "captures": 1,
                "captured_at_utc": "t", "status": "Active"})

    # A NUL byte — a truncated or interrupted write — is what csv refuses outright.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.tracker_path(root).parent.mkdir(parents=True)
        it.tracker_path(root).write_text(good + "\x00\x01 broken\n")
        for fn, args in ((it.load_status_index, (root,)), (it.weeks_present, (root, 2026)),
                         (it.weeks_finalized, (root, 2026)), (it.sweep_counts, (root, 2026, 1))):
            fn(*args)          # readers must not raise
        it.merge_capture(root, [new], final=True)
        idx = it.load_status_index(root)
        assert len(idx) == 11, sorted(idx)                  # 10 recovered + the new one
        assert ("fresh", 2026, 9) in idx
        assert ("keep0", 2026, 1) in idx, "history was dropped instead of salvaged"
        it.merge_into_csv(root, [new])                      # the --force path too

    # A file with nothing recoverable in it must REFUSE, not truncate.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.tracker_path(root).parent.mkdir(parents=True)
        it.tracker_path(root).write_bytes(b"\x00" * 2048)
        for writer in (lambda: it.merge_capture(root, [new], final=True),
                       lambda: it.merge_into_csv(root, [new])):
            try:
                writer()
            except it.TrackerUnreadable:
                pass
            else:
                raise AssertionError("wrote over an unreadable tracker instead of refusing")

    # An absent or empty file is not damaged — it is the normal first run.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.merge_capture(root, [new], final=True)
        assert len(it.load_status_index(root)) == 1
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        it.tracker_path(root).parent.mkdir(parents=True)
        it.tracker_path(root).write_text("")
        it.merge_capture(root, [new], final=True)
        assert len(it.load_status_index(root)) == 1


def _load_capture_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_cap_under_test", _ROOT / "scripts" / "capture_injuries.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Args:
    def __init__(self, **kw):
        self.season = kw.get("season"); self.week = kw.get("week")
        self.force = kw.get("force", False); self.dry_run = kw.get("dry_run", False)
        self.mode = kw.get("mode", "final")


class _State:
    """Just /state/nfl, which is all resolve_week reads off the client."""
    def __init__(self, **kw):
        self.state = kw

    def get(self, path):
        return self.state if "/state/nfl" in str(path) else None


def test_the_two_reasons_the_schedule_gives_no_week_are_not_the_same():
    """week_from_schedule() returns None both before the opener and when the
    fetch failed, and conflating them is a WEEK-1 bug.

    Verified live on 2026-08-31, nine days before the opener: Sleeper's
    /state/nfl already reported season_type='regular', week=1. So the pre-season
    Tuesdays the cron fires on look exactly like a schedule outage, `season_type`
    does not tell them apart, and falling through to Sleeper's week files the
    camp PUP/NFI picture as week 1 — after which weeks_finalized() reports week 1
    done and the real capture is skipped."""
    cap = _load_capture_script()
    saved = (cap.schedule_available, cap.week_from_schedule, cap.gameday_week, cap.ROOT)
    try:
        live = _State(season="2026", week=1, season_type="regular",
                      season_start_date="2026-09-09")

        # 1. Schedule readable, no week started yet -> SKIP, never Sleeper's week 1.
        cap.schedule_available = lambda season, timeout=30: True
        cap.week_from_schedule = lambda season, timeout=30: None
        wk, notes = cap.resolve_week(live, 2026, _Args())
        assert wk is None, f"filed week {wk} before the season started"
        assert any("not started" in n for n in notes), notes
        assert not any("::warning::" in n for n in notes), notes

        # 2. Schedule readable and a week has started -> that week.
        cap.week_from_schedule = lambda season, timeout=30: 3
        assert cap.resolve_week(live, 2026, _Args())[0] == 3

        # 3. Schedule genuinely unreachable and NOTHING captured yet: there is no
        #    way to tell pre-season from in-season, so skip and shout.
        cap.schedule_available = lambda season, timeout=30: False
        cap.week_from_schedule = lambda season, timeout=30: None
        with tempfile.TemporaryDirectory() as d:
            cap.ROOT = Path(d)
            wk, notes = cap.resolve_week(live, 2026, _Args())
            assert wk is None, f"guessed week {wk} with no schedule and no history"
            assert any("::warning::" in n for n in notes), notes

            # 4. Same outage, but the season has demonstrably started because we
            #    already captured a block. NOW Sleeper's week is worth trusting.
            rows = [{**{c: "" for c in it.TRACKER_COLUMNS}, "season": 2026, "week": 1,
                     "player_id": "x", "captures": 1, "captured_at_utc": "t"}]
            it.merge_capture(cap.ROOT, rows, final=True)
            live2 = _State(season="2026", week=4, season_type="regular")
            wk, notes = cap.resolve_week(live2, 2026, _Args())
            assert wk == 4, (wk, notes)
            assert any("::warning::" in n for n in notes), notes

        # 5. A sweep never guesses either: no schedule means no sweep.
        cap.gameday_week = lambda season, now=None, timeout=30: 9
        cap.schedule_available = lambda season, timeout=30: False
        wk, notes = cap.resolve_week(live, 2026, _Args(mode="sweep"))
        assert wk is None and any("::warning::" in n for n in notes), (wk, notes)
        cap.schedule_available = lambda season, timeout=30: True
        assert cap.resolve_week(live, 2026, _Args(mode="sweep"))[0] == 9
    finally:
        (cap.schedule_available, cap.week_from_schedule, cap.gameday_week, cap.ROOT) = saved


def test_capture_script_refuses_to_overwrite_or_reach_backwards():
    """main()'s three refusal paths. The scheduled one matters most: once the
    regular season is over the schedule keeps resolving to week 18, so every
    remaining January Tuesday would otherwise replace week 18's real snapshot
    with a mid-playoffs one."""
    cap = _load_capture_script()
    sc = _MockSleeper(WEEK)

    with _fixture_nfl_schedule(), tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "config").mkdir()
        (root / "config" / "league.yaml").write_text("league_id: '1'\n")
        saved = (cap.ROOT, cap.SleeperClient, cap.week_from_schedule,
                 cap.capture_rows, cap.played_index, cap.gameday_week)
        cap.ROOT = root
        cap.SleeperClient = lambda *a, **k: sc
        cap.week_from_schedule = lambda season, timeout=30: 1
        cap.capture_rows = lambda _sc, season, week, played=None: it.capture_rows(sc, season, week)
        cap.played_index = lambda *a, **k: {}
        cap.gameday_week = lambda season, now=None, timeout=30: None   # no game today
        try:
            argv = sys.argv
            sys.argv = ["capture_injuries.py"]
            try:
                assert cap.main() == 0                       # fresh capture
                assert it.weeks_present(root, 2026) == {1}
                first = it.tracker_path(root).read_text()

                assert cap.main() == 0                       # scheduled re-run: SKIP
                assert it.tracker_path(root).read_text() == first, \
                    "a scheduled re-run overwrote an existing block"

                sys.argv = ["capture_injuries.py", "--week", "1"]
                assert cap.main() == 1                       # explicit --week: REFUSE

                sys.argv = ["capture_injuries.py", "--season", "2024", "--week", "3"]
                assert cap.main() == 1                       # before TRACKER_FIRST_SEASON
                assert it.weeks_present(root, 2024) == set()

                sys.argv = ["capture_injuries.py", "--week", "1", "--force", "--dry-run"]
                assert cap.main() == 0                       # --force + --dry-run writes nothing
                assert it.tracker_path(root).read_text() == first

                # --- sweep mode ---
                # No game today: exits clean, writes nothing, costs one schedule read.
                sys.argv = ["capture_injuries.py", "--mode", "sweep"]
                assert cap.main() == 0
                assert it.tracker_path(root).read_text() == first

                # A gameday: sweeps, and MERGES into the already-finalized week
                # instead of being refused the way a second final capture is.
                cap.gameday_week = lambda season, now=None, timeout=30: 1
                assert cap.main() == 0
                assert max(it.sweep_counts(root, 2026, 1)) == 2, "the sweep did not merge"
                assert it.weeks_finalized(root, 2026) == {1}, "a sweep must not finalize"
                assert set(it.load_status_index(root)) == {(p[0], 2026, 1) for p in WEEK}
            finally:
                sys.argv = argv
        finally:
            (cap.ROOT, cap.SleeperClient, cap.week_from_schedule,
             cap.capture_rows, cap.played_index, cap.gameday_week) = saved


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
