"""Build the league website (static, precomputed JSON) into a folder.

    python scripts/build_site.py --out _site                 # what .github/workflows/site.yml runs
    python scripts/build_site.py --out _site --no-forecast   # skip the ~20 s odds simulation
    python scripts/build_site.py --out _site --with-docs     # also copy docs/ (the rating page) in

Read-only over the repo: it writes only under --out. See lotg_support.league_site.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from lotg_support import league_site  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="_site")
    ap.add_argument("--no-forecast", action="store_true")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--with-docs", action="store_true",
                    help="copy docs/ (rate/) into the output, as the Pages deploy does")
    a = ap.parse_args(argv)
    t = time.time()
    out = Path(a.out)
    report = league_site.build(out, forecast=not a.no_forecast, sims=a.sims)
    if a.with_docs:
        for item in (ROOT / "docs").iterdir():
            dest = out / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
    report["wall_seconds"] = round(time.time() - t, 1)
    report["site_bytes_total"] = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
