"""Who actually scored — touchdowns underneath a fantasy lineup.

Nothing this repo publishes knows what a player *did*, only what he was worth.
`player_week["Points"]` is a total; the snapshot's per-week `stats_nfl.json` is
an empty list in every season folder. So "did anyone in this lineup score a
touchdown" has no source here at all — it needs nflverse's weekly stat lines,
joined onto the league's own starters. This module is that join, and the guards
that say the join landed on the right players.

Three pieces:

  * **The stat side.** `touchdowns(season)` reduces the build's own nflverse
    weekly stats (`external.load_nflverse_stats_player_week`, reading the same
    `.cache/` the build fills) to one row per `gsis_id` and week, carrying each
    kind of touchdown a player can SCORE and, separately, the ones he threw.

  * **The lineup side.** `starter_touchdowns(season)` puts one row under every
    starter of every week: who he was, the slot he filled, what Sleeper paid him
    — and what he actually did. Snapshot seasons come from the snapshot, keyed
    by Sleeper id through `gsis_bridge()`; 2020, which has exports but no
    snapshot, comes from `player_week` and the committed ESPN id map.

  * **The question.** `lineups_without_touchdowns()` is the scan this was
    written for: team-weeks in which nobody outside the quarterback slot reached
    the end zone.

  * **Careers.** `career_totals()` and `starter_careers()` answer the other
    shape of stat-line question — not what a starter did that week but what he
    had ever done. Every starter-week comes back with two career numbers for any
    nflverse stat: `career_to_date`, what he had entering that game (the résumé
    the manager was looking at), and `career_total`, the whole career including
    everything after. `lowest_careers()` ranks them.

`check_touchdown_join()` is the guard. There is no touchdown column anywhere in
`exports/` to reconcile against, so it ties the *join* rather than the count:
re-scoring each matched stat line with the league's settings (`contracts.
lotg_points`) has to reproduce the points the build already has for that same
starter-week. A row whose points agree to the cent is a row about the right
player.

Read-only and inquiry-only: nothing in `src/` or `.github/workflows/` imports
this, and it writes nothing outside the nflverse cache.

## Assumptions, all of them parameters

* **What "scoring" means** is `TD_KINDS` — rushing, receiving, return and
  fumble-recovery touchdowns. A passing touchdown is thrown, not scored, so it
  is reported in its own column and never counted in `touchdowns`. Pass your own
  `kinds` to disagree.
* **What makes a starter a quarterback** is `qb_rule`: `"position"` reads the
  player's own position, so a quarterback in the superflex is excluded like any
  other; `"slot"` reads the lineup slot, so only the dedicated QB slot is, and
  the superflex quarterback has to stay out of the end zone too.

## Traps

* **Regular season only.** Fantasy weeks 15-17 are NFL weeks 15-17, so the
  fantasy postseason lives in nflverse's REG rows; its POST rows are the NFL
  playoffs, which no fantasy week ever covers. Including them would silently
  double some weeks.
* **nflverse back-corrects, Sleeper does not.** A touchdown reassigned weeks
  later moves the stat line and not the fantasy points. Across 2021-2025,
  1.1-1.6% of joined starter-weeks re-score to something other than the points
  the build holds: nearly all by exactly 1 (a residual in `contracts.lotg_points`
  itself, concentrated on quarterbacks and two-point conversions) and three by
  6 — a touchdown moved to another player after the fact. `check_touchdown_join`
  measures the rate rather than demanding zero; a *specific* answer that turns
  on one player should be read against both sources (`weekly_stats` carries the
  stat line, the snapshot the points).
* **A cancelled game leaves points with no stat line.** The 2022 Bills-Bengals
  week 17 game was abandoned and struck from nflverse; Sleeper kept the partial
  fantasy points. Three starter-weeks in this league land there, and they come
  back `resolved=False` rather than as a confident zero.
* **A seasonal file carries three kinds of row**: `REG`, `POST` and `REG+POST`,
  the last being the sum of the other two. Summing the column without choosing
  rows double-counts every career. `CAREER_BASES` picks the rows; nothing here
  ever reads a `REG+POST` row.
* **The newest seasons have no seasonal file.** `career_totals()` falls back to
  aggregating the weekly file for those, which is why a career total is current
  to the last week played rather than the last finished season — and why the two
  sources have to agree (`check_career_sources_agree`). It reaches the
  in-progress season through the BUILD's loader, so that season's weekly file
  lands in `.cache/` and its stamp in `_fetch_log.json`. Keep the two together:
  reverting the log while leaving the file is what makes `test_refresh_external`
  report an undated cache file, and
  `test_the_season_cache_stays_out_of_the_builds_freshness_gate` will say so.
* **"Years in the league" has three readings and they change answers.** See
  `YEARS_RULES`: a player's tenure as of a start is not his career length.
* **2020 has no snapshot**, so its rows are matched by name, and its `slot`
  comes from the export column — which was only correct from the build that
  carried the `espn_2020._slot_ordered` fix. `qb_rule="slot"` on 2020 against
  older exports is reading shuffled labels.
"""
from __future__ import annotations

