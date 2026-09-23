"""Carry the digest snapshot across a build that re-dated existing rows.

    python scripts/migrate_digest_keys.py --old OLD_EXPORTS --new NEW_EXPORTS \
        [--snapshot data/digest/ranks_snapshot.json] [--dry-run]

OLD_EXPORTS is the export set the snapshot was taken from, NEW_EXPORTS one from
the build that re-dated rows. See lotg_support.digest.redate_key_map.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
from lotg_support import digest as D  # noqa: E402


def _frames(d: Path) -> dict:
    return {s: pd.read_csv(d / f"{s}.csv", low_memory=False) for s in D._REDATE_IDENTITY
            if (d / f"{s}.csv").exists()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", required=True, type=Path)
    ap.add_argument("--new", required=True, type=Path)
    ap.add_argument("--snapshot", type=Path, default=_ROOT / "data" / "digest" / "ranks_snapshot.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    old, new = _frames(a.old), _frames(a.new)
    kmap = D.redate_key_map(old, new)
    by_sheet = {}
    for k in kmap:
        by_sheet[k.split("|")[0]] = by_sheet.get(k.split("|")[0], 0) + 1
    print(f"re-dated rows: {len(kmap)} {by_sheet}")
    snap = json.loads(a.snapshot.read_text())
    before = sum(1 for e in snap.get("event_board") or [] if e.get("key") in kmap)
    snap = D.apply_key_map(snap, kmap, new)
    print(f"board entries re-keyed: {before}")
    if not a.dry_run:
        D.save_snapshot(a.snapshot, snap)      # the digest's own format
    return 0


if __name__ == "__main__":
    sys.exit(main())
