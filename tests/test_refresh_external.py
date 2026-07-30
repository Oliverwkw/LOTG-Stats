"""LOTG_REFRESH_EXTERNAL: force a re-download of EVERY season's external data.

The weekly health audit (scripts/audit_weekly.py Part 1) diffs a fresh build
against the committed exports to answer "does this still reproduce?". That only
means something if the fresh build reads LIVE upstream data. It didn't: `.cache`
is committed, and the nflverse loaders download only when a file is missing /
empty or `force_refresh` is set — which the build sets for the in-progress
season alone. So the audit build read the committed cache for every completed
season while the Tuesday build read the (newer) Actions cache, and Part 1
reported that cache-vintage skew as a historical-immutability breakage.

These tests cover the loader contract the fix depends on:
  * force_refresh=False + a cached file present  -> no download (the cheap path
    the Tuesday build keeps)
  * force_refresh=True                           -> download, every time
  * force_refresh=True + the download failing    -> fall back to the cached copy
    rather than failing the build

Run: PYTHONPATH=src:lib python tests/test_refresh_external.py
"""
from __future__ import annotations

import sys
import tempfile
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


def _run(tmp: Path, force: bool, download):
    """Call each loader against a pre-seeded cache; return {name: (df, n_calls)}."""
    out = {}
    for label, loader, fname in _LOADERS:
        d = tmp / label
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(_CACHED)
        calls = []

        def _fake(urls, path, timeout, _calls=calls, _dl=download):
            _calls.append(str(path))
            _dl(path)

        orig = X._download_best_effort
        X._download_best_effort = _fake
        try:
            df = loader(X.ExternalConfig(cache_dir=d, timeout_seconds=5), 2025,
                        force_refresh=force)
        finally:
            X._download_best_effort = orig
        out[label] = (df, len(calls))
    return out


def check_cached_read_when_not_forced(tmp):
    res = _run(tmp / "a", force=False, download=lambda p: p.write_text(_FRESH))
    ok = True
    for label, (df, calls) in res.items():
        ok &= _ok(f"{label}: present cache + no force -> no download", calls == 0, f"calls={calls}")
        ok &= _ok(f"{label}: serves the cached rows", len(df) == 1, f"rows={len(df)}")
    return ok


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
        for t in (check_cached_read_when_not_forced,
                  check_forced_refresh_downloads,
                  check_forced_refresh_falls_back_on_failure):
            print(f"\n{t.__name__}:")
            all_ok &= bool(t(Path(d)))
    print("\ncheck_build_reads_the_env_flag:")
    all_ok &= bool(check_build_reads_the_env_flag())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_refresh_external():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
