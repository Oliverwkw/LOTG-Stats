"""Counterfactual season replay: "what if this move had never happened?"

Generalises the one-off script written for the 2025 Herbert-for-Jackson
question (`plan/notes/WHATIF_HERBERT_TRADE_2025.md`) into something any season
and any set of roster moves can be run through, with the league's real rules
and the build's own numbers as the reference.

Nothing here is part of the build; `python -m lotg` does not import it.

WHAT IT DOES
------------
Given a season and a list of `Move`s (player X sits on roster B instead of
roster A from week N), it replays every week: rebuilds the affected lineups,
rescores the affected teams, re-decides every head-to-head, re-seeds the
regular season and re-runs the bracket — then diffs all of that against what
really happened.

THE LINEUP MODEL IS THE LOAD-BEARING ASSUMPTION
-----------------------------------------------
"Who would the manager have started?" cannot be observed, and answering it with
hindsight (start whoever scored most) flatters whichever roster you point it at.
Three models are provided; run more than one and report where they disagree:

  anchored (default) — real decisions, minimally perturbed. The counterfactual
      lineup is the real lineup minus departures; an arriving player is started
      only if his real manager started him that week (revealed startability, no
      hindsight about *this* team); any resulting hole or surplus is resolved by
      prior-form PPG — points per game over the weeks already played — subject
      to slot legality, skipping anyone the build flags as bye/injured/suspended.
  strict — the arrival plays only in the slot the departing player occupied.
      No other lineup change at all. The most conservative reading.
  ceiling — the team's score moves by the change in its *optimal* lineup, i.e.
      by how much the roster's ceiling moved. Uses the build's own Max PF
      routine (`lotg_support.lineup.compute_optimal_lineup`), so it agrees with
      the `Max PF` column by construction.

LEAGUE RULES THAT ARE EASY TO GET WRONG (all handled here)
----------------------------------------------------------
  * Seeding is wins + 0.5·ties, then regular-season PF — the build's rule.
  * The higher seed in each semifinal scores +5 (home field). `team_week.PF`
    includes it; Sleeper's raw `points` does not. Eight rows across 2021-2025
    differ by exactly this.
  * The starting-lineup template is per-season (one flex before 2024, two
    after), and playoffs start week 16 through 2025 but week 15 in 2026, where
    the final is a two-week round. All read from each season's `league.json`.

GUARDS
------
`validate(season)` runs three checks before any counterfactual is believed:
every lineup actually fielded that season is legal under the slot template; the
ceiling routine reproduces `team_week.Max PF` exactly; and a replay with *no
moves* reproduces the real PF, the real bracket and the real champion. The CLI
runs them by default.

Usage:
    from lotg_support import replay as R
    scn = R.undo_trade(2025, player="Justin Herbert")
    print(R.render(R.replay(scn)))
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace as _dc_replace
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from lotg_support import inquiry as Q
from lotg_support.lineup import compute_optimal_lineup

MODELS: Tuple[str, ...] = ("anchored", "strict", "ceiling")


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Move:
    """One player on a different roster than he really was, from `from_week` on."""
    player_id: str
    from_roster: int
    to_roster: int
    from_week: int = 1

    def describe(self, season: int) -> str:
        table = Q.teams(season)
        return (f"{Q.players().name(self.player_id)} "
                f"{table.get(self.from_roster, self.from_roster)} -> "
                f"{table.get(self.to_roster, self.to_roster)}"
                + (f" (from week {self.from_week})" if self.from_week > 1 else ""))


@dataclass(frozen=True)
class Scenario:
    season: int
    moves: Tuple[Move, ...]
    model: str = "anchored"
    label: str = ""

    def with_model(self, model: str) -> "Scenario":
        return _dc_replace(self, model=model)


def undo_trade(season: int, player: Optional[str] = None, date: Optional[str] = None,
               transaction_id: Optional[str] = None, from_week: int = 1) -> Scenario:
    """A scenario that rewinds one real trade — every player back where he was.

    Identifies the trade by player, date or transaction id; raises if that
    matches zero or several trades rather than picking one.
    """
    found = Q.trades(season=season, player=player, date=date)
    if transaction_id:
        found = [t for t in found if t.transaction_id == str(transaction_id)]
    if not found:
        raise LookupError(f"no completed {season} trade matches "
                          f"player={player!r} date={date!r} id={transaction_id!r}")
    if len(found) > 1:
        raise LookupError("several trades match; narrow with --date or --transaction-id:\n  "
                          + "\n  ".join(t.describe() for t in found))
    trade = found[0]
    moves = []
    for rid, gained in trade.received.items():
        others = [r for r in trade.roster_ids if r != rid]
        for pid in gained:
            # Undo = the player goes back to whoever gave him up. Two-sided
            # trades are the norm here; a 3-way would need explicit routing.
            if len(others) != 1:
                raise LookupError(f"trade {trade.transaction_id} has {len(trade.roster_ids)} sides; "
                                  "build the Move list explicitly")
            moves.append(Move(player_id=pid, from_roster=rid, to_roster=others[0],
                              from_week=from_week))
    return Scenario(season=season, moves=tuple(moves), label=f"undo trade {trade.describe()}")


# ---------------------------------------------------------------------------
# Lineup legality
# ---------------------------------------------------------------------------
def is_legal(lineup: Sequence[str], eligibility: Dict[str, frozenset],
             slots: Sequence[Sequence[str]]) -> bool:
    """Can these players fill the season's start slots? (bipartite matching)

    `eligibility` is `inquiry.season_eligibility(season)` — the *season's*
    positions, not today's, so a player whose listed position has since changed
    does not make his own real lineup look illegal.

    Sleeper's `"0"` empty-slot sentinel is a wildcard: a real lineup may legally
    leave a spot unfilled, and rejecting it would fail an honest lineup.
    """
    if len(lineup) != len(slots):
        return False
    match: Dict[int, str] = {}

    def assign(player: str, seen: Set[int]) -> bool:
        for idx, eligible in enumerate(slots):
            if idx in seen:
                continue
            if player != Q.EMPTY_SLOT and not (eligibility.get(player, frozenset()) & set(eligible)):
                continue
            seen.add(idx)
            if idx not in match or assign(match[idx], seen):
                match[idx] = player
                return True
        return False

    return all(assign(p, set()) for p in lineup)


def _prior_ppg(pid: str, history: Dict[str, List[float]]) -> float:
    """Points per game over the weeks already played — no hindsight."""
    played = history.get(pid) or []
    return sum(played) / len(played) if played else 0.0


def _anchored_lineup(real_starters: Sequence[str], roster: Sequence[str],
                     departing: Set[str], arrivals: Sequence[str],
                     eligibility: Dict[str, frozenset], history: Dict[str, List[float]],
                     benched_out: Set[str], slots: Sequence[Sequence[str]]) -> List[str]:
    """Real lineup, minimally perturbed (see the module docstring's `anchored`)."""
    lineup = [p for p in real_starters if p not in departing]
    lineup.extend(a for a in arrivals if a not in lineup)

    size = len(slots)
    while len(lineup) > size:
        for cand in sorted(lineup, key=lambda p: _prior_ppg(p, history)):
            trial = [p for p in lineup if p != cand]
            if len(trial) > size or is_legal(trial, eligibility, slots):
                lineup = trial
                break
        else:  # pragma: no cover - a legal lineup always exists in this data
            lineup = lineup[:size]

    bench = [p for p in roster if p not in lineup and p not in departing and p not in benched_out]
    while len(lineup) < size:
        for cand in sorted(bench, key=lambda p: -_prior_ppg(p, history)):
            trial = lineup + [cand]
            if len(trial) < size or is_legal(trial, eligibility, slots):
                lineup = trial
                bench.remove(cand)
                break
        else:  # pragma: no cover - only if the roster cannot field a legal ten
            break
    return lineup


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Standing:
    roster_id: int
    team: str
    wins: int
    losses: int
    ties: int
    points_for: float

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")

    @property
    def sort_key(self) -> Tuple[float, float]:
        return (self.wins + 0.5 * self.ties, self.points_for)


@dataclass(frozen=True)
class Flip:
    week: int
    real_winner: str
    new_winner: str
    detail: str


@dataclass(frozen=True)
class Bracket:
    semifinals: Tuple[Tuple[str, float, str, float], ...] = ()
    final: Tuple[str, float, str, float] = ()
    third_place: Tuple[str, float, str, float] = ()
    champion: str = ""
    runner_up: str = ""


@dataclass
class Result:
    scenario: Scenario
    teams: Dict[int, str]
    real_scores: Dict[int, Dict[int, float]]
    scores: Dict[int, Dict[int, float]]
    pairings: Dict[int, List[Tuple[int, int]]]
    real_standings: List[Standing]
    standings: List[Standing]
    real_bracket: Bracket
    bracket: Bracket
    flips: List[Flip] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.flips) or self.bracket.champion != self.real_bracket.champion

    def moved_weeks(self) -> List[Tuple[int, int, float, float]]:
        """(week, roster_id, real, counterfactual) for every score that moved."""
        out = []
        for wk in sorted(self.scores):
            for rid, val in self.scores[wk].items():
                real = self.real_scores[wk][rid]
                if abs(real - val) > 0.005:
                    out.append((wk, rid, real, val))
        return out


