"""FAAB versions of the KTC-derived columns (the build's side output, never a sheet).

  python scripts/faab_derived.py check   [--dir D]   recompute every KTC and FAAB version from the side output's
                                                     components; prints the rows that differ from the build (0 = trusted)
  python scripts/faab_derived.py compare [--dir D]   each column vs its FAAB version (rows, means, |diff|, correlations)
  python scripts/faab_derived.py search  [--dir D] [--powers 0.25,0.5,1] [--pivots 50,100] [--cash] [--today YYYY-MM-DD]
        one global transform of every FAAB value, v -> pivot * (v / pivot) ** power, recomputed through every
        derived column and scored against today's (KTC) column: err = mean |diff| / sd, Spearman. --today = the
        build's date (default: today). Exports are read from D's grandparent (an artifact's root).

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
    ap.add_argument("cmd", choices=["check", "compare", "search"])
    ap.add_argument("--dir", default=str(D.OUT))
    ap.add_argument("--powers", default="0.15,0.2,0.25,0.3,0.5,1")
    ap.add_argument("--pivots", default="50,100")
    ap.add_argument("--cash", action="store_true", help="also transform FAAB dollars moved in trades")
    ap.add_argument("--today", default=None)
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
    if a.cmd == "search":
        from datetime import date
        d = Path(a.dir)
        s = D.Search(d.parent.parent, d, date.fromisoformat(a.today) if a.today else date.today())
        rows, per = [], {}
        for pw in [float(x) for x in a.powers.split(",")]:
            for pv in ([1.0] if pw == 1.0 else [float(x) for x in a.pivots.split(",")]):
                sc = D.score(s.side, s.run(D.Transform(scale=pv ** (1 - pw), power=pw, cash=a.cash)))
                rows.append({"power": pw, "pivot": None if pw == 1.0 else pv, "mean err": sc.err.mean(),
                             "mean spearman": sc.spearman.mean()})
                per[(pw, pv)] = sc.set_index(sc.sheet + ": " + sc.column).err
        out = pd.DataFrame(rows).sort_values("mean err")
        print(out.round(4).to_string(index=False))
        b = out.iloc[0]
        best = per[(b["power"], b["pivot"] if pd.notna(b["pivot"]) else 1.0)]
        print("\nper column, err (identity -> best):")
        print(pd.DataFrame({"identity": per.get((1.0, 1.0)), "best": best}).round(3).to_string())
        return 0
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(D.compare(side).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
