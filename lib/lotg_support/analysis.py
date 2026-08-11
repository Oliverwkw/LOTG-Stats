"""Analysis primitives for the question shapes that keep coming up.

Layered on `lotg_support.inquiry` (which finds and filters rows); this module is
about the joins and comparisons that a *judgement* question needs and that no
single export sheet holds:

  * **Position, attached to anything.** `picks`, `transactions` and `trades` do
    not carry a position column, so any "are QBs overvalued / who had the best
    WR corps" question stalls immediately. `position_of()` / `with_position()`
    supply it, per season, from the build's own `player_week.Position` — which
    also sidesteps the current-only Sleeper dictionary's position drift.

  * **Roster groups over a window.** `position_group()` turns "the WRs on this
    team that season" into a row with depth measures — how much the group
    scored, how concentrated it was, how many players actually carried it —
    rather than a single total that a lone star can dominate.

  * **Lineup composition.** `lineups()` / `lineup_stacks()` expose what each
    fielded lineup was made of, including how many starters shared an NFL team,
    so "does stacking cost me ceiling" becomes a group-by instead of a project.

  * **Cohort comparison.** `compare()` splits any frame on a predicate and
    reports both sides — n, mean, median, difference, effect size, a
    permutation p-value, and a per-season breakdown so a result driven by one
    season cannot hide inside a pooled average.

  * **Ownership, for every player at once.** `timeline()` tells the story of
    one entity; `ownership_ledger()` / `ownership_summary()` are the vectorised
    form — one row per acquisition for the whole league, collapsed to how many
    rosters held a player and in what order — which is what a "who has property
    P about their ownership history" question needs.
    `check_trade_counts_match_build` ties it to `player_all_time`.

  * **Positional scarcity.** `value_curve()` / `scarcity()` measure what a
    position's points actually cost: the drop from the best player at a
    position to the *replacement* one, where replacement rank is taken from how
    many of that position the league actually starts each week, not assumed.

  * **Roster age, including right now.** `roster_ages()` recomputes
    `team_week."Player average age"` from the snapshot, which lets it answer the
    question for the *current* rosters — the exports stop at the last completed
    season, so the built column cannot. `check_roster_age_matches_build` ties it
    back to that column for every team-week the build did compute.

  * **Spend by position.** `spend_by_position()` joins draft capital (pick slot
    and KTC on draft day) and FAAB outlay to the points that came back, per
    team, so "am I valuing QBs differently from the league" is answerable per
    manager.

Every number here is derived from the committed exports; nothing writes, and
the build does not import this module. Where a result rests on an assumption
(replacement level, what counts as a "contributor"), the assumption is a named
parameter with a documented default rather than a constant buried in a loop.

Guards live in `check_*` functions and are exercised by `tests/test_analysis.py`:
the starter points this module reconstructs must reconcile with `team_week.PF`,
and the NFL-team stack counts must match the build's own
"Most number of players started from same NFL team" column.
"""
from __future__ import annotations

import functools
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from lotg_support import inquiry as Q

POSITIONS: Tuple[str, ...] = ("QB", "RB", "WR", "TE")

# A "contributor" week: a start is the league's own revealed judgement that the
# player was worth a slot, so depth is counted in starts rather than in points
# above an arbitrary threshold.
STARTER = "Starter"


# ---------------------------------------------------------------------------
# Position, attached to anything
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _positions_cached(root: str) -> Dict[Tuple[str, int], str]:
    pw = Q.load_sheet("player_week")
    years = Q.numeric(pw, "Year")
    out: Dict[Tuple[str, int], str] = {}
    for idx, (name, pos) in enumerate(zip(pw["Player"], pw["Position"])):
        year = years.iloc[idx]
        if pos and pd.notna(year):
            out[(str(name), int(year))] = str(pos)
    return out


def positions_by_season() -> Dict[Tuple[str, int], str]:
    """{(player, season): position} from the build's own player_week.

    Per-season by construction, so it is immune to the drift in Sleeper's
    current-only player dictionary (see `inquiry.season_eligibility`).
    """
    return _positions_cached(str(Q.repo_root()))


def position_of(player: str, season: Optional[int] = None) -> Optional[str]:
    """A player's position in one season, or his most common one across all."""
    table = positions_by_season()
    if season is not None:
        return table.get((str(player), int(season)))
    seen = [pos for (name, _), pos in table.items() if name == str(player)]
    return max(set(seen), key=seen.count) if seen else None


# Rows that name no real player: an undrafted future pick is written "Unknown",
# and a drop-only transaction has an empty "Player Added". Neither can carry a
# position, so they are excluded from placement rates rather than counted as
# failures — and reported separately, never silently.
PLACEHOLDER_NAMES = frozenset({"", "unknown", "n/a", "na", "-", "none"})


def is_placeholder(name: object) -> bool:
    """True if this cell names no actual player."""
    return str(name).strip().lower() in PLACEHOLDER_NAMES


def with_position(df: pd.DataFrame, name_column: str = "Player",
                  season_column: Optional[str] = "Year") -> pd.DataFrame:
    """Copy of `df` with a `Position` column joined on player (and season).

    This is the join that unlocks `picks` / `transactions`, neither of which
    carries a position. Sources, in order: the build's `player_week` for that
    exact season (best — it is per-season and immune to dictionary drift), then
    the same player in any season, then Sleeper's current dictionary (which
    covers players who were drafted or added but never appeared in a fielded
    week, and so have no `player_week` row at all).

    Rows whose player cannot be placed get an empty string rather than being
    dropped — count them and say so, per the over-inclusive rule
    (`unplaced()` gives them back).
    """
    table = positions_by_season()
    seasons = (Q.numeric(df, season_column)
               if season_column and season_column in df.columns else None)
    values = []
    for i, name in enumerate(df[name_column]):
        if is_placeholder(name):
            values.append("")
            continue
        year = seasons.iloc[i] if seasons is not None else None
        pos = None
        if year is not None and pd.notna(year):
            pos = table.get((str(name), int(year)))
        values.append(pos or position_of(name) or _dictionary_position(str(name)) or "")
    return df.assign(Position=values)


@functools.lru_cache(maxsize=None)
def _dictionary_position(name: str) -> str:
    """Position from Sleeper's current player dictionary, or "" if unresolvable."""
    try:
        players = Q.players()
        return players.position(players.resolve(name)) or ""
    except (KeyError, LookupError, FileNotFoundError):
        return ""


def unplaced(df: pd.DataFrame, name_column: str = "Player",
             include_placeholders: bool = False) -> pd.DataFrame:
    """Rows `with_position` could not place — report these, do not ignore them.

    Placeholder rows (an unexercised future pick, a drop-only transaction) are
    excluded by default: they name no player, so there is nothing to place.
    """
    if "Position" not in df.columns:
        df = with_position(df, name_column)
    keep = [not str(p).strip() and (include_placeholders or not is_placeholder(n))
            for p, n in zip(df["Position"], df[name_column])]
    return df[keep]


# ---------------------------------------------------------------------------
# Lineup composition
# ---------------------------------------------------------------------------
def lineups(season: Optional[int] = None, starters_only: bool = True) -> pd.DataFrame:
    """One row per rostered player-week, typed: Team, Year, Week, Player,
    Position, NFL team, Points, and whether he started.

    This is `player_week` with the numeric columns already parsed — the frame
    most composition questions want to group by.
    """
    filters = [f"Year={season}"] if season else []
    df = Q.rows("player_week", *filters)
    if starters_only:
        df = df[[str(v) == STARTER for v in df["Starter/Bench"]]]
    out = pd.DataFrame({
        "Team": df["Team"].astype(str),
        "Year": Q.numeric(df, "Year").astype("Int64"),
        "Week": Q.numeric(df, "Week").astype("Int64"),
        "Week Name": df["Week Name"].astype(str),
        "Player": df["Player"].astype(str),
        "Position": df["Position"].astype(str),
        "NFL team": df["NFL team"].astype(str),
        "Points": Q.numeric(df, "Points"),
        "Starter": [str(v) == STARTER for v in df["Starter/Bench"]],
    })
    return out.reset_index(drop=True)


