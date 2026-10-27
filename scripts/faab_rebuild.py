"""Rebuild the FAAB value inputs from public data — a thin command line over `lotg_support.faab_pipeline`.

    python scripts/faab_rebuild.py                 # fetch, rebuild (finished snapshots reused), write data/faab_value/
    python scripts/faab_rebuild.py --full          # refit every quarterly snapshot from scratch (~9 h: 5 fold bags x 24+ quarters)
    python scripts/faab_rebuild.py --no-fetch      # use the cached downloads
    python scripts/faab_rebuild.py --end 2021-03-15 --out /tmp/x   # a short window, written elsewhere (smoke test)
    python scripts/faab_rebuild.py --max-minutes 270   # stop fitting new snapshots after 270 min (exit 3; resume next run)

Writes data/faab_value/inputs.csv and evidence.json (and awards.csv when a fresh parse finds at least as many
awards). Needs scikit-learn, scipy and pyarrow besides the build's requirements. Rule strengths are not refit.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from lotg_support import faab_pipeline as P  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--end")
    ap.add_argument("--out")
    ap.add_argument("--max-minutes", type=float, help="stop fitting new snapshots after this long (cached blocks resume next run)")
    a = ap.parse_args(argv)
    R = P.rebuild(full=a.full, fetch=not a.no_fetch, end=a.end, out=Path(a.out) if a.out else None, max_minutes=a.max_minutes,
                  log=lambda m: print(m, flush=True))
    if R is None:
        sys.exit(3)          # incomplete (time budget): the workflow keeps the cache and skips the commit


if __name__ == "__main__":
    main()
