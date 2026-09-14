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
* **2020 has no snapshot**, so its rows are matched by name, and its `slot`
  comes from the export column — which was only correct from the build that
  carried the `espn_2020._slot_ordered` fix. `qb_rule="slot"` on 2020 against
  older exports is reading shuffled labels.
"""
from __future__ import annotations

import csv
import functools
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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