def lineup_stacks(season: Optional[int] = None) -> pd.DataFrame:
    """One row per fielded lineup: how concentrated it was by NFL team.

    Columns: Team, Year, Week, starters, `max_same_nfl_team` (the largest block
    of starters from one NFL team), a `stack_<POS>` count for each position
    (the largest same-NFL-team block *within* that position — the "two Rams
    receivers" case), plus the team-week's PF, Max PF and Efficiency joined in
    so ceiling questions need no second lookup.
    """
    rows = lineups(season=season, starters_only=True)
    if rows.empty:
        return rows
    tw = Q.rows("team_week", *( [f"Year={season}"] if season else [] ))
    joined = {(str(r["Team"]), int(float(r["Year"])), int(float(r["Week"]))): r
              for _, r in tw.iterrows()}

    out: List[dict] = []
    for (team, year, week), grp in rows.groupby(["Team", "Year", "Week"], sort=True):
        nfl_counts = grp["NFL team"].value_counts()
        record = {
            "Team": team, "Year": int(year), "Week": int(week),
            "starters": int(len(grp)),
            "max_same_nfl_team": int(nfl_counts.max()) if len(nfl_counts) else 0,
            "distinct_nfl_teams": int(len(nfl_counts)),
            "starter_points": round(float(grp["Points"].sum()), 2),
        }
        for pos in POSITIONS:
            sub = grp[grp["Position"] == pos]
            counts = sub["NFL team"].value_counts()
            record[f"stack_{pos}"] = int(counts.max()) if len(counts) else 0
        built = joined.get((team, int(year), int(week)))
        if built is not None:
            record["PF"] = Q.to_number(built.get("PF"))
            record["Max PF"] = Q.to_number(built.get("Max PF"))
            record["Efficiency"] = Q.to_number(built.get("Efficiency"))
            record["Win?"] = str(built.get("Win?", ""))
        out.append(record)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Position groups (depth, not just a total)
