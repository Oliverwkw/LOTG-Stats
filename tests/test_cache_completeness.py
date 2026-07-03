"""Guard: the committed NFLverse cache baseline must stay complete.

Offline / audit builds (`scripts/offline_build.py`) read the committed
`.cache/nflverse_*_{season}.csv` files straight off disk. Historical seasons
are never re-downloaded — only the current season force-refreshes
(`force_refresh=(season == _current_lotg_season)` in `src/lotg.py`) — so a
missing or truncated committed file does NOT error: it silently degrades that
season's roster / player->NFL-team resolution to the "NFL" free-agent
sentinel.

That is exactly the failure behind PR #319, which had to re-add three
historical files (`stats_player_week_2018`, `injuries_2020`,
`weekly_rosters_2020`) that had gone missing from the committed cache — the
source of the phantom 2018/2020 differences in the run 401-vs-403 audit diff.

This test pins the baseline: every REQUIRED file below must be git-tracked and
non-trivially sized. When a season finalizes and its data is committed, bump
the range ceilings. The in-progress season is intentionally omitted — upstream
NFLverse stats/injuries for a not-yet-started season don't exist, so its
absence must never trip this guard.

Run: python tests/test_cache_completeness.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Per-family REQUIRED seasons = FINALIZED seasons whose data must be committed.
# Floors are fixed league-history facts (earliest season each feed is needed):
#   stats_player_week -> 2018 (earliest NFL season of a rostered player)
#   weekly_rosters / injuries -> 2020 (start of the tracked league era)
# Ceiling = last FINALIZED NFL season. Bump each family's upper bound by one
# when a season ends and its data is committed. (range() is exclusive, so
# range(2018, 2026) == 2018..2025.)
_REQUIRED_SEASONS = {
    "nflverse_stats_player_week": range(2018, 2026),  # 2018..2025
    "nflverse_weekly_rosters": range(2020, 2026),     # 2020..2025
    "nflverse_injuries": range(2020, 2026),           # 2020..2025
}

# Non-seasonal feeds that must always be committed.
_REQUIRED_SINGLETONS = [
    "dynastyprocess_playerids.csv",
    "nflverse_player_ids.csv",
    "nfldata_games.csv",
]

# A genuine NFLverse season CSV is hundreds of KB to several MB; the id/games
# feeds are far larger. 1 KB comfortably clears real files while catching an
# empty or header-only stub.
_MIN_BYTES = 1024


def _expected_files() -> list[str]:
    files = [f".cache/{name}" for name in _REQUIRED_SINGLETONS]
    for family, seasons in _REQUIRED_SEASONS.items():
        for season in seasons:
            files.append(f".cache/{family}_{season}.csv")
    return files


def _tracked_cache_files() -> set[str]:
    """Files git actually tracks under .cache/ — the offline-build baseline.

    Checking the tracked set (not just the working tree) is deliberate: a file
    that a CI run downloaded but never committed would exist on disk yet be
    absent for offline/audit builds. Falls back to a filesystem walk when this
    isn't a git checkout.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", ".cache"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return {line.strip() for line in out.splitlines() if line.strip()}
    except Exception:
        return {
            str(p.relative_to(_ROOT))
            for p in (_ROOT / ".cache").rglob("*")
            if p.is_file()
        }


def test_committed_nflverse_cache_is_complete():
    tracked = _tracked_cache_files()
    missing = [f for f in _expected_files() if f not in tracked]
    assert not missing, (
        "Committed .cache baseline is missing required NFLverse files — offline "
        "and audit builds will silently degrade these seasons to the 'NFL' "
        "sentinel instead of failing:\n  "
        + "\n  ".join(missing)
        + "\n\nRe-commit the file(s), or — if a season was intentionally dropped "
        "— update _REQUIRED_SEASONS in tests/test_cache_completeness.py."
    )


def test_committed_nflverse_cache_files_nonempty():
    problems = []
    for f in _expected_files():
        p = _ROOT / f
        if not p.exists():
            continue  # absence is reported by the completeness test above
        size = p.stat().st_size
        if size < _MIN_BYTES:
            problems.append(f"{f} ({size} bytes)")
    assert not problems, (
        "Committed .cache files are suspiciously small (empty/truncated stub?):\n  "
        + "\n  ".join(problems)
    )


if __name__ == "__main__":
    tracked = _tracked_cache_files()
    expected = _expected_files()
    missing = [f for f in expected if f not in tracked]
    small = [
        f"{f} ({(_ROOT / f).stat().st_size} bytes)"
        for f in expected
        if (_ROOT / f).exists() and (_ROOT / f).stat().st_size < _MIN_BYTES
    ]
    print(f"expected committed cache files: {len(expected)}")
    if missing:
        print(f"MISSING ({len(missing)}):")
        for f in missing:
            print(f"  {f}")
    if small:
        print(f"TOO SMALL ({len(small)}):")
        for f in small:
            print(f"  {f}")
    if not missing and not small:
        print("OK — committed NFLverse cache baseline is complete.")
    raise SystemExit(1 if (missing or small) else 0)
