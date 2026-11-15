#!/usr/bin/env python3
"""Daily ESPN injury capture: every NFL team's injury list with ESPN's estimated
return date, mapped to Sleeper ids, into data/espn_injuries.csv (overwritten)
and data/espn_injury_log.csv (one row per change, for calibrating the dates
after the season). Run by .github/workflows/espn_injuries.yml; no API key.

    python scripts/capture_espn_injuries.py            # current season
    python scripts/capture_espn_injuries.py --dry-run  # fetch and summarise only

See lib/lotg_support/espn_injuries.py for what the dates mean and how the
forecast uses them.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lotg_support import espn_injuries as E  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    today = date.today()
    ap.add_argument("--season", type=int, default=today.year if today.month >= 3 else today.year - 1)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(E.capture(a.season, dry_run=a.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