import csv
import functools
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from lotg_support import contracts as C
from lotg_support import external as X
from lotg_support import inquiry as Q

#: Touchdowns a player SCORES. `passing_tds` is deliberately not here.
TD_KINDS: Tuple[str, ...] = (
    "rushing_tds", "receiving_tds", "special_teams_tds", "fumble_recovery_tds",
)
PASSING_KIND = "passing_tds"

#: How a starter counts as a quarterback — see the module docstring.
QB_RULES: Tuple[str, ...] = ("position", "slot")

#: The ESPN backfill's own player bridge, the only id map that covers 2020.
ESPN_ID_MAP = Path("data") / "espn_2020_raw" / "player_id_map.csv"


def _config() -> X.ExternalConfig:
    return X.ExternalConfig(cache_dir=Q.repo_root() / ".cache")


# ---------------------------------------------------------------------------
# The stat side
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=8)
def _weekly_cached(season: int, root: str) -> pd.DataFrame:
    df = X.load_nflverse_stats_player_week(_config(), season)
    df = df[df["season_type"].astype(str).str.upper() == "REG"].copy()
    df["player_id"] = df["player_id"].astype(str)
    df["week"] = pd.to_numeric(df["week"], errors="coerce").astype("Int64")
    return df


def weekly_stats(season: int) -> pd.DataFrame:
    """nflverse's weekly stat lines for one season, regular season only."""
    return _weekly_cached(int(season), str(Q.repo_root())).copy()