# ---------------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------------
def _score_weeks(scenario: Scenario, meta: Q.SeasonMeta,
                 warnings: List[str]) -> Tuple[Dict[int, Dict[int, float]],
                                               Dict[int, Dict[int, float]],
                                               Dict[int, List[Tuple[int, int]]]]:
    positions = Q.players().positions()
    eligibility = Q.season_eligibility(scenario.season)
    unavailable = Q.unavailable(scenario.season) if scenario.model == "anchored" else set()
    slots = meta.starting_slots
    history: Dict[str, List[float]] = {}

    real_scores: Dict[int, Dict[int, float]] = {}
    scores: Dict[int, Dict[int, float]] = {}
    pairs: Dict[int, List[Tuple[int, int]]] = {}

    for wk in Q.played_weeks(scenario.season):
        rows = Q.week(scenario.season, wk)
        pairs[wk] = Q.pairings(scenario.season, wk)
        real_scores[wk] = {rid: row.points for rid, row in rows.items()}
        scores[wk] = dict(real_scores[wk])

        active = [m for m in scenario.moves if m.from_week <= wk]
        points = {pid: val for row in rows.values() for pid, val in row.players_points.items()}
        started_anywhere = {p for row in rows.values() for p in row.starters}

        arriving: Dict[int, List[str]] = {}
        leaving: Dict[int, Set[str]] = {}
        for mv in active:
            arriving.setdefault(mv.to_roster, []).append(mv.player_id)
            leaving.setdefault(mv.from_roster, set()).add(mv.player_id)
            if mv.player_id not in points:
                warnings.append(
                    f"week {wk}: {Q.players().name(mv.player_id)} was on nobody's roster, "
                    "so no score is available — counted as 0.00")

        for rid in sorted(set(arriving) | set(leaving)):
            row = rows.get(rid)
            if row is None:
                continue
            gained = [p for p in arriving.get(rid, ()) if p not in row.players]
            lost = {p for p in leaving.get(rid, ()) if p in row.players}
            roster = [p for p in row.players if p not in lost] + gained

            if scenario.model == "ceiling":
                real_pool = {p: points.get(p, 0.0) for p in row.players}
                cf_pool = {p: points.get(p, 0.0) for p in roster}
                delta = (compute_optimal_lineup(cf_pool, positions, scenario.season)
                         - compute_optimal_lineup(real_pool, positions, scenario.season))
                scores[wk][rid] = round(row.points + delta, 2)
                continue

            if scenario.model == "strict":
                # The arrival plays exactly where the departing player played,
                # and nothing else moves. Slots are matched by position — a
                # departing QB is replaced by an arriving QB, never by the
                # arriving WR who happened to come first in the trade — and a
                # slot with no eligible arrival is simply left empty.
                lineup = list(row.starters)
                spare = list(gained)
                for idx, pid in enumerate(lineup):
                    if pid not in lost:
                        continue
                    slot = set(slots[idx]) if idx < len(slots) else set()
                    fits = [g for g in spare if eligibility.get(g, frozenset()) & slot]
                    same = [g for g in fits if positions.get(g) == positions.get(pid)]
                    pick = (same or fits or [None])[0]
                    lineup[idx] = pick if pick else Q.EMPTY_SLOT
                    if pick:
                        spare.remove(pick)
            else:
                arrivals = [p for p in gained if p in started_anywhere]
                out = {p for p in roster if (p, wk) in unavailable}
                lineup = _anchored_lineup(row.starters, roster, lost, arrivals,
                                          eligibility, history, out, slots)
            scores[wk][rid] = round(sum(points.get(p, 0.0) for p in lineup), 2)

        for pid, val in points.items():
            history.setdefault(pid, []).append(val)

    return real_scores, scores, pairs


