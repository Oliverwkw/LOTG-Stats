"""The cron schedules, and the gates that are coupled to them.

GitHub queues `schedule` events on a shared, best-effort pool and defers them
under load — load that peaks at the top of every hour. Measured on this repo's
own run history: every scheduled run has started LATE, never early and never on
time, median ~80 minutes, tail to 8h47m (Thu 2026-08-27 landed 00:47 UTC on the
Friday), and 2026-07-07's Tuesday fire was dropped outright.

Two things follow, and this file guards both.

1. WHERE A DELAY COSTS DATA, the cron has to sit inside a real-world window with
   headroom, and unrecoverable work needs a second fire behind it. The gameday
   sweep is the sharp case: its designations exist only while Sleeper is showing
   them, and its window (inactive report -> kickoff) is 90 minutes wide.

2. WHERE A GATE IS KEYED TO A CRON STRING, moving the cron must not silently
   change behaviour. build.yml used to carry the literal "0 14 * * 2" in three
   separate places — the digest email gate, the snapshot rotation gate and the
   commit-reason branch. Editing the schedule without editing all three would
   have left the Tuesday build running and building its digest, and silently
   never mailing or rotating it. Nothing in the suite caught that.

Run: python tests/test_workflow_schedules.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
WF = _ROOT / ".github" / "workflows"

# Real-world instants, in UTC minutes-since-midnight, that the crons are placed
# against. Sources are named because a wrong one here silently relaxes a test.
MNF_LATEST_END = 3 * 60 + 30      # a Monday night game can run past 03:30 UTC (PR #415)
WEEK_FINAL_GATE = 8 * 60          # src/lotg.py::_week_complete_cutoff
EARLY_INACTIVES = 15 * 60 + 30    # 90 min before a 1pm ET kick
EARLY_KICK = 17 * 60
LATE_INACTIVES = 18 * 60 + 35     # 90 min before a 4:05pm ET kick
LATE_KICK = 20 * 60 + 5


def _load(name: str) -> dict:
    doc = yaml.safe_load((WF / name).read_text())
    # YAML 1.1: a bare `on:` key parses as the boolean True.
    doc["on"] = doc.get("on", doc.get(True))
    return doc


def _crons(name: str) -> list:
    sched = (_load(name)["on"] or {}).get("schedule") or []
    return [str(e["cron"]).strip() for e in sched]


def _fields(cron: str):
    minute, hour, dom, month, dow = cron.split()
    return minute, hour, dom, month, dow


def _at(cron: str) -> int:
    """Minutes since midnight UTC. Only fixed minute/hour crons are used here."""
    minute, hour, *_ = _fields(cron)
    return int(hour) * 60 + int(minute)


SCHEDULED = ["build.yml", "capture_injuries.yml", "sweep_injuries.yml",
             "weekly_health_email.yml"]


def test_no_cron_fires_on_the_hour():
    """:00 is the most contended minute on GitHub's scheduler."""
    on_the_hour = [(f, c) for f in SCHEDULED for c in _crons(f)
                   if _fields(c)[0] == "0"]
    assert not on_the_hour, (
        f"crons sitting on the top of the hour: {on_the_hour}")


def test_tuesday_send_list_matches_the_tuesday_crons():
    """The digest gate's idea of "Tuesday" must be the schedule's.

    A Tuesday fire that is not in TUESDAY_SEND builds the digest and never mails
    it. A non-Tuesday cron that IS in the list mails one off-cadence.
    """
    doc = _load("build.yml")
    expr = doc["env"]["TUESDAY_SEND"]
    listed = json.loads(re.search(r"fromJSON\('(\[.*?\])'\)", expr).group(1))
    actual = [c for c in _crons("build.yml") if _fields(c)[4] == "2"]
    assert sorted(listed) == sorted(actual), (
        f"TUESDAY_SEND={sorted(listed)} but on.schedule Tuesdays are {sorted(actual)}")


def test_no_gate_hardcodes_a_cron_string():
    """Every schedule-keyed gate goes through TUESDAY_SEND, not its own copy."""
    body = (WF / "build.yml").read_text()
    stray = re.findall(r"github\.event\.schedule\s*(?:==|\}\}\"\s*=)", body)
    assert not stray, (
        f"{len(stray)} gate(s) still compare github.event.schedule directly; "
        "route them through the TUESDAY_SEND env instead")


def test_the_send_and_rotation_gates_use_the_shared_flag():
    body = (WF / "build.yml").read_text()
    gates = [ln for ln in body.splitlines()
             if ln.strip().startswith("if:") and "TUESDAY_SEND" in ln]
    assert len(gates) >= 2, (
        "expected the digest-email and snapshot-rotation gates to read "
        f"env.TUESDAY_SEND; found {len(gates)}")


