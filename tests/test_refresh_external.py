"""LOTG_REFRESH_EXTERNAL: force a re-download of EVERY season's external data.

The weekly health audit (scripts/audit_weekly.py Part 1) diffs a fresh build
against the committed exports to answer "does this still reproduce?". That only
means something if the fresh build reads LIVE upstream data. It didn't: `.cache`
is committed, and the nflverse loaders download only when a file is missing /
empty or `force_refresh` is set — which the build sets for the in-progress
season alone. So the audit build read the committed cache for every completed
season while the Tuesday build read the (newer) Actions cache, and Part 1
reported that cache-vintage skew as a historical-immutability breakage.

`force_refresh` was only ever half the story, and the other half was the bug:
past the audit build, NOTHING re-downloaded a completed season, because the
loaders' own gate was "absent or empty". The committed `.cache` is hand-written
and CI never commits it back, so the shipped exports ran on a 2026-06-29 vintage
for 65 days. Freshness is now the loaders' job (`cache_is_stale`), which is what
keeps the Tuesday build under a week old with no workflow step to forget.

These tests cover the loader contract both halves depend on:
  * a cached file that is FRESH + no force      -> no download (the cheap path
    the Tuesday build keeps between refreshes)
  * a cached file that is STALE                 -> download, unforced
  * a cached file with no fetch-log entry       -> download (unknown vintage is
    treated as stale, which is the safe direction)
  * force_refresh=True                          -> download, every time
  * a download that fails                       -> fall back to the copy on disk
    rather than failing the build, and do NOT stamp it fresh, so the next build
    retries instead of waiting out another horizon

Run: PYTHONPATH=src:lib python tests/test_refresh_external.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import external as X  # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond or not detail else f" — {detail}"))
    return bool(cond)


_LOADERS = (
    ("stats_player_week", X.load_nflverse_stats_player_week, "nflverse_stats_player_week_2025.csv"),
    ("weekly_rosters", X.load_nflverse_weekly_rosters, "nflverse_weekly_rosters_2025.csv"),
    ("injuries", X.load_nflverse_injuries, "nflverse_injuries_2025.csv"),
)
_CACHED = "player_id,season,week\nX,2025,1\n"
_FRESH = "player_id,season,week\nX,2025,1\nY,2025,2\n"


@contextmanager
def _horizon(days):
    """Pin the staleness horizon for one case.

    tests/conftest.py holds the whole suite at an effectively infinite horizon so
    no test downloads the repo's committed `.cache`. This file is the one that
    tests the horizon, so it sets its own and puts the suite default back.
    """
    prior = os.environ.get("LOTG_CACHE_MAX_AGE_DAYS")
    os.environ["LOTG_CACHE_MAX_AGE_DAYS"] = str(days)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("LOTG_CACHE_MAX_AGE_DAYS", None)
        else:
            os.environ["LOTG_CACHE_MAX_AGE_DAYS"] = prior


def _AGE_FRESH():
    return datetime.now(timezone.utc) - timedelta(days=1)


def _AGE_STALE():
    return datetime.now(timezone.utc) - timedelta(days=X.CACHE_MAX_AGE_DAYS + 1)


def _run(tmp: Path, force: bool, download, stamp=_AGE_FRESH, horizon=None):
    """Call each loader against a pre-seeded cache; return {name: (df, n_calls)}.

    `stamp` is when the seeded file was last "downloaded" — None leaves it out
    of the fetch log entirely, which is the checked-out-but-unknown case."""
    out = {}
    for label, loader, fname in _LOADERS:
        d = tmp / label
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(_CACHED)
        if stamp is not None:
            X.record_fetch(d / fname, stamp())
        calls = []

        def _fake(urls, path, timeout, _calls=calls, _dl=download):
            _calls.append(str(path))
            _dl(path)

        orig = X._download_best_effort
        X._download_best_effort = _fake
        try:
            with _horizon(X.CACHE_MAX_AGE_DAYS if horizon is None else horizon):
                df = loader(X.ExternalConfig(cache_dir=d, timeout_seconds=5), 2025,
                            force_refresh=force)
        finally:
            X._download_best_effort = orig
        out[label] = (df, len(calls))
    return out


def check_fresh_cache_read_when_not_forced(tmp):
    res = _run(tmp / "a", force=False, download=lambda p: p.write_text(_FRESH),
               stamp=_AGE_FRESH)
    ok = True
    for label, (df, calls) in res.items():
        ok &= _ok(f"{label}: fresh cache + no force -> no download", calls == 0, f"calls={calls}")
        ok &= _ok(f"{label}: serves the cached rows", len(df) == 1, f"rows={len(df)}")
    return ok


def check_stale_cache_refreshes_unforced(tmp):
    """The fix. A file past the horizon re-downloads with force_refresh=False —
    which is what makes the Tuesday build self-refreshing."""
    res = _run(tmp / "d", force=False, download=lambda p: p.write_text(_FRESH),
               stamp=_AGE_STALE)
    ok = True
    for label, (df, calls) in res.items():
        ok &= _ok(f"{label}: stale cache + no force -> downloads", calls == 1, f"calls={calls}")
        ok &= _ok(f"{label}: serves the freshly downloaded rows", len(df) == 2, f"rows={len(df)}")
    return ok


def check_unstamped_cache_counts_as_stale(tmp):
    """A checked-out `.cache` with no fetch-log entry is of unknown vintage.
    mtime can't answer it (checkout rewrites mtimes), so it must read stale."""
    res = _run(tmp / "e", force=False, download=lambda p: p.write_text(_FRESH), stamp=None)
    ok = True
    for label, (df, calls) in res.items():
        ok &= _ok(f"{label}: unstamped cache -> downloads", calls == 1, f"calls={calls}")
    return ok


