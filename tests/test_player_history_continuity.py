"""Player-history roster-lineage continuity guard.

A player's rendered history (the hover-comment chain on player_all_time / picks)
must never skip a step: a player can only be dropped or traded away by a team
that holds them, and can only be added off waivers/free agency while no team
holds them. A break means the player teleported on/off a roster — the class of
bug fixed by the history-ordering + missing-departure-synthesis passes in
lotg.py.

This test reuses the same reconstruction as scripts/audit_player_history.py and
asserts the freshly built workbook has no continuity breaks. It is skipped when
no workbook is present (e.g. a CSV-only check), so it never fails a partial run.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _xlsx_path() -> Path:
    return Path(os.environ.get("LOTG_EXPORTS", REPO / "exports")) / "LOTG_Stats.xlsx"


def _is_fixera_build() -> bool:
    # The roster-lineage reconciliation logs this marker on every fix-era build.
    # Its absence means the workbook predates the fix (e.g. a stale committed
    # snapshot); skip rather than assert against pre-fix histories. CI builds
    # fresh before pytest, so the marker is present and the test runs.
    log = Path(os.environ.get("LOTG_EXPORTS", REPO / "exports")) / "raw" / "build_debug.log"
    try:
        return "orphaned roster lineage" in log.read_text(errors="ignore")
    except Exception:
        return False


@pytest.mark.skipif(not _xlsx_path().exists() or not _is_fixera_build(),
                    reason="no fix-era workbook to audit")
def test_no_player_history_continuity_breaks():
    pytest.importorskip("openpyxl")
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    import audit_player_history as aud

    comments = aud.load_history_comments(_xlsx_path())
    players = {}
    for k, v in comments.items():
        sheet, name = k.split(":", 1)
        if sheet == "player_all_time":
            players[name] = v
    for k, v in comments.items():
        sheet, name = k.split(":", 1)
        if sheet == "picks":
            players.setdefault(name, v)

    breaks = []
    for name, txt in players.items():
        breaks.extend(b for b in aud.audit_text(name, txt) if b[2] != "UNPARSED")

    detail = "\n".join(f"  {b[0]} {b[1]} {b[2]}: {b[4]}" for b in sorted(breaks)[:60])
    assert not breaks, f"{len(breaks)} player-history continuity break(s):\n{detail}"
