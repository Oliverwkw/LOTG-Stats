"""Snapshot staleness guard: age accounting drives the build-time auto-refresh.

Unit-tests the pure decision logic in `lotg_support.snapshot` (no network): a
snapshot with no capture stamp reads as stale, a fresh stamp reads as current,
and an old stamp trips the max-age threshold. This is what lets a build-only run
refresh a week-old committed snapshot instead of building on it.

Run: python tests/test_snapshot_freshness.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support.snapshot import (  # noqa: E402
    SNAPSHOT_META_NAME,
    snapshot_age_days,
    snapshot_is_stale,
)


def _write_stamp(repo_root: Path, captured_at) -> None:
    meta = repo_root / "exports" / "snapshot" / SNAPSHOT_META_NAME
    meta.parent.mkdir(parents=True, exist_ok=True)
    payload = {"league_id": "x"}
    if captured_at is not None:
        payload["captured_at"] = captured_at
    meta.write_text(json.dumps(payload))


def test_missing_or_undated_snapshot_is_stale(tmp_path):
    # No snapshot at all → stale (and age unknown).
    assert snapshot_age_days(tmp_path) is None
    assert snapshot_is_stale(tmp_path, max_age_days=7)
    # Present but with no capture stamp → still stale.
    _write_stamp(tmp_path, captured_at=None)
    assert snapshot_age_days(tmp_path) is None
    assert snapshot_is_stale(tmp_path, max_age_days=7)


def test_fresh_snapshot_is_not_stale(tmp_path):
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    _write_stamp(tmp_path, (now - timedelta(days=2)).isoformat())
    assert abs(snapshot_age_days(tmp_path, now=now) - 2.0) < 1e-6
    assert not snapshot_is_stale(tmp_path, max_age_days=7, now=now)


def test_old_snapshot_trips_threshold(tmp_path):
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    _write_stamp(tmp_path, (now - timedelta(days=22)).isoformat())
    assert snapshot_age_days(tmp_path, now=now) > 7
    assert snapshot_is_stale(tmp_path, max_age_days=7, now=now)
    # A naive (tz-less) stamp is still handled (treated as UTC).
    _write_stamp(tmp_path, (now.replace(tzinfo=None) - timedelta(days=22)).isoformat())
    assert snapshot_is_stale(tmp_path, max_age_days=7, now=now)


if __name__ == "__main__":
    import tempfile

    for fn in (test_missing_or_undated_snapshot_is_stale,
               test_fresh_snapshot_is_not_stale,
               test_old_snapshot_trips_threshold):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        print(f"ok: {fn.__name__}")
    print("all snapshot-freshness checks passed")
