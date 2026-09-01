"""A weekly run that never happened has to become a line in an email.

It is the only failure in this pipeline with NO artifact: a late run is visible
in the Actions list, a broken run is a red X, but a run GitHub simply never
dispatched (2026-07-07) leaves nothing at all — and every other section of the
health email then describes a week-old dataset as though it were current.

The signal is the two committed stamps that record a weekly cycle COMPLETING,
not the GitHub API: `data/digest/ranks_snapshot.json` (rotated only by the
Tuesday cron, and on every Tuesday run) and `exports/snapshot/_snapshot_meta.json`.

The sharp edge here is the grace window. GitHub's worst observed dispatch delay
on this repo is 8h47m, so "the stamp is older than the fire + grace" would alarm
on an ordinary late week. The rule is: a fire is only JUDGED once it has had
grace_hours to finish, and then the stamp merely has to be at or after the fire
instant itself.

Run: PYTHONPATH=src:lib python tests/test_schedule_watch.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import schedule_watch as SW  # noqa: E402

UTC = timezone.utc
# 2026-09-02 is a Wednesday; 14:37 UTC is when the health email is scheduled.
WED = datetime(2026, 9, 2, 14, 37, tzinfo=UTC)
TUE_FIRE = datetime(2026, 9, 1, 13, 47, tzinfo=UTC)


def _repo(digest_at=None, exports_at=None):
    root = Path(tempfile.mkdtemp())
    (root / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(_ROOT / ".github" / "workflows" / "build.yml",
                root / ".github" / "workflows" / "build.yml")
    (root / "data" / "digest").mkdir(parents=True)
    (root / "exports" / "snapshot").mkdir(parents=True)
    if digest_at is not None:
        (root / "data" / "digest" / "ranks_snapshot.json").write_text(json.dumps(
            {"meta": {"captured_at": digest_at.isoformat(), "season": 2026,
                      "weeks_completed": 0}}))
    if exports_at is not None:
        (root / "exports" / "snapshot" / "_snapshot_meta.json").write_text(json.dumps(
            {"captured_at": exports_at.isoformat()}))
    return root


def test_the_schedule_is_read_from_the_workflow_not_restated():
    fires = SW.cron_fires(_ROOT, "build.yml", "2")
    assert fires == [(13, 47), (17, 47)], fires
    # Thursday has no catch-up: nothing unrecoverable rides on a pregame refresh.
    assert SW.cron_fires(_ROOT, "build.yml", "4") == [(15, 47)]


def test_the_most_recent_fire_is_judged_once_it_has_had_time():
    fires = SW.cron_fires(_ROOT, "build.yml", "2")
    # Judged because the 17:47 catch-up has had its grace; compared against the
    # 13:47 PRIMARY, so a run that finished at 14:52 counts as done.
    assert SW.last_expected_fire(WED, fires, "2") == TUE_FIRE


def test_a_fire_still_inside_the_grace_window_is_not_judged():
    """43 minutes after the fire, GitHub may simply not have dispatched it yet."""
    fires = [(13, 47)]
    soon = TUE_FIRE + timedelta(minutes=43)
    assert SW.last_expected_fire(soon, fires, "2") == TUE_FIRE - timedelta(days=7)


def test_a_successful_primary_is_not_flagged_by_its_own_catch_up():
    """The regression that a real-repo run caught.

    Anchoring on the day's LAST fire made every ordinary week look missed: the
    primary rotates the snapshot at, say, 14:52, the 17:47 catch-up correctly
    finds nothing to do and rotates nothing, and the stamp then sits before the
    instant being compared against.
    """
    root = _repo(digest_at=TUE_FIRE + timedelta(minutes=65),
                 exports_at=TUE_FIRE + timedelta(minutes=65))
    assert SW.missed_runs(root, now=WED) == []


def test_a_healthy_week_reports_nothing():
    root = _repo(digest_at=WED - timedelta(hours=2), exports_at=WED - timedelta(hours=2))
    assert SW.missed_runs(root, now=WED) == []


def test_a_nine_hour_delay_is_healthy_not_an_alarm():
    """The stamp only has to be at or after the FIRE, never after fire+grace."""
    late = TUE_FIRE + timedelta(hours=9)
    root = _repo(digest_at=late, exports_at=late)
    assert SW.missed_runs(root, now=WED) == []


def test_a_skipped_tuesday_is_caught():
    stale = TUE_FIRE - timedelta(days=7)
    root = _repo(digest_at=stale, exports_at=stale)
    missed = SW.missed_runs(root, now=WED)
    assert {m.what for m in missed} == {"weekly build + digest",
                                        "committed exports refresh"}
    dig = [m for m in missed if m.what == "weekly build + digest"][0]
    assert dig.cycles >= 1
    assert 7.0 < dig.age_days(WED) < 8.5, dig.age_days(WED)


def test_several_skipped_weeks_are_counted_not_just_flagged():
    root = _repo(digest_at=TUE_FIRE - timedelta(days=21),
                 exports_at=WED - timedelta(hours=2))
    missed = SW.missed_runs(root, now=WED)
    assert [m.what for m in missed] == ["weekly build + digest"]
    assert missed[0].cycles == 3, missed[0].cycles   # three Tuesdays, not six fires


def test_a_thursday_commit_cannot_clear_the_digest_finding():
    """exports/ can be fresh from Thursday while Tuesday's digest never ran."""
    root = _repo(digest_at=TUE_FIRE - timedelta(days=7), exports_at=WED - timedelta(hours=1))
    assert [m.what for m in SW.missed_runs(root, now=WED)] == ["weekly build + digest"]


