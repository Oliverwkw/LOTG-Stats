#!/usr/bin/env python3
"""
KTC historical SUPERFLEX backfill from the community Google Sheet (Phase 13).

WHY: dynasty-daddy (our live KTC source) only has per-player history back to
2021-04-16. A community-maintained Google Sheet carries daily SUPERFLEX values
for ~460 currently-rated players AND the future-pick labels, going back to
2020-04-01 — the same 2020/early-2021 gap. Unlike the Wayback rankings snapshots
(capped at ~top-100 by Wayback's 1MB id_ limit), the sheet has the FULL player
column set with no cap, so it fills the active-player 2020 gap far more broadly
and cleanly than the scraper can. Retired players (Brees, A.J. Green, Robby
Anderson, ...) are NOT columns in the sheet (dropped from current ratings), so
they still rely on the Wayback scrape + the "off-rolls -> KTC 0" rule.

SHEET: https://docs.google.com/spreadsheets/d/1n5aqip8iFCpltO8deiS7q9m3u_dFvKTZpwzfZXVTpgs
       gid=991742784  (daily SF values; col 0 = date, then 36 pick-label cols
       "YYYY Early/Mid/Late Nth" for 2024-2026, then ~464 player-name cols).
       Only the player columns carry pre-floor (2020-21) data — the pick columns
       are 2024-2026 only, so they give no help for our 2020-21 pick gap.

INPUT: a CSV export of that gid (download once; not committed). Default path
       /tmp/ktc_sheet_991742784.csv, override with --csv.
       Export with:
         curl -sL "https://docs.google.com/spreadsheets/d/1n5aqip8iFCpltO8deiS7q9m3u_dFvKTZpwzfZXVTpgs/export?format=csv&gid=991742784" -o /tmp/ktc_sheet_991742784.csv

OUTPUT: merges pre-floor (< 2021-04-16) weekly SF values into the existing
        data/ktc_backfill/<sleeper_id>.json series (dedup by date; existing
        scraped/dynasty-daddy dates win). Idempotent.

CROSSWALK: sheet columns are player NAMES (KTC's spelling). Map name -> sleeper_id
via the live KTC directory + DynastyProcess db_playerids, preferring a sleeper_id
that is currently KTC-rated (the sheet is a current sheet, so name-change players
resolve to their current id).
"""
import argparse
import csv
import glob
import json
import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FLOOR = "2021-04-16"  # dynasty-daddy history floor; only pre-floor needs backfill
PICK_RE = re.compile(r"^\d{4}\s+(Early|Mid|Late)\s+\d")


def _nrm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _build_resolver():
    """name -> sleeper_id, preferring the currently-KTC-rated id."""
    cand = defaultdict(list)
    direc = json.load(open(REPO / "data/ktc_cache/directory.json"))
    cur = {str(p["sleeper_id"]) for p in direc if p.get("sleeper_id")}
    for p in direc:
        if p.get("sleeper_id") and p.get("full_name"):
            cand[_nrm(p["full_name"])].append(str(p["sleeper_id"]))
    dp = REPO / "data/ktc_cache/db_playerids.csv"
    if dp.exists():
        for r in csv.DictReader(open(dp)):
            sl = (r.get("sleeper_id") or "").split(".")[0]
            if sl and r.get("name"):
                cand[_nrm(r["name"])].append(sl)

    def resolve(name):
        cs = [s for s in cand.get(_nrm(name), []) if s.isdigit()]
        for s in cs:
            if s in cur:
                return s
        return cs[0] if cs else None

    return resolve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="/tmp/ktc_sheet_991742784.csv")
    ap.add_argument("--every", type=int, default=7, help="downsample: keep every Nth daily snapshot")
    args = ap.parse_args()

    resolve = _build_resolver()
    rdr = csv.reader(open(args.csv))
    cols = next(rdr)[1:]
    rows = [r for r in rdr if r and r[0][:4].isdigit() and r[0] < FLOOR]
    rows.sort(key=lambda r: r[0])
    weekly = [r for n, r in enumerate(rows) if n % args.every == 0 or n == len(rows) - 1]
    print(f"pre-floor snapshots kept: {len(weekly)} ({weekly[0][0]}..{weekly[-1][0]})")

    player_series = defaultdict(dict)
    unmapped = []
    for i, c in enumerate(cols):
        if PICK_RE.match(c):  # pick cols are 2024-2026 only -> no pre-floor data
            continue
        sid = resolve(c)
        if not sid:
            unmapped.append(c)
            continue
        for r in weekly:
            v = r[i + 1].strip() if i + 1 < len(r) else ""
            if v and v != "0":
                try:
                    player_series[sid][r[0]] = float(v)
                except ValueError:
                    pass

    outdir = REPO / "data/ktc_backfill"
    updated = created = 0
    for sid, dv in player_series.items():
        f = outdir / f"{sid}.json"
        ex = json.load(open(f)) if f.exists() else []
        seen = {x["date"] for x in ex}
        add = [{"date": d, "sf_trade_value": v} for d, v in sorted(dv.items()) if d not in seen]
        if add:
            json.dump(sorted(ex + add, key=lambda x: x["date"]), open(f, "w"))
            if ex:
                updated += 1
            else:
                created += 1
    print(f"players with pre-floor data: {len(player_series)} | files updated: {updated} | created: {created}")
    print(f"unmapped (post-2021 rookies / name misses, no pre-floor impact): {len(unmapped)} {unmapped[:6]}")


if __name__ == "__main__":
    main()
