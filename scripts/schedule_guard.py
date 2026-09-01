"""Thin CLI over lotg_support.schedule_watch for the build's catch-up cron.

Prints `true` when the run should proceed, `false` when this fire is a catch-up
whose primary already completed the weekly cycle end to end.

FAILS OPEN, always: any error prints `true`. The catch-up exists because GitHub
silently drops scheduled fires; a guard that errs toward skipping would put that
silence straight back.

Which cron is the primary is derived from the workflow's own `on.schedule`, so no
cron string is restated anywhere outside it.

Usage (from the workflow):
  python scripts/schedule_guard.py --schedule "${{ github.event.schedule }}"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", default="", help="github.event.schedule of this run")
    ap.add_argument("--workflow", default="build.yml")
    ap.add_argument("--dow", default="2", help="cron day-of-week the catch-up sits on")
    ap.add_argument("--root", default=str(_ROOT))
    args = ap.parse_args(argv)
    try:
        from lotg_support import schedule_watch as SW
        skip = SW.should_skip_run(Path(args.root), args.schedule,
                                  workflow=args.workflow, dow=args.dow)
    except Exception as e:
        print(f"guard unavailable ({type(e).__name__}: {e}) — running", file=sys.stderr)
        skip = False
    print("false" if skip else "true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