def test_a_missing_or_corrupt_stamp_is_reported_not_crashed_on():
    root = _repo(digest_at=None, exports_at=WED - timedelta(hours=2))
    missed = SW.missed_runs(root, now=WED)
    assert [m.what for m in missed] == ["weekly build + digest"]
    assert missed[0].captured_at is None and missed[0].age_days(WED) is None
    (root / "data" / "digest" / "ranks_snapshot.json").write_text("{not json")
    assert [m.what for m in SW.missed_runs(root, now=WED)] == ["weekly build + digest"]


def test_the_email_carries_the_section_and_counts_it_in_the_subject():
    sys.path.insert(0, str(_ROOT / "scripts"))
    import send_audit_email as E
    missed = SW.missed_runs(_repo(digest_at=TUE_FIRE - timedelta(days=7),
                                  exports_at=TUE_FIRE - timedelta(days=7)), now=WED)
    subject, html, has_issues = E.render_email(
        [], {}, True, drift=None, missed=missed, now=WED)
    assert has_issues, "a skipped run must not render as an all-clear week"
    assert "missed scheduled run" in subject, subject
    assert "Missed scheduled runs" in html
    assert "did not complete" in html
    clean_subj, clean_html, clean_issues = E.render_email([], {}, True, drift=None,
                                                          missed=[], now=WED)
    assert not clean_issues
    assert "✅ Every scheduled weekly run" in clean_html



# ---------------------------------------------------------------------------
# The catch-up guard
# ---------------------------------------------------------------------------
PRIMARY, CATCH_UP = "47 13 * * 2", "47 17 * * 2"


def test_the_catch_up_skips_once_the_primary_has_done_the_work():
    root = _repo(digest_at=TUE_FIRE + timedelta(minutes=28))
    assert SW.should_skip_run(root, CATCH_UP, now=TUE_FIRE + timedelta(hours=4)) is True


def test_the_primary_itself_is_never_skipped():
    root = _repo(digest_at=TUE_FIRE + timedelta(minutes=28))
    assert SW.should_skip_run(root, PRIMARY, now=TUE_FIRE + timedelta(hours=4)) is False


def test_the_catch_up_runs_when_the_primary_did_not():
    """The whole point: a dropped primary leaves last week's stamp behind."""
    root = _repo(digest_at=TUE_FIRE - timedelta(days=7))
    assert SW.should_skip_run(root, CATCH_UP, now=TUE_FIRE + timedelta(hours=4)) is False


def test_a_primary_that_died_before_rotating_does_not_suppress_the_catch_up():
    """Rotation is the LAST step, after the email — a stale stamp means the
    chain did not finish, however far the run got."""
    root = _repo(digest_at=TUE_FIRE - timedelta(days=7), exports_at=TUE_FIRE)
    assert SW.should_skip_run(root, CATCH_UP, now=TUE_FIRE + timedelta(hours=4)) is False


def test_the_guard_fails_open_on_every_unknown():
    fresh = TUE_FIRE + timedelta(minutes=28)
    now = TUE_FIRE + timedelta(hours=4)
    # no stamp at all
    assert SW.should_skip_run(_repo(digest_at=None), CATCH_UP, now=now) is False
    # unreadable stamp
    root = _repo(digest_at=fresh)
    (root / "data" / "digest" / "ranks_snapshot.json").write_text("{not json")
    assert SW.should_skip_run(root, CATCH_UP, now=now) is False
    # a manual dispatch carries no schedule
    assert SW.should_skip_run(_repo(digest_at=fresh), "", now=now) is False
    assert SW.should_skip_run(_repo(digest_at=fresh), None, now=now) is False
    # a cron from another day, and an unrecognised one
    assert SW.should_skip_run(_repo(digest_at=fresh), "47 15 * * 4", now=now) is False
    assert SW.should_skip_run(_repo(digest_at=fresh), "0 3 * * 2", now=now) is False
    assert SW.should_skip_run(_repo(digest_at=fresh), "garbage", now=now) is False
    # a repo with no workflow to read
    import tempfile as _tf
    assert SW.should_skip_run(Path(_tf.mkdtemp()), CATCH_UP, now=now) is False