def check_failed_refresh_leaves_it_stale(tmp):
    """A source that is down must not get stamped fresh — that would buy it
    another full horizon of silence."""
    def _boom(_path):
        raise RuntimeError("403 Forbidden")

    d = tmp / "f"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "nflverse_stats_player_week_2025.csv"
    f.write_text(_CACHED)
    X.record_fetch(f, _AGE_STALE())
    orig = X._download_best_effort
    X._download_best_effort = lambda urls, path, timeout: _boom(path)
    try:
        with _horizon(X.CACHE_MAX_AGE_DAYS):
            df = X.load_nflverse_stats_player_week(
                X.ExternalConfig(cache_dir=d, timeout_seconds=5), 2025)
            ok = _ok("failed refresh keeps the cached rows", len(df) == 1, f"rows={len(df)}")
            ok &= _ok("failed refresh stays stale (retries next build)", X.cache_is_stale(f))
    finally:
        X._download_best_effort = orig
    return ok


def check_horizon_keeps_it_under_a_week():
    """The Tuesday build is the refresh mechanism, so the horizon has to be
    short enough that consecutive Tuesdays always straddle it — GitHub's
    schedule queue routinely runs this repo ~80 minutes late, and a flat 7 would
    let a late-then-early pair skip a week."""
    return _ok(f"CACHE_MAX_AGE_DAYS ({X.CACHE_MAX_AGE_DAYS}) is under 7",
               0 < X.CACHE_MAX_AGE_DAYS < 7)


def check_forced_refresh_downloads(tmp):
    res = _run(tmp / "b", force=True, download=lambda p: p.write_text(_FRESH))
    ok = True
    for label, (df, calls) in res.items():
        ok &= _ok(f"{label}: force_refresh -> downloads over the cache", calls == 1, f"calls={calls}")
        ok &= _ok(f"{label}: serves the freshly downloaded rows", len(df) == 2, f"rows={len(df)}")
    return ok


def check_forced_refresh_falls_back_on_failure(tmp):
    def _boom(_path):
        raise RuntimeError("403 Forbidden")

    res = _run(tmp / "c", force=True, download=_boom)
    ok = True
    for label, (df, calls) in res.items():
        ok &= _ok(f"{label}: failed refresh attempted the download", calls == 1, f"calls={calls}")
        ok &= _ok(f"{label}: failed refresh degrades to the cached copy", len(df) == 1, f"rows={len(df)}")
    return ok


def check_every_loader_is_freshness_gated():
    """A loader added later with its own absent-or-empty gate would silently
    freeze another file for months — that is exactly how the id bridge and the
    bye schedule ended up 77 days old. Every download site must go through
    `_ensure`, which is the one place the horizon is applied."""
    src = (_ROOT / "lib" / "lotg_support" / "external.py").read_text()
    loaders = re.findall(r"^def (load_\w+)\(", src, re.M)
    bodies = re.split(r"^def ", src, flags=re.M)
    ungated = []
    for b in bodies:
        name = b.split("(", 1)[0]
        if not name.startswith("load_"):
            continue
        if "_ensure(" not in b:
            ungated.append(name)
    ok = _ok(f"all {len(loaders)} loaders route through _ensure", not ungated, f"ungated={ungated}")
    ok &= _ok("no loader keeps its own absent-or-empty gate",
              "st_size == 0" not in "".join(b for b in bodies if b.split("(", 1)[0].startswith("load_")))
    lotg = (_ROOT / "src" / "lotg.py").read_text()
    ok &= _ok("the bye-schedule download is freshness-gated too",
              "cache_is_stale(path)" in lotg and "record_fetch(path)" in lotg)
    return ok


