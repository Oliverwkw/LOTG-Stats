"""Draft capital: what a slot has returned, and what a slot costs to reach.

Layered on `lotg_support.inquiry` (rows) and `lotg_support.analysis` (cohort
tests). This module exists because "is tanking worth it" is really three
separate questions that no single sheet answers, and answering them by hand
walks into the `picks` traps every time:

  * **What does a slot return?** `slot_table()` / `haul_table()` price a draft
    position across *every* round, not just the first — the tank is chasing
    1.01 *and* 2.01, 3.01, 4.01, and the rounds behave very differently.
    `slot_cohorts()` runs the comparison that matters (already-bottom-four vs
    pushed-to-the-very-bottom) through `analysis.compare`, so it comes back
    with n, both cohorts, a permutation p-value and a per-draft breakdown
    rather than a bare mean.

  * **Who gets which slot?** The rule has changed. Through the 2025 draft the
    bottom four picked in reverse final placement; from the 2026 draft they
    pick in **ascending Max PF** — the roster's ceiling, not its record.
    `bottom_four_order()` implements both, `order_rule()` says which era a
    draft belongs to, and `check_bottom_four_order_matches_picks()` ties the
    whole thing to the build's own `picks."Original Team"` for every draft
    that has happened.

  * **What does moving up cost?** Under the ceiling rule you cannot buy draft
    position with losses — only by actually having less scoring talent.
    `ceiling_cost()` prices that in the currency the rule is denominated in:
    which players have to leave a roster for its Max PF to reach a target, and
    how much real production that costs. It removes players greedily and calls
    the build's own `lineup.compute_optimal_lineup`, so the baseline it starts
    from is the built `Max PF` exactly (`check_max_pf_matches_build`).

Everything is read-only and derived from the committed exports plus the
snapshot. Nothing the build runs imports this module, and no workflow runs it.
Debatable choices — which metric ranks a pick, how many rounds count as "the
haul", what replacement looks like when a player is stripped — are named
parameters with documented defaults, so the next question can vary them and
report the sensitivity.

Three traps this module absorbs, all of which have produced a wrong answer at
least once:

  * `picks."Points added"` is **cumulative and stops at the pick's next
    transaction**, so it flatters long tenures and scores a flipped pick at 0
    no matter what came back. It is still the default for a *whole-draft*
    total (nothing else sums), but `RATE_METRIC` is the fair per-pick ranking
    and `slot_cohorts()` reports both — they disagree, and the disagreement is
    the finding.
  * The **startup and 2021 vet drafts are not rookie drafts**; unmade future
    picks are written `1.??`. All three are excluded and *counted*, never
    silently dropped (`excluded_report()`).
  * A draft's slot count is not the league size in every year — 2025 ran to
    5.07 and 2026 to 5.02 — so slots above `TEAMS` exist and are kept, flagged
    rather than filtered.

Guards live in `check_*` and are exercised by `tests/test_draft_capital.py`.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from lotg_support import analysis as A
from lotg_support import inquiry as Q
from lotg_support.lineup import compute_optimal_lineup

# --------------------------------------------------------------------------
# Parameters, all overridable
# --------------------------------------------------------------------------
#: Cumulative points a pick's player added while rostered by the drafting team.
#: The only column that *sums* across a draft, and the reason `haul_table` uses
#: it — but see the module docstring: it is tenure-biased and blind to a pick
#: that was flipped before its player suited up.
TOTAL_METRIC = "Points added"

#: Per-start, position-adjusted rate. The fair way to rank two picks against
#: each other, and immune to the tenure bias in `TOTAL_METRIC`.
RATE_METRIC = "Avg points added adjusted by position"

#: Rounds that make up "the haul" a draft slot owns. The league has drafted 4
#: rounds every year (2025 and 2026 added a partial 5th of reward picks).
HAUL_ROUNDS = 4

#: League size. Slots above this exist in the sheets (toilet-reward picks) and
#: are kept and flagged rather than dropped.
TEAMS = 8

#: How many non-playoff teams the bottom-four ordering rule applies to.
BOTTOM = 4

#: First draft whose bottom-four order was set by ascending Max PF rather than
#: by reverse final placement. Verified against `picks."Original Team"` for
#: every draft 2021-2026 by `check_bottom_four_order_matches_picks`.
MAX_PF_RULE_FROM_DRAFT = 2026

_PICK_RE = re.compile(r"^(?P<round>\d+)\.(?P<slot>\d+)$")


# --------------------------------------------------------------------------
# The rookie-pick frame
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PickFrame:
    """Rookie-draft picks, plus what had to be left out to get there."""
    rows: pd.DataFrame
    excluded: Dict[str, int] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()

    def describe_exclusions(self) -> str:
        if not self.excluded:
            return "nothing excluded"
        return ", ".join(f"{n} {label}" for label, n in sorted(self.excluded.items()))


@functools.lru_cache(maxsize=None)
def _rookie_picks_cached(root: str) -> PickFrame:
    df = Q.load_sheet("picks").copy()
    excluded: Dict[str, int] = {}

    year_txt = df["Year"].astype(str)
    is_rookie_year = year_txt.str.fullmatch(r"20\d\d")
    excluded["startup / vet-draft rows (not a rookie draft)"] = int((~is_rookie_year).sum())
    df = df[is_rookie_year].copy()

    parsed = df["Number"].astype(str).str.extract(_PICK_RE)
    unmade = parsed["round"].isna()
    excluded["unmade future picks (written `x.??`)"] = int(unmade.sum())
    df = df[~unmade].copy()
    parsed = parsed[~unmade]

    df["draft_year"] = year_txt[df.index].astype(int)
    df["round"] = parsed["round"].astype(int)
    df["slot"] = parsed["slot"].astype(int)

    warnings: List[str] = []
    wide = df[df["slot"] > TEAMS]
    if len(wide):
        warnings.append(
            f"{len(wide)} pick(s) sit at a slot above the {TEAMS}-team league "
            f"({', '.join(sorted(set(wide['Year'].astype(str) + ' ' + wide['Number'])))}) "
            "— toilet-bowl reward picks; kept, not filtered")
    return PickFrame(rows=df.reset_index(drop=True), excluded=excluded,
                     warnings=tuple(warnings))


def rookie_picks(seasons: Optional[Sequence[int]] = None,
                 max_round: Optional[int] = None,
                 played_only: bool = True) -> PickFrame:
    """Every rookie-draft pick, with `draft_year` / `round` / `slot` attached.

    `played_only` drops drafts whose players have not had a season yet — the
    in-progress season's class reads 0.0 in every return column, and averaging
    it in silently drags every slot toward zero. Off by default only when you
    want the raw ledger.
    """
    frame = _rookie_picks_cached(str(Q.repo_root()))
    df, excluded = frame.rows.copy(), dict(frame.excluded)
    warnings = list(frame.warnings)

    if played_only:
        completed = set(Q.completed_seasons())
        unplayed = ~df["draft_year"].isin(completed)
        if int(unplayed.sum()):
            years = sorted(set(df.loc[unplayed, "draft_year"]))
            excluded[f"picks from drafts with no completed season yet ({years})"] = int(unplayed.sum())
            df = df[~unplayed]
    if seasons is not None:
        df = df[df["draft_year"].isin(list(seasons))]
    if max_round is not None:
        df = df[df["round"] <= max_round]
    return PickFrame(rows=df.reset_index(drop=True), excluded=excluded,
                     warnings=tuple(warnings))


def excluded_report(**kwargs) -> Dict[str, int]:
    """What `rookie_picks` left out and why. Report it; do not filter quietly."""
    return dict(rookie_picks(**kwargs).excluded)


# --------------------------------------------------------------------------
# What a slot has returned
# --------------------------------------------------------------------------
def slot_table(metric: str = TOTAL_METRIC, rounds: int = HAUL_ROUNDS,
               seasons: Optional[Sequence[int]] = None,
               statistic: str = "mean") -> pd.DataFrame:
    """Round x slot table of `metric`.

    `statistic` is any pandas aggregation, plus the two that matter for a
    small sample: `"bust_rate"` (share of picks that returned nothing at all)
    and `"hit_rate"` (share above `hit_threshold`, see `hit_rate`).
    """
    df = rookie_picks(seasons=seasons, max_round=rounds).rows
    values = pd.to_numeric(df[metric], errors="coerce")
    work = df.assign(_v=values)
    if statistic == "bust_rate":
        agg = lambda s: float((s == 0).mean())  # noqa: E731
    else:
        agg = statistic
    return work.pivot_table(index="round", columns="slot", values="_v", aggfunc=agg)


def hit_rate(threshold: float = 300.0, metric: str = TOTAL_METRIC,
             rounds: int = HAUL_ROUNDS,
             seasons: Optional[Sequence[int]] = None) -> pd.DataFrame:
    """Share of picks at each round/slot that cleared `threshold`.

    A mean hides the shape of a draft: the useful question is how often a slot
    produced something that mattered, not what it averaged across one hit and
    four zeros.
    """
    df = rookie_picks(seasons=seasons, max_round=rounds).rows
    work = df.assign(_v=pd.to_numeric(df[metric], errors="coerce"))
    return work.pivot_table(index="round", columns="slot", values="_v",
                            aggfunc=lambda s: float((s > threshold).mean()))


def haul_table(metric: str = TOTAL_METRIC, rounds: int = HAUL_ROUNDS,
               seasons: Optional[Sequence[int]] = None) -> pd.DataFrame:
    """What the *whole draft* at each slot returned — one column per round plus a total.

    This is the frame the tanking question actually needs. Owning 1.01 means
    owning 2.01, 3.01 and 4.01 as well, and the rounds do not behave alike, so
    a first-round-only comparison over- or under-states the prize depending on
    which way the later rounds happened to fall.
    """
    df = rookie_picks(seasons=seasons, max_round=rounds).rows
    work = df.assign(_v=pd.to_numeric(df[metric], errors="coerce"))
    out = work.pivot_table(index="slot", columns="round", values="_v", aggfunc="mean")
    out["TOTAL"] = out.sum(axis=1)
    return out


def hauls(metric: str = TOTAL_METRIC, rounds: int = HAUL_ROUNDS,
          seasons: Optional[Sequence[int]] = None,
          league_slots_only: bool = True) -> Tuple[pd.DataFrame, Tuple[str, ...]]:
    """One row per (draft, slot): the summed return of that slot's whole draft.

    The unit a cohort test needs — a slot-draft, not a pick — because the four
    picks a slot owns in one draft are not independent observations.

    `league_slots_only` drops slots above the league size. Those rows are the
    **toilet-bowl reward picks** (2.09), which belong to a *non-playoff* team,
    so leaving them in silently files them under "playoff teams' slots" and
    overstates the bottom-four advantage. They are dropped and counted, not
    filtered quietly.
    """
    df = rookie_picks(seasons=seasons, max_round=rounds).rows
    warnings: List[str] = []
    if league_slots_only:
        wide = df[df["slot"] > TEAMS]
        if len(wide):
            warnings.append(
                f"{len(wide)} reward pick(s) above slot {TEAMS} excluded from the cohorts "
                f"({', '.join(sorted(set(wide['Year'].astype(str) + ' ' + wide['Number'])))}) "
                "— they belong to a non-playoff team, so scoring them as a playoff "
                "team's slot would overstate the bottom-four gap")
            df = df[df["slot"] <= TEAMS]
    work = df.assign(_v=pd.to_numeric(df[metric], errors="coerce"))
    out = (work.groupby(["draft_year", "slot"])["_v"].sum()
           .reset_index().rename(columns={"_v": metric, "draft_year": "Year"}))
    return out, tuple(warnings)


@dataclass(frozen=True)
class SlotCohorts:
    """The two cohort tests the tanking question turns on, plus what was left out."""
    metric: str
    comparisons: Dict[str, A.Comparison]
    warnings: Tuple[str, ...] = ()

    def describe(self) -> str:
        lines = []
        for label, cmp in self.comparisons.items():
            lines.append(f"### {label}")
            lines.append(cmp.describe())
            lines.append("")
        for w in self.warnings:
            lines.append(f"warning: {w}")
        return "\n".join(lines)


def slot_cohorts(metric: str = TOTAL_METRIC, rounds: int = HAUL_ROUNDS,
                 seasons: Optional[Sequence[int]] = None,
                 permutations: int = 20000,
                 aggregate: str = "auto") -> SlotCohorts:
    """The two comparisons the tanking question turns on.

    * `"bottom_four_vs_playoff"` — slots 1-4 against 5-8. Is missing the
      playoffs worth draft capital at all?
    * `"pushed_vs_already_bottom"` — slots 1-2 against 3-4, i.e. the *marginal*
      question: given that you are already going to pick in the bottom four, is
      pushing for the very top of it worth anything?

    Both run through `analysis.compare`, so each comes back with both cohorts,
    an effect size, a deterministic permutation p-value and a per-draft
    breakdown. Read the breakdown: with five drafts, a pooled gap can be one
    class.

    `aggregate` decides the unit of observation, and it is not a free choice:

    * `"haul"` sums the metric over a slot's whole draft — right for a
      cumulative column like `Points added`, and the unit the tanking question
      is actually about (you own all four picks, not one).
    * `"pick"` treats each pick as its own row — the only correct unit for a
      **rate** column such as `RATE_METRIC`, because points-per-start does not
      add up across four players.

    `"auto"` picks `"haul"` for `TOTAL_METRIC` and `"pick"` for anything else,
    which is the distinction that matters; override it deliberately.
    """
    if aggregate == "auto":
        aggregate = "haul" if metric == TOTAL_METRIC else "pick"
    if aggregate == "haul":
        frame, warnings = hauls(metric=metric, rounds=rounds, seasons=seasons)
    elif aggregate == "pick":
        picks = rookie_picks(seasons=seasons, max_round=rounds).rows
        wide = picks[picks["slot"] > TEAMS]
        warnings = ((f"{len(wide)} reward pick(s) above slot {TEAMS} excluded",)
                    if len(wide) else ())
        frame = (picks[picks["slot"] <= TEAMS]
                 .drop(columns=["Year"])           # the sheet's own text label
                 .rename(columns={"draft_year": "Year"})
                 .assign(**{metric: lambda d: pd.to_numeric(d[metric], errors="coerce")}))
    else:
        raise ValueError(f"unknown aggregate {aggregate!r} (expected 'haul', 'pick' or 'auto')")
    return SlotCohorts(
        metric=metric,
        comparisons={
            "bottom_four_vs_playoff": A.compare(
                frame, f"slot<={BOTTOM}", metric, by="Year", permutations=permutations),
            "pushed_vs_already_bottom": A.compare(
                frame[frame["slot"] <= BOTTOM], "slot<=2", metric, by="Year",
                permutations=permutations),
        },
        warnings=warnings)


# --------------------------------------------------------------------------
# Who gets which slot: the two ordering rules
# --------------------------------------------------------------------------
def _final_place(season: int) -> Dict[str, int]:
    """Team -> finishing position for a season, from the built `Result`."""
    out: Dict[str, int] = {}
    for _, r in Q.rows("team_year", f"Year={season}").iterrows():
        label = str(r["Result"])
        if label.lower() == "champion":
            out[str(r["Team"])] = 1
        else:
            m = re.match(r"(\d+)", label)
            if m:
                out[str(r["Team"])] = int(m.group(1))
    return out


def built_max_pf(season: int, regular_season_only: bool = False) -> Dict[str, float]:
    """Season Max PF per team, straight off the built `team_week` sheet.

    `regular_season_only` matters for a strength question (four teams play two
    extra weeks) but not for the ordering rule — the bottom four play the same
    number of weeks as each other, and both readings produce the same order in
    every season on record. The parameter is here so the next question can
    check that rather than take it on trust.
    """
    rows = Q.rows("team_week", f"Year={season}")
    weeks = pd.to_numeric(rows["Week"], errors="coerce")
    if regular_season_only:
        rows = rows[weeks <= Q.season_meta(season).regular_season_weeks]
    values = pd.to_numeric(rows["Max PF"], errors="coerce")
    return {t: float(v) for t, v in rows.assign(_v=values).groupby("Team")["_v"].sum().items()}


def order_rule(draft_year: int) -> str:
    """Which rule set the bottom four's order for a given draft.

    `"placement"` — reverse final placement (8th picks 1.01). Every draft
    through 2025.
    `"max_pf"` — ascending Max PF, i.e. the lowest roster ceiling picks 1.01,
    regardless of record. The 2026 draft on.
    """
    return "max_pf" if draft_year >= MAX_PF_RULE_FROM_DRAFT else "placement"


def bottom_four_order(draft_year: int, rule: Optional[str] = None) -> List[str]:
    """The bottom-four draft order the rule implies for `draft_year`.

    Returns teams in pick order — index 0 holds 1.01. Only the bottom four are
    modelled: the playoff block's internal order is not a rule this data can
    pin down (it is reverse placement through the 2022 draft and swaps 3rd/4th
    from the 2023 draft on, with no stated reason), and no tanking question
    depends on it. `playoff_block()` returns the observed order instead of
    guessing at one.
    """
    season = draft_year - 1
    rule = rule or order_rule(draft_year)
    places = _final_place(season)
    non_playoff = [t for t, p in places.items() if p > Q.season_meta(season).playoff_teams]
    if rule == "placement":
        return sorted(non_playoff, key=lambda t: -places[t])
    if rule == "max_pf":
        ceilings = built_max_pf(season)
        return sorted(non_playoff, key=lambda t: ceilings[t])
    raise ValueError(f"unknown rule {rule!r} (expected 'placement' or 'max_pf')")


def observed_order(draft_year: int) -> List[str]:
    """The order that actually happened, from `picks."Original Team"`.

    Past seasons' snapshots carry no `drafts.json` — only the current season's
    does — so the build's own pick sheet is the record of who owned which slot.
    """
    df = rookie_picks(played_only=False, seasons=[draft_year], max_round=1).rows
    df = df[df["slot"] <= TEAMS].sort_values("slot")
    return [str(t) for t in df["Original Team"]]


def playoff_block(draft_year: int) -> List[str]:
    """Observed order of the four playoff teams' slots (1.05-1.08). Data, not a rule."""
    return observed_order(draft_year)[BOTTOM:]


