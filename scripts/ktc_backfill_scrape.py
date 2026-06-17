#!/usr/bin/env python3
"""
One-time KTC.com historical SUPERFLEX value scrape (Phase 13 — KTC backfill).

WHY: dynasty-daddy (our live KTC source) only publishes per-player history back to
2021-04-16. KTC.com itself has daily values back to ~2020-04-01 — exactly the 2020
ESPN season + early-2021 window dynasty-daddy is missing. This script scrapes that
gap ONCE and commits it, so the build never has to scrape per run (mirrors
scripts/espn_dump_2020.py). Re-runnable to add more players (idempotent: skips any
sleeper_id already saved).

LEAGUE IS SUPERFLEX -> we take the SUPERFLEX value series only (the `overallValue`
array under `var playerSuperflex` on each KTC player page). 1QB is ignored.

CROSSWALK: KTC player pages need the exact name-slug ("christian-mccaffrey-283").
We map each Sleeper id -> KTC slug via the KTC dynasty-rankings page's playersArray
(which carries playerID + slug + mflid) joined to DynastyProcess db_playerids
(mfl_id <-> sleeper_id). Players not in KTC's current rankings (retired / off the
rolls) can't be resolved here and fall back to KTC=0 in the build (per the
"retired off the rolls -> 0" rule), so they don't need scraping.

OUTPUT: data/ktc_cache/backfill/<sleeper_id>.json
        = [{"date":"YYYY-MM-DD","sf_trade_value":<int>}, ...] ascending by date.

USAGE:
  python scripts/ktc_backfill_scrape.py            # scrape the 2020-relevant players
  python scripts/ktc_backfill_scrape.py --all-rankings   # scrape every active KTC player
  python scripts/ktc_backfill_scrape.py --sleeper 4034 167 ...   # specific ids
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RANK_URL = "https://keeptradecut.com/dynasty-rankings"
PLAYER_URL = "https://keeptradecut.com/dynasty-rankings/players/{slug}"
UA = "Mozilla/5.0 (LOTG-Stats KTC backfill; +https://github.com/Oliverwkw/LOTG-Stats)"
OUTDIR = REPO / "data" / "ktc_backfill"  # committed (data/ktc_cache/ is gitignored)


def _get(url: str) -> str:
    # Prefer `requests`: it streams the FULL response (no 1MB cap seen on some
    # curl builds / sandboxes) and negotiates modern TLS (older system Python +
    # LibreSSL urllib cannot reach KTC). Fall back to curl, then urllib.
    try:
        import requests  # type: ignore
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        return r.text
    except ImportError:
        pass
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["curl", "-sSL", "-A", UA, "--max-time", "60", url],
            capture_output=True, check=True,
        )
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.read().decode("utf-8", "replace")


def build_crosswalk() -> dict:
    """sleeper_id -> KTC slug, via KTC rankings (playerID/slug/mflid) + DP mfl<->sleeper."""
    html = _get(RANK_URL)
    arr = json.loads(re.search(r'var playersArray\s*=\s*(\[\{.*?\}\]);', html, re.S).group(1))
    import csv
    mfl2sleeper = {}
    with open(REPO / "data" / "ktc_cache" / "db_playerids.csv") as f:
        for row in csv.DictReader(f):
            mf = (row.get("mfl_id") or "").split(".")[0]
            sl = (row.get("sleeper_id") or "").split(".")[0]
            if mf and sl:
                mfl2sleeper[mf] = sl
    cross = {}
    for p in arr:
        mf = str(p.get("mflid") or "").split(".")[0]
        sl = mfl2sleeper.get(mf)
        if sl and p.get("slug"):
            cross[sl] = p["slug"]
    return cross


def _yymmdd_to_iso(d: str):
    if len(d) != 6 or not d.isdigit():
        return None
    return f"20{d[0:2]}-{d[2:4]}-{d[4:6]}"


def scrape_player_sf(slug: str) -> list:
    """Return [{'date': ISO, 'sf_trade_value': int}, ...] from the player's SF history."""
    html = _get(PLAYER_URL.format(slug=slug))
    sf_start = html.find("var playerSuperflex")
    oneqb_start = html.find("var playerOneQB")
    if sf_start < 0:
        return []
    region = html[sf_start: oneqb_start if oneqb_start > sf_start else sf_start + 4_000_000]
    m = re.search(r'"overallValue":(\[\{"d":"\d+","v":\d+\}(?:,\{"d":"\d+","v":\d+\})*\])', region)
    if not m:
        return []
    out = []
    for e in json.loads(m.group(1)):
        iso = _yymmdd_to_iso(e.get("d", ""))
        if iso is not None and e.get("v") is not None:
            out.append({"date": iso, "sf_trade_value": int(e["v"])})
    out.sort(key=lambda r: r["date"])
    return out


def _parse_players_array(html: str) -> list:
    """String-aware bracket match to extract `var playersArray = [...]`."""
    i = html.find("playersArray")
    if i < 0:
        return []
    start = html.find("[", i)
    depth = instr = esc = 0
    instr = False
    for j in range(start, len(html)):
        c = html[j]
        if esc:
            esc = False; continue
        if c == "\\":
            esc = True; continue
        if c == '"':
            instr = not instr; continue
        if instr:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:j + 1])
                except Exception:
                    return []
    return []


