from __future__ import annotations
from typing import Dict, List, Tuple
import re, Iterable, Set
from ortools.sat.python import cp_model

# slot eligibility rules (expanded as needed)
SLOT_RULES = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF", "DST"},
    "DST": {"DEF", "DST"},
    "FLEX": {"RB","WR","TE"},
    "REC_FLEX": {"WR","TE"},
    "WRRB_FLEX": {"WR","RB"},
    "SUPER_FLEX": {"QB","RB","WR","TE"},
}

def slot_positions(roster_positions: List[str]) -> List[str]:
    # Normalize a little
    out=[]
    for s in roster_positions:
        s = (s or "").upper()
        out.append(s)
    return out

def eligibility(slot: str, pos: str) -> bool:
    """Return True if a player with `pos` can be used in `slot`.

    `pos` may be a single position ("RB") or a multi-eligible string like "RB/WR".
    """
    slot = (slot or "").upper().strip()
    pos_s = (pos or "").upper().strip()

    # Split multi-eligibility markers (RB/WR, RB,WR, etc.)
    poss = [p for p in re.split(r"[^A-Z]+", pos_s) if p] if pos_s else []
    if not poss:
        return False

    if slot in SLOT_RULES:
        allowed = set(SLOT_RULES[slot])
        return any(p in allowed for p in poss)

    # Unknown slot → allow any position (defensive)
    return True

def max_points_lineup(roster_positions: List[str], players: List[str], points: Dict[str, float], pos_map: Dict[str, str]) -> Tuple[float, Dict[str, str]]:
    # CP-SAT exact assignment: each slot gets exactly one player, each player used at most once.
    slots = slot_positions(roster_positions)
    model = cp_model.CpModel()
    x = {}  # (i, pid) -> bool
    for i, slot in enumerate(slots):
        for pid in players:
            if eligibility(slot, pos_map.get(pid, "")):
                x[(i,pid)] = model.NewBoolVar(f"x_{i}_{pid}")

    # each slot exactly one
    for i, slot in enumerate(slots):
        vars_i = [x[(i,pid)] for pid in players if (i,pid) in x]
        if not vars_i:
            # slot cannot be filled (league mismatch); treat as 0 slot
            continue
        model.Add(sum(vars_i) == 1)

    # each player at most once
    for pid in players:
        vars_p = [x[(i,pid)] for i in range(len(slots)) if (i,pid) in x]
        if vars_p:
            model.Add(sum(vars_p) <= 1)

    # maximize points
    objective_terms=[]
    for (i,pid), var in x.items():
        objective_terms.append(int(round(points.get(pid, 0.0)*100)) * var)
    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    chosen = {}
    total = 0.0
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (i,pid), var in x.items():
            if solver.Value(var) == 1:
                chosen[slots[i]] = pid
                total += points.get(pid, 0.0)
    return round(total,2), chosen
