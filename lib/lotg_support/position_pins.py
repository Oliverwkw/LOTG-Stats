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

from typing import Any, Dict, Optional

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