@functools.lru_cache(maxsize=8)
def _touchdowns_cached(season: int, kinds: Tuple[str, ...], root: str) -> pd.DataFrame:
    df = _weekly_cached(season, root)
    cols = [k for k in kinds if k in df.columns]
    missing = [k for k in kinds if k not in df.columns]
    if missing:
        raise KeyError(f"nflverse {season} has no column(s) {missing}")
    out = df[["player_id", "week", "player_display_name", "position"]].copy()
    for col in cols:
        out[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    out["touchdowns"] = out[cols].sum(axis=1)
    out["passing_touchdowns"] = pd.to_numeric(
        df.get(PASSING_KIND), errors="coerce").fillna(0.0) if PASSING_KIND in df else 0.0
    # A player traded mid-week, or credited under two teams, can hold two rows.
    grouped = out.groupby(["player_id", "week"], as_index=False).agg(
        {**{c: "sum" for c in cols},
         "touchdowns": "sum", "passing_touchdowns": "sum",
         "player_display_name": "last", "position": "last"})
    return grouped


def touchdowns(season: int, kinds: Sequence[str] = TD_KINDS) -> pd.DataFrame:
    """One row per (`gsis_id`, week): each kind of touchdown, plus the total.

    `touchdowns` counts only what the player scored himself; `passing_touchdowns`
    rides alongside so a caller can ask the other question without a second load.
    """
    return _touchdowns_cached(int(season), tuple(kinds), str(Q.repo_root())).copy()


# ---------------------------------------------------------------------------
# Sleeper / ESPN -> nflverse
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _bridge_cached(root: str) -> Dict[str, str]:
    bridge = dict(Q._sleeper_to_gsis())          # DynastyProcess, the build's own map
    blob = Q._snap("sleeper_players_nfl.json")   # Sleeper's own gsis_id, where it has one
    for pid, meta in (blob or {}).items():
        gsis = str((meta or {}).get("gsis_id") or "").strip()
        if gsis and gsis.lower() != "nan":
            bridge.setdefault(str(pid), gsis)
    return bridge


def gsis_bridge() -> Dict[str, str]:
    """`sleeper_id -> gsis_id`, DynastyProcess first and Sleeper's own field second."""
    return dict(_bridge_cached(str(Q.repo_root())))


@functools.lru_cache(maxsize=1)
def _espn_names_cached(root: str) -> Dict[str, str]:
    """`player name -> gsis_id` from the 2020 backfill's committed bridge."""
    path = Path(root) / ESPN_ID_MAP
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    with path.open() as fh:
        for row in csv.DictReader(fh):
            gsis = str(row.get("gsis_id") or "").strip()
            name = str(row.get("name") or "").strip()
            if name and gsis and gsis.lower() != "nan":
                out.setdefault(name, gsis)
    return out


def _gsis_for_name(name: str) -> Optional[str]:
    """A 2020 export name to `gsis_id`: the ESPN bridge, else Sleeper's dictionary.

    The sheets carry a player's CURRENT Sleeper spelling ("DJ Moore"), which the
    2020 bridge — written in 2020 — does not always hold; and Sleeper's
    dictionary has two players for some names. Neither source covers 2020 alone;
    together they do, and `check_2020_coverage()` holds them to it.
    """
    direct = _espn_names_cached(str(Q.repo_root())).get(name)
    if direct:
        return direct
    try:
        pid = Q.players().resolve(name)
    except Exception:
        return None
    return _bridge_cached(str(Q.repo_root())).get(str(pid))


# ---------------------------------------------------------------------------
# The lineup side
# ---------------------------------------------------------------------------
_SLOT_LABEL_POSITION = {"QB1": "QB", "QB": "QB"}


def _slot_name(slot: Sequence[str]) -> str:
    """A snapshot slot tuple as the sheets spell it: ('RB','WR','TE') -> FLEX."""
    if len(slot) == 1:
        return slot[0]
    return {2: "WRRB_FLEX", 3: "FLEX", 4: "SUPER_FLEX"}.get(len(slot), "FLEX")


def _starter_rows_from_snapshot(season: int, weeks: Optional[Sequence[int]]) -> List[dict]:
    meta = Q.season_meta(season)
    teams = Q.teams(season)
    players = Q.players()
    bridge = _bridge_cached(str(Q.repo_root()))
    wanted = list(weeks) if weeks is not None else Q.played_weeks(season)
    rows: List[dict] = []
    for week in wanted:
        for roster_id, row in Q.week(season, week).items():
            for index, pid in enumerate(row.starters):
                slot = meta.starting_slots[index] if index < len(meta.starting_slots) else ("?",)
                if pid == Q.EMPTY_SLOT:
                    rows.append(dict(Year=season, Week=week, Team=teams.get(roster_id),
                                     Player=None, player_id=None, gsis_id=None,
                                     Position=None, slot=_slot_name(slot),
                                     Points=0.0, empty_slot=True, source="snapshot"))
                    continue
                rows.append(dict(Year=season, Week=week, Team=teams.get(roster_id),
                                 Player=players.name(pid), player_id=str(pid),
                                 gsis_id=bridge.get(str(pid)),
                                 Position=players.position(pid), slot=_slot_name(slot),
                                 Points=float(row.players_points.get(pid, 0.0)),
                                 empty_slot=False, source="snapshot"))
    return rows


#: How the sheets label each slot of the 2020 template, mapped back to the slot.
_EXPORT_SLOT = {"QB": "QB", "RB1": "RB", "RB2": "RB", "WR1": "WR", "WR2": "WR",
                "WR3": "WR", "TE": "TE", "FLX1": "FLEX", "SFLX": "SUPER_FLEX"}


def _starter_rows_from_exports(season: int, weeks: Optional[Sequence[int]]) -> List[dict]:
    sheet = Q.rows("player_week", f"Year={season}", "Starter/Bench=Starter")
    rows: List[dict] = []
    for _, row in sheet.iterrows():
        week = int(float(row["Week"]))
        if weeks is not None and week not in set(weeks):
            continue
        name = str(row["Player"])
        label = str(row.get("Position started in (if starter)") or "")
        rows.append(dict(Year=season, Week=week, Team=str(row["Team"]),
                         Player=name, player_id=None, gsis_id=_gsis_for_name(name),
                         Position=str(row.get("Position") or ""),
                         slot=_EXPORT_SLOT.get(label, label),
                         Points=Q.to_number(row.get("Points")) or 0.0,
                         empty_slot=False, source="exports"))
    return rows


def starter_touchdowns(season: int, weeks: Optional[Sequence[int]] = None,
                       kinds: Sequence[str] = TD_KINDS) -> pd.DataFrame:
    """One row per starter-week: who started, in which slot, and what he scored.

    `resolved` is False where the starter could not be matched to a stat line —
    no `gsis_id`, or a week he has none (a bye, an inactive, the cancelled 2022
    week 17 game). Those rows keep a touchdown count of 0 and are counted, never
    dropped: a scan reports them beside its answer rather than swallowing them.
    """
    season = int(season)
    rows = (_starter_rows_from_snapshot(season, weeks)
            if Q.season_meta(season).has_snapshot
            else _starter_rows_from_exports(season, weeks))
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    stats = touchdowns(season, kinds).rename(columns={"player_id": "gsis_id",
                                                      "week": "Week"})
    stats["Week"] = stats["Week"].astype(int)
    merged = frame.merge(stats.drop(columns=["player_display_name"]),
                         how="left", on=["gsis_id", "Week"], suffixes=("", "_nflverse"))
    merged["resolved"] = merged["touchdowns"].notna() & ~merged["empty_slot"]
    for column in list(kinds) + ["touchdowns", "passing_touchdowns"]:
        merged[column] = pd.to_numeric(merged.get(column), errors="coerce").fillna(0.0)
    # nflverse's own position is the better one where it exists — the Sleeper
    # dictionary is current-only and drifts (see the playbook's trap list).
    nfl_pos = merged.pop("position") if "position" in merged else None
    if nfl_pos is not None:
        merged["Position"] = [n if isinstance(n, str) and n else s
                              for n, s in zip(nfl_pos, merged["Position"])]
    return merged


def _is_quarterback(row: pd.Series, qb_rule: str) -> bool:
    if qb_rule == "slot":
        return str(row["slot"]) == "QB"
    return str(row["Position"]).upper() == "QB"


def lineups_without_touchdowns(seasons: Optional[Sequence[int]] = None,
                               qb_rule: str = "position",
                               kinds: Sequence[str] = TD_KINDS) -> pd.DataFrame:
    """Team-weeks in which no non-quarterback starter scored a touchdown.

    `qb_rule` decides what "non-quarterback" means — `"position"` excludes every
    quarterback, superflex included; `"slot"` excludes only the dedicated QB
    slot, so a superflex quarterback has to come up empty too. The two give
    different answers and both are defensible, which is why it is an argument.

    Every row carries `unresolved`, the number of its counted starters with no
    stat line: a team-week with a zero count and a non-zero `unresolved` is a
    candidate, not a finding.
    """
    if qb_rule not in QB_RULES:
        raise ValueError(f"qb_rule must be one of {QB_RULES}, got {qb_rule!r}")
    years = list(seasons) if seasons is not None else sorted(
        set(Q.export_seasons()) & set(Q.completed_seasons()) | {y for y in Q.export_seasons()
                                                                if not Q.season_meta(y).has_snapshot})
    frames = []
    for season in years:
        rows = starter_touchdowns(season, kinds=kinds)
        if rows.empty:
            continue
        counted = rows[~rows["empty_slot"] & ~rows.apply(_is_quarterback, axis=1,
                                                         qb_rule=qb_rule)]
        grouped = counted.groupby(["Year", "Week", "Team"], as_index=False).agg(
            touchdowns=("touchdowns", "sum"),
            starters_counted=("Player", "count"),
            unresolved=("resolved", lambda s: int((~s).sum())),
            starter_points=("Points", "sum"))
        frames.append(grouped)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out[out["touchdowns"] == 0].sort_values(["Year", "Week", "Team"])
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
#: Floor for `check_touchdown_join`, by whether the season's points are Sleeper's.
EXACT_RATE_FLOOR: Dict[bool, float] = {True: 0.95, False: 0.88}


def check_touchdown_join(season: int, min_exact_rate: Optional[float] = None,
                         tolerance: float = 0.011) -> List[str]:
    """The stat line attached to a starter must be that starter's own.

    No sheet carries a touchdown, so there is no count to reconcile. What can be
    reconciled is the JOIN: re-score each matched nflverse line with the
    league's settings (`contracts.lotg_points`) and it has to reproduce the
    points the build already holds for that same starter-week. Landing on the
    wrong player moves the points immediately.

    Not an identity, and not asserted as one. Observed 98.4-98.9% exact across
    2021-2025, the residual being a point here and there in the scoring model
    plus three back-corrected touchdowns. 2020 sits at 91.8% for a different
    reason — its points are ESPN's, not Sleeper's — so a season without a
    snapshot gets the lower floor. Either way a real mis-join, landing stat
    lines on the wrong players, would take the rate nowhere near these.
    """
    season = int(season)
    if min_exact_rate is None:
        min_exact_rate = EXACT_RATE_FLOOR[Q.season_meta(season).has_snapshot]
    rows = starter_touchdowns(season)
    if rows.empty:
        return [f"{season}: no starter rows"]
    weekly = weekly_stats(season)
    weekly["_points"] = C.lotg_points(weekly)
    scored = dict(zip(zip(weekly["player_id"].astype(str),
                          weekly["week"].astype(int)), weekly["_points"].astype(float)))
    live = rows[rows["resolved"]]
    if live.empty:
        return [f"{season}: no starter-week resolved to a stat line"]
    agree = 0
    for _, row in live.iterrows():
        rescored = scored.get((str(row["gsis_id"]), int(row["Week"])))
        if rescored is not None and abs(rescored - float(row["Points"])) <= tolerance:
            agree += 1
    rate = agree / len(live)
    problems: List[str] = []
    if rate < min_exact_rate:
        problems.append(f"{season}: re-scored nflverse points match the build's own "
                        f"starter points on only {rate:.3f} of {len(live)} joined "
                        f"starter-weeks (floor {min_exact_rate})")
    return problems


def check_2020_coverage() -> List[str]:
    """Every 2020 starter must reach a `gsis_id`; neither name source alone does.

    2020 is the season with exports and no snapshot, so it is matched by name
    rather than by id. The ESPN bridge misses players the sheets now spell
    differently ("DJ Moore"); Sleeper's dictionary holds two players for some
    names. The pair covers all of them, and this is what says so.
    """
    if 2020 not in Q.export_seasons():
        return []
    rows = starter_touchdowns(2020)
    if rows.empty:
        return ["2020: no starter rows in player_week"]
    unmatched = sorted({str(r["Player"]) for _, r in rows.iterrows() if not r["gsis_id"]})
    return [f"2020: {len(unmatched)} starter name(s) reach no gsis_id: {unmatched[:8]}"] if unmatched else []


# ---------------------------------------------------------------------------
# Careers: what a starter had already done, and what he ended up doing
# ---------------------------------------------------------------------------
#: nflverse's earliest season. Nothing before this can be counted, which is
#: safe here only because no player ever started in this league debuted before
#: 2000 (`check_career_window_covers_starters` is what says so).
FIRST_NFLVERSE_SEASON = 1999

#: Season totals, one file per season. The release tag differs from the weekly
#: one, and the newest seasons have no seasonal file at all — see `_seasonal`.
SEASONAL_URLS = (
    "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_season_{season}.csv",
    "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_season_{season}.csv",
)
#: They live in a SUBDIRECTORY of the cache, deliberately. `.cache/*.csv` is the
#: build's freshness-gated baseline: every file directly in there is expected to
#: carry a stamp in `_fetch_log.json` (`test_refresh_external` asserts it), and
#: these are pulled by `_download_best_effort`, which does not stamp. Dropping
#: them beside the build's files fails that guard — which is exactly what
#: happened the first time this was written.
SEASONAL_DIR = "seasons"
SEASONAL_FILE = "nflverse_stats_player_season_{season}.csv"


def seasonal_path(season: int) -> Path:
    """Where one season-totals file is cached (never directly in `.cache/`)."""
    return (Q.repo_root() / ".cache" / SEASONAL_DIR
            / SEASONAL_FILE.format(season=int(season)))

#: Which games count toward a career. The fantasy season ends before the NFL
#: playoffs, so `"reg"` is the default; `"reg_post"` is the sensitivity run.
CAREER_BASES: Tuple[str, ...] = ("reg", "reg_post")

#: How long a player has been "in the league". `"roster"` counts league years
#: over his whole career (last season on a roster minus rookie season), so a
#: year lost to injury still counts; `"played"` counts only seasons with a stat
#: line; `"at_start"` counts league years AS OF the start being ranked, which is
#: the only one that answers "he had been around N years when they started him".
#: They disagree often enough to change an answer: Jahan Dotson was a 2022
#: rookie started in 2023 — two years in at the time, four by `"roster"`.
YEARS_RULES: Tuple[str, ...] = ("roster", "played", "at_start")

#: Which tenure rule fits which career measure, when the caller names neither.
DEFAULT_YEARS_RULE = {"career_total": "roster", "career_to_date": "at_start"}


@functools.lru_cache(maxsize=64)
def _seasonal(season: int, root: str) -> Optional[pd.DataFrame]:
    """nflverse season totals for one season, or None where none is published.

    Downloaded once and never refreshed: a finished season's totals do move
    (nflverse back-corrects), but not enough to re-pull 27 files per question,
    and `check_career_sources_agree()` measures the drift that is left. The
    current and in-progress seasons have no seasonal file — `career_totals()`
    aggregates those from the weekly file instead.
    """
    path = (Path(root) / ".cache" / SEASONAL_DIR
            / SEASONAL_FILE.format(season=season))
    if not (path.exists() and path.stat().st_size > 0):
        path.parent.mkdir(parents=True, exist_ok=True)
        urls = [u.format(season=season) for u in SEASONAL_URLS]
        try:
            X._download_best_effort(urls, path, _config().timeout_seconds)
        except Exception:
            return None
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    if "season_type" not in df.columns or "player_id" not in df.columns:
        return None
    df["player_id"] = df["player_id"].astype(str)
    df["season_type"] = df["season_type"].astype(str).str.upper()
    return df


def _basis_types(basis: str) -> Tuple[str, ...]:
    # A seasonal file carries THREE kinds of row per player: REG, POST and
    # REG+POST — the last being the sum of the other two. Adding them all up
    # double-counts every career, so a basis names the rows it wants and never
    # touches "REG+POST".
    if basis not in CAREER_BASES:
        raise ValueError(f"basis must be one of {CAREER_BASES}, got {basis!r}")
    return ("REG",) if basis == "reg" else ("REG", "POST")


@functools.lru_cache(maxsize=16)
def _season_values_cached(stat: str, basis: str, through: int, root: str
                          ) -> Tuple[Dict[Tuple[str, int], float], Tuple[str, ...]]:
    """{(gsis_id, season): stat} for every season up to `through`, plus warnings."""
    types = _basis_types(basis)
    out: Dict[Tuple[str, int], float] = {}
    warnings: List[str] = []
    for season in range(FIRST_NFLVERSE_SEASON, through + 1):
        frame = _seasonal(season, root)
        if frame is not None:
            if stat not in frame.columns:
                warnings.append(f"{season}: seasonal file has no column {stat!r}")
                continue
            rows = frame[frame["season_type"].isin(types)]
            values = pd.to_numeric(rows[stat], errors="coerce").fillna(0.0)
            for pid, value in zip(rows["player_id"], values):
                out[(str(pid), season)] = out.get((str(pid), season), 0.0) + float(value)
            continue
        # No seasonal file: aggregate the weekly one, which exists from 2018.
        try:
            weekly = _weekly_all(season, root)
        except Exception:
            warnings.append(f"{season}: no seasonal file and no weekly file — "
                            f"careers spanning it are understated")
            continue
        if stat not in weekly.columns:
            warnings.append(f"{season}: weekly file has no column {stat!r}")
            continue
        rows = weekly[weekly["season_type"].astype(str).str.upper().isin(types)]
        grouped = pd.to_numeric(rows[stat], errors="coerce").fillna(0.0).groupby(
            rows["player_id"].astype(str)).sum()
        for pid, value in grouped.items():
            out[(str(pid), season)] = float(value)
    return out, tuple(warnings)


@functools.lru_cache(maxsize=8)
def _weekly_all(season: int, root: str) -> pd.DataFrame:
    """The weekly file with POST rows kept — `_weekly_cached` drops them."""
    df = X.load_nflverse_stats_player_week(_config(), season)
    df = df.copy()
    df["player_id"] = df["player_id"].astype(str)
    df["week"] = pd.to_numeric(df["week"], errors="coerce").astype("Int64")
    return df


def career_totals(stat: str = "rushing_yards", basis: str = "reg",
                  through: Optional[int] = None) -> Dict[str, float]:
    """Lifetime `stat` per `gsis_id`, everything nflverse has through `through`.

    `through` defaults to the newest season with any data, so an in-progress
    season counts the weeks already played — a career total is as of today, not
    as of last January.
    """
    through = int(through) if through is not None else max(snapshot_or_export_seasons())
    values, _ = _season_values_cached(stat, basis, int(through), str(Q.repo_root()))
    out: Dict[str, float] = {}
    for (pid, _season), value in values.items():
        out[pid] = out.get(pid, 0.0) + value
    return out


def snapshot_or_export_seasons() -> List[int]:
    """Every season this league has data for, in-progress one included."""
    return sorted(set(Q.export_seasons()) | set(Q.snapshot_seasons()))


@functools.lru_cache(maxsize=1)
def _service_cached(root: str) -> Dict[str, Dict[str, Any]]:
    ids = X.load_nflverse_player_ids(_config())
    out: Dict[str, Dict[str, Any]] = {}
    for row in ids.itertuples(index=False):
        gsis = getattr(row, "gsis_id", None)
        if not isinstance(gsis, str) or not gsis:
            continue
        rookie = getattr(row, "rookie_season", None)
        last = getattr(row, "last_season", None)
        out[gsis] = {
            "rookie_season": None if pd.isna(rookie) else int(rookie),
            "last_season": None if pd.isna(last) else int(last),
        }
    return out


def service(gsis_id: str) -> Dict[str, Any]:
    """`rookie_season` / `last_season` for one player, from nflverse's own file."""
    return dict(_service_cached(str(Q.repo_root())).get(str(gsis_id), {}))


def starter_careers(stat: str = "rushing_yards", basis: str = "reg",
                    seasons: Optional[Sequence[int]] = None,
                    through: Optional[int] = None) -> pd.DataFrame:
    """Every starter-week with the player's career in `stat` beside it.

    Two career numbers, because they answer different questions and get mixed
    up: `career_to_date` is what he had done *entering that game* (prior
    seasons plus earlier weeks of the same one) — the résumé the manager was
    looking at; `career_total` is the whole career, including everything he did
    afterwards. `years_in_league` and `seasons_played` are the two readings of
    tenure (`YEARS_RULES`), so a filter like "3+ years" can be taken either way.

    Joined on `gsis_id` throughout: nflverse renames players between vintages
    (John Metchie is "John Metchie III" in 2023 and "John Metchie" in 2024), so
    a name join silently loses seasons.
    """
    years = tuple(seasons) if seasons is not None else tuple(Q.export_seasons())
    root = str(Q.repo_root())
    through = int(through) if through is not None else max(snapshot_or_export_seasons())
    return _starter_careers_cached(stat, basis, years, through, root).copy()


@functools.lru_cache(maxsize=8)
def _starter_careers_cached(stat: str, basis: str, years: Tuple[int, ...],
                            through: int, root: str) -> pd.DataFrame:
    per_season, _ = _season_values_cached(stat, basis, through, root)
    lifetime = career_totals(stat, basis, through)
    types = _basis_types(basis)
    played: Dict[str, set] = {}
    for (pid, season) in per_season:
        played.setdefault(pid, set()).add(season)

    rows: List[dict] = []
    for season in years:
        starters = starter_touchdowns(season)
        if starters.empty:
            continue
        weekly = _weekly_all(season, root)
        weekly = weekly[weekly["season_type"].astype(str).str.upper().isin(types)]
        values = pd.to_numeric(weekly.get(stat), errors="coerce").fillna(0.0)
        by_player_week: Dict[Tuple[str, int], float] = {}
        for pid, week, value in zip(weekly["player_id"], weekly["week"], values):
            if pd.isna(week):
                continue
            key = (str(pid), int(week))
            by_player_week[key] = by_player_week.get(key, 0.0) + float(value)
        prior: Dict[str, float] = {}
        for (pid, yr), value in per_season.items():
            if yr < season:
                prior[pid] = prior.get(pid, 0.0) + value
        for _, row in starters.iterrows():
            gsis = row["gsis_id"]
            if row["empty_slot"] or not isinstance(gsis, str) or not gsis:
                continue
            week = int(row["Week"])
            same = sum(v for (pid, wk), v in by_player_week.items()
                       if pid == gsis and wk < week)
            svc = _service_cached(root).get(gsis, {})
            rookie, last = svc.get("rookie_season"), svc.get("last_season")
            rows.append(dict(
                Year=season, Week=week, Team=row["Team"], Player=row["Player"],
                Position=row["Position"], slot=row["slot"], gsis_id=gsis,
                Points=row["Points"],
                career_to_date=round(prior.get(gsis, 0.0) + same, 2),
                career_total=round(lifetime.get(gsis, 0.0), 2),
                rookie_season=rookie, last_season=last,
                years_in_league=(last - rookie + 1) if rookie and last else None,
                years_at_start=(season - rookie + 1) if rookie else None,
                seasons_played=len({y for y in played.get(gsis, ()) if y <= season}),
                seasons_played_career=len(played.get(gsis, ())),
            ))
    return pd.DataFrame(rows)


def lowest_careers(stat: str = "rushing_yards", basis: str = "reg",
                   measure: str = "career_total", min_years: int = 3,
                   years_rule: Optional[str] = None, positions: Sequence[str] = (),
                   n: int = 5, seasons: Optional[Sequence[int]] = None) -> pd.DataFrame:
    """The starters with the least career `stat`, one row per player.

    `measure` picks which career: `"career_total"` (the whole career) or
    `"career_to_date"` (what he had when he was started, i.e. his thinnest
    qualifying start). `min_years` drops players too new for the question to
    mean anything, counted by `years_rule` — left unset it follows
    `DEFAULT_YEARS_RULE`, pairing a career-to-date question with the tenure the
    player actually had at that start rather than the one he ended up with.

    Among equal values the EARLIEST start is the one reported, so a player whose
    career sat still across several starts always shows the first of them. Ties
    at the cutoff are kept, not broken: asking for 5 can return 6 rows.
    """
    if measure not in ("career_total", "career_to_date"):
        raise ValueError(f"measure must be career_total or career_to_date, got {measure!r}")
    years_rule = years_rule or DEFAULT_YEARS_RULE[measure]
    if years_rule not in YEARS_RULES:
        raise ValueError(f"years_rule must be one of {YEARS_RULES}, got {years_rule!r}")
    frame = starter_careers(stat=stat, basis=basis, seasons=seasons)
    if frame.empty:
        return frame
    column = {"roster": "years_in_league", "played": "seasons_played_career",
              "at_start": "years_at_start"}[years_rule]
    frame = frame[frame[column].fillna(0) >= int(min_years)]
    if positions:
        wanted = {p.upper() for p in positions}
        frame = frame[frame["Position"].astype(str).str.upper().isin(wanted)]
    if frame.empty:
        return frame
    # one row per player: the earliest start that shows the measure at its lowest
    best = (frame.sort_values([measure, "Year", "Week"])
            .groupby("Player", as_index=False).first())
    best = best.sort_values([measure, "Player"])
    if n and len(best) > n:
        cutoff = best.iloc[n - 1][measure]
        best = best[best[measure] <= cutoff]      # keep ties at the boundary
    # how many of his starts the tenure filter kept — not his career total,
    # which is why the name says so.
    kept = frame.groupby("Player")["Week"].count()
    best["qualifying_starts"] = [int(kept.get(p, 0)) for p in best["Player"]]
    return best.reset_index(drop=True)


def check_career_sources_agree(seasons: Optional[Sequence[int]] = None,
                               stat: str = "rushing_yards",
                               max_mismatch_rate: float = 0.01) -> List[str]:
    """The seasonal files and the weekly files must tell the same story.

    A career mixes the two — seasonal totals for past seasons, the weekly file
    for the one a start sits in — so they have to agree where they overlap
    (2018 on). They very nearly do: nflverse revises a season after publishing
    its totals, which left 12 of 4,328 player-seasons apart when this was
    written (0.3%). The floor catches a real breakage — a units change, a
    double-counted REG+POST row — rather than that drift.
    """
    root = str(Q.repo_root())
    years = list(seasons) if seasons is not None else [
        y for y in range(2018, max(snapshot_or_export_seasons()) + 1)]
    problems: List[str] = []
    compared = mismatched = 0
    for season in years:
        frame = _seasonal(season, root)
        if frame is None or stat not in frame.columns:
            continue
        try:
            weekly = _weekly_all(season, root)
        except Exception:
            continue
        reg = frame[frame["season_type"] == "REG"]
        want = dict(zip(reg["player_id"].astype(str),
                        pd.to_numeric(reg[stat], errors="coerce").fillna(0.0)))
        wk = weekly[weekly["season_type"].astype(str).str.upper() == "REG"]
        got = pd.to_numeric(wk[stat], errors="coerce").fillna(0.0).groupby(
            wk["player_id"].astype(str)).sum().to_dict()
        for pid, value in want.items():
            if pid not in got:
                continue
            compared += 1
            if abs(float(value) - float(got[pid])) > 0.5:
                mismatched += 1
    if compared and mismatched / compared > max_mismatch_rate:
        problems.append(f"seasonal vs weekly {stat}: {mismatched} of {compared} "
                        f"player-seasons disagree "
                        f"({mismatched / compared:.3f} > {max_mismatch_rate})")
    if not compared:
        problems.append(f"no overlapping player-seasons to compare for {stat}")
    return problems


def check_career_window_covers_starters() -> List[str]:
    """No starter may have debuted before nflverse's first season.

    A career is only a career if it is whole: a player who took his first snap
    in 1998 would come back missing a year, silently. Nobody started in this
    league did — the earliest is a 2000 rookie — and this is what keeps that
    true if an older player is ever acquired.
    """
    problems: List[str] = []
    for season in Q.export_seasons():
        starters = starter_touchdowns(season)
        if starters.empty:
            continue
        for gsis in {g for g in starters["gsis_id"] if isinstance(g, str) and g}:
            rookie = service(gsis).get("rookie_season")
            if rookie is not None and rookie < FIRST_NFLVERSE_SEASON:
                problems.append(f"{gsis} debuted in {rookie}, before nflverse's "
                                f"{FIRST_NFLVERSE_SEASON} — career totals are truncated")
    return problems


def check_career_to_date_arithmetic(stat: str = "rushing_yards",
                                   basis: str = "reg",
                                   max_player_rate: float = 0.05) -> List[str]:
    """The mixed-source career must match the single-source one where both exist.

    `career_to_date` adds seasonal totals for past seasons to weekly rows for
    the season a start sits in. For a player whose whole career is inside the
    weekly files (a 2018-or-later rookie) the same number can be rebuilt from
    weekly rows alone, and the two should agree.

    It is a rate, not an identity, for the reason `check_career_sources_agree`
    exists: nflverse revises a season after publishing its totals, so a few
    player-seasons differ between the two files and every start after one of
    them inherits the gap (Kyler Murray's 2019 rushing yards are 539 in the
    seasonal file and 544 in the weekly one). What this actually guards is the
    SEAM — an off-by-one week, a dropped season, a double-counted `REG+POST`
    row would put most players wrong, not a handful. So the floor is on the
    share of PLAYERS affected.
    """
    root = str(Q.repo_root())
    types = _basis_types(basis)
    frame = starter_careers(stat=stat, basis=basis)
    if frame.empty:
        return ["no starter-weeks to check"]
    by_week: Dict[int, Dict[Tuple[str, int], float]] = {}

    def index(season: int) -> Dict[Tuple[str, int], float]:
        if season not in by_week:
            df = _weekly_all(season, root)
            df = df[df["season_type"].astype(str).str.upper().isin(types)]
            values = pd.to_numeric(df.get(stat), errors="coerce").fillna(0.0)
            table: Dict[Tuple[str, int], float] = {}
            for pid, week, value in zip(df["player_id"], df["week"], values):
                if pd.isna(week):
                    continue
                key = (str(pid), int(week))
                table[key] = table.get(key, 0.0) + float(value)
            by_week[season] = table
        return by_week[season]

    checked: set = set()
    off: Dict[str, str] = {}
    for row in frame.itertuples(index=False):
        rookie = row.rookie_season
        if rookie is None or rookie < 2018:
            continue
        total = 0.0
        for season in range(int(rookie), int(row.Year) + 1):
            limit = int(row.Week) if season == int(row.Year) else 99
            total += sum(v for (pid, wk), v in index(season).items()
                         if pid == row.gsis_id and wk < limit)
        checked.add(row.gsis_id)
        if abs(total - float(row.career_to_date)) > 0.5 and row.gsis_id not in off:
            off[row.gsis_id] = (f"{row.Player} {row.Year} wk{row.Week}: "
                                f"{row.career_to_date} vs weekly-only {total:.1f}")
    if not checked:
        return ["no 2018-or-later rookie start to cross-check"]
    rate = len(off) / len(checked)
    if rate > max_player_rate:
        listed = "; ".join(list(off.values())[:5])
        return [f"career_to_date disagrees with a weekly-only rebuild for "
                f"{len(off)} of {len(checked)} players ({rate:.3f} > "
                f"{max_player_rate}) — the seam, not upstream drift: {listed}"]
    return []