def _standings(scores: Dict[int, Dict[int, float]], pairs: Dict[int, List[Tuple[int, int]]],
               teams: Dict[int, str], meta: Q.SeasonMeta) -> List[Standing]:
    """Regular-season table, ordered the way the build seeds: W+0.5T, then PF."""
    tally = {rid: [0, 0, 0, 0.0] for rid in teams}
    for wk in range(1, meta.regular_season_weeks + 1):
        if wk not in scores:
            continue
        for a, b in pairs.get(wk, ()):
            pa, pb = scores[wk].get(a, 0.0), scores[wk].get(b, 0.0)
            tally[a][3] += pa
            tally[b][3] += pb
            if pa > pb:
                tally[a][0] += 1
                tally[b][1] += 1
            elif pb > pa:
                tally[b][0] += 1
                tally[a][1] += 1
            else:
                tally[a][2] += 1
                tally[b][2] += 1
    table = [Standing(rid, teams.get(rid, str(rid)), w, l, t, round(pf, 2))
             for rid, (w, l, t, pf) in tally.items()]
    table.sort(key=lambda s: (-s.sort_key[0], -s.sort_key[1], s.team))
    return table


def _bracket(scores: Dict[int, Dict[int, float]], standings: Sequence[Standing],
             teams: Dict[int, str], meta: Q.SeasonMeta) -> Bracket:
    """Seed-driven championship bracket: 1v4 / 2v3, +5 to the higher seed."""
    seeds = [s.roster_id for s in standings[:meta.playoff_teams]]
    if len(seeds) < 4 or meta.semifinal_week not in scores:
        return Bracket()
    semi_pairs = ((seeds[0], seeds[3]), (seeds[1], seeds[2]))
    sf_week = meta.semifinal_week

    def total(rid: int, weeks: Iterable[int]) -> float:
        return round(sum(scores.get(w, {}).get(rid, 0.0) for w in weeks), 2)

    semis, winners, losers = [], [], []
    for high, low in semi_pairs:
        ph = round(scores[sf_week].get(high, 0.0) + Q.SEMIFINAL_HOME_BONUS, 2)
        pl = round(scores[sf_week].get(low, 0.0), 2)
        semis.append((teams.get(high, str(high)), ph, teams.get(low, str(low)), pl))
        winners.append(high if ph >= pl else low)
        losers.append(low if ph >= pl else high)

    fw = [w for w in meta.finals_weeks if w in scores]
    if not fw:
        return Bracket(semifinals=tuple(semis))
    a, b = winners
    pa, pb = total(a, fw), total(b, fw)
    champ, runner = (a, b) if pa >= pb else (b, a)
    c, d = losers
    return Bracket(
        semifinals=tuple(semis),
        final=(teams.get(a, str(a)), pa, teams.get(b, str(b)), pb),
        third_place=(teams.get(c, str(c)), total(c, fw), teams.get(d, str(d)), total(d, fw)),
        champion=teams.get(champ, str(champ)),
        runner_up=teams.get(runner, str(runner)),
    )


