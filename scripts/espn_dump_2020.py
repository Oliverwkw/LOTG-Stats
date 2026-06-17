#!/usr/bin/env python3
"""
One-time ESPN 2020 dump for LOTG-Stats (Phase 13).

The league's first season (2020) lived on ESPN (leagueId 34086) before moving to
Sleeper. This script — run ONCE by the league commissioner (who still has access) —
saves the entire 2020 season as raw JSON so the build can hardcode it and never
scrape again.

WHO RUNS THIS: the commissioner (or anyone with access to the league). The data is
authorized off YOUR ESPN login, so the rest of us never need visibility into the
league.

SETUP (about 2 minutes):
  1) Install the one dependency:        pip install requests
  2) Get your two ESPN cookies (private-league auth). In a desktop browser:
       - Log in to https://fantasy.espn.com and open the league.
       - Open DevTools (F12) -> Application/Storage -> Cookies -> fantasy.espn.com
       - Copy the VALUES of:   espn_s2     and     SWID
         (SWID looks like {AAAA-BBBB-...}; keep the curly braces.)
  3) Run it (paste the cookies when prompted, or pass as flags/env vars):
       python espn_dump_2020.py
     or
       python espn_dump_2020.py --espn_s2 "AABB..." --swid "{XXXX-...}"
     or set ESPN_S2 / ESPN_SWID env vars.

OUTPUT: a folder `espn_2020_dump/` plus `espn_2020_dump.zip`. Send the .zip back.

If the league happens to be PUBLIC, you can run with no cookies at all.

Nothing is written anywhere except the local output folder. No data leaves your
machine except the .zip you choose to send.
"""

import argparse
import json
import os
import sys
import time
import zipfile

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

LEAGUE_ID = 34086
SEASON = 2020
HOST = "https://lm-api-reads.fantasy.espn.com"
BASE = f"{HOST}/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}"

# Season-level views (one request grabs all of them; we also fetch each alone as a
# fallback in case the combined call drops one). These are the "safe" views that
# need no x-fantasy-filter header — keeping risky/filtered views out of the combined
# call so one bad view can't error the whole response. (kona_player_info needs a
# filter header and is fetched separately below; mBoxscore matters per-week, below.)
SEASON_VIEWS = [
    "mSettings",        # scoring, roster slots, schedule, playoff structure
    "mTeam",            # teams + owners (member ids) + records/standings
    "mRoster",          # latest rosters (per-week handled separately below)
    "mMatchup",         # full schedule + scores (pointsByScoringPeriod)
    "mMatchupScore",    # matchup scores
    "mStandings",       # final standings / playoff seeds
    "mDraftDetail",     # the startup draft (player, team, round, pick, keeper)
    "mTransactions2",   # adds / drops / trades / waivers
    "mPositionalRatings",
]

# Per-week views: request with &scoringPeriodId=N to get that week's lineups
# (lineupSlotId distinguishes starter vs bench) and applied points per player.
WEEK_VIEWS = ["mMatchup", "mMatchupScore", "mRoster", "mBoxscore"]
# 2020 = 16-week season (reg 1-14, playoffs 15-16). Pull a generous range and skip
# anything that comes back empty so we never miss a week.
WEEK_RANGE = range(1, 19)

OUTDIR = "espn_2020_dump"


def _swid(s: str) -> str:
    s = (s or "").strip()
    if s and not s.startswith("{"):
        s = "{" + s.strip("{}") + "}"
    return s


def make_session(espn_s2: str, swid: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (LOTG-Stats espn_dump_2020)",
        "Accept": "application/json",
    })
    if espn_s2 and swid:
        s.cookies.set("espn_s2", espn_s2)
        s.cookies.set("SWID", _swid(swid))
    return s


def get(session, params=None, extra_headers=None, path="", tries=5):
    """GET BASE(+path) with retry/backoff. Returns parsed JSON or raises."""
    url = BASE + path
    last = None
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, headers=extra_headers or {}, timeout=45)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise SystemExit(
                    f"\nAccess denied ({r.status_code}). The league is private and the "
                    "cookies were missing/expired/wrong.\n"
                    "Re-copy espn_s2 and SWID from a logged-in browser (SWID needs its "
                    "curly braces) and run again.\n"
                )
            if r.status_code == 404:
                # not-found for a week view = that week doesn't exist; signal soft-skip
                return None
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))  # backoff; also eases ESPN rate limits
    raise RuntimeError(f"Failed after {tries} tries: {url}  ({last})")


def save(obj, name):
    path = os.path.join(OUTDIR, name)
    with open(path, "w") as f:
        json.dump(obj, f)
    return path


def dump_transactions(session, weeks):
    """Full season transaction log (adds / drops / waivers / TRADES / draft).

    The season-level mTransactions2 view only returns a tiny recent slice, so we
    pull mTransactions2 PER scoringPeriod and dedupe by id — that returns the
    complete history (proposals, accepts, vetoes, upholds, waivers, FAs, etc.).
    Saved consolidated to transactions_all.json."""
    by_id = {}
    for wk in weeks:
        try:
            data = get(session, params=[("view", "mTransactions2"), ("scoringPeriodId", wk)])
        except Exception:
            continue
        for t in (data or {}).get("transactions", []) if isinstance(data, dict) else []:
            tid = t.get("id")
            if tid is not None:
                by_id[tid] = t
        time.sleep(0.4)
    txns = list(by_id.values())
    if txns:
        save({"transactions": txns}, "transactions_all.json")
    types = {}
    for t in txns:
        types[t.get("type")] = types.get(t.get("type"), 0) + 1
    return len(txns), types


