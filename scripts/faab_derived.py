"""FAAB versions of the KTC-derived columns (the build's side output, never a sheet).

  python scripts/faab_derived.py check   [--dir D]   recompute every KTC and FAAB version from the side output's
                                                     components; prints the rows that differ from the build (0 = trusted)
  python scripts/faab_derived.py compare [--dir D]   each column vs its FAAB version (rows, means, |diff|, correlations)

D defaults to exports/raw/faab_derived/ (written by the CI build; download it from the run's LOTG_outputs artifact).
See lib/lotg_support/faab_derived.py.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "lib"), str(ROOT / "src")]

from lotg_support import faab_derived as D  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "compare"])
    ap.add_argument("--dir", default=str(D.OUT))
    a = ap.parse_args(argv)
    side = D.load_side(Path(a.dir))
    if not side:
        print(f"no side output in {a.dir}")
        return 2
    if a.cmd == "check":
        res = D.reproduce(side)
        print(json.dumps(res, indent=1))
        return 0 if all(v == 0 for r in res.values() for v in r.values()) else 1
    import pandas as pd
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(D.compare(side).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
