"""Did the scheduled runs this repo depends on actually happen?

GitHub's `schedule` events are best-effort. They arrive late — every scheduled
run this repo has had started late, median ~80 minutes, tail to 8h47m — and
sometimes they do not arrive at all (2026-07-07). PR #416 moved every cron off
the top of the hour and put catch-up fires behind the two whose loss is
unrecoverable, but a catch-up is not a guarantee, and a run that never happened
is SILENT: no failed workflow, no red X, nothing in an inbox.

This module turns that silence into a line in the Wednesday health email.

WHAT IT READS. Not the GitHub API — the two committed stamps that record the
weekly cycle actually completing, which is the fact worth checking rather than
whether a workflow object exists:

  * `data/digest/ranks_snapshot.json` -> `meta.captured_at`. Rotated ONLY by the
    Tuesday cron's rotation step, and rotated on EVERY Tuesday run: the digest
    writes `captured_at=now` unconditionally, so the file always differs and the
    step always commits, even in a dead-quiet offseason week. That makes it a
    clean "the weekly build ran end to end, through the digest" signal, and it is
    the head of the week-over-week reference chain the digest diffs against.
  * `exports/snapshot/_snapshot_meta.json` -> `captured_at`. Written by any build
    that commits refreshed exports. The Tuesday cron ALWAYS commits, so a stamp
    older than the last expected Tuesday means neither the Tuesday nor the
    Thursday run got that far. Weaker in the other direction — a Thursday commit
    can keep this fresh while Tuesday was missed — so it is reported separately
    and never used to clear the digest finding.

Injury captures are deliberately NOT checked here: `injury_coverage.py` and
`injury_tracker.missing_weeks()` already report tracker week gaps, and they get
their own section of the same email.

WHEN IT JUDGES. `last_expected_fire()` returns the most recent scheduled instant
that has had `grace_hours` to finish; anything more recent is still allowed to be
in flight. So a Tuesday run delayed nine hours is healthy, not an alarm — the
stamp only has to be at or after the FIRE instant, not after fire+grace.

The schedule is read from `.github/workflows/build.yml` rather than restated
here. Restating it is the bug this repo already had: three gates carrying their
own copy of a cron string, so moving the cron silently changed behaviour.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import yaml

UTC = timezone.utc

# How long a fire is allowed to still be in flight before its absence counts.
# GitHub's worst observed dispatch delay here is 8h47m and the build takes ~25
# minutes, so 12 hours clears the tail without letting a genuinely missed week
# hide for another seven days.
GRACE_HOURS = 12

# Python's Monday=0 weekday, for cron's Sunday=0 day-of-week field.
_CRON_DOW_TO_PY = {"0": 6, "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}


@dataclass
class MissedRun:
    what: str
    stamp_path: str
    captured_at: Optional[datetime]
    expected_at: datetime
    cycles: int                 # scheduled fires that came and went unrecorded
    detail: str

    def age_days(self, now: datetime) -> Optional[float]:
        if self.captured_at is None:
            return None
        return (now - self.captured_at).total_seconds() / 86400.0


def cron_fires(repo_root: Path, workflow: str, dow: str) -> List[Tuple[int, int]]:
    """(hour, minute) of every cron in `workflow` firing on cron day-of-week `dow`.

    Read from the workflow itself so a moved cron moves this check with it.
    """
    doc = yaml.safe_load((repo_root / ".github" / "workflows" / workflow).read_text())
    on = doc.get("on", doc.get(True)) or {}      # YAML 1.1 parses bare `on:` as True
    out: List[Tuple[int, int]] = []
    for entry in (on.get("schedule") or []):
        parts = str(entry.get("cron", "")).split()
        if len(parts) != 5:
            continue
        minute, hour, _dom, _month, cdow = parts
        if cdow != dow or not minute.isdigit() or not hour.isdigit():
            continue
        out.append((int(hour), int(minute)))
    return sorted(out)


def fire_days(now: datetime, fires: Sequence[Tuple[int, int]], dow: str,
              back_weeks: int = 60) -> List[Tuple[datetime, datetime]]:
    """(first fire, last fire) for each scheduled DAY at or before `now`, newest first.

    A day, not a fire, is the unit: a Tuesday now has a primary at 13:47 and a
    catch-up at 17:47, and the week is healthy if EITHER did the work. Treating
    each fire separately makes a perfectly good primary run look stale the moment
    a catch-up cron is added behind it, because the catch-up correctly finds
    nothing to do — which is exactly the false positive this shape avoids.
    """
    py_dow = _CRON_DOW_TO_PY.get(dow)
    if py_dow is None or not fires:
        return []
    lo, hi = min(fires), max(fires)
    out: List[Tuple[datetime, datetime]] = []
    day = now.astimezone(UTC).date()
    while len(out) < back_weeks:
        if day.weekday() == py_dow:
            first = datetime(day.year, day.month, day.day, lo[0], lo[1], tzinfo=UTC)
            last = datetime(day.year, day.month, day.day, hi[0], hi[1], tzinfo=UTC)
            if first <= now:
                out.append((first, last))
        day -= timedelta(days=1)
    return out


def last_expected_fire(now: datetime, fires: Sequence[Tuple[int, int]], dow: str,
                       grace_hours: int = GRACE_HOURS) -> Optional[datetime]:
    """The PRIMARY fire of the most recent scheduled day that is done waiting.

    Two separate clocks, and conflating them is the bug:
      * a day is only JUDGED once its LAST fire (the catch-up) has had
        `grace_hours` to complete — GitHub may not have dispatched it yet; and
      * the stamp is then compared against that day's FIRST fire, because a run
        that completed at 14:52 on a 13:47 primary did its job, whatever the
        catch-up behind it did.
    This is why a nine-hour delay is healthy and a skipped week is not.
    """
    for first, last in fire_days(now, fires, dow):
        if now - last >= timedelta(hours=grace_hours):
            return first
    return None


def _read_stamp(path: Path, *keys: str) -> Optional[datetime]:
    try:
        blob = json.loads(path.read_text())
    except Exception:
        return None
    for k in keys:
        blob = (blob or {}).get(k) if isinstance(blob, dict) else None
    if not blob:
        return None
    try:
        dt = datetime.fromisoformat(str(blob))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def missed_runs(repo_root: Path, now: Optional[datetime] = None,
                grace_hours: int = GRACE_HOURS) -> List[MissedRun]:
    """Weekly cycles that should have completed and left no trace that they did."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    repo_root = Path(repo_root)
    fires = cron_fires(repo_root, "build.yml", "2")     # the Tuesday crons
    expected = last_expected_fire(now, fires, "2", grace_hours)
    if expected is None:
        return []

    checks = (
        ("weekly build + digest",
         repo_root / "data" / "digest" / "ranks_snapshot.json", ("meta", "captured_at"),
         "The digest snapshot is the head of the week-over-week reference chain — "
         "the baseline every future digest diffs against. It is rotated only by "
         "the Tuesday cron, so a stale one means that Tuesday's run never "
         "finished."),
        ("committed exports refresh",
         repo_root / "exports" / "snapshot" / "_snapshot_meta.json", ("captured_at",),
         "The Tuesday cron always commits refreshed exports, so a stamp older "
         "than the last expected Tuesday means neither the Tuesday nor the "
         "Thursday run got that far."),
    )

    out: List[MissedRun] = []
    for what, path, keys, detail in checks:
        stamp = _read_stamp(path, *keys)
        if stamp is not None and stamp >= expected:
            continue
        cycles = len([first for first, _last in fire_days(now, fires, "2")
                      if first <= expected and (stamp is None or first > stamp)])
        out.append(MissedRun(
            what=what,
            stamp_path=str(path.relative_to(repo_root)) if path.is_absolute() else str(path),
            captured_at=stamp,
            expected_at=expected,
            cycles=max(cycles, 1),
            detail=detail,
        ))
    return out