def test_the_cli_prints_a_bare_boolean_and_never_raises():
    import subprocess
    root = _repo(digest_at=TUE_FIRE + timedelta(minutes=28))
    for sched in (CATCH_UP, PRIMARY, "", "garbage"):
        r = subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "schedule_guard.py"),
             "--schedule", sched, "--root", str(root)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() in ("true", "false"), r.stdout


# ---------------------------------------------------------------------------
# The injury tracker's own scheduled runs (PR #415)
# ---------------------------------------------------------------------------
def test_an_unswept_week_is_a_finding():
    """sweep_injuries.yml never ran for that week; Sleeper keeps no history."""
    got = SW.injury_capture_health({(2026, 4): {"finalized": True, "captures": 1}})
    assert [(g.kind, g.week) for g in got] == [("unswept", 4)]


def test_an_unfinalized_week_is_a_finding():
    """capture_injuries.yml's Tuesday run never landed — but the week HAS rows,
    so injury_coverage.week_gaps() is silent about it."""
    got = SW.injury_capture_health({(2026, 4): {"finalized": False, "captures": 2}})
    assert [(g.kind, g.week) for g in got] == [("unfinalized", 4)]


def test_a_healthy_injury_week_is_not_a_finding():
    assert SW.injury_capture_health({(2026, 4): {"finalized": True, "captures": 3}}) == []
    assert SW.injury_capture_health({}) == []


def test_an_unfinalized_week_is_reported_as_that_not_as_unswept():
    """A week with sweeps but no final capture has captures > 1 already; the
    missing FINAL is the bigger fact and must not be masked by it."""
    got = SW.injury_capture_health({(2026, 4): {"finalized": False, "captures": 1}})
    assert [g.kind for g in got] == ["unfinalized"]


def test_incomplete_injury_weeks_reach_the_email():
    sys.path.insert(0, str(_ROOT / "scripts"))
    import send_audit_email as E
    inc = SW.injury_capture_health({(2026, 4): {"finalized": True, "captures": 1},
                                    (2026, 5): {"finalized": False, "captures": 2}})
    subject, html, has_issues = E.render_email(
        [], {}, True, drift=None, now=WED, injury_incomplete=inc)
    assert has_issues, "an incomplete injury week must not render as all clear"
    assert "2 incomplete injury weeks" in subject, subject
    assert "no gameday sweep" in html and "no post-week capture" in html
    assert "2026 week 4" in html and "2026 week 5" in html


TESTS = [test_the_schedule_is_read_from_the_workflow_not_restated,
         test_the_most_recent_fire_is_judged_once_it_has_had_time,
         test_a_fire_still_inside_the_grace_window_is_not_judged,
         test_a_successful_primary_is_not_flagged_by_its_own_catch_up,
         test_a_healthy_week_reports_nothing,
         test_a_nine_hour_delay_is_healthy_not_an_alarm,
         test_a_skipped_tuesday_is_caught,
         test_several_skipped_weeks_are_counted_not_just_flagged,
         test_a_thursday_commit_cannot_clear_the_digest_finding,
         test_a_missing_or_corrupt_stamp_is_reported_not_crashed_on,
         test_the_email_carries_the_section_and_counts_it_in_the_subject,
         test_the_catch_up_skips_once_the_primary_has_done_the_work,
         test_the_primary_itself_is_never_skipped,
         test_the_catch_up_runs_when_the_primary_did_not,
         test_a_primary_that_died_before_rotating_does_not_suppress_the_catch_up,
         test_the_guard_fails_open_on_every_unknown,
         test_the_cli_prints_a_bare_boolean_and_never_raises,
         test_an_unswept_week_is_a_finding,
         test_an_unfinalized_week_is_a_finding,
         test_a_healthy_injury_week_is_not_a_finding,
         test_an_unfinalized_week_is_reported_as_that_not_as_unswept,
         test_incomplete_injury_weeks_reach_the_email]

if __name__ == "__main__":
    bad = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            bad += 1; print(f"FAIL  {t.__name__}: {e}")
    sys.exit(1 if bad else 0)
