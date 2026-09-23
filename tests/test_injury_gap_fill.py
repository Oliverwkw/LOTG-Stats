"""The injury gap-fill, and the appearance list it depends on.

`src/lotg.py` fills an injury for every week a player did not appear in, once
he has appeared at least once that season. That is the only way a player on
season-ending IR gets flagged at all, because nflverse's game-status report
drops him entirely — so the gap-fill has to exist.

What it got wrong was "appear". It read `stats_player_week`, which is an EVENT
list: a row per player who recorded a countable statistic, 31-40 per team per
week against the ~47 who dress. A receiver who plays eight snaps and is not
targeted records nothing and is simply absent from it. Reading that absence as
an absence from the field flagged **275 of the 3,826 `Injury?` weeks in
2020-2025** on players who were playing — every one of them flipped True ->
False in the export diff of the first build with the fix (run 34873813049 vs
run 496), and nothing else flipped:

    2020   14/394 ( 3.6%)        2023   59/561 (10.5%)
    2021   22/685 ( 3.2%)        2024   80/779 (10.3%)
    2022   14/587 ( 2.4%)        2025   86/820 (10.5%)

(An earlier count of 262 bridged players to snap counts by NAME. That missed 16
real cases spelt differently upstream — A.J. Dillon, D.J. Chark, Dont'e
Thornton Jr. — and wrongly counted 3 weeks where Michael Carter the RB, who was
hurt, borrowed the snaps of Michael Carter II the CB. The build joins on ids and
was right both times; see `_pfr_by_name_and_position` for how this guard
avoids the same trap.)

Worst cases played near-full games, each with 0.00 points and an injury flag:
Gabe Davis 2023 wk11 (67 snaps), Cole Kmet 2024 wk9 (66), Cade Otton 2025 wk3
(66), Justin Watson 2024 wk5 (63), Courtland Sutton 2024 wk7 (57). Ben Sinnott
had sixteen such weeks across 2024-2025. It inflated Hardship, and through it
Luck and `Loss from hardship?`, and dropped those weeks out of played-week
denominators like `Adjusted Avg`.

The fix unions nflverse's `snap_counts` release — a true appearance list — into
`played_players_by_week`. The alternative considered and rejected was gating on
the weekly-roster status: it kills the same false flags but also ~253 that are
genuine game-day inactives, because `ACT` covers those too.

Run: PYTHONPATH=src:lib python tests/test_injury_gap_fill.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "lib", _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_EXPORTS = _ROOT / "exports"
_CACHE = _ROOT / ".cache"

# The INFO line the build logs once the snap union has run. Its presence in the
# committed build log is how a data-dependent test here knows the shipped
# exports were produced WITH the fix — before the first post-merge rebuild they
# are not, and asserting against them would fail for the right reason at the
# wrong time.
_UNION_MARKER = "snap_appearances"


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _snap_seasons():
    return sorted(int(p.stem.rsplit("_", 1)[1])
                  for p in _CACHE.glob("nflverse_snap_counts_*.csv"))


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
# nflverse roster position -> the fantasy position player_week carries.
_FANTASY_POSITION = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "K": "K"}


def _norm_name(name) -> str:
    """'A.J. Dillon' == 'AJ Dillon', "Dont'e Thornton Jr." == "Dont'e Thornton"."""
    words = re.sub(r"[^a-z ]", "", str(name).lower()).split()
    return "".join(w for w in words if w not in _NAME_SUFFIXES)


def _pfr_by_name_and_position(wr) -> dict:
    """{(normalized name, fantasy position): pfr_id} from one season's weekly
    rosters, keeping ONLY keys that resolve to a single player.

    player_week carries no id, so the bridge has to go through the name — and a
    bare name is not an identity. Keyed on the name alone, Michael Carter the
    NYJ running back (CartMi03, 0 snaps in 2021 wks 12-13, genuinely hurt)
    borrowed the snaps of Michael Carter II, the NYJ corner (CartMi02, listed
    as "Michael Carter" in the same file), and this guard failed run 34873813049
    on three correct flags. The position splits them; a key two fantasy-eligible
    players still share is dropped rather than guessed. Pinned positions win, so
    a two-way player is read at the position the sheets give him."""
    from lotg_support.position_pins import FANTASY_POSITION_PINS

    seen: dict = {}
    for r in wr.itertuples():
        pfr = getattr(r, "pfr_id", None)
        if not isinstance(pfr, str) or not pfr.strip():
            continue
        gsis = str(getattr(r, "gsis_id", "") or "").strip()
        pos = FANTASY_POSITION_PINS.get(gsis) or _FANTASY_POSITION.get(str(r.position))
        if not pos:
            continue
        seen.setdefault((_norm_name(r.full_name), pos), set()).add(pfr.strip())
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def _exports_built_with_the_fix() -> bool:
    log = _EXPORTS / "raw" / "build_debug.log"
    try:
        return _UNION_MARKER in log.read_text(errors="replace")
    except Exception:
        return False


def test_the_snap_loader_points_at_the_appearance_release():
    """A pure check on the loader: right release, right cache name, and it does
    NOT go through the position pins (snap counts carry no position column and
    no gsis to pin on)."""
    import inspect
    from lotg_support import external as E

    src = inspect.getsource(E.load_nflverse_snap_counts)
    assert "releases/download/snap_counts/snap_counts_" in src
    assert "nflverse_snap_counts_" in src, "cache filename is not season-scoped"
    assert "apply_position_pins" not in src


def test_the_build_unions_snaps_into_the_played_set():
    """Asserted on the source: the union is built inside build_all(), which
    needs the whole external-data chain to reach.

    Each of these is load-bearing. Without the pfr bridge there is no way from
    snap counts (which carry no gsis) to the build's gsis world; without the
    REG filter the postseason leaks in as regular-season appearances; without
    the >0 total, a dressed-but-never-on-the-field row would read as played and
    re-open the hole from the other side."""
    src = (_ROOT / "src" / "lotg.py").read_text()
    assert "load_nflverse_snap_counts" in src, "the snap loader is not wired in"
    assert "pfr_to_gsis" in src, "the pfr_player_id -> gsis bridge is gone"
    assert '_tot > 0' in src, "a zero-snap row would count as an appearance"
    assert 'game_type"].astype(str).str.upper() == "REG"' in src, \
        "the postseason is not filtered out of the snap counts"
    assert _UNION_MARKER in src, "the build no longer logs the union"


def test_no_injury_flag_coincides_with_snaps_played():
    """The regression guard: nobody is injured in a week he took the field.

    Needs the snap counts cached and the exports built with the fix; skips
    otherwise, which is the state of a fresh checkout before the first
    post-merge build."""
    try:
        import pandas as pd
    except ImportError:
        return _skip("pandas not installed")
    pw_path = _EXPORTS / "player_week.csv"
    if not pw_path.exists():
        return _skip("no exports/player_week.csv")
    seasons = _snap_seasons()
    if not seasons:
        return _skip("no .cache/nflverse_snap_counts_*.csv — run a build first")
    if not _exports_built_with_the_fix():
        return _skip("the committed exports predate the snap union "
                     f"(no {_UNION_MARKER!r} in exports/raw/build_debug.log); "
                     "this asserts from the first post-merge build onward")

    import lotg
    from lotg_support.external import read_cached_csv
    pw = pd.read_csv(pw_path, low_memory=False)
    # EVERY completed season the sheet carries, not just the ones whose cache
    # files happen to be present and parse: this loop used to `continue` past a
    # missing roster file and crash on an unreadable snap file, and the
    # 2026-09-23 health run lost 2025 that way (a gzip body under a .csv name)
    # while reporting only a UnicodeDecodeError. A season that cannot be
    # checked is now named in the failure, after every other season has been.
    years = sorted({int(y) for y in pd.to_numeric(pw["Year"], errors="coerce").dropna()})
    completed = [y for y in years if lotg._season_is_complete(y)]
    offenders, unchecked, checked = [], [], []
    for season in completed:
        try:
            pfr_of = _pfr_by_name_and_position(read_cached_csv(
                _CACHE / f"nflverse_weekly_rosters_{season}.csv", low_memory=False))
            sn = read_cached_csv(_CACHE / f"nflverse_snap_counts_{season}.csv",
                                 low_memory=False)
        except Exception as e:  # noqa: BLE001 — reported below, never swallowed
            unchecked.append(f"{season}: {type(e).__name__}: {e}"[:200])
            continue
        checked.append(season)
        if "game_type" in sn.columns:
            sn = sn[sn["game_type"].astype(str).str.upper() == "REG"]
        snaps = {}
        for r in sn.itertuples():
            tot = sum(0 if pd.isna(v) else v
                      for v in (getattr(r, "offense_snaps", 0),
                                getattr(r, "defense_snaps", 0),
                                getattr(r, "st_snaps", 0)))
            if tot > 0 and pd.notna(r.week):
                k = (str(r.pfr_player_id), int(r.week))
                snaps[k] = max(snaps.get(k, 0), tot)
        inj = pw[(pw["Year"] == season) & (pw["Injury?"] == True)]  # noqa: E712
        for r in inj.itertuples():
            p = pfr_of.get((_norm_name(r.Player), str(r.Position)))
            if not p:
                continue      # unbridgeable or ambiguous; not this test's business
            s = snaps.get((p, int(r.Week)))
            if s and s > 0:
                offenders.append((int(season), str(r.Player), int(r.Week), int(s)))

    print(f"  checked {checked} (completed seasons in player_week: {completed})")
    worst = sorted(offenders, key=lambda o: -o[3])[:12]
    assert not unchecked, (
        f"{len(unchecked)} completed season(s) could not be checked: {unchecked}"
        + (f". Separately, {len(offenders)} flagged-while-playing week(s) in the "
           f"seasons that were: {worst}" if offenders else ""))
    assert not offenders, (
        f"{len(offenders)} player-week(s) are flagged Injury? while nflverse "
        f"records snaps played. Worst: {worst}. The gap-fill has gone back to "
        "reading an event list as an appearance list.")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
