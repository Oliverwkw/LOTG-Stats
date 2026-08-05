"""What-if: the 2025 season replayed without the Herbert-for-Jackson trade.

On 2025-08-06 (preseason, so before a single game was played) shmuel256 and
plehv79 swapped:

    shmuel256  ->  plehv79 : Justin Herbert, Tre' Harris, $35 FAAB,
                             2026 1st, 2026 3rd, 2027 1st, 2027 2nd
    plehv79    ->  shmuel256 : Lamar Jackson, Chris Godwin

shmuel256 then went 12-3 and won the title. This script rewinds that trade and
replays all 17 weeks of 2025 to answer: does he still win?

Only two rosters change, so every other team's weekly score is untouched; what
moves is (a) shmuel256's and plehv79's weekly totals, (b) the head-to-head
results in the matchups those two played, and therefore (c) the standings, the
playoff seeding and the bracket.

LINEUP MODEL
------------
The hard part of any counterfactual is "who would the manager have started?".
Guessing with hindsight (always play the highest scorer) would flatter whichever
team we point it at, so the model is anchored to decisions that were actually
observed in 2025:

  1. Counterfactual roster = real roster - players sent + players received.
  2. Counterfactual lineup starts as the real lineup, minus any player who is
     no longer on the team.
  3. An arriving player is started if and only if his real manager started him
     that week. That is a revealed-startability signal collected without
     hindsight about *this* team: it is why Herbert (started all 17 weeks for
     plehv79) plays every week for shmuel256, and why Lamar Jackson does not
     play for plehv79 in the weeks he was hurt and shmuel256 benched him.
  4. If that leaves more than ten starters, the lowest player by PRIOR FORM
     (points-per-game over the weeks already played, i.e. information the
     manager had at the time) is dropped -- but only if the remaining ten are
     still a legal lineup, so a surplus QB is displaced by a QB, not by a WR.
  5. If it leaves fewer than ten, the open slots are filled from the bench by
     the same prior-form ordering, again subject to legality -- skipping anyone
     the build already flags as on bye / injured / suspended that week
     (exports/player_week.csv), because no manager knowingly starts a player who
     is not going to take the field.

Two sensitivity variants are also reported (--scenarios), to show the answer
does not depend on step 3:

  strict   -- an arriving player plays only in the slot the departing player
              actually occupied; no other lineup changes at all.
  ceiling  -- each team's score moves by the change in its optimal (max PF)
              lineup, i.e. by how much the *roster's ceiling* moved.

Usage:
    python scripts/whatif_herbert_trade_2025.py
    python scripts/whatif_herbert_trade_2025.py --scenarios
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from typing import Dict, Iterable, List, Sequence, Set, Tuple

SEASON = 2025
SNAPSHOT = os.path.join("exports", "snapshot", f"season_{SEASON}")
PLAYERS_JSON = os.path.join("exports", "snapshot", "sleeper_players_nfl.json")
PLAYER_WEEK_CSV = os.path.join("exports", "player_week.csv")

REGULAR_SEASON_WEEKS = 15
PLAYOFF_WEEKS = (16, 17)
PLAYOFF_TEAMS = 4

# 8-team superflex: QB / RB / RB / WR / WR / WR / TE / FLEX / FLEX / SUPER_FLEX
SLOTS: Tuple[Tuple[str, ...], ...] = (
    ("QB",),
    ("RB",),
    ("RB",),
    ("WR",),
    ("WR",),
    ("WR",),
    ("TE",),
    ("RB", "WR", "TE"),
    ("RB", "WR", "TE"),
    ("QB", "RB", "WR", "TE"),
)

# The trade, by Sleeper player id.
SHMUEL_RID, PLEHV_RID = 8, 5
SENT_BY_SHMUEL = {"6797": "Justin Herbert", "12509": "Tre' Harris"}
SENT_BY_PLEHV = {"4881": "Lamar Jackson", "4037": "Chris Godwin"}


# --------------------------------------------------------------------------
# data loading
# --------------------------------------------------------------------------
def load_positions() -> Dict[str, str]:
    with open(PLAYERS_JSON) as fh:
        blob = json.load(fh)
    return {pid: (rec.get("position") or "") for pid, rec in blob.items()}


def load_names() -> Dict[str, str]:
    with open(PLAYERS_JSON) as fh:
        blob = json.load(fh)
    return {pid: (rec.get("full_name") or pid) for pid, rec in blob.items()}


def load_teams() -> Dict[int, str]:
    with open(os.path.join(SNAPSHOT, "users.json")) as fh:
        users = {u["user_id"]: u.get("display_name") for u in json.load(fh)}
    with open(os.path.join(SNAPSHOT, "rosters.json")) as fh:
        return {r["roster_id"]: users.get(r["owner_id"]) for r in json.load(fh)}


def load_unavailable(names: Dict[str, str]) -> Set[Tuple[str, int]]:
    """{(player_id, week)} for every player the build flags as bye/injured/suspended."""
    by_name: Dict[str, Set[int]] = {}
    with open(PLAYER_WEEK_CSV) as fh:
        for row in csv.DictReader(fh):
            if row["Year"] != str(SEASON):
                continue
            if "True" in (row["Bye?"], row["Injury?"], row["Suspension?"]):
                by_name.setdefault(row["Player"], set()).add(int(row["Week"]))
    return {(pid, wk) for pid, name in names.items() for wk in by_name.get(name, ())}


def load_week(week: int) -> Dict[int, dict]:
    path = os.path.join(SNAPSHOT, "weeks", f"week_{week:02d}", "matchups.json")
    with open(path) as fh:
        return {row["roster_id"]: row for row in json.load(fh)}


# --------------------------------------------------------------------------
# lineup legality + selection
# --------------------------------------------------------------------------
EMPTY_SLOT = "0"  # Sleeper's sentinel for a starting spot left unfilled


def is_legal(lineup: Sequence[str], pos: Dict[str, str]) -> bool:
    """Can these players fill the slot template? (bipartite matching)."""
    if len(lineup) != len(SLOTS):
        return False
    match: Dict[int, str] = {}

    def assign(player: str, seen: set) -> bool:
        for idx, eligible in enumerate(SLOTS):
            if idx in seen or (player != EMPTY_SLOT and pos.get(player, "") not in eligible):
                continue
            seen.add(idx)
            if idx not in match or assign(match[idx], seen):
                match[idx] = player
                return True
        return False

    return all(assign(p, set()) for p in lineup)


def prior_form(pid: str, history: Dict[str, List[float]]) -> float:
    """Points per game over the weeks already played (no hindsight)."""
    played = history.get(pid) or []
    return sum(played) / len(played) if played else 0.0


def build_lineup(
    real_starters: Sequence[str],
    roster: Iterable[str],
    departed: Iterable[str],
    arrivals: Sequence[str],
    pos: Dict[str, str],
    history: Dict[str, List[float]],
    benched_out: Set[str],
) -> List[str]:
    """Counterfactual lineup: real decisions, minimally perturbed (steps 2-5)."""
    departed = set(departed)
    lineup = [p for p in real_starters if p not in departed]
    lineup.extend(a for a in arrivals if a not in lineup)

    while len(lineup) > len(SLOTS):
        for cand in sorted(lineup, key=lambda p: prior_form(p, history)):
            trial = [p for p in lineup if p != cand]
            if is_legal(trial, pos) or len(trial) > len(SLOTS):
                lineup = trial
                break
        else:  # pragma: no cover - a legal 10 always exists in this data
            lineup = lineup[: len(SLOTS)]

    bench = [p for p in roster if p not in lineup and p not in departed and p not in benched_out]
    while len(lineup) < len(SLOTS):
        for cand in sorted(bench, key=lambda p: -prior_form(p, history)):
            trial = lineup + [cand]
            if len(trial) < len(SLOTS) or is_legal(trial, pos):
                lineup = trial
                bench.remove(cand)
                break
        else:  # pragma: no cover
            break
    return lineup


def optimal_points(players: Iterable[str], pts: Dict[str, float], pos: Dict[str, str]) -> float:
    """Max PF: the best legal lineup, used only by the 'ceiling' sensitivity run.

    Exact for this slot template, and deliberately identical in semantics to
    lotg_support.lineup.compute_optimal_lineup (which the build uses for the
    Max PF column), including its treatment of an unknown position as
    flex-eligible: fill QB / RB x2 / WR x3 / TE greedily, then the two flex
    slots from what is left, then superflex. Nesting makes that greedy optimal --
    every fixed slot's pool is a subset of the flex pool below it.
    """
    pools: Dict[str, List[float]] = {"QB": [], "RB": [], "WR": [], "TE": [], "FLEX": []}
    for p in players:
        val = float(pts.get(p) or 0.0)
        pools.get(pos.get(p, "") or "FLEX", pools["FLEX"]).append(val)
    for vals in pools.values():
        vals.sort(reverse=True)

    lineup = pools["QB"][:1] + pools["RB"][:2] + pools["WR"][:3] + pools["TE"][:1]
    flex_pool = sorted(
        pools["RB"][2:] + pools["WR"][3:] + pools["TE"][1:] + pools["FLEX"], reverse=True
    )
    lineup += flex_pool[:2]
    superflex = pools["QB"][1:2] + flex_pool[2:3]
    if superflex:
        lineup.append(max(superflex))
    return round(sum(lineup), 2)


# --------------------------------------------------------------------------
# season replay
# --------------------------------------------------------------------------
def replay(
    scenario: str, pos: Dict[str, str], unavailable: Set[Tuple[str, int]]
) -> Tuple[Dict[int, Dict[int, float]], Dict[int, Dict[int, int]]]:
    """Return {week: {roster_id: points}} and {week: {roster_id: matchup_id}}."""
    scores: Dict[int, Dict[int, float]] = {}
    pairings: Dict[int, Dict[int, int]] = {}
    history: Dict[str, List[float]] = {}

    swap = {
        SHMUEL_RID: (list(SENT_BY_SHMUEL), list(SENT_BY_PLEHV)),  # (gets back, gives up)
        PLEHV_RID: (list(SENT_BY_PLEHV), list(SENT_BY_SHMUEL)),
    }

    for week in range(1, max(PLAYOFF_WEEKS) + 1):
        rows = load_week(week)
        scores[week] = {}
        pairings[week] = {rid: row["matchup_id"] for rid, row in rows.items()}

        # revealed startability: did this player's real manager start him?
        started_for_real = {p for row in rows.values() for p in row["starters"]}
        points_for_real: Dict[str, float] = {}
        for row in rows.values():
            for pid, val in (row["players_points"] or {}).items():
                points_for_real[pid] = float(val or 0.0)

        for rid, row in rows.items():
            if rid not in swap:
                scores[week][rid] = float(row["points"])
                continue

            arriving_all, departing = swap[rid]
            roster = [p for p in row["players"] if p not in departing] + arriving_all

            if scenario == "ceiling":
                real_pool = {p: points_for_real.get(p, 0.0) for p in row["players"]}
                cf_pool = {p: points_for_real.get(p, 0.0) for p in roster}
                delta = optimal_points(cf_pool, cf_pool, pos) - optimal_points(real_pool, real_pool, pos)
                scores[week][rid] = round(float(row["points"]) + delta, 2)
                continue

            if scenario == "strict":
                # same slot, same week: the arrival only plays where the
                # departing player actually played.
                pairs = dict(zip(departing, arriving_all))  # QB<->QB, WR<->WR
                lineup = [pairs.get(p, p) for p in row["starters"]]
            else:  # "anchored" -- the headline model
                arrivals = [p for p in arriving_all if p in started_for_real]
                out = {p for p in roster if (p, week) in unavailable}
                lineup = build_lineup(row["starters"], roster, departing, arrivals, pos, history, out)

            scores[week][rid] = round(sum(points_for_real.get(p, 0.0) for p in lineup), 2)

        for pid, val in points_for_real.items():
            history.setdefault(pid, []).append(val)

    return scores, pairings


def standings(scores, pairings, teams) -> List[Tuple[str, int, int, float]]:
    rec = {rid: [0, 0, 0.0] for rid in teams}
    for week in range(1, REGULAR_SEASON_WEEKS + 1):
        by_matchup: Dict[int, List[int]] = {}
        for rid, mid in pairings[week].items():
            by_matchup.setdefault(mid, []).append(rid)
        for sides in by_matchup.values():
            a, b = sides
            pa, pb = scores[week][a], scores[week][b]
            rec[a][2] += pa
            rec[b][2] += pb
            if pa > pb:
                rec[a][0] += 1
                rec[b][1] += 1
            elif pb > pa:
                rec[b][0] += 1
                rec[a][1] += 1
    table = [(teams[rid], w, l, round(pf, 2), rid) for rid, (w, l, pf) in rec.items()]
    table.sort(key=lambda r: (-r[1], -r[3]))
    return table


def validate_slot_model(pos: Dict[str, str]) -> None:
    """Every lineup actually fielded in 2025 must be legal under SLOTS.

    Cheap guard against a wrong slot template or a stale position map silently
    reshaping the counterfactual lineups.
    """
    for week in range(1, max(PLAYOFF_WEEKS) + 1):
        for rid, row in load_week(week).items():
            if not is_legal(row["starters"], pos):
                raise SystemExit(
                    f"slot model rejects a real lineup: week {week}, roster {rid} "
                    f"({[pos.get(p) for p in row['starters']]})"
                )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", action="store_true", help="also run the strict / ceiling sensitivity variants")
    args = ap.parse_args()

    pos, names, teams = load_positions(), load_names(), load_teams()
    unavailable = load_unavailable(names)
    validate_slot_model(pos)

    real_scores: Dict[int, Dict[int, float]] = {}
    real_pairings: Dict[int, Dict[int, int]] = {}
    for week in range(1, max(PLAYOFF_WEEKS) + 1):
        rows = load_week(week)
        real_scores[week] = {rid: float(r["points"]) for rid, r in rows.items()}
        real_pairings[week] = {rid: r["matchup_id"] for rid, r in rows.items()}

    real_table = standings(real_scores, real_pairings, teams)
    real_shm = next(row for row in real_table if row[4] == SHMUEL_RID)

    print("WHAT REALLY HAPPENED")
    for seed, (name, w, l, pf, _rid) in enumerate(real_table, 1):
        mark = " *playoffs*" if seed <= PLAYOFF_TEAMS else ""
        print(f"  {seed}. {name:<18} {w:>2}-{l:<2}  {pf:>8.2f} PF{mark}")
    print("  champion: Shmuel256 (beat stevenb123 in the semifinal, AceMatthew in the final)")

    for scenario in (["anchored", "strict", "ceiling"] if args.scenarios else ["anchored"]):
        cf_scores, pairings = replay(scenario, pos, unavailable)
        print(f"\n{'=' * 78}\nSCENARIO: {scenario}\n{'=' * 78}")

        flips: List[str] = []
        for week in range(1, max(PLAYOFF_WEEKS) + 1):
            tag = "PLAYOFFS " if week in PLAYOFF_WEEKS else ""
            print(f"\n{tag}WEEK {week}")
            by_matchup: Dict[int, List[int]] = {}
            for rid, mid in pairings[week].items():
                by_matchup.setdefault(mid, []).append(rid)
            for sides in sorted(by_matchup.values()):
                a, b = sides
                line = []
                for rid in (a, b):
                    real, cf = real_scores[week][rid], cf_scores[week][rid]
                    moved = f" ({real:.2f} -> {cf:.2f})" if abs(real - cf) > 0.005 else ""
                    line.append(f"{teams[rid]} {cf:.2f}{moved}")
                won = a if cf_scores[week][a] > cf_scores[week][b] else b
                real_won = a if real_scores[week][a] > real_scores[week][b] else b
                flag = ""
                if won != real_won:
                    flag = "   << RESULT FLIPS"
                    flips.append(f"week {week}: {teams[real_won]} beat {teams[won]}, now {teams[won]} wins")
                print(f"  {line[0]:>46}  vs  {line[1]:<46}{flag}")

        table = standings(cf_scores, pairings, teams)
        print("\nFINAL REGULAR-SEASON STANDINGS (counterfactual)")
        for seed, (name, w, l, pf, _rid) in enumerate(table, 1):
            mark = " *playoffs*" if seed <= PLAYOFF_TEAMS else ""
            print(f"  {seed}. {name:<18} {w:>2}-{l:<2}  {pf:>8.2f} PF{mark}")

        seeds = [row[4] for row in table[:PLAYOFF_TEAMS]]
        semis = [(seeds[0], seeds[3]), (seeds[1], seeds[2])]
        print("\nPLAYOFFS (week 16 semifinals, week 17 final)")
        finalists = []
        for hi, lo in semis:
            ph, pl_ = cf_scores[16][hi], cf_scores[16][lo]
            win = hi if ph > pl_ else lo
            finalists.append(win)
            print(f"  SF: {teams[hi]} {ph:.2f} vs {teams[lo]} {pl_:.2f}  ->  {teams[win]}")
        a, b = finalists
        pa, pb = cf_scores[17][a], cf_scores[17][b]
        champ = a if pa > pb else b
        print(f"  F : {teams[a]} {pa:.2f} vs {teams[b]} {pb:.2f}  ->  CHAMPION: {teams[champ]}")

        shm = next(row for row in table if row[4] == SHMUEL_RID)
        print(f"\nSUMMARY ({scenario})")
        print(
            f"  shmuel256: {shm[1]}-{shm[2]} (was {real_shm[1]}-{real_shm[2]}), "
            f"{shm[3]:.2f} PF (was {real_shm[3]:.2f})"
        )
        print(f"  head-to-head results that change: {len(flips)}")
        for f in flips:
            print(f"    - {f}")
        print(f"  2025 champion: {teams[champ]}")


if __name__ == "__main__":
    main()