def dump_player_universe(session):
    """Best-effort full player universe (names/position/proTeam/eligibleSlots).
    Needs an x-fantasy-filter header or ESPN rejects it. NOT essential — every
    rostered player's full object is already embedded in the per-week rosters —
    so failure here is harmless."""
    flt = {"players": {"limit": 2000,
                       "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
    try:
        data = get(session, params={"view": "kona_player_info"},
                   extra_headers={"x-fantasy-filter": json.dumps(flt)})
        if data is not None:
            save(data, "player_universe.json")
            n = len(data.get("players", [])) if isinstance(data, dict) else 0
            return n
    except Exception as e:
        print(f"    player universe: SKIPPED ({e}) — players are embedded in rosters anyway")
    return 0


def main():
    ap = argparse.ArgumentParser(description="One-time ESPN 2020 dump for LOTG-Stats")
    ap.add_argument("--espn_s2", default=os.environ.get("ESPN_S2", ""))
    ap.add_argument("--swid", default=os.environ.get("ESPN_SWID", ""))
    ap.add_argument("--leagueId", type=int, default=LEAGUE_ID)
    ap.add_argument("--season", type=int, default=SEASON)
    args = ap.parse_args()

    global BASE
    BASE = f"{HOST}/apis/v3/games/ffl/seasons/{args.season}/segments/0/leagues/{args.leagueId}"

    espn_s2, swid = args.espn_s2, args.swid
    if not espn_s2 and not swid:
        print("Private leagues need cookies. Leave BOTH blank only if the league is public.")
        espn_s2 = input("  espn_s2  (Enter to skip): ").strip()
        swid = input("  SWID     (Enter to skip): ").strip()

    os.makedirs(OUTDIR, exist_ok=True)
    session = make_session(espn_s2, swid)

    print(f"\nLeague {args.leagueId}, season {args.season}")
    print("Auth:", "cookies provided" if (espn_s2 and swid) else "NONE (assuming public)")

    # 1) One combined season-level request (all views at once).
    print("\n[1/5] Season-level views (combined) ...")
    combined = get(session, params=[("view", v) for v in SEASON_VIEWS])
    if combined is not None:
        save(combined, "league_combined.json")
        # quick sanity
        teams = combined.get("teams", []) if isinstance(combined, dict) else []
        members = combined.get("members", []) if isinstance(combined, dict) else []
        draft = (combined.get("draftDetail") or {}).get("picks", []) if isinstance(combined, dict) else []
        sched = combined.get("schedule", []) if isinstance(combined, dict) else []
        print(f"    teams={len(teams)} members={len(members)} draftPicks={len(draft)} matchups={len(sched)}")

    # 2) Each season view individually (fallback so nothing is silently dropped).
    print("[2/5] Season-level views (individual fallbacks) ...")
    for v in SEASON_VIEWS:
        try:
            data = get(session, params={"view": v})
            if data is not None:
                save(data, f"view_{v}.json")
                print(f"    {v}: ok")
        except Exception as e:
            print(f"    {v}: SKIPPED ({e})")
        time.sleep(0.5)

    # 3) Per-week lineups/boxscores (who started + weekly points).
    print("[3/5] Per-week rosters & boxscores ...")
    weeks_got = []
    for wk in WEEK_RANGE:
        params = [("view", v) for v in WEEK_VIEWS] + [("scoringPeriodId", wk)]
        try:
            data = get(session, params=params)
        except Exception as e:
            print(f"    week {wk}: error ({e})")
            continue
        if data is None:
            continue
        sched = data.get("schedule", []) if isinstance(data, dict) else []
        # only keep weeks that actually have lineup data
        save(data, f"week_{wk:02d}.json")
        weeks_got.append(wk)
        print(f"    week {wk}: ok ({len(sched)} matchups in schedule)")
        time.sleep(0.8)
    print(f"    weeks saved: {weeks_got}")

    # 4) Full transaction log (per-week mTransactions2, deduped).
    print("[4/5] Transactions (per-week mTransactions2) ...")
    try:
        n, types = dump_transactions(session, WEEK_RANGE)
        print(f"    transactions saved: {n}  types={types}")
    except Exception as e:
        print(f"    transactions: SKIPPED ({e}) — season-level mTransactions2 still captured above")

    # 5) Player universe (best-effort; players are also embedded in rosters).
    print("[5/5] Player universe (best-effort) ...")
    pu = dump_player_universe(session)
    print(f"    players saved: {pu}")

    # manifest
    save({
        "leagueId": args.leagueId, "season": args.season,
        "season_views": SEASON_VIEWS, "week_views": WEEK_VIEWS,
        "weeks_saved": weeks_got, "host": HOST,
    }, "_manifest.json")

    # zip it up for easy sending
    zip_path = OUTDIR + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(OUTDIR)):
            z.write(os.path.join(OUTDIR, fn), arcname=os.path.join(OUTDIR, fn))

    print(f"\nDONE. Wrote folder '{OUTDIR}/' and '{zip_path}'.")
    print("Send the .zip back. Nothing else left your machine.")


if __name__ == "__main__":
    main()