def order_comparison(draft_year: int) -> pd.DataFrame:
    """What each bottom-four team gets under *each* rule, side by side.

    The point of the table: the same season is priced completely differently by
    the two rules, so a teardown that was optimal under one can be penalised by
    the other.
    """
    season = draft_year - 1
    places, ceilings = _final_place(season), built_max_pf(season)
    by_rule = {r: bottom_four_order(draft_year, rule=r) for r in ("placement", "max_pf")}
    rows = []
    for team in by_rule["placement"]:
        rows.append({
            "Team": team,
            "finish": places[team],
            "Max PF": round(ceilings[team], 2),
            "placement_rule": f"1.0{by_rule['placement'].index(team) + 1}",
            "max_pf_rule": f"1.0{by_rule['max_pf'].index(team) + 1}",
            "slots_moved": by_rule["placement"].index(team) - by_rule["max_pf"].index(team),
            "in_force": order_rule(draft_year),
        })
    return pd.DataFrame(rows).sort_values("finish", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# What a slot costs: Max PF, recomputed and strippable
# --------------------------------------------------------------------------
def _weekly_pools(season: int) -> Dict[int, Dict[int, Dict[str, float]]]:
    """{roster_id: {week: {player_id: points}}} for a season's snapshot weeks."""
    out: Dict[int, Dict[int, Dict[str, float]]] = {}
    for wk in Q.played_weeks(season):
        for rid, row in Q.week(season, wk).items():
            pool = {pid: float(row.players_points.get(pid, 0.0)) for pid in row.players}
            out.setdefault(rid, {})[wk] = pool
    return out


def season_max_pf(season: int, team: Optional[str] = None,
                  drop: Sequence[str] = (),
                  weeks: Optional[Sequence[int]] = None) -> Dict[str, float]:
    """Recompute season Max PF from the snapshot, optionally without some players.

    Calls the build's own `lineup.compute_optimal_lineup`, so with `drop` empty
    it reproduces `team_week."Max PF"` exactly rather than approximating it
    (`check_max_pf_matches_build`). That exactness is the whole point: it makes
    the counterfactual ("what would this roster's ceiling have been without
    these players") comparable with the number the draft order is now set by.

    `drop` removes players outright — nobody replaces them. A real sale returns
    players and a real manager would add off waivers, both of which push Max PF
    back up, so a stripping cost computed this way is a **floor**.
    """
    meta = Q.season_meta(season)
    if not meta.has_snapshot:
        raise ValueError(f"{season} has exports but no snapshot — Max PF cannot be recomputed")
    positions = Q.players().positions()
    drop = set(drop)
    names = Q.teams(season)
    out: Dict[str, float] = {}
    for rid, by_week in _weekly_pools(season).items():
        label = names.get(rid, str(rid))
        if team is not None and label != Q.canonical_team(team):
            continue
        total = 0.0
        for wk, pool in by_week.items():
            if weeks is not None and wk not in set(weeks):
                continue
            total += compute_optimal_lineup(
                {p: v for p, v in pool.items() if p not in drop}, positions, season)
        out[label] = round(total, 2)
    return out


@dataclass(frozen=True)
class StripStep:
    """One player removed on the way to a target ceiling."""
    player_id: str
    player: str
    position: str
    max_pf_after: float
    ceiling_given_up: float
    points_scored: float


@dataclass(frozen=True)
class CeilingCost:
    """What it would have cost a roster to reach a target Max PF."""
    season: int
    team: str
    baseline: float
    target: float
    steps: Tuple[StripStep, ...]
    reached: bool
    warnings: Tuple[str, ...] = ()

    @property
    def ceiling_shed(self) -> float:
        return round(self.baseline - (self.steps[-1].max_pf_after if self.steps
                                      else self.baseline), 2)

    @property
    def production_lost(self) -> float:
        return round(sum(s.points_scored for s in self.steps), 2)

    @property
    def exchange_rate(self) -> float:
        """Real production surrendered per point of ceiling shed.

        Always above 1: removing a starter only lowers the *optimal* lineup by
        his margin over the next-best legal option, so the bench absorbs part
        of the loss and you must strip depth as well as stars.
        """
        shed = self.ceiling_shed
        return round(self.production_lost / shed, 2) if shed else float("nan")

    def describe(self) -> str:
        head = (f"{self.team} {self.season}: Max PF {self.baseline:.2f} -> target "
                f"{self.target:.2f}" + ("" if self.reached else "  (NOT REACHED)"))
        lines = [head]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"  {i:2d}. drop {s.player:<24} ({s.position:<2}) "
                         f"Max PF -> {s.max_pf_after:8.2f}  "
                         f"(-{s.ceiling_given_up:6.2f} ceiling; that player scored "
                         f"{s.points_scored:6.1f})")
        if self.steps:
            lines.append(f"  => {len(self.steps)} player(s), {self.production_lost:.1f} points of "
                         f"production for {self.ceiling_shed:.1f} of ceiling "
                         f"({self.exchange_rate:.2f} produced per 1 shed)")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        return "\n".join(lines)