# ---------------------------------------------------------------------------
def position_group(position: str = "WR", season: Optional[int] = None,
                   team: Optional[str] = None, starters_only: bool = True,
                   min_share: float = 0.05) -> pd.DataFrame:
    """One row per (Team, Year) for a position group, with depth measures.

    A single total flatters a team that had one great receiver, so alongside
    `points` this reports how the group's scoring was *distributed*:

      players            distinct players used at the position
      contributors       players carrying at least `min_share` of the group's points
      effective_players  1 / Σ(share²) — the inverse-Herfindahl "effective number"
                         of players, i.e. depth as a single number: 1.0 means one
                         player did everything, 4.0 means four equal contributors
      top1_share ..      fraction of group points from the best 1 / 2 / 3 players
      ppg                points per starter-week (quality, independent of volume)
      share_of_team      the group's share of the team's starter points

    `starters_only` keeps this about lineups actually fielded (the question is
    usually "what did the corps deliver", not "who sat on the bench").
    """
    rows = lineups(season=season, starters_only=starters_only)
    if rows.empty:
        return rows
    if team:
        rows = rows[rows["Team"].str.lower() == Q.canonical_team(team).lower()]
    team_totals = rows.groupby(["Team", "Year"])["Points"].sum()
    grp_rows = rows[rows["Position"] == position]

    out: List[dict] = []
    for (tm, year), grp in grp_rows.groupby(["Team", "Year"], sort=True):
        by_player = grp.groupby("Player")["Points"].sum().sort_values(ascending=False)
        total = float(by_player.sum())
        shares = (by_player / total) if total else by_player * 0.0
        weeks = int(len(grp))
        out.append({
            "Team": tm, "Year": int(year), "Position": position,
            "players": int(len(by_player)),
            "starter_weeks": weeks,
            "points": round(total, 2),
            "ppg": round(total / weeks, 2) if weeks else 0.0,
            "contributors": int((shares >= min_share).sum()),
            "effective_players": round(1.0 / float((shares ** 2).sum()), 2) if total else 0.0,
            "top1_share": round(float(shares.iloc[0]), 4) if len(shares) else 0.0,
            "top2_share": round(float(shares.iloc[:2].sum()), 4),
            "top3_share": round(float(shares.iloc[:3].sum()), 4),
            "best_player": str(by_player.index[0]) if len(by_player) else "",
            "share_of_team": round(total / float(team_totals.get((tm, year), 0.0)), 4)
            if team_totals.get((tm, year)) else 0.0,
        })
    return pd.DataFrame(out).sort_values("points", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Cohort comparison
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Comparison:
    """Two cohorts on one metric, with everything needed to judge the gap."""
    metric: str
    condition: str
    n_with: int
    n_without: int
    mean_with: float
    mean_without: float
    median_with: float
    median_without: float
    std_with: float
    std_without: float
    difference: float
    effect_size: float          # Cohen's d, pooled
    p_value: float              # two-sided permutation test
    permutations: int
    by_group: Tuple[Tuple[str, int, int, float, float], ...] = ()

    def describe(self) -> str:
        direction = "higher" if self.difference > 0 else "lower"
        lines = [
            f"{self.metric} — rows where [{self.condition}] vs the rest",
            f"  with:    n={self.n_with:<5} mean={self.mean_with:8.2f} "
            f"median={self.median_with:8.2f} sd={self.std_with:6.2f}",
            f"  without: n={self.n_without:<5} mean={self.mean_without:8.2f} "
            f"median={self.median_without:8.2f} sd={self.std_without:6.2f}",
            f"  difference: {self.difference:+.2f} ({direction}), "
            f"Cohen's d={self.effect_size:+.2f}, "
            f"permutation p={self.p_value:.3f} ({self.permutations:,} shuffles)",
        ]
        if self.by_group:
            lines.append("  per group (a pooled gap driven by one group is not a finding):")
            for label, n_a, n_b, m_a, m_b in self.by_group:
                lines.append(f"    {label:<8} n={n_a:>4}/{n_b:<4}  "
                             f"{m_a:8.2f} vs {m_b:8.2f}  ({m_a - m_b:+.2f})")
        return "\n".join(lines)


def _cohens_d(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    va, vb = pd.Series(a).var(ddof=1), pd.Series(b).var(ddof=1)
    pooled = math.sqrt(((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2))
    return float((pd.Series(a).mean() - pd.Series(b).mean()) / pooled) if pooled else 0.0


def _permutation_p(a: Sequence[float], b: Sequence[float], permutations: int,
                   seed: int) -> float:
    """Two-sided permutation test on the difference of means. Deterministic.

    Vectorised, because the over-inclusive sweeps run one of these per column
    and a Python-level shuffle loop would make them unusable.
    """
    if not len(a) or not len(b):
        return float("nan")
    import numpy as np

    pool = np.asarray(list(a) + list(b), dtype=float)
    n_a, total = len(a), len(pool)
    observed = abs(pool[:n_a].mean() - pool[n_a:].mean())
    rng = np.random.default_rng(seed)
    # argsort of uniform noise == an independent shuffle per row.
    picks = np.argsort(rng.random((permutations, total)), axis=1)[:, :n_a]
    sums_a = pool[picks].sum(axis=1)
    means_a = sums_a / n_a
    means_b = (pool.sum() - sums_a) / (total - n_a)
    hits = int((np.abs(means_a - means_b) >= observed - 1e-12).sum())
    return (hits + 1) / (permutations + 1)


def fdr_q_values(p_values: Sequence[float]) -> List[float]:
    """Benjamini-Hochberg q-values for a family of tests.

    An over-inclusive sweep runs a hundred tests at once, so five of them will
    clear p<0.05 by chance alone. Reporting a raw p-value from a sweep without
    saying how many tests produced it overstates the finding; the q-value is the
    expected false-discovery rate if you treat everything at or below it as
    real. Report both, and never quote a sweep's p-value on its own.
    """
    m = len(p_values)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: (math.inf if p_values[i] != p_values[i]
                                            else p_values[i]))
    out = [1.0] * m
    running = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        position = m - rank + 1
        p = p_values[idx]
        if p != p:  # NaN
            out[idx] = float("nan")
            continue
        running = min(running, p * m / position)
        out[idx] = round(min(1.0, running), 5)
    return out


def compare(df: pd.DataFrame, condition: str, metric: str,
            by: Optional[str] = "Year", permutations: int = 2000,
            seed: int = 0) -> Comparison:
    """Split `df` on `condition` and compare `metric` across the two cohorts.

    `condition` is an inquiry predicate (`stack_WR>=2`, `Position=QB`), applied
    to a frame that may already be numeric. Reports both cohorts in full plus a
    per-`by` breakdown, because a difference that only exists in one season is a
    different claim from one that holds every season — and the pooled number
    alone cannot tell you which you have.

    The p-value is a permutation test, not an assumption of normality; treat it
    as a guard against reading noise, not as proof.
    """
    pred = Q.parse_predicate(condition)
    if pred.column not in df.columns:
        raise KeyError(f"no column {pred.column!r} in this frame")
    if metric not in df.columns:
        raise KeyError(f"no column {metric!r} in this frame")

    mask = [pred.matches(v) for v in df[pred.column]]
    values = pd.to_numeric(df[metric], errors="coerce")
    keep = values.notna()
    with_rows = values[[m and k for m, k in zip(mask, keep)]]
    without_rows = values[[(not m) and k for m, k in zip(mask, keep)]]

    groups: List[Tuple[str, int, int, float, float]] = []
    if by and by in df.columns:
        for label, sub in df.groupby(by, sort=True):
            sub_mask = [pred.matches(v) for v in sub[pred.column]]
            sub_vals = pd.to_numeric(sub[metric], errors="coerce")
            a = sub_vals[[m and pd.notna(v) for m, v in zip(sub_mask, sub_vals)]]
            b = sub_vals[[(not m) and pd.notna(v) for m, v in zip(sub_mask, sub_vals)]]
            if len(a) and len(b):
                groups.append((str(label), len(a), len(b),
                               round(float(a.mean()), 2), round(float(b.mean()), 2)))

    return Comparison(
        metric=metric, condition=condition,
        n_with=int(len(with_rows)), n_without=int(len(without_rows)),
        mean_with=round(float(with_rows.mean()), 2) if len(with_rows) else float("nan"),
        mean_without=round(float(without_rows.mean()), 2) if len(without_rows) else float("nan"),
        median_with=round(float(with_rows.median()), 2) if len(with_rows) else float("nan"),
        median_without=round(float(without_rows.median()), 2) if len(without_rows) else float("nan"),
        std_with=round(float(with_rows.std(ddof=1)), 2) if len(with_rows) > 1 else 0.0,
        std_without=round(float(without_rows.std(ddof=1)), 2) if len(without_rows) > 1 else 0.0,
        difference=round(float(with_rows.mean() - without_rows.mean()), 2)
        if len(with_rows) and len(without_rows) else float("nan"),
        effect_size=round(_cohens_d(list(with_rows), list(without_rows)), 3),
        p_value=round(_permutation_p(list(with_rows), list(without_rows), permutations, seed), 4),
        permutations=permutations,
        by_group=tuple(groups),
    )


# ---------------------------------------------------------------------------
# Over-inclusive comparison: test EVERY column, then control for having done so
# ---------------------------------------------------------------------------
def numeric_columns(frame: pd.DataFrame, exclude: Sequence[str] = (),
                    min_values: int = 2) -> List[str]:
    """Every column of an arbitrary frame that can be compared as a number."""
    skip = set(exclude) | {"Team", "Year", "Week", "Week Name", "Player", "Position"}
    out = []
    for col in frame.columns:
        if col in skip:
            continue
        values = pd.to_numeric(frame[col], errors="coerce")
        if values.notna().sum() >= min_values and values.nunique() > 1:
            out.append(col)
    return out


def compare_all(frame: pd.DataFrame, condition: str, by: Optional[str] = "Year",
                columns: Optional[Sequence[str]] = None, permutations: int = 500,
                seed: int = 0, min_n: int = 5) -> pd.DataFrame:
    """Run `compare()` on EVERY numeric column, ranked by effect size.

    The over-inclusive form of a cohort question: instead of picking the metric
    you expect the condition to move ("does stacking cost me Max PF?"), test the
    condition against everything and let the data say what it moves.

    Returns one row per column with both cohorts' n and mean, the difference,
    Cohen's d, the permutation p — and a **BH q-value across the whole family**,
    because a hundred tests at p<0.05 yield about five hits from noise alone.
    Sort order is |d| descending; read `q` before believing any single row.
    """
    pred = Q.parse_predicate(condition)
    if pred.column not in frame.columns:
        raise KeyError(f"no column {pred.column!r} in this frame")
    cols = list(columns) if columns else numeric_columns(frame, exclude=[pred.column])
    rows: List[dict] = []
    for col in cols:
        result = compare(frame, condition, col, by=None, permutations=permutations, seed=seed)
        if min(result.n_with, result.n_without) < min_n:
            continue
        rows.append({
            "column": col, "n_with": result.n_with, "n_without": result.n_without,
            "mean_with": result.mean_with, "mean_without": result.mean_without,
            "difference": result.difference, "effect_size": result.effect_size,
            "p": result.p_value,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["q"] = fdr_q_values(list(df["p"]))
    df["tests"] = len(df)
    return (df.reindex(df["effect_size"].abs().sort_values(ascending=False).index)
            .reset_index(drop=True))


def correlate_all(frame: pd.DataFrame, target: str,
                  columns: Optional[Sequence[str]] = None,
                  method: str = "pearson", min_n: int = 10) -> pd.DataFrame:
    """Correlation of EVERY numeric column against one target, ranked by |r|.

    "What goes with winning?" answered without choosing the candidates first.
    `p` comes from the Fisher z-transform (a normal approximation, fine at these
    sample sizes and dependency-free), and `q` is the BH false-discovery rate
    across the family — the same multiple-testing discipline as `compare_all`.

    Correlation is not causation and these columns are not independent of each
    other; treat the ranking as a place to look, not as a result.
    """
    from statistics import NormalDist

    if target not in frame.columns:
        raise KeyError(f"no column {target!r} in this frame")
    y = pd.to_numeric(frame[target], errors="coerce")
    cols = [c for c in (columns or numeric_columns(frame)) if c != target]
    rows: List[dict] = []
    for col in cols:
        x = pd.to_numeric(frame[col], errors="coerce")
        pair = pd.DataFrame({"x": x, "y": y}).dropna()
        if len(pair) < min_n or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
            continue
        r = float(pair["x"].corr(pair["y"], method=method))
        if r != r:
            continue
        n = len(pair)
        if n > 3 and abs(r) < 1.0:
            z = math.atanh(r) * math.sqrt(n - 3)
            p = 2 * (1 - NormalDist().cdf(abs(z)))
        else:
            p = float("nan")
        rows.append({"column": col, "n": n, "r": round(r, 4), "p": round(p, 5)})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["q"] = fdr_q_values(list(df["p"]))
    df["tests"] = len(df)
    return (df.reindex(df["r"].abs().sort_values(ascending=False).index)
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Timelines: the same question over a different window
# ---------------------------------------------------------------------------
def _label(value: object) -> str:
    """Render an order key without float noise: 2025.0 -> '2025'."""
    number = Q.to_number(value)
    if number is not None and abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return str(value)


def best_stretch(frame: pd.DataFrame, value_column: str, length: int,
                 entity_columns: Sequence[str] = ("Team",),
                 order_columns: Sequence[str] = ("Year", "Week"),
                 n: int = 10, aggregate: str = "sum") -> pd.DataFrame:
    """Best contiguous run of `length` rows per entity, ranked.

    "All time" is rarely one window: a corps that dominated three seasons and a
    single monster year are different claims, and a season-level total answers
    neither. Give this any long frame — team-weeks, a `position_group()` table,
    a player's seasons — and it finds the best run of `length` consecutive rows
    for each entity.

    Contiguity is by row order *within the entity* after sorting on
    `order_columns`, not by calendar: if an entity is missing a week, its
    neighbours become adjacent. `span` reports the real endpoints, so a run that
    silently jumped a gap is visible in the output rather than hidden in it.
    """
    entity_columns, order_columns = list(entity_columns), list(order_columns)
    order_columns = [c for c in order_columns if c in frame.columns]
    work = frame.copy()
    work["_value"] = pd.to_numeric(work[value_column], errors="coerce")
    work = work.dropna(subset=["_value"]).sort_values(entity_columns + order_columns)

    rows: List[dict] = []
    for key, grp in work.groupby(entity_columns, sort=False):
        values = grp["_value"].to_numpy()
        if len(values) < length:
            continue
        labels = [" ".join(_label(v) for v in tup)
                  for tup in grp[order_columns].itertuples(index=False)] \
            if order_columns else [str(i) for i in range(len(values))]
        for start in range(len(values) - length + 1):
            window = values[start:start + length]
            total = float(window.sum())
            rows.append({
                **dict(zip(entity_columns, key if isinstance(key, tuple) else (key,))),
                "start": labels[start], "end": labels[start + length - 1],
                "span": f"{labels[start]} -> {labels[start + length - 1]}",
                "length": length,
                "total": round(total, 2),
                "mean": round(total / length, 2),
                "min": round(float(window.min()), 2),
                "max": round(float(window.max()), 2),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    metric = "total" if aggregate == "sum" else "mean"
    # One row per entity: its own best window, then rank entities against each other.
    best = (df.sort_values(metric, ascending=False)
            .groupby(entity_columns, sort=False).head(1)
            .sort_values(metric, ascending=False))
    return best.head(n).reset_index(drop=True)


def timeline(player: Optional[str] = None, team: Optional[str] = None,
             season: Optional[int] = None) -> pd.DataFrame:
    """Every recorded event for a player or a team, in date order.

    Draft picks, adds, drops and trades arrive from three different sheets with
    three different date columns, so "tell me the story of X" otherwise means
    three lookups and a manual merge. Rows are `date, season, event, team,
    detail` — undated rows keep their season and sort to the front of it, and
    are marked, rather than being dropped for lacking a date.
    """
    events: List[dict] = []
    canonical = Q.canonical_team(team) if team else None

    def matches_team(value: object) -> bool:
        return canonical is None or str(value).strip().lower() == canonical.lower()

    def matches_player(value: object) -> bool:
        return player is None or str(value).strip().lower() == str(player).strip().lower()

    picks = Q.load_sheet("picks")
    for _, r in picks.iterrows():
        if not (matches_player(r["Player Picked"]) and matches_team(r["Team"])):
            continue
        year = Q.to_number(r["Year"])
        if season and year != season:
            continue
        events.append({"date": "", "season": int(year) if year else None,
                       "event": "drafted", "team": str(r["Team"]),
                       "detail": f"pick {r['Number']}: {r['Player Picked']}"
                                 + (f" (from {r['Original Team']})"
                                    if str(r.get("Original Team", "")).strip()
                                    and r.get("Original Team") != r["Team"] else "")})

    txns = Q.load_sheet("transactions")
    for _, r in txns.iterrows():
        year = Q.to_number(r["Season"])
        if season and year != season:
            continue
        if matches_team(r["Team"]) and (matches_player(r["Player Added"])
                                        or matches_player(r["Player Dropped"])):
            bits = []
            if str(r["Player Added"]).strip():
                bits.append(f"+{r['Player Added']}")
            if str(r["Player Dropped"]).strip():
                bits.append(f"-{r['Player Dropped']}")
            faab = Q.to_number(r["Faab"])
            if faab:
                bits.append(f"${faab:g} FAAB")
            events.append({"date": str(r["Date"]), "season": int(year) if year else None,
                           "event": str(r["type of transaction (waiver/free agency)"]) or "add/drop",
                           "team": str(r["Team"]), "detail": " ".join(bits)})

    trades = Q.load_sheet("trades")
    for _, r in trades.iterrows():
        year = Q.to_number(r["Season"])
        if season and year != season:
            continue
        received, sent = str(r["Assets received"]), str(r["Assets sent"])
        touches_player = player is None or any(
            str(player).strip().lower() in text.lower() for text in (received, sent))
        if matches_team(r["Team"]) and touches_player:
            events.append({"date": str(r["Date"]), "season": int(year) if year else None,
                           "event": "trade", "team": str(r["Team"]),
                           "detail": f"got {received} | sent {sent}"})

    df = pd.DataFrame(events)
    if df.empty:
        return df
    df["undated"] = [not str(d).strip() for d in df["date"]]
    return (df.sort_values(["season", "undated", "date"], ascending=[True, False, True])
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Ownership: which rosters held a player, in what order
# ---------------------------------------------------------------------------
# A traded draft pick is written into the `trades` sheet's asset cells as
# "2021 1.06(T. Etienne)" — the leading season is what distinguishes it from a
# player. Splitting an asset cell on ";" without this test reads "T. Etienne"
# as a traded player, which invents a 2020 trade for a player who did not enter
# the league until 2021. The build itself never has this problem (it counts
# trades by Sleeper pid, off `_recv_player_ids`); it is only a hazard for code
# reading the *exported* sheet, where the pids are gone and only names survive.
PICK_ASSET = re.compile(r"^\d{4}\s")

# FAAB rides along in the same asset cells, written "$15 FAAB" (25 distinct
# amounts across the sheet, 166 tokens, 2022 onward). It is neither a pick nor a
# placeholder, so anything testing only for those reads cash as a player.
FAAB_ASSET = re.compile(r"^\$")

# Sleeper can record one exchange twice — once as the pick trade, once as the
# player swap that executes it — when the picks change hands around the draft
# that converts them. The league's only instance: on 2021-08-29 LWebs53 and
# shmuel256 traded 2021 2.08 for 3.06 + two later fourths (transaction
# 737726835374374912), and the same pair separately swapped the two players
# those picks became, Michael Carter for Rhamondre Stevenson (transaction
# 737729902018686976, timestamped inside the draft window). `picks` confirms
# they are the same assets: 2.08 is Carter, held by LWebs53, originally
# shmuel256's; 3.06 is Stevenson, held by shmuel256, originally LWebs53's.
# Counting both would move each player twice for one deal, so the player-side
# record is dropped and the pick trade kept — which is what the build does, and
# why `check_trade_counts_match_build` reconciles exactly.
DUPLICATE_TRADE_TRANSACTIONS: Dict[str, str] = {
    "737729902018686976": "player-side duplicate of pick trade 737726835374374912 "
                          "(2021-08-29, LWebs53 <-> shmuel256)",
}

ACQUISITION_EVENTS: Tuple[str, ...] = ("draft", "add", "trade")

# The exported sheets write their `Date` as Sleeper's `created` stamp rendered in
# US Eastern: 524 of the 548 `trades` rows land within two seconds of a snapshot
# trade's `created` under this zone (the 24 that do not are exactly the 2020 ESPN
# rows, which have no snapshot), against 2 under UTC and 6 under US Central.
# Ordering a snapshot event against a sheet event therefore means putting both on
# this clock — the snapshot's own date is day-precision only, so without it a
# waiver add and the trade that moved the player out the same day sort by luck.
EXPORT_TIMEZONE = "America/New_York"


def split_assets(cell: object) -> Tuple[List[str], List[str], List[str]]:
    """One `trades` sheet asset cell -> (player names, pick labels, FAAB).

    Use this rather than a bare `split(";")`: the cell mixes three kinds of
    asset and only one of them is a player. See `PICK_ASSET` and `FAAB_ASSET`
    for what the other two look like and why each has bitten. The three lists
    are returned rather than filtered away so a caller pricing a trade can see
    everything that moved.
    """
    players: List[str] = []
    picks: List[str] = []
    faab: List[str] = []
    for raw in str(cell if cell is not None else "").split(";"):
        asset = raw.strip()
        if not asset or asset.lower() == "nan" or is_placeholder(asset):
            continue
        if PICK_ASSET.match(asset):
            picks.append(asset)
        elif FAAB_ASSET.match(asset):
            faab.append(asset)
        else:
            players.append(asset)
    return players, picks, faab


def _sheet_epoch_ms(stamp: object) -> Optional[int]:
    """A sheet timestamp -> epoch ms, so it can be ordered against a snapshot event.

    Returns None for a blank or unparseable cell (a draft row carries a season,
    not a day), which sorts to the front of its season rather than being dropped.
    """
    text = str(stamp if stamp is not None else "").strip()
    if not text:
        return None
    try:
        local = datetime.fromisoformat(text)
    except ValueError:
        return None
    if local.tzinfo is None:
        local = local.replace(tzinfo=ZoneInfo(EXPORT_TIMEZONE))
    return int(local.timestamp() * 1000)


def _resolve_quietly(name: str) -> str:
    """Sleeper pid for a name, or "" — a lookup failure is data, not an error."""
    try:
        return Q.players().resolve(name)
    except (KeyError, LookupError, ValueError):
        return ""


def _season_of_label(label: object) -> Optional[int]:
    """Season out of a `picks.Year` label — "2021 (vet)" -> 2021, "startup" -> inception.

    "startup" is the league's 19-round inception draft: 152 rows numbered
    through 19.08, matching the ESPN draft of 2020-09-10 recorded in
    `exports/raw/drafts_2020.json`, and 150 of its 152 picks played here that
    same season. It therefore belongs to the earliest exported season, not to
    no season at all — leaving it unlabelled drops every startup acquisition
    out of any season-filtered view, which loses the origin of every original
    roster and makes a filtered `path` start at a player's first *trade*.
    """
    match = re.search(r"(\d{4})", str(label))
    if match:
        return int(match.group(1))
    if str(label).strip().lower() == "startup":
        seasons = Q.export_seasons()
        return min(seasons) if seasons else None
    return None


def _sheet_trade_events(seasons: Sequence[int]) -> List[dict]:
    """Acquisitions from the exported `trades` sheet, for seasons given.

    Only used where no snapshot exists (2020, the ESPN backfill), because the
    sheet has lost the pids and a multi-team trade's sender has to be recovered
    by matching the player's name on the other rows of the same trade.
    """
    wanted = {int(s) for s in seasons}
    if not wanted:
        return []
    sheet = Q.load_sheet("trades")
    senders: Dict[Tuple[int, str, str], List[str]] = {}
    rows: List[Tuple[int, str, str, List[str]]] = []
    for _, r in sheet.iterrows():
        year = Q.to_number(r["Season"])
        if year is None or int(year) not in wanted:
            continue
        year, date, team = int(year), str(r["Date"]), str(r["Team"])
        for name in split_assets(r["Assets sent"])[0]:
            senders.setdefault((year, date, name), []).append(team)
        rows.append((year, date, team, split_assets(r["Assets received"])[0]))
    events: List[dict] = []
    for year, date, team, received in rows:
        for name in received:
            gave = [t for t in senders.get((year, date, name), []) if t != team]
            events.append({
                "player": name, "player_id": _resolve_quietly(name), "season": year,
                "date": date, "event": "trade", "team": team,
                "from_team": gave[0] if len(gave) == 1 else "",
                "source": "sheet", "_order": _sheet_epoch_ms(date),
            })
    return events


def _snapshot_trade_events(seasons: Sequence[int],
                           include_duplicates: bool = False) -> List[dict]:
    """Acquisitions from the raw Sleeper snapshot — pid-exact.

    Skips `DUPLICATE_TRADE_TRANSACTIONS` unless asked for them.
    """
    events: List[dict] = []
    names = Q.players()
    for year in seasons:
        teams = Q.teams(year)
        # `Q.trades` decides what counts as a completed trade; the raw pass here
        # is only to recover the *sending* roster, which `Trade` does not carry.
        dropped_by: Dict[str, Dict[str, int]] = {}
        completed_at: Dict[str, int] = {}
        for txn in Q.raw_transactions(year):
            if txn.get("type") == "trade":
                txn_id = str(txn.get("transaction_id"))
                dropped_by[txn_id] = {
                    str(k): int(v) for k, v in (txn.get("drops") or {}).items()}
                # `created`, not `status_updated`: that is the stamp the sheets
                # print, so the two sources order consistently against each other.
                completed_at[txn_id] = int(txn.get("created") or 0)
        for trade in Q.trades(season=year):
            if not include_duplicates and trade.transaction_id in DUPLICATE_TRADE_TRANSACTIONS:
                continue
            drops = dropped_by.get(trade.transaction_id, {})
            for roster_id, pids in trade.received.items():
                for pid in pids:
                    sender = drops.get(str(pid))
                    events.append({
                        "player": names.name(str(pid)), "player_id": str(pid),
                        "season": trade.season, "date": trade.date, "event": "trade",
                        "team": teams.get(int(roster_id), str(roster_id)),
                        "from_team": teams.get(int(sender), "") if sender else "",
                        "source": "snapshot",
                        "_order": completed_at.get(trade.transaction_id, 0),
                    })
    return events


def ownership_ledger(player: Optional[str] = None, season: Optional[int] = None,
                     events: Sequence[str] = ACQUISITION_EVENTS,
                     include_duplicates: bool = False) -> pd.DataFrame:
    """Every acquisition of every player, in date order — the all-players `timeline`.

    `timeline()` answers "tell me the story of X" one entity at a time, which
    cannot answer "across all players, who has property P about their ownership
    history" — most traded, longest single tenure, never changed hands, kept
    bouncing between the same two rosters. This is the vectorised form: one row
    per *acquisition*, `player, player_id, season, date, event, team, from_team,
    source`, for the whole league at once. Departures are implied by the next
    acquisition, so a spell's end is `NaN` for whoever is still rostered.

    Trades come from the raw snapshot wherever one exists, keyed by Sleeper pid
    exactly as the build counts them; 2020 has no snapshot (the ESPN backfill)
    so its trades are parsed out of the exported sheet's asset text instead, and
    marked `source="sheet"` because that path is name-matched and cannot see a
    pick that was already converted. Drafts come from `picks` (undated — the
    sheet records a season, not a day) and waiver/free-agent adds from
    `transactions`.

    `events` selects which acquisition kinds to include; dropping "add" and
    "draft" leaves the pure trade ledger. `include_duplicates` restores the
    `DUPLICATE_TRADE_TRANSACTIONS` rows, which are excluded by default because
    they record a second time an exchange that is already in the ledger.
    """
    kinds = {str(e).strip().lower() for e in events}
    unknown = kinds - set(ACQUISITION_EVENTS)
    if unknown:
        raise ValueError(f"unknown event kind(s) {sorted(unknown)}; "
                         f"expected any of {list(ACQUISITION_EVENTS)}")
    rows: List[dict] = []

    if "trade" in kinds:
        snapshot_years = [y for y in Q.snapshot_seasons() if season is None or y == season]
        sheet_years = [y for y in Q.export_seasons()
                       if y not in set(Q.snapshot_seasons())
                       and (season is None or y == season)]
        rows.extend(_snapshot_trade_events(snapshot_years, include_duplicates))
        rows.extend(_sheet_trade_events(sheet_years))

    if "draft" in kinds:
        for _, r in Q.load_sheet("picks").iterrows():
            name = str(r["Player Picked"]).strip()
            if is_placeholder(name):
                continue
            year = _season_of_label(r["Year"])
            if season is not None and year != season:
                continue
            rows.append({"player": name, "player_id": _resolve_quietly(name),
                         "season": year, "date": "", "event": "draft",
                         "team": str(r["Team"]), "from_team": "", "source": "sheet",
                         "_order": None})

    if "add" in kinds:
        for _, r in Q.load_sheet("transactions").iterrows():
            name = str(r["Player Added"]).strip()
            if is_placeholder(name):
                continue
            year = Q.to_number(r["Season"])
            year = int(year) if year is not None else None
            if season is not None and year != season:
                continue
            rows.append({"player": name, "player_id": _resolve_quietly(name),
                         "season": year, "date": str(r["Date"]), "event": "add",
                         "team": str(r["Team"]), "from_team": "", "source": "sheet",
                         "_order": _sheet_epoch_ms(r["Date"])})

    df = pd.DataFrame(rows, columns=["player", "player_id", "season", "date",
                                     "event", "team", "from_team", "source", "_order"])
    if df.empty:
        return df.drop(columns=["_order"])
    df["_order"] = pd.to_numeric(df["_order"], errors="coerce")
    # A pid is the only identity that survives a rename, so prefer the
    # dictionary's spelling when we have one and keep the sheet's when we do not.
    known = df["player_id"].astype(str).str.strip() != ""
    df.loc[known, "player"] = [Q.players().name(p) for p in df.loc[known, "player_id"]]
    if player is not None:
        pid = _resolve_quietly(player)
        wanted = Q.players().name(pid) if pid else str(player).strip()
        match = df["player"].str.lower() == wanted.lower()
        if pid:
            match = match | (df["player_id"].astype(str) == pid)
        df = df[match]
    df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
    # Order on the instant, not on the printed date: snapshot dates are
    # day-precision, so sorting their text against a sheet timestamp puts a
    # same-day trade before the waiver add that preceded it. Undated rows (the
    # draft, which records a season and not a day) and the startup draft (no
    # season at all) sort to the front rather than to the end, so `path` reads
    # in the order the player actually moved.
    return (df.sort_values(["player", "season", "_order"], na_position="first")
            .drop(columns=["_order"]).reset_index(drop=True))


def ownership_summary(ledger: Optional[pd.DataFrame] = None,
                      season: Optional[int] = None) -> pd.DataFrame:
    """One row per player: how many rosters held him, and how often he moved.

    `spells` counts acquisitions, `teams` counts *distinct* rosters, so the two
    coming apart is the whole point — a player with 4 spells and 2 teams went
    back somewhere. `boomerangs` counts the acquisitions by a roster that had
    already owned him, and `path` writes the route out in order.

    Pass a `ledger` to summarise a filtered one; the default builds the full
    ledger, which is the expensive call.
    """
    df = ownership_ledger(season=season) if ledger is None else ledger
    if df.empty:
        return pd.DataFrame()
    rows: List[dict] = []
    for name, events in df.groupby("player", sort=False):
        teams: List[str] = [str(t) for t in events["team"]]
        seen: set = set()
        boomerangs = 0
        for team in teams:
            if team in seen:
                boomerangs += 1
            seen.add(team)
        counts = events["event"].value_counts()
        ids = sorted({str(p) for p in events["player_id"] if str(p).strip()})
        rows.append({
            "player": name,
            "player_id": ids[0] if len(ids) == 1 else ";".join(ids),
            "spells": len(events),
            "trades": int(counts.get("trade", 0)),
            "adds": int(counts.get("add", 0)),
            "drafted": bool(counts.get("draft", 0)),
            "teams": len(seen),
            "boomerangs": boomerangs,
            "first_team": teams[0],
            "last_team": teams[-1],
            "path": " > ".join(teams),
        })
    out = pd.DataFrame(rows)
    return out.sort_values(["trades", "spells", "player"],
                           ascending=[False, False, True]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Positional scarcity
# ---------------------------------------------------------------------------
def observed_demand(season: Optional[int] = None) -> Dict[str, float]:
    """{position: average number started league-wide per week}.

    Measured, not assumed: the flex slots mean you cannot read positional
    demand off the lineup template, so replacement level is anchored to what
    the league actually fields.
    """
    rows = lineups(season=season, starters_only=True)
    if rows.empty:
        return {}
    weeks = rows.groupby(["Year", "Week"]).ngroups
    counts = rows["Position"].value_counts()
    return {pos: round(float(counts.get(pos, 0)) / weeks, 2) for pos in POSITIONS}


def value_curve(season: Optional[int] = None, metric: str = "Points",
                starters_only: bool = True) -> pd.DataFrame:
    """Players ranked *within their position*, per season: the scarcity curve.

    Columns: Year, Position, rank, Player, value. Rank 1 is the best at that
    position that season. This is the frame behind "how much better is an elite
    QB than a merely fine one".
    """
    rows = lineups(season=season, starters_only=starters_only)
    if rows.empty:
        return rows
    totals = (rows.groupby(["Year", "Position", "Player"])["Points"].sum()
              .reset_index().rename(columns={"Points": "value"}))
    totals["rank"] = (totals.groupby(["Year", "Position"])["value"]
                      .rank(ascending=False, method="first").astype(int))
    return totals.sort_values(["Year", "Position", "rank"]).reset_index(drop=True)


@dataclass(frozen=True)
class Scarcity:
    """How much a position's points cost, relative to its replacement level."""
    season: int
    position: str
    replacement_rank: int
    best: float
    replacement: float
    surplus: float              # best - replacement
    surplus_pct: float          # surplus as a share of replacement
    starters_per_week: float

    def describe(self) -> str:
        return (f"{self.season} {self.position:<3} best {self.best:8.2f} vs "
                f"replacement (#{self.replacement_rank}) {self.replacement:8.2f}  "
                f"surplus {self.surplus:+8.2f} ({self.surplus_pct:+.0%})  "
                f"[{self.starters_per_week:.1f} started/week]")


def scarcity(season: int, demand_multiple: float = 1.0,
             metric: str = "Points") -> List[Scarcity]:
    """Surplus of the best player at each position over a replacement starter.

    Replacement rank is `round(starters started per week × demand_multiple)` —
    derived from `observed_demand`, so it reflects how many of that position
    the league genuinely needs rather than a rule of thumb. Raise
    `demand_multiple` to test a stricter definition of replacement.

    The comparison across positions is the point: a position whose best player
    is barely ahead of its replacement is one where paying up buys little.
    """
    curve = value_curve(season=season, metric=metric)
    demand = observed_demand(season=season)
    out: List[Scarcity] = []
    for pos in POSITIONS:
        sub = curve[(curve["Position"] == pos) & (curve["Year"] == season)]
        if sub.empty:
            continue
        rank = max(1, int(round(demand.get(pos, 1.0) * demand_multiple)))
        rank = min(rank, int(sub["rank"].max()))
        best = float(sub[sub["rank"] == 1]["value"].iloc[0])
        repl = float(sub[sub["rank"] == rank]["value"].iloc[0])
        out.append(Scarcity(
            season=season, position=pos, replacement_rank=rank,
            best=round(best, 2), replacement=round(repl, 2),
            surplus=round(best - repl, 2),
            surplus_pct=round((best - repl) / repl, 4) if repl else 0.0,
            starters_per_week=demand.get(pos, 0.0)))
    return out


# ---------------------------------------------------------------------------
# Roster age
# ---------------------------------------------------------------------------
# The build anchors each week's ages at Sept 1 + 7·(week-1) rather than at the
# real calendar date of the week, because the snapshot carries no per-week
# timestamp. Mirrored here so a recomputed age can be checked against the
# build's own column (check_roster_age_matches_build).
AGE_SEASON_START = (9, 1)
# Rookies average ~22 when the league's rookie draft wraps in early September,
# so a not-yet-known pick is priced as someone born Sept 1 of (Y - 22). Same
# anchor the build uses for 'Team age including picks'.
PICK_ROOKIE_AGE = 22
# 'Team age including picks' looks three drafts ahead; further out, a pick's
# expected age is too uncertain to average into a roster.
PICK_HORIZON = 3
# Which rostered players an average is taken over. "all" is the build's own
# definition (every player on the roster, taxi and IR included); the other two
# exist so a ranking can be shown not to depend on that choice.
ROSTER_POOLS = ("all", "active", "starters")


@functools.lru_cache(maxsize=1)
def _birth_dates_cached(root: str) -> Dict[str, str]:
    blob = Q._snap("sleeper_players_nfl.json")
    out: Dict[str, str] = {}
    for pid, rec in (blob or {}).items():
        born = (rec or {}).get("birth_date") or (rec or {}).get("birthdate")
        if born:
            out[str(pid)] = str(born)
    return out


def birth_dates() -> Dict[str, str]:
    """{player_id: birth date} from the Sleeper dictionary in the snapshot.

    `inquiry.Players` deliberately keeps only name/position/team, so this is
    the one place the raw dictionary's birth dates are read.
    """
    return dict(_birth_dates_cached(str(Q.repo_root())))


def player_age(player_id: str, on: date) -> Optional[float]:
    """Age in years on a date, or None when the dictionary has no birth date.

    Days / 365.25, rounded to 2 — the build's own arithmetic, so the two agree
    to the last digit rather than to a tolerance.
    """
    born = _birth_dates_cached(str(Q.repo_root())).get(str(player_id))
    if not born:
        return None
    try:
        parsed = datetime.strptime(str(born)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return round((on - parsed).days / 365.25, 2)


def pick_expected_age(pick_year: int, on: date) -> float:
    """Synthetic age of the not-yet-known rookie a future pick will become."""
    return round((on - date(int(pick_year) - PICK_ROOKIE_AGE, *AGE_SEASON_START)).days
                 / 365.25, 2)


def week_reference_date(season: int, week: int) -> date:
    """The date the build ages a season's week at (Sept 1 + 7·(week-1))."""
    return date(int(season), *AGE_SEASON_START) + timedelta(days=7 * (int(week) - 1))


def _roster_pool(roster: dict, pool: str) -> List[str]:
    if pool not in ROSTER_POOLS:
        raise ValueError(f"pool must be one of {ROSTER_POOLS}, got {pool!r}")
    players = [str(p) for p in (roster.get("players") or ())]
    if pool == "all":
        return players
    if pool == "starters":
        return [str(p) for p in (roster.get("starters") or ()) if str(p) != Q.EMPTY_SLOT]
    benched = {str(p) for p in (roster.get("taxi") or ())}
    benched |= {str(p) for p in (roster.get("reserve") or ())}
    return [p for p in players if p not in benched]


def picks_held(season: int, horizon: int = PICK_HORIZON) -> Dict[int, List[int]]:
    """{roster_id: [pick year, ...]} for the future picks each team holds *now*.

    Reads the snapshot's `traded_picks.json`, which lists only picks that have
    moved — every other pick still belongs to its original owner, so the
    un-listed ones are filled in rather than dropped (a team's own retained
    picks are most of its capital). This is current ownership only: the file
    is a snapshot, not a ledger, so unlike the build there is no walking back
    to a past date. Raises FileNotFoundError for a season without the file.
    """
    rosters = Q._snap(f"season_{int(season)}/rosters.json")
    roster_ids = [int(r["roster_id"]) for r in rosters]
    rounds = _draft_rounds(season)
    moved = {(int(p["season"]), int(p["round"]), int(p["roster_id"])): int(p["owner_id"])
             for p in Q._snap(f"season_{int(season)}/traded_picks.json")}
    out: Dict[int, List[int]] = {rid: [] for rid in roster_ids}
    for offset in range(1, int(horizon) + 1):
        year = int(season) + offset
        for rnd in range(1, rounds + 1):
            for original in roster_ids:
                out[moved.get((year, rnd, original), original)].append(year)
    return out


def _draft_rounds(season: int, default: int = 4) -> int:
    try:
        drafts = Q._snap(f"season_{int(season)}/drafts.json")
    except FileNotFoundError:
        return default
    for draft in (drafts or []):
        rounds = ((draft or {}).get("settings") or {}).get("rounds")
        if rounds:
            return int(rounds)
    return default


def roster_ages(season: int, week: Optional[int] = None, on: Optional[date] = None,
                pool: str = "all", include_picks: bool = False) -> pd.DataFrame:
    """How old each team's roster is, ranked oldest first.

    The exports stop at the last completed season, so "how old is each roster
    *now*" cannot be read off `team_week."Player average age"` — it has to come
    from the snapshot. This computes that column the build's way and extends it
    to the in-progress season.

    Three parameters carry the assumptions:

    `week` — omit it for the current rosters (`rosters.json`, i.e. the snapshot's
    live state); pass one to age the roster Sleeper fielded that week
    (`matchups.json`), which is what the build's per-week column does.

    `on` — the date ages are measured at. Defaults to `week_reference_date` when
    a week is given (matching the build) and to today otherwise.

    `pool` — which players count: `all` (the build's definition, taxi and IR
    included), `active` (taxi and IR removed) or `starters`. Roster sizes are not
    equal across this league, so a deep bench of young stashes moves the mean;
    reporting the ranking under more than one pool is how you show it doesn't.

    Set `include_picks` for the companion `Team age including picks` measure,
    which averages the next `PICK_HORIZON` drafts' picks in at their expected
    rookie age. Requires the season's `traded_picks.json`; only the current
    season's snapshot carries one.

    Columns: Team, players, aged, avg_age, median_age, youngest, oldest,
    youngest_player, oldest_player (+ picks, avg_age_incl_picks) and `missing`,
    the count of rostered players the dictionary has no birth date for — kept
    as a column rather than filtered, since it is the denominator's caveat.
    """
    teams = Q.teams(season)
    if week is None:
        rosters = {int(r["roster_id"]): r for r in Q._snap(f"season_{int(season)}/rosters.json")}
        at = on or date.today()
    else:
        rosters = {rid: {"players": list(row.players), "starters": list(row.starters)}
                   for rid, row in Q.week(season, int(week)).items()}
        at = on or week_reference_date(season, int(week))
        if pool == "active":
            raise ValueError("pool='active' needs taxi/reserve, which a week's "
                             "matchups do not carry — use rosters (week=None)")
    held = picks_held(season) if include_picks else {}
    names = Q.players()
    rows: List[Dict[str, object]] = []
    for rid, roster in sorted(rosters.items()):
        ids = _roster_pool(roster, pool)
        aged = [(pid, player_age(pid, at)) for pid in ids]
        known = [(pid, age) for pid, age in aged if age is not None]
        if not known:
            continue
        ages = sorted((age for _, age in known))
        oldest = max(known, key=lambda pair: pair[1])
        youngest = min(known, key=lambda pair: pair[1])
        row: Dict[str, object] = {
            "Team": teams.get(rid, f"Roster {rid}"),
            "players": len(ids),
            "aged": len(known),
            "missing": len(ids) - len(known),
            "avg_age": round(sum(ages) / len(ages), 2),
            "median_age": round(float(pd.Series(ages).median()), 2),
            "youngest": youngest[1],
            "oldest": oldest[1],
            "youngest_player": names.name(youngest[0]),
            "oldest_player": names.name(oldest[0]),
        }
        if include_picks:
            pick_ages = [pick_expected_age(year, at) for year in held.get(rid, [])]
            combined = [age for _, age in known] + pick_ages
            row["picks"] = len(pick_ages)
            row["avg_age_incl_picks"] = round(sum(combined) / len(combined), 2)
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values("avg_age", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Spend by position
# ---------------------------------------------------------------------------
def spend_by_position(team: Optional[str] = None,
                      season: Optional[int] = None) -> pd.DataFrame:
    """What each team paid for each position, and what came back.

    Two acquisition channels the exports price directly:

      draft — `picks`: how many picks a team spent at a position, how early
              (`avg_pick`), and their market value on draft day (`draft_ktc`).
      FAAB  — `transactions`: total FAAB spent on the position.

    Return is `points`, the starter points that position produced for that team
    (from `player_week`), plus `points_share` and `pick_share` so a manager's
    allocation can be compared to what the allocation delivered.

    **Trades are not priced here.** `trades` stores its assets as text, so
    attributing a trade's cost to a position needs its own parse — the omission
    is deliberate and must be stated in any write-up that uses this table.
    """
    picks = Q.rows("picks", *( [f"Year={season}"] if season else [] ))
    picks = with_position(picks, "Player Picked", "Year")
    txns = Q.rows("transactions", *( [f"Season={season}"] if season else [] ))
    txns = with_position(txns, "Player Added", "Season")
    starts = lineups(season=season, starters_only=True)

    if team:
        canonical = Q.canonical_team(team)
        picks = picks[picks["Team"].str.lower() == canonical.lower()]
        txns = txns[txns["Team"].str.lower() == canonical.lower()]
        starts = starts[starts["Team"].str.lower() == canonical.lower()]

    rows: List[dict] = []
    teams = sorted(set(picks["Team"]) | set(txns["Team"]) | set(starts["Team"]))
    for tm in teams:
        tm_picks = picks[picks["Team"] == tm]
        tm_txns = txns[txns["Team"] == tm]
        tm_starts = starts[starts["Team"] == tm]
        total_points = float(tm_starts["Points"].sum())
        for pos in POSITIONS:
            p = tm_picks[tm_picks["Position"] == pos]
            t = tm_txns[tm_txns["Position"] == pos]
            s = tm_starts[tm_starts["Position"] == pos]
            numbers = Q.numeric(p, "Number").dropna() if len(p) else pd.Series(dtype=float)
            ktc = Q.numeric(p, "KTC on draft day").dropna() if len(p) else pd.Series(dtype=float)
            faab = Q.numeric(t, "Faab").dropna() if len(t) else pd.Series(dtype=float)
            points = float(s["Points"].sum())
            rows.append({
                "Team": tm, "Position": pos,
                "picks": int(len(p)),
                "avg_pick": round(float(numbers.mean()), 1) if len(numbers) else None,
                "earliest_pick": int(numbers.min()) if len(numbers) else None,
                "draft_ktc": round(float(ktc.sum()), 0) if len(ktc) else 0.0,
                "faab": round(float(faab.sum()), 0) if len(faab) else 0.0,
                "adds": int(len(t)),
                "starter_points": round(points, 2),
                "points_share": round(points / total_points, 4) if total_points else 0.0,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    totals = df.groupby("Team")["picks"].sum()
    df["pick_share"] = [round(r.picks / totals[r.Team], 4) if totals[r.Team] else 0.0
                        for r in df.itertuples()]
    faab_totals = df.groupby("Team")["faab"].sum()
    df["faab_share"] = [round(r.faab / faab_totals[r.Team], 4) if faab_totals[r.Team] else 0.0
                        for r in df.itertuples()]
    return df


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def check_starter_points_reconcile(season: int, tolerance: float = 0.02) -> List[str]:
    """Starter points rebuilt from player_week must equal the built `PF`.

    Allows exactly the league's +5 semifinal home-field bonus, which the build
    adds to `PF` on top of the starters' scores.
    """
    rows = lineups(season=season, starters_only=True)
    totals = rows.groupby(["Team", "Year", "Week"])["Points"].sum()
    problems: List[str] = []
    meta = Q.season_meta(season)
    for _, r in Q.rows("team_week", f"Year={season}").iterrows():
        week = int(float(r["Week"]))
        key = (str(r["Team"]), season, week)
        if key not in totals.index:
            continue
        built, got = Q.to_number(r["PF"]), float(totals.loc[key])
        if built is None:
            continue
        delta = round(built - got, 2)
        allowed = (0.0, Q.SEMIFINAL_HOME_BONUS) if week == meta.semifinal_week else (0.0,)
        if not any(abs(delta - a) <= tolerance for a in allowed):
            problems.append(f"{season} week {week} {r['Team']}: starters sum {got:.2f} "
                            f"vs PF {built:.2f} (delta {delta:+.2f})")
    return problems


def check_stack_counts_match_build(season: int) -> List[str]:
    """`max_same_nfl_team` must equal the build's own column for every lineup."""
    stacks = lineup_stacks(season=season)
    built = {(str(r["Team"]), int(float(r["Week"]))):
             Q.to_number(r["Most number of players started from same NFL team"])
             for _, r in Q.rows("team_week", f"Year={season}").iterrows()}
    problems: List[str] = []
    for r in stacks.itertuples():
        want = built.get((r.Team, int(r.Week)))
        if want is None:
            continue
        if abs(r.max_same_nfl_team - want) > 0.001:
            problems.append(f"{season} week {r.Week} {r.Team}: stack {r.max_same_nfl_team} "
                            f"!= built {want:g}")
    return problems


def check_roster_age_matches_build(season: int, tolerance: float = 0.011) -> List[str]:
    """`roster_ages` must reproduce `team_week."Player average age"` exactly.

    The whole point of the primitive is to carry that column forward into a
    season the exports do not cover yet, so it is only trustworthy if it
    reproduces the column on the seasons they do. Tolerance is half of the
    build's own rounding step, not a fudge factor.
    """
    problems: List[str] = []
    built = {(str(r["Team"]), int(float(r["Week"]))): Q.to_number(r["Player average age"])
             for _, r in Q.rows("team_week", f"Year={season}").iterrows()}
    for week in Q.played_weeks(season):
        for row in roster_ages(season, week=week).itertuples():
            want = built.get((row.Team, int(week)))
            if want is None:
                continue
            if abs(row.avg_age - want) > tolerance:
                problems.append(f"{season} week {week} {row.Team}: avg age {row.avg_age:.2f} "
                                f"!= built {want:g}")
    return problems


def check_trade_counts_match_build(include_duplicates: bool = False) -> List[str]:
    """Ledger trade counts must equal `player_all_time."Number of trades"`.

    The build counts a trade once per *received* player per trade, keyed by
    Sleeper pid; the ledger's trade rows are the same events from the same
    source, so the two are directly comparable and any drift is a real defect
    in one of them. Currently exact for all 651 players, which is what makes the
    ledger quotable — including across 2020, whose trades the ledger has to
    recover by name from the exported sheet because there is no snapshot.

    This is also the detector for a new `DUPLICATE_TRADE_TRANSACTIONS` case: a
    second Sleeper record of an exchange already in the ledger shows up here as
    a player counted once more than the build counts him.
    """
    ledger = ownership_ledger(events=("trade",), include_duplicates=include_duplicates)
    counted = ledger["player"].value_counts() if not ledger.empty else {}
    problems: List[str] = []
    known = {str(p).strip() for p in Q.load_sheet("player_all_time")["Player"]}
    for _, r in Q.load_sheet("player_all_time").iterrows():
        name = str(r["Player"]).strip()
        built = Q.to_number(r["Number of trades"])
        if built is None:
            continue
        got = int(counted.get(name, 0))
        if got != int(built):
            problems.append(f"{name}: ledger counts {got} trade(s), "
                            f"player_all_time says {built:g} "
                            f"(delta {got - int(built):+d})")
    # Both directions. Comparing only the names the build knows about cannot see
    # a *phantom* — an asset the ledger mistook for a player, which has no
    # `player_all_time` row to be compared against and so passes silently. That
    # is exactly how FAAB ("$15 FAAB") would enter as a traded player.
    for name in sorted(set(counted.index if hasattr(counted, "index") else ()) - known):
        problems.append(f"{name!r}: {int(counted[name])} ledger trade(s) but no "
                        f"player_all_time row — not a player?")
    return problems


def check_ledger_chains() -> List[str]:
    """Every trade must take a player from exactly where the ledger last had him.

    The strongest statement available about the ledger, because it tests three
    things a count cannot: that the events are in the right order, that the
    sending roster is attributed correctly, and that merging the snapshot with
    the sheets did not lose a move. A player who arrives at team B "from" team A
    while the ledger shows him last acquired by C means one of those is wrong.

    Exact for all 464 hand-offs today. The two ways it has caught a defect: two
    trades of one player on the same day ordered by luck, and a waiver add
    sorting after the same-day trade that moved the player out.
    """
    ledger = ownership_ledger()
    problems: List[str] = []
    for name, events in ledger.groupby("player", sort=False):
        rows = list(events.itertuples())
        for previous, current in zip(rows, rows[1:]):
            if current.event != "trade" or not current.from_team:
                continue
            if current.from_team != previous.team:
                problems.append(
                    f"{name}: {current.date} trade to {current.team} says it came "
                    f"from {current.from_team}, but the ledger last had him "
                    f"acquired by {previous.team} ({previous.event})")
    return problems


def check_positions_are_placed(min_rate: float = 0.99) -> List[str]:
    """Every real player in picks/transactions must get a position.

    Rows naming no player (an unexercised future pick, a drop-only transaction)
    are excluded from the rate — they are counted by `placement_report()`, which
    is what a write-up should quote.
    """
    problems: List[str] = []
    for sheet, name_col, season_col in (("picks", "Player Picked", "Year"),
                                        ("transactions", "Player Added", "Season")):
        stats = placement_report(sheet, name_col, season_col)
        if stats["rate"] < min_rate:
            problems.append(f"{sheet}: only {stats['rate']:.1%} of named players got a "
                            f"position ({stats['unplaced']} unplaced, e.g. "
                            f"{stats['examples']})")
    return problems


def placement_report(sheet: str, name_column: str, season_column: str) -> Dict[str, object]:
    """How well the position join covered a sheet — placed, placeholder, missed."""
    df = with_position(Q.load_sheet(sheet), name_column, season_column)
    placeholders = sum(1 for n in df[name_column] if is_placeholder(n))
    named = len(df) - placeholders
    missed = unplaced(df, name_column)
    return {
        "sheet": Q.sheet_name(sheet), "rows": len(df), "named": named,
        "placeholders": placeholders, "unplaced": len(missed),
        "rate": (named - len(missed)) / named if named else 1.0,
        "examples": sorted({str(n) for n in missed[name_column]})[:5],
    }


def validate(season: int) -> List[str]:
    """Every guard for one season; empty means the analysis layer reconciles."""
    return (check_starter_points_reconcile(season)
            + check_stack_counts_match_build(season)
            + check_roster_age_matches_build(season)
            + check_positions_are_placed())
