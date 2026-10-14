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
# Max PF: the position Sleeper scored a player at THEN, by season and week
# ---------------------------------------------------------------------------
# The build computes Max PF from one position per player, Sleeper's CURRENT
# label. Sleeper's own season max points (`rosters[].settings.ppts`) were
# computed each week with the label of that week, so a player Sleeper has since
# relabelled moves the ceiling. Every entry here was found by reconciling the
# regular-season Max PF of all 40 Sleeper team-seasons (2021-2025) against
# `ppts`, and each one closes its team-season's gap to the cent:
#
#   Taysom Hill (TE today)        2021 all season QB  stevenb123 wk13 +2.82, LWebs53 wk14 +15.10
#                                 2023 week 9 QB      LWebs53 -0.10
#                                 2024 week 11 QB     LWebs53 +3.54
#   Cordarrelle Patterson (RB)    2021 all season WR  shmuel256 wk3 -2.30, wk7 -0.80
#
# Hill's 2023 and 2024 entries are single weeks because a full-season QB label
# opens gaps elsewhere (2023 weeks 8/13, 2024 weeks 4/9/10, where he was also
# fielded in a strict TE slot). In 2023 week 9 a QB/TE label fits as well as QB;
# QB is used because 2024 week 11 needs QB alone. The one gap these leave,
# stevenb123 2024 +1.00, is not a position: Sleeper's `fpts` and the opponent's
# `fpts_against` are off by the same 1.00, i.e. a stat correction after Sleeper
# froze its season totals. See plan/notes/MAX_PF_SLEEPER_RECONCILE.md.
#
# Keyed by SLEEPER id, unlike the registry above: this corrects Sleeper's own
# history, never NFLverse's, and the Max PF routine only ever sees Sleeper ids.
# `week` None = the whole season. Read only by callers that pass a week to
# `lineup.compute_optimal_lineup`, i.e. the Max PF column and the routines that
# must reproduce it exactly.
MAX_PF_POSITION_PINS: Dict[str, Tuple[Tuple[int, Optional[int], str], ...]] = {
    "4381": ((2021, None, "QB"), (2023, 9, "QB"), (2024, 11, "QB")),   # Taysom Hill
    "1535": ((2021, None, "WR"),),                                     # Cordarrelle Patterson
}


def max_pf_position(sleeper_id: Any, season: Any, week: Any) -> Optional[str]:
    """The pinned Max PF position for this player in this week, or None.

    A week-specific entry beats a season-wide one."""
    entries = MAX_PF_POSITION_PINS.get(str(sleeper_id))
    if not entries:
        return None
    try:
        season, week = int(season), int(week)
    except (TypeError, ValueError):
        return None
    season_wide = None
    for yr, wk, pos in entries:
        if yr != season:
            continue
        if wk == week:
            return pos
        if wk is None:
            season_wide = pos
    return season_wide