def ceiling_cost(season: int, team: str, target: float,
                 max_steps: int = 12,
                 weeks: Optional[Sequence[int]] = None) -> CeilingCost:
    """Which players must leave `team`'s roster for its Max PF to reach `target`.

    Greedy: at each step it removes whichever remaining player lowers season
    Max PF the most. Greedy is not guaranteed optimal — a different set of the
    same size could in principle do better — so read the result as "about this
    many players, about this much production", not as an exact minimum.

    This is the cost of moving *up* the draft order under the ceiling rule,
    denominated the way that rule denominates it. Under the old placement rule
    the same movement cost only losses, which is why the rule change matters:
    the currency went from wins nobody was going to get anyway to the roster
    itself.
    """
    canonical = Q.canonical_team(team)
    baseline_all = season_max_pf(season, team=canonical, weeks=weeks)
    if canonical not in baseline_all:
        raise KeyError(f"no roster for {team!r} in {season}")
    baseline = baseline_all[canonical]

    positions = Q.players().positions()
    names = Q.players().name
    rid = Q.roster_id(season, canonical)
    by_week = _weekly_pools(season)[rid]
    if weeks is not None:
        by_week = {w: p for w, p in by_week.items() if w in set(weeks)}
    everyone = sorted({p for pool in by_week.values() for p in pool})

    def ceiling(dropped: frozenset) -> float:
        return round(sum(compute_optimal_lineup(
            {p: v for p, v in pool.items() if p not in dropped}, positions, season)
            for pool in by_week.values()), 2)

    scored = {p: round(sum(pool.get(p, 0.0) for pool in by_week.values()), 1)
              for p in everyone}
    dropped: set = set()
    steps: List[StripStep] = []
    current = baseline
    while current > target and len(steps) < max_steps:
        best: Optional[Tuple[str, float]] = None
        for p in everyone:
            if p in dropped:
                continue
            v = ceiling(frozenset(dropped | {p}))
            if best is None or v < best[1]:
                best = (p, v)
        if best is None or best[1] >= current - 1e-9:
            break                      # nothing left that moves the ceiling
        dropped.add(best[0])
        steps.append(StripStep(
            player_id=best[0], player=names(best[0]) or best[0],
            position=positions.get(best[0], "?"), max_pf_after=best[1],
            ceiling_given_up=round(current - best[1], 2),
            points_scored=scored[best[0]]))
        current = best[1]

    warnings: List[str] = []
    if len(steps) >= max_steps and current > target:
        warnings.append(f"stopped at max_steps={max_steps} without reaching the target")
    warnings.append("players are removed outright — a real sale returns assets and "
                    "waivers refill the roster, so this is a floor on the cost")
    return CeilingCost(season=season, team=canonical, baseline=baseline, target=target,
                       steps=tuple(steps), reached=current <= target,
                       warnings=tuple(warnings))


