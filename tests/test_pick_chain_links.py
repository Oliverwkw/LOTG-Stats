"""Round-4 audit Part G: asset-chain link integrity guard.

Every "Link to previous/next transaction" reference across picks and trades must
be in-range and round-trip consistent, and a picks-sheet link must NEVER point at
a DIFFERENT picks row (a sibling pick). That sibling-self-link was the bug fixed
by keying the pick chain on the FULL numbered identity (year, round, number,
orig) instead of the colliding (year, round, orig): a team holding several
same-round picks originally its own (e.g. BROsenzweig's 2025 5.02/5.03/5.06, or a
2.09 toilet pick alongside the real 2nd-rounder) had all their draft terminals
collapse into one bucket, so a pick linked to a sibling instead of its own trade.

Reads built CSVs (default <repo>/exports or $LOTG_EXPORTS); SKIPS when absent.

A "PH#N" ref is the picks FRAME's positional index, and the frame ships as two
interleaved sheets, so the frame is rebuilt in build order from
`raw/pick_ref_index.csv` before any of the row numbers below mean anything.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import pick_index  # noqa: E402


def _exports_dir() -> Path:
    return Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))


def _rows(p: Path):
    with p.open() as f:
        return list(csv.DictReader(f))


def _refs(v):
    return [r.strip() for r in re.split(r"[;,]", v or "")
            if r.strip() and re.match(r"(PH#|T#|#)\d+$", r.strip())]


@pytest.mark.skipif(not (_exports_dir() / "non_rookie_picks.csv").exists(),
                    reason="no build present")
def test_pick_chain_link_integrity():
    d = _exports_dir()
    tx = _rows(d / "add_drops.csv")
    tr = _rows(d / "trades.csv")
    # The picks frame in BUILD order — NOT the two sheets concatenated, which is
    # a different order and would point every PH# ref at the wrong row. A build
    # that stopped emitting the map fails here rather than quietly skipping:
    # this is the only committed guard on the PH# invariant.
    ph = pick_index.order_rows(d, {s: _rows(d / f"{s}.csv") for s in pick_index.SHEETS})
    assert ph is not None, (
        f"no usable {pick_index.RAW_SUBDIR}/{pick_index.FILE_NAME} under {d} — "
        "PH# refs cannot be resolved, so this guard cannot run")
    maxn = {"#": len(tx), "T#": len(tr), "PH#": len(ph)}

    def inrange(ref):
        m = re.match(r"(PH#|T#|#)(\d+)$", ref)
        return 1 <= int(m.group(2)) <= maxn[m.group(1)]

    oor, sibling, roundtrip = [], [], []

    # (1) every link cell in-range
    link_cols = {
        "add_drops": ["Link to next transaction (added player)",
                         "Link to previous transaction (added player)",
                         "Link to next transaction (dropped player)",
                         "Link to previous transaction (dropped player)"],
        "trades": ["Link to next transaction per asset",
                   "Link to previous transaction per asset"],
        "picks": ["Link to next transaction", "Link to previous transaction"],
    }
    # "picks" here names the rebuilt FRAME, which is what PH#N counts through —
    # the rows come from both sheets.
    for sheet, rows in (("add_drops", tx), ("trades", tr), ("picks", ph)):
        for i, row in enumerate(rows):
            for c in link_cols[sheet]:
                for ref in _refs(row.get(c, "")):
                    if not inrange(ref):
                        oor.append(f"{sheet} row{i + 1} {c}={ref}")

    # (2) no picks-sheet link to a DIFFERENT picks (sibling) row
    for i, row in enumerate(ph):
        me = f"PH#{i + 1}"
        for c in ("Link to next transaction", "Link to previous transaction"):
            v = (row.get(c) or "").strip()
            if v.startswith("PH#") and v != me:
                sibling.append(f"picks row{i + 1} "
                               f"({row.get('Year')} {row.get('Number')} "
                               f"orig={row.get('Original Team')}) {c}={v}")

    # (3) round-trip: a picks.prev that is a trade must be echoed in that trade's
    #     per-asset "next" as this pick's draft row.
    for i, row in enumerate(ph):
        me = f"PH#{i + 1}"
        m = re.match(r"T#(\d+)$", (row.get("Link to previous transaction") or "").strip())
        if m:
            k = int(m.group(1)) - 1
            if 0 <= k < len(tr) and me not in (tr[k].get("Link to next transaction per asset") or ""):
                roundtrip.append(f"picks row{i + 1} prev=T#{k + 1} not echoed in that trade's next-per-asset")

    assert not oor, f"{len(oor)} out-of-range link ref(s):\n  " + "\n  ".join(oor[:30])
    assert not sibling, f"{len(sibling)} sibling-pick self-link(s):\n  " + "\n  ".join(sibling[:30])
    assert not roundtrip, f"{len(roundtrip)} pick<->trade round-trip break(s):\n  " + "\n  ".join(roundtrip[:30])


if __name__ == "__main__":
    test_pick_chain_link_integrity()
    print("pick-chain link integrity: OK")