def scrape_wayback_retirees(sleeper_targets: set) -> dict:
    """Historical SUPERFLEX values for players NOT on KTC's current rolls (retired),
    pulled from Wayback Machine snapshots of KTC's dynasty-rankings page across
    2020-2021. Each snapshot's playersArray carries every then-ranked player's
    superflexValues.value at that date -> map by name+position to sleeper_id.

    Returns {sleeper_id: [{"date": ISO, "sf_trade_value": v}, ...]}.

    NOTE: Wayback's id_ raw endpoint can cap large 2020 snapshots at 1MB in some
    sandboxes (the array is then truncated/unparseable and skipped). Run in an
    unconstrained environment for full 2020 coverage.
    """
    import csv as _csv
    name_pos_to_sleeper = {}
    for r in _csv.DictReader(open(REPO / "data" / "ktc_cache" / "db_playerids.csv")):
        sl = (r.get("sleeper_id") or "").split(".")[0]
        nm = re.sub(r"[^a-z]", "", (r.get("name") or "").lower())
        ps = (r.get("position") or "").upper()
        if sl and nm:
            name_pos_to_sleeper[(nm, ps)] = sl
            name_pos_to_sleeper.setdefault((nm, ""), sl)  # position-agnostic fallback

    cdx = _get("http://web.archive.org/cdx/search/cdx?url=keeptradecut.com/dynasty-rankings"
               "&from=20200801&to=20211231&output=json&filter=statuscode:200&collapse=digest")
    snaps = []
    try:
        for row in json.loads(cdx)[1:]:
            snaps.append(row[1])  # timestamp
    except Exception:
        pass
    out = {}
    for ts in snaps:
        try:
            html = _get(f"http://web.archive.org/web/{ts}id_/https://keeptradecut.com/dynasty-rankings")
        except Exception:
            continue
        arr = _parse_players_array(html)
        if not arr:
            print(f"  wayback {ts}: unparseable (capped/truncated) — skipped")
            continue
        iso = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
        hit = 0
        for p in arr:
            nm = re.sub(r"[^a-z]", "", (p.get("playerName") or "").lower())
            ps = (p.get("position") or "").upper()
            sl = name_pos_to_sleeper.get((nm, ps)) or name_pos_to_sleeper.get((nm, ""))
            if not sl or sl not in sleeper_targets:
                continue
            sf = p.get("superflexValues")
            v = sf.get("value") if isinstance(sf, dict) else sf
            if v is None:
                continue
            out.setdefault(sl, {})[iso] = int(v)
            hit += 1
        print(f"  wayback {ts} ({iso}): {len(arr)} players, {hit} target hits")
        time.sleep(0.5)
    return {sl: [{"date": d, "sf_trade_value": v} for d, v in sorted(dates.items())]
            for sl, dates in out.items()}


def needed_2020_sleeper_ids() -> set:
    sys.path.insert(0, str(REPO / "src"))
    import espn_2020
    e = espn_2020.emit_sleeper_2020(espn_2020.load_espn_2020(str(REPO / "data" / "espn_2020_raw")))
    need = set()
    for p in e["draft_picks"]:
        if p.get("player_id"):
            need.add(str(p["player_id"]))
    for _wk, txs in e["transactions_by_week"].items():
        for t in txs:
            for pid in list(t.get("adds") or {}) + list(t.get("drops") or {}):
                need.add(str(pid))
    return need


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-rankings", action="store_true", help="scrape every active KTC player")
    ap.add_argument("--sleeper", nargs="*", default=None, help="specific sleeper ids")
    ap.add_argument("--sleep", type=float, default=0.7, help="seconds between fetches")
    ap.add_argument("--wayback", action="store_true",
                    help="backfill retirees (off current rolls) from Wayback rankings snapshots")
    args = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)

    if args.wayback:
        targets = set(args.sleeper) if args.sleeper else needed_2020_sleeper_ids()
        print(f"Wayback retiree backfill for {len(targets)} target players ...")
        hist_by_sid = scrape_wayback_retirees(targets)
        FLOOR = "2021-04-16"
        wrote = 0
        for sid, rows in hist_by_sid.items():
            out = OUTDIR / f"{sid}.json"
            existing = json.loads(out.read_text()) if out.exists() else []
            seen = {r["date"] for r in existing}
            merged = existing + [r for r in rows if r["date"] not in seen and r["date"] < FLOOR]
            merged.sort(key=lambda r: r["date"])
            if merged:
                out.write_text(json.dumps(merged))
                wrote += 1
        print(f"\nDONE (wayback). players written/updated: {wrote} -> {OUTDIR}")
        return

    print("Building sleeper->KTC-slug crosswalk from KTC rankings + DP db_playerids ...")
    cross = build_crosswalk()
    print(f"  crosswalk covers {len(cross)} active KTC players")

    if args.sleeper:
        targets = set(args.sleeper)
    elif args.all_rankings:
        targets = set(cross.keys())
    else:
        targets = needed_2020_sleeper_ids()
        print(f"  2020-relevant players needed: {len(targets)}")

    resolvable = [s for s in sorted(targets) if s in cross]
    unresolved = [s for s in sorted(targets) if s not in cross]
    print(f"  resolvable (in KTC rankings): {len(resolvable)} | unresolved (retired/off-rolls -> KTC=0): {len(unresolved)}")

    ok = skip = empty = err = 0
    for sid in resolvable:
        out = OUTDIR / f"{sid}.json"
        if out.exists():
            skip += 1
            continue
        try:
            hist = scrape_player_sf(cross[sid])
        except Exception as exc:
            err += 1
            print(f"  {sid} ({cross[sid]}): ERROR {type(exc).__name__}: {exc}")
            continue
        if not hist:
            empty += 1
            print(f"  {sid} ({cross[sid]}): no SF history extracted")
            continue
        out.write_text(json.dumps(hist))
        ok += 1
        if ok % 20 == 0:
            print(f"  ... {ok} saved")
        time.sleep(args.sleep)
    print(f"\nDONE. saved={ok} skipped(existing)={skip} empty={empty} errors={err} "
          f"unresolved={len(unresolved)} -> {OUTDIR}")


if __name__ == "__main__":
    main()
