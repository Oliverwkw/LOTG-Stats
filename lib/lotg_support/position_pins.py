"""Fantasy-position pins — the registry, with no third-party imports.

Split out of `external.py` so the pin is readable from code that cannot afford
pandas. The injury capture is the case: `.github/workflows/capture_injuries.yml`
and `sweep_injuries.yml` install `pyyaml` and `requests` and nothing else, so
importing `external` there would fail on `import pandas` — and a capture that
records Sleeper's raw position writes a row that disagrees with every sheet the
build ships (see `pinned_position`).

`external` re-exports both names, so `external.FANTASY_POSITION_PINS` and
`external.apply_position_pins` keep working for every existing reader.

Keyed by gsis_id, never by name: names collide and upstream re-spells them.

This is a pin, not a mapping table to grow by default: add a player only when
his fantasy position here is genuinely unambiguous and upstream disagrees.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

FANTASY_POSITION_PINS: Dict[str, str] = {
    "00-0040718": "WR",   # Travis Hunter (JAX) — two-way WR/CB, rostered as a WR
}


def pinned_position(gsis_id: Optional[str], sleeper_position: Any) -> str:
    """The position to record for a player: his pin if he has one, else what
    the source said.

    Sleeper's dictionary is current-only and re-labels two-way players — it
    flipped Travis Hunter WR -> DB on 2026-09-08 — so a capture that stores the
    raw label disagrees with the sheets for the life of the row. Whitespace is
    stripped from the key because Sleeper pads its own gsis_ids (see
    `injury_tracker.resolve_gsis`).
    """
    key = str(gsis_id or "").strip()
    return FANTASY_POSITION_PINS.get(key) or (str(sleeper_position or "").strip())


# ---------------------------------------------------------------------------
# Max PF: the positions Sleeper listed a player at THEN, by season
# ---------------------------------------------------------------------------
# The build computes Max PF from one position per player, Sleeper's CURRENT
# label. Sleeper's own season max points (`rosters[].settings.ppts`) used the
# listing of the time, which for a few players was a different position or more
# than one. A player listed at several positions is eligible at each of them.
# Each entry was checked by reconciling the regular-season Max PF of all 40
# Sleeper team-seasons (2021-2025) against `ppts`:
#
#   Taysom Hill (TE today)        2021 QB      closes stevenb123 wk13 +2.82, LWebs53 wk14 +15.10
#                                 2022- QB/TE  closes LWebs53 2023 wk9 -0.10
#   Cordarrelle Patterson (RB)    2021 RB/WR   closes shmuel256 wk3 -2.30, wk7 -0.80
#
# Rejected by the same check: Hill QB/TE in 2021 (leaves both 2021 gaps open);
# Patterson RB/WR in 2022 (opens Oliverwkw 2022 week 4, +3.50).
# Left open, see plan/notes/MAX_PF_SLEEPER_RECONCILE.md:
#   LWebs53 2024 +3.54 (week 11) — only Hill as QB-ONLY that week closes it, and
#     QB/TE cannot (it only ever raises Max PF, which is already above Sleeper's);
#   stevenb123 2024 +1.00 — a stat correction: `fpts` and the opponent's
#     `fpts_against` are off by the same 1.00.
#
# Keyed by SLEEPER id, unlike the registry above: this corrects Sleeper's own
# history, never NFLverse's, and the Max PF routine only ever sees Sleeper ids.
# Entries are (first season, last season or None = still, positions). Read only
# by callers that pass a week to `lineup.compute_optimal_lineup`, i.e. the Max
# PF column and the routines that must reproduce it exactly.
MAX_PF_POSITION_PINS: Dict[str, Tuple[Tuple[int, Optional[int], Tuple[str, ...]], ...]] = {
    "4381": ((2021, 2021, ("QB",)), (2022, None, ("QB", "TE"))),   # Taysom Hill
    "1535": ((2021, 2021, ("RB", "WR")),),                         # Cordarrelle Patterson
}


def max_pf_positions(sleeper_id: Any, season: Any) -> Optional[Tuple[str, ...]]:
    """The positions Sleeper listed this player at in `season`, if pinned."""
    entries = MAX_PF_POSITION_PINS.get(str(sleeper_id))
    if not entries:
        return None
    try:
        season = int(season)
    except (TypeError, ValueError):
        return None
    for first, last, positions in entries:
        if first <= season and (last is None or season <= last):
            return positions
    return None