def cost_to_pick_first(draft_year: int, team: str,
                       weeks: Optional[Sequence[int]] = None,
                       **kwargs) -> CeilingCost:
    """What `team` would have had to shed to hold 1.01 in `draft_year`.

    Convenience over `ceiling_cost`: the target is whatever the team that
    actually picked first had as its Max PF. The target is recomputed over the
    **same weeks** as the roster being stripped — comparing a regular-season
    baseline against a full-season target silently understates the cost, since
    the bottom four play two fewer weeks than nobody and four fewer than the
    finalists.
    """
    season = draft_year - 1
    leader = bottom_four_order(draft_year, rule="max_pf")[0]
    target = season_max_pf(season, team=leader, weeks=weeks)[Q.canonical_team(leader)]
    return ceiling_cost(season, team, target, weeks=weeks, **kwargs)


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------
def check_max_pf_matches_build(season: int, tolerance: float = 0.01) -> List[str]:
    """Recomputed season Max PF must equal the built `team_week."Max PF"`.

    This is what licenses `ceiling_cost`: a stripping cost is only meaningful
    if the un-stripped baseline is the number the league's own tables report,
    and now the number the draft order is set by.
    """
    problems: List[str] = []
    mine = season_max_pf(season)
    built = built_max_pf(season)
    for team, want in built.items():
        got = mine.get(team)
        if got is None:
            problems.append(f"{season} {team}: no recomputed Max PF")
        elif abs(got - want) > tolerance:
            problems.append(f"{season} {team}: recomputed {got:.2f} != built {want:.2f}")
    return problems