def replay(scenario: Scenario) -> Result:
    """Replay a season under a scenario and diff it against what really happened."""
    if scenario.model not in MODELS:
        raise ValueError(f"unknown model {scenario.model!r}; pick one of {MODELS}")
    meta = Q.season_meta(scenario.season)
    if not meta.has_snapshot:
        raise LookupError(f"{scenario.season} has no Sleeper snapshot to replay "
                          "(2020 came from the ESPN backfill and cannot be replayed)")
    teams = Q.teams(scenario.season)
    warnings: List[str] = []
    real_scores, scores, pairs = _score_weeks(scenario, meta, warnings)

    real_standings = _standings(real_scores, pairs, teams, meta)
    new_standings = _standings(scores, pairs, teams, meta)

    flips: List[Flip] = []
    for wk in sorted(scores):
        for a, b in pairs.get(wk, ()):
            ra, rb = real_scores[wk][a], real_scores[wk][b]
            ca, cb = scores[wk][a], scores[wk][b]
            if (ra > rb) == (ca > cb):
                continue
            real_winner = teams.get(a if ra > rb else b, "")
            new_winner = teams.get(a if ca > cb else b, "")
            flips.append(Flip(
                wk, real_winner, new_winner,
                f"{teams.get(a)} {ra:.2f}->{ca:.2f} vs {teams.get(b)} {rb:.2f}->{cb:.2f}"))

    return Result(
        scenario=scenario, teams=teams,
        real_scores=real_scores, scores=scores, pairings=pairs,
        real_standings=real_standings, standings=new_standings,
        real_bracket=_bracket(real_scores, real_standings, teams, meta),
        bracket=_bracket(scores, new_standings, teams, meta),
        flips=flips, warnings=sorted(set(warnings)),
    )