def test_injury_capture_lands_between_the_monday_game_and_the_build():
    """Not before the MNF it is snapshotting, not after the build that reads it."""
    build_tue = min(_at(c) for c in _crons("build.yml") if _fields(c)[4] == "2")
    for c in _crons("capture_injuries.yml"):
        assert _at(c) >= MNF_LATEST_END, (
            f"{c} can fire while a Monday night game is still running")
        assert _at(c) <= build_tue, (
            f"{c} fires after the {build_tue // 60:02d}:{build_tue % 60:02d} "
            "build that reads its snapshot")
    primary = min(_at(c) for c in _crons("capture_injuries.yml"))
    assert primary >= WEEK_FINAL_GATE - 3 * 60, (
        "the primary capture has drifted so early it loses PR #415's MNF margin")


def test_every_sweep_sits_in_an_inactive_report_window():
    """A sweep before the inactive report reads a practice report instead."""
    windows = [(EARLY_INACTIVES, EARLY_KICK), (LATE_INACTIVES, LATE_KICK)]
    for c in _crons("sweep_injuries.yml"):
        t = _at(c)
        assert any(lo <= t < hi for lo, hi in windows), (
            f"sweep {c} ({t // 60:02d}:{t % 60:02d} UTC) is outside every "
            "inactive-report -> kickoff window")


def test_the_sweep_is_redundant_and_has_delay_headroom():
    """One fire cannot survive this scheduler; the window is only 90 min wide."""
    crons = _crons("sweep_injuries.yml")
    assert len(crons) >= 2, (
        "a single daily sweep lands after kickoff more often than not — the "
        "merge cannot recover what Sleeper is no longer showing")
    headroom = max(EARLY_KICK - _at(c) for c in crons
                   if EARLY_INACTIVES <= _at(c) < EARLY_KICK)
    assert headroom >= 60, (
        f"only {headroom} min of delay headroom before the early kickoff")


def test_unrecoverable_work_has_a_catch_up_fire():
    """GitHub drops schedule events outright; these two cannot afford it."""
    tuesdays = [c for c in _crons("build.yml") if _fields(c)[4] == "2"]
    assert len(tuesdays) >= 2, "the weekly digest send has no catch-up fire"
    sep_dec = [c for c in _crons("capture_injuries.yml")
               if _fields(c)[3] == "9-12"]
    assert len(sep_dec) >= 2, "the weekly injury capture has no catch-up fire"


def test_recoverable_work_does_not_get_one():
    """A catch-up is not free — it is a second full build and a second commit.

    Thursday is the pregame refresh: a dropped one costs a fresher roster until
    Tuesday and nothing else, so it does not get a catch-up. Adding one here
    would double the Thursday build for no recovered data.
    """
    thursdays = [c for c in _crons("build.yml") if _fields(c)[4] == "4"]
    assert len(thursdays) == 1, thursdays


def test_the_catch_up_is_guarded_and_the_guard_can_only_gate_the_build():
    doc = _load("build.yml")
    assert "guard" in doc["jobs"], "the Tuesday catch-up runs unguarded"
    build = doc["jobs"]["build"]
    assert build.get("needs") == "guard" or "guard" in (build.get("needs") or [])
    assert "needs.guard.outputs.should_run" in str(build.get("if", "")), build.get("if")
    # The guard decides from the workflow's own crons, never a restated string.
    body = (WF / "build.yml").read_text()
    guard = body.split("guard:", 1)[1].split("\n  build:", 1)[0]
    assert "schedule_guard.py" in guard
    for c in _crons("build.yml"):
        assert c not in guard, f"the guard step restates the cron {c!r}"


TESTS = [test_no_cron_fires_on_the_hour,
         test_tuesday_send_list_matches_the_tuesday_crons,
         test_no_gate_hardcodes_a_cron_string,
         test_the_send_and_rotation_gates_use_the_shared_flag,
         test_injury_capture_lands_between_the_monday_game_and_the_build,
         test_every_sweep_sits_in_an_inactive_report_window,
         test_the_sweep_is_redundant_and_has_delay_headroom,
         test_unrecoverable_work_has_a_catch_up_fire,
         test_recoverable_work_does_not_get_one,
         test_the_catch_up_is_guarded_and_the_guard_can_only_gate_the_build]

if __name__ == "__main__":
    bad = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            bad += 1
            print(f"FAIL  {t.__name__}: {e}")
    sys.exit(1 if bad else 0)