def check_bottom_four_order_matches_picks(draft_year: int) -> List[str]:
    """The era's rule must reproduce who actually owned slots 1.01-1.04.

    `picks."Original Team"` is the build's record of the slot owner before any
    trade, so this ties the inferred rule — and with it every claim about what
    a tank buys — to something the build computed independently.
    """
    want = observed_order(draft_year)[:BOTTOM]
    got = bottom_four_order(draft_year)
    if got == want:
        return []
    return [f"{draft_year} draft: rule {order_rule(draft_year)!r} gives {got}, "
            f"picks sheet says {want}"]


def check_haul_table_reconciles(rounds: int = HAUL_ROUNDS,
                                tolerance: float = 0.01) -> List[str]:
    """Slot means must add back up to the pick sheet's own total.

    Cheap, but it is the guard that catches a filter quietly dropping picks —
    the failure mode that would make every slot in this module look better or
    worse than it was.
    """
    df = rookie_picks(max_round=rounds).rows
    total = pd.to_numeric(df[TOTAL_METRIC], errors="coerce").sum()
    per_slot = df.groupby(["draft_year", "slot"]).size()
    rebuilt = 0.0
    for (year, slot), _ in per_slot.items():
        sub = df[(df["draft_year"] == year) & (df["slot"] == slot)]
        rebuilt += pd.to_numeric(sub[TOTAL_METRIC], errors="coerce").sum()
    if abs(rebuilt - total) > tolerance:
        return [f"haul rows sum to {rebuilt:.2f} but the pick frame sums to {total:.2f}"]
    return []


def checkable_drafts() -> List[int]:
    """Drafts whose bottom-four order can be checked against the pick sheet.

    Needs the prior season's standings (and, for the ceiling rule, its
    `team_week`), so it runs from the first draft after a season the exports
    cover — which includes 2020, the ESPN-backfilled season with no snapshot.
    """
    have = set(Q.export_seasons())
    drafts = sorted(set(rookie_picks(played_only=False).rows["draft_year"]))
    return [d for d in drafts if d - 1 in have and observed_order(d)]


def validate(seasons: Optional[Sequence[int]] = None) -> Dict[str, List[str]]:
    """Run every guard. Empty lists mean clean."""
    completed = [s for s in (seasons or Q.completed_seasons())
                 if Q.season_meta(s).has_snapshot]
    out: Dict[str, List[str]] = {}
    for s in completed:
        out[f"max_pf_matches_build[{s}]"] = check_max_pf_matches_build(s)
    for draft_year in checkable_drafts():
        out[f"bottom_four_order[{draft_year}]"] = check_bottom_four_order_matches_picks(draft_year)
    out["haul_table_reconciles"] = check_haul_table_reconciles()
    return out