def no_op(season: int, model: str = "anchored") -> Result:
    """Replay with no moves — must reproduce reality. Used by validate()."""
    return replay(Scenario(season=season, moves=(), model=model, label="no-op"))


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def check_lineup_template(season: int) -> List[str]:
    """Every lineup actually fielded must be legal under the season's slots."""
    meta = Q.season_meta(season)
    eligibility = Q.season_eligibility(season)
    problems = []
    for wk in Q.played_weeks(season):
        for rid, row in Q.week(season, wk).items():
            if not is_legal(row.starters, eligibility, meta.starting_slots):
                problems.append(
                    f"{season} week {wk} roster {rid}: real lineup is illegal under "
                    f"{[list(s) for s in meta.starting_slots]} "
                    f"(eligibility {[sorted(eligibility.get(p, ())) for p in row.starters]})")
    return problems


def check_max_pf(season: int) -> List[str]:
    """The ceiling routine must reproduce the build's `Max PF` column exactly."""
    positions = Q.players().positions()
    df = Q.rows("team_week", f"Year={season}")
    by_key = {(str(r["Team"]), int(float(r["Week"]))): Q.to_number(r["Max PF"])
              for _, r in df.iterrows() if str(r.get("Max PF", "")).strip()}
    teams = Q.teams(season)
    problems = []
    for wk in Q.played_weeks(season):
        for rid, row in Q.week(season, wk).items():
            want = by_key.get((teams.get(rid, ""), wk))
            if want is None:
                continue
            got = compute_optimal_lineup({p: row.players_points.get(p, 0.0) for p in row.players},
                                         positions, season)
            if abs(got - want) > 0.02:
                problems.append(f"{season} week {wk} {teams.get(rid)}: Max PF {got:.2f} != {want:.2f}")
    return problems


def check_identity(season: int) -> List[str]:
    """A no-move replay must reproduce the real PF, bracket and champion.

    This is the strongest guard in the module: it exercises scoring, seeding,
    the +5 home-field rule and the bracket against the build's own output, so a
    counterfactual that passes it differs from reality only where the moves bite.
    """
    result = no_op(season)
    problems: List[str] = []

    df = Q.rows("team_week", f"Year={season}")
    meta = Q.season_meta(season)
    for _, r in df.iterrows():
        wk = int(float(r["Week"]))
        want = Q.to_number(r["PF"])
        rid = next((i for i, t in result.teams.items() if t == str(r["Team"])), None)
        if rid is None or want is None or wk not in result.scores:
            continue
        got = result.scores[wk][rid]
        if wk == meta.semifinal_week:
            seeds = [s.roster_id for s in result.standings[:meta.playoff_teams]]
            higher = {seeds[0], seeds[1]} if len(seeds) >= 4 else set()
            if rid in higher:
                got = round(got + Q.SEMIFINAL_HOME_BONUS, 2)
        if abs(got - want) > 0.02:
            problems.append(f"{season} week {wk} {r['Team']}: replay PF {got:.2f} != built {want:.2f}")

    champ = Q.rows("team_year", f"Year={season}", "Result~^Champion$")
    if len(champ) == 1:
        want_champ = str(champ.iloc[0]["Team"])
        if result.bracket.champion != want_champ:
            problems.append(f"{season}: replay champion {result.bracket.champion!r} "
                            f"!= built {want_champ!r}")
    return problems


