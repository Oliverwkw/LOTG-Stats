#!/usr/bin/env python3
"""One-at-a-time KTC-direct backfill for pre-2021-04-16 values.

Why this exists
---------------
dynasty-daddy (the build's normal KTC source) only serves history from
2021-04-16 — that date is baked in as `KTC_FLOOR`. keeptradecut.com itself
serves DAILY history back to **2020-04-01**, for retired players too (Drew
Brees and Tom Brady still resolve years after retiring). Everything between
those two dates was N/A in the exports purely because we were asking the
wrong source: the 2020 startup draft, every 2020 waiver/FA move, and the
2020 trades.

Approach
--------
Deliberately player-by-player, not a bulk sweep. Each player is resolved to a
KTC slug, fetched, verified, and merged individually, and anything ambiguous
is reported rather than guessed. Bulk name-matching against KTC has been tried
here before and produces silent mis-attributions.

Slug resolution has two sources, because KTC's live rankings page only lists
~500 CURRENTLY-RANKED players — every retired player we care about is absent:
  1. the live rankings page      (active players)
  2. Wayback snapshots of that page from 2020-2022 (retired players, whose
     slug/playerID stay valid on the live site long after they drop off)

Values are written in the shape the build already reads
(`data/ktc_backfill/<sleeper_id>.json`, a list of
`{"date": "YYYY-MM-DD", "sf_trade_value": N}`), merged with whatever is
already there. Existing datapoints are never overwritten — this only ADDS
dates the file doesn't have.

NOTE the value column: the league is superflex, so the build reads
`sf_trade_value` and this scraper must take KTC's `playerSuperflex` series.
`playerOneQB` would silently under-value every non-QB.

Usage
-----
    python scripts/ktc_direct_backfill.py --plan          # what would change
    python scripts/ktc_direct_backfill.py --apply         # write the files
    python scripts/ktc_direct_backfill.py --apply --only "Julio Jones"
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
BACKFILL_DIR = ROOT / "data" / "ktc_backfill"
SLUG_CACHE = ROOT / "data" / "ktc_cache" / "ktc_slug_index.json"

KTC_RANKINGS = "https://keeptradecut.com/dynasty-rankings"
KTC_PLAYER = "https://keeptradecut.com/dynasty-rankings/players/{slug}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Wayback snapshots of the rankings page, chosen to span the era we need so
# players who retired at different points are all covered by at least one.
WAYBACK_SNAPSHOTS = [
    "20210117214916",
    "20210724022232",
    "20211201011535",
    "20220928165952",
]
WAYBACK = "https://web.archive.org/web/{ts}id_/" + KTC_RANKINGS

# KTC's own history starts here; nothing earlier exists to fetch.
KTC_EARLIEST = date(2020, 4, 1)

# Only values BEFORE this are worth committing. data/ktc_backfill/ is tracked in
# git; data/ktc_cache/ (dynasty-daddy, which covers 2021-04-16 onward) is
# gitignored and refetched every build. Storing the post-mirror half here would
# duplicate ~9 MB of data the build already fetches. Keep a couple of weeks of
# overlap past the mirror's start so there's no seam if a fetch is short.
KEEP_BEFORE = date(2021, 5, 1)

# Players whose Sleeper name doesn't match KTC's. Each was resolved BY HAND and
# position-checked against Sleeper — never fuzzy-match this list, the near-misses
# are real different players (Samaje vs La'Mical Perine, Aaron vs Richard
# Rodgers, the five other Millers). slug -> the KTC page that is genuinely them.
NAME_ALIASES: Dict[str, str] = {
    # Sleeper name          KTC slug                 why
    "Robbie Chosen":        "robbie-chosen-256",     # renamed from Robby Anderson; KTC id 256 kept, name part updated
    "William Fuller":       "will-fuller-213",       # KTC lists him as Will Fuller (V)
    "Tyron Billy-Johnson":  "tyron-johnson-472",     # Sleeper appends the second surname; both WR
    "La'Mical Perine":      "lamical-perine-630",    # apostrophe dropped in KTC's slug
    "Scotty Miller":        "scotty-miller-442",     # archived arrays say "Scott"; live page is "Scotty"
}

_SLEEP = 1.5  # be polite: one page per ~1.5s


# --------------------------------------------------------------------------
# fetch helpers
# --------------------------------------------------------------------------

def _get(url: str, timeout: int = 60) -> str:
    """GET via curl.

    urllib is deliberately avoided: KTC's TLS negotiation fails under some
    Python/OpenSSL builds with `TLSV1_ALERT_PROTOCOL_VERSION`, while curl
    negotiates fine against the same host.
    """
    try:
        res = subprocess.run(
            ["curl", "-sS", "--compressed", "--max-time", str(timeout), "-A", UA, url],
            capture_output=True, timeout=timeout + 15,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timeout fetching {url}")
    if res.returncode != 0:
        raise RuntimeError(f"curl exit {res.returncode}: {res.stderr.decode('utf-8','ignore')[:200]}")
    return res.stdout.decode("utf-8", "ignore")


def _players_array(html: str) -> List[Dict]:
    """Pull the `playersArray = [...]` blob out of a rankings page."""
    m = re.search(r"playersArray\s*=\s*(\[.*?\])\s*;", html, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception:
        return []


def build_slug_index(refresh: bool = False) -> Dict[str, Dict[str, str]]:
    """name.lower() -> {slug: position}. Cached on disk; rebuilt with --refresh."""
    if SLUG_CACHE.exists() and not refresh:
        try:
            return json.loads(SLUG_CACHE.read_text())
        except Exception:
            pass
    idx: Dict[str, Dict[str, str]] = {}

    def _ingest(arr: List[Dict]) -> None:
        for pl in arr:
            nm = (pl.get("playerName") or "").strip()
            slug = pl.get("slug")
            if not nm or not slug:
                continue
            idx.setdefault(nm.lower(), {})[slug] = pl.get("position") or ""

    try:
        _ingest(_players_array(_get(KTC_RANKINGS)))
    except Exception as e:
        print(f"  ! live rankings fetch failed: {e}", file=sys.stderr)
    for ts in WAYBACK_SNAPSHOTS:
        try:
            _ingest(_players_array(_get(WAYBACK.format(ts=ts))))
            time.sleep(_SLEEP)
        except Exception as e:
            print(f"  ! wayback {ts} failed: {e}", file=sys.stderr)
    SLUG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SLUG_CACHE.write_text(json.dumps(idx, indent=0, sort_keys=True))
    return idx


def _slugify(name: str) -> str:
    s = name.lower().replace("'", "").replace(".", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def fetch_history(slug: str, alt_names: Optional[List[str]] = None) -> List[Tuple[str, float]]:
    """[(YYYY-MM-DD, sf_trade_value)] for one KTC player page, ascending.

    Reads the SUPERFLEX series (`playerSuperflex`), matching the build's
    `sf_trade_value` column. `playerOneQB` runs ~22% lower for non-QBs and
    would silently corrupt the backfill.

    A KTC slug is `<name-part>-<id>`. The id is stable forever but the name
    part tracks the player's CURRENT name, so a slug harvested from a Wayback
    snapshot 404s for anyone renamed since (Robby Anderson -> Robbie Chosen,
    "Scott" -> "Scotty" Miller). On a miss, retry the same id with each
    alternate spelling before giving up.
    """
    html = _get(KTC_PLAYER.format(slug=slug))
    m = re.search(r"playerSuperflex\s*=\s*(\{.*?\});\s*\n", html, re.S)
    if not m and alt_names:
        pid = slug.rsplit("-", 1)[-1]
        for alt in alt_names:
            cand = f"{_slugify(alt)}-{pid}"
            if cand == slug:
                continue
            time.sleep(_SLEEP)
            try:
                html = _get(KTC_PLAYER.format(slug=cand))
            except Exception:
                continue
            m = re.search(r"playerSuperflex\s*=\s*(\{.*?\});\s*\n", html, re.S)
            if m:
                break
    if not m:
        return []
    try:
        blob = json.loads(m.group(1))
    except Exception:
        return []
    out: List[Tuple[str, float]] = []
    for row in blob.get("overallValue") or []:
        d = str(row.get("d") or "")
        v = row.get("v")
        if len(d) != 6 or v is None:
            continue
        iso = f"20{d[0:2]}-{d[2:4]}-{d[4:6]}"
        try:
            out.append((iso, float(v)))
        except Exception:
            continue
    out.sort()
    return out


# --------------------------------------------------------------------------
# name -> sleeper id
# --------------------------------------------------------------------------

def sleeper_name_map() -> Dict[str, str]:
    """full_name -> sleeper_id, from the committed players snapshot."""
    snap = ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json"
    data = json.loads(snap.read_text())
    out: Dict[str, str] = {}
    for sid, p in (data.items() if isinstance(data, dict) else []):
        nm = (p or {}).get("full_name")
        if nm:
            out.setdefault(nm, str(sid))
    return out


def resolve_slug(name: str, idx: Dict[str, Dict[str, str]],
                 want_pos: Optional[str] = None) -> Tuple[Optional[str], str]:
    """(slug, note). Only returns a slug when the choice is unambiguous."""
    if name in NAME_ALIASES:
        return NAME_ALIASES[name], "hand-resolved alias"
    cands = idx.get(name.lower())
    if not cands:
        return None, "no KTC entry for this name"
    if len(cands) == 1:
        return next(iter(cands)), "exact"
    if want_pos:
        same = [s for s, p in cands.items() if (p or "").upper() == want_pos.upper()]
        if len(same) == 1:
            return same[0], f"disambiguated by position {want_pos}"
    return None, f"ambiguous ({len(cands)} slugs: {', '.join(sorted(cands))})"


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------

def merge_player(sid: str, hist: List[Tuple[str, float]], apply: bool) -> Tuple[int, int]:
    """Merge into data/ktc_backfill/<sid>.json. Returns (added, existing)."""
    path = BACKFILL_DIR / f"{sid}.json"
    cur: Dict[str, float] = {}
    if path.exists():
        try:
            for row in json.loads(path.read_text()):
                d = (row.get("date") or "")[:10]
                v = row.get("sf_trade_value")
                if d and v is not None:
                    cur[d] = float(v)
        except Exception:
            cur = {}
    before = len(cur)
    added = 0
    keep_before = KEEP_BEFORE.isoformat()
    for d, v in hist:
        if d >= keep_before:      # the mirror covers this range; don't duplicate it
            continue
        if d not in cur:          # never overwrite an existing datapoint
            cur[d] = v
            added += 1
    if apply and added:
        BACKFILL_DIR.mkdir(parents=True, exist_ok=True)
        rows = [{"date": d, "sf_trade_value": cur[d]} for d in sorted(cur)]
        path.write_text(json.dumps(rows))
    return added, before


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write files (default: plan only)")
    ap.add_argument("--refresh-slugs", action="store_true", help="rebuild the slug index")
    ap.add_argument("--only", action="append", default=[], help="restrict to these player names")
    ap.add_argument("--needs", default=None, help="JSON file with the player-name list")
    args = ap.parse_args()

    if args.needs:
        names = json.loads(Path(args.needs).read_text())
    elif args.only:
        names = list(args.only)
    else:
        print("nothing to do: pass --needs <file.json> or --only <name>", file=sys.stderr)
        return 2
    if args.only:
        names = [n for n in names if n in set(args.only)]

    print(f"resolving {len(names)} player(s) against KTC ...")
    idx = build_slug_index(refresh=args.refresh_slugs)
    name2sid = sleeper_name_map()

    ok = skipped = 0
    total_added = 0
    unresolved: List[Tuple[str, str]] = []
    for i, nm in enumerate(sorted(names), 1):
        sid = name2sid.get(nm)
        if not sid:
            unresolved.append((nm, "no sleeper id"))
            skipped += 1
            continue
        slug, note = resolve_slug(nm, idx)
        if not slug:
            unresolved.append((nm, note))
            skipped += 1
            continue
        try:
            hist = fetch_history(slug, alt_names=[nm])
        except Exception as e:
            unresolved.append((nm, f"fetch failed: {e}"))
            skipped += 1
            continue
        time.sleep(_SLEEP)
        if not hist:
            unresolved.append((nm, f"no history on {slug}"))
            skipped += 1
            continue
        pre = [d for d, _ in hist if d < "2021-04-16"]
        added, before = merge_player(sid, hist, args.apply)
        total_added += added
        ok += 1
        print(f"{i:4d}. {nm:<26} {slug:<28} pts={len(hist):5d} "
              f"pre-floor={len(pre):4d} earliest={hist[0][0]} +{added} new (had {before})")

    print(f"\nresolved {ok}, skipped {skipped}, datapoints added {total_added}"
          f"{' (DRY RUN)' if not args.apply else ''}")
    if unresolved:
        print(f"\nunresolved ({len(unresolved)}) — handle individually:")
        for nm, why in unresolved:
            print(f"  {nm:<28} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
