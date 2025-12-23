"""Max PF utilities without OR-Tools.

This mirrors the Apps Script approach that already worked for LOTG.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def compute_optimal_lineup(points_dict: Dict[str, Any], pos_map: Dict[str, str], season: int) -> float:
    """Compute Max PF for LOTG.

    Lineup model:
    - 1 QB
    - 2 RB
    - 3 WR
    - 1 TE
    - 1 FLEX (RB/WR/TE)
    - season >= 2024: +1 FLEX (RB/WR/TE)
    - 1 SUPERFLEX (best remaining from QB/RB/WR/TE)

    Unknown positions are treated as FLEX-eligible.
    """
    if not isinstance(points_dict, dict) or not points_dict:
        return 0.0

    pos_points: Dict[str, List[float]] = {"QB": [], "RB": [], "WR": [], "TE": [], "_FLEX_": []}

    for pid, pts in points_dict.items():
        v = _to_float(pts)
        pos = (pos_map.get(str(pid)) or "").upper()
        if pos in ("QB", "RB", "WR", "TE"):
            pos_points[pos].append(v)
        else:
            pos_points["_FLEX_"].append(v)

    for k in pos_points:
        pos_points[k].sort(reverse=True)

    lineup: List[float] = []

    # core
    if pos_points["QB"]:
        lineup.append(pos_points["QB"][0])
    lineup.extend(pos_points["RB"][:2])
    lineup.extend(pos_points["WR"][:3])
    if pos_points["TE"]:
        lineup.append(pos_points["TE"][0])

    # flex pool
    flex_candidates: List[float] = []
    flex_candidates.extend(pos_points["RB"][2:])
    flex_candidates.extend(pos_points["WR"][3:])
    flex_candidates.extend(pos_points["TE"][1:])
    flex_candidates.extend(pos_points["_FLEX_"])

    def take_best(cands: List[float]) -> float | None:
        if not cands:
            return None
        m = max(cands)
        cands.remove(m)
        return m

    best1 = take_best(flex_candidates)
    if best1 is not None:
        lineup.append(best1)

    if int(season) >= 2024:
        best2 = take_best(flex_candidates)
        if best2 is not None:
            lineup.append(best2)

    # superflex from remaining of all eligible positions
    all_vals: List[float] = []
    all_vals.extend(pos_points["QB"])
    all_vals.extend(pos_points["RB"])
    all_vals.extend(pos_points["WR"])
    all_vals.extend(pos_points["TE"])
    all_vals.extend(pos_points["_FLEX_"])

    remaining = all_vals[:]
    for chosen in lineup:
        try:
            remaining.remove(chosen)
        except ValueError:
            pass

    if remaining:
        lineup.append(max(remaining))

    return float(sum(lineup))


def max_points_lineup(
    roster_positions: List[str],
    players: List[str],
    points: Dict[str, float],
    pos_map: Dict[str, str],
    season: int | None = None,
) -> Tuple[float, Dict[str, str]]:
    """Compatibility wrapper.

    Older code expected (max_pf, assignment). We keep it but ignore `roster_positions`.
    """
    yr = int(season) if season is not None else 0
    return compute_optimal_lineup(points, pos_map, yr), {}