def validate(season: int) -> List[str]:
    """Run every guard for one season; empty list means the replay is trustworthy."""
    return check_lineup_template(season) + check_max_pf(season) + check_identity(season)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _standings_block(title: str, table: Sequence[Standing], meta: Q.SeasonMeta) -> List[str]:
    out = [title]
    for seed, s in enumerate(table, 1):
        mark = "  *playoffs*" if seed <= meta.playoff_teams else ""
        out.append(f"  {seed}. {s.team:<18} {s.record:>6}  {s.points_for:>8.2f} PF{mark}")
    return out


def _bracket_block(title: str, bracket: Bracket) -> List[str]:
    if not bracket.semifinals:
        return []
    out = [title]
    for a, pa, b, pb in bracket.semifinals:
        out.append(f"  SF: {a} {pa:.2f} vs {b} {pb:.2f}  ->  {a if pa >= pb else b}")
    if bracket.final:
        a, pa, b, pb = bracket.final
        out.append(f"  F : {a} {pa:.2f} vs {b} {pb:.2f}  ->  CHAMPION: {bracket.champion}")
    if bracket.third_place:
        a, pa, b, pb = bracket.third_place
        out.append(f"  3rd: {a} {pa:.2f} vs {b} {pb:.2f}")
    return out


def render(result: Result, weekly: bool = False) -> str:
    """Human-readable report: what moved, what flipped, and what it changed."""
    meta = Q.season_meta(result.scenario.season)
    out: List[str] = [
        "=" * 78,
        f"{result.scenario.season} replay — model: {result.scenario.model}",
        f"scenario: {result.scenario.label or 'custom'}",
        "=" * 78,
    ]
    for mv in result.scenario.moves:
        out.append(f"  move: {mv.describe(result.scenario.season)}")

    moved = result.moved_weeks()
    out.append("")
    out.append(f"scores that move: {len(moved)}")
    if weekly:
        for wk, rid, real, cf in moved:
            out.append(f"  week {wk:>2} {result.teams.get(rid, rid):<18} {real:8.2f} -> {cf:8.2f}"
                       f"  ({cf - real:+.2f})")

    out.append("")
    out.append(f"head-to-head results that change: {len(result.flips)}")
    for flip in result.flips:
        out.append(f"  week {flip.week:>2}: {flip.real_winner} won -> now {flip.new_winner}"
                   f"   [{flip.detail}]")

    out.append("")
    out.extend(_standings_block("REAL regular-season standings", result.real_standings, meta))
    out.append("")
    out.extend(_standings_block("COUNTERFACTUAL regular-season standings", result.standings, meta))
    out.append("")
    out.extend(_bracket_block("REAL bracket", result.real_bracket))
    out.append("")
    out.extend(_bracket_block("COUNTERFACTUAL bracket", result.bracket))

    out.append("")
    out.append("SUMMARY")
    real_champ = result.real_bracket.champion or "?"
    new_champ = result.bracket.champion or "?"
    out.append(f"  champion: {real_champ} -> {new_champ}"
               + ("  (unchanged)" if real_champ == new_champ else "   << CHANGES"))
    for s in result.standings:
        was = next((r for r in result.real_standings if r.roster_id == s.roster_id), None)
        if was and was.record != s.record:
            out.append(f"  {s.team}: {was.record} -> {s.record}")
    if result.warnings:
        out.append("")
        out.append("WARNINGS (reported over-inclusively — read before quoting a number)")
        for w in result.warnings:
            out.append(f"  - {w}")
    return "\n".join(out)
