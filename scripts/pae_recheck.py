"""Yearly re-check of the points-above-expectation model (plan/MASTER_TODO.md).

Replays the build as of the end of each season on the model's inputs, which
every build writes to exports/raw/pae_additions.json.gz (artifact only — not
committed). Get them from a build's artifact:

  gh run download <run id> -n LOTG_outputs -D /tmp/lotg && \
  PYTHONPATH=lib python scripts/pae_recheck.py --dump /tmp/lotg/raw/pae_additions.json.gz

Prints calibration and oldest-tenure error per season against the 2026-10-04
baseline, and "ok" or what to re-tune. Read-only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lotg_support import expectation_recheck as RC  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dump", default=str(Path("exports") / "raw" / RC.DUMP_NAME))
    ap.add_argument("--seasons", type=int, nargs="*", default=None,
                    help="seasons to replay (default: the third on)")
    args = ap.parse_args(argv)
    if not Path(args.dump).exists():
        print(f"no inputs at {args.dump} — download a build's LOTG_outputs artifact (see --help)")
        return 1
    adds = RC.load_additions(args.dump)
    checks = RC.replay(adds, args.seasons)
    print(f"{'as of':>6} {'additions':>9} {'calibration':>11} {'baseline':>8} {'oldest-tenure':>13}")
    for c in checks:
        cal = f"{c.calibration:.3f}" if c.calibration is not None else "-"
        base = f"{c.baseline:.3f}" if c.baseline is not None else "-"
        edge = f"{c.edge:.3f}" if c.edge is not None else "-"
        print(f"{c.season:>6} {c.additions:>9} {cal:>11} {base:>8} {edge:>13}")
    print(f"limits: calibration <= {RC.MAX_CALIBRATION}, oldest-tenure <= {RC.MAX_EDGE_ERROR}")
    print(RC.verdict(checks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
