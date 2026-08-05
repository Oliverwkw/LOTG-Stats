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

  * **Positional scarcity.** `value_curve()` / `scarcity()` measure what a
    position's points actually cost: the drop from the best player at a
    position to the *replacement* one, where replacement rank is taken from how
    many of that position the league actually starts each week, not assumed.

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
from dataclasses import dataclass, field
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
    """Two-sided permutation test on the difference of means. Deterministic."""
    if not len(a) or not len(b):
        return float("nan")
    observed = abs(sum(a) / len(a) - sum(b) / len(b))
    pool = list(a) + list(b)
    rng = random.Random(seed)
    hits = 0
    for _ in range(permutations):
        rng.shuffle(pool)
        left, right = pool[:len(a)], pool[len(a):]
        if abs(sum(left) / len(left) - sum(right) / len(right)) >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (permutations + 1)


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
            + check_positions_are_placed())