def check_the_suite_is_hermetic():
    """A test that reaches a loader against the repo's own `.cache` would now
    pull ~156MB before asserting anything — the committed copy is months old by
    design. `tests/test_contracts.py` re-scores league points straight out of it
    and did exactly that until conftest pinned the horizon."""
    cf = _ROOT / "tests" / "conftest.py"
    ok = _ok("tests/conftest.py exists", cf.is_file())
    if ok:
        body = cf.read_text()
        ok &= _ok("it pins LOTG_CACHE_MAX_AGE_DAYS", "LOTG_CACHE_MAX_AGE_DAYS" in body)
        ok &= _ok("...for the whole session, automatically",
                  "autouse=True" in body and 'scope="session"' in body)
    return ok


def check_the_committed_cache_is_dated():
    """The horizon is read off `.cache/_fetch_log.json`, not mtime — checkout
    rewrites mtimes, so without the log a two-month-old file reads brand new and
    nothing ever refreshes. The seed has to be committed and has to be older
    than the horizon, or the first build after this lands refreshes nothing."""
    import json
    log_path = _ROOT / ".cache" / X.FETCH_LOG_NAME
    ok = _ok("committed fetch log exists", log_path.is_file())
    if not ok:
        return ok
    log = json.loads(log_path.read_text())
    csvs = {p.name for p in (_ROOT / ".cache").glob("*.csv")}
    missing = sorted(csvs - set(log))
    ok &= _ok("every committed cache CSV is dated", not missing, f"missing={missing[:4]}")
    stale = [n for n in csvs if X.cache_is_stale(_ROOT / ".cache" / n, max_age_days=6.0)]
    ok &= _ok("the committed seed reads stale (so it refreshes on first build)",
              len(stale) == len(csvs), f"{len(stale)}/{len(csvs)}")
    return ok


def check_build_reads_the_env_flag():
    """The build gates the loaders on LOTG_REFRESH_EXTERNAL; keep the workflow
    that sets it and the code that reads it from drifting apart."""
    src = (_ROOT / "src" / "lotg.py").read_text()
    ok = _ok("build reads LOTG_REFRESH_EXTERNAL", "LOTG_REFRESH_EXTERNAL" in src)
    ok &= _ok("no call site still hardcodes the current-season-only rule",
              "force_refresh=(season == _current_lotg_season)" not in src)
    ok &= _ok("every nflverse loader call goes through the helper",
              src.count("force_refresh=_force_refresh_season(") == 4,
              f"count={src.count('force_refresh=_force_refresh_season(')}")
    wf = (_ROOT / ".github" / "workflows" / "weekly_health_email.yml").read_text()
    ok &= _ok("the health workflow sets it", 'LOTG_REFRESH_EXTERNAL: "1"' in wf)
    build = (_ROOT / ".github" / "workflows" / "build.yml").read_text()
    ok &= _ok("the Tuesday build does NOT (keeps the cached read)",
              "LOTG_REFRESH_EXTERNAL" not in build)
    return ok


def run_all() -> bool:
    all_ok = True
    with tempfile.TemporaryDirectory() as d:
        for t in (check_fresh_cache_read_when_not_forced,
                  check_stale_cache_refreshes_unforced,
                  check_unstamped_cache_counts_as_stale,
                  check_forced_refresh_downloads,
                  check_forced_refresh_falls_back_on_failure,
                  check_failed_refresh_leaves_it_stale):
            print(f"\n{t.__name__}:")
            all_ok &= bool(t(Path(d)))
    print("\ncheck_horizon_keeps_it_under_a_week:")
    all_ok &= bool(check_horizon_keeps_it_under_a_week())
    print("\ncheck_every_loader_is_freshness_gated:")
    all_ok &= bool(check_every_loader_is_freshness_gated())
    print("\ncheck_the_suite_is_hermetic:")
    all_ok &= bool(check_the_suite_is_hermetic())
    print("\ncheck_the_committed_cache_is_dated:")
    all_ok &= bool(check_the_committed_cache_is_dated())
    print("\ncheck_build_reads_the_env_flag:")
    all_ok &= bool(check_build_reads_the_env_flag())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_refresh_external():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
