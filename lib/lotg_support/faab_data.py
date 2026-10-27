"""External data for the FAAB value base: fetched into a git-ignored cache, never committed.

Sources (all public):
  - nflverse-data releases: weekly rosters, injury reports, play participation, PFR advanced stats, FTN charting,
    Next Gen Stats, combine, draft picks, players, schedules; and the player-stat / depth-chart / snap / contract
    files `faab_frame` reads (season and weekly stats, PPR).
  - ffverse/ffopportunity: expected fantasy points per player-week.
  - sportsdataverse-data: college player stats, rosters and ESPN usage (college usage share, breakout age).
  - Wikipedia (wikitext via the MediaWiki API): AP awards, All-Pro teams, Heisman and college position awards.
  - dynasty-daddy: KTC history per player (the stats translator's training scale; never an input).

Everything is skipped when already cached and non-empty, except the current season's files, which are refetched
when older than `max_age_days` (they change every week). Network errors are reported, never fatal: a source that
is not published yet (next season's files) is simply absent.

    python -c "from lotg_support import faab_data as D; D.fetch_all()"
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "faab"              # this module's downloads
FRAME_CACHE = ROOT / ".cache" / "ktc_proxy"   # the stats files faab_frame reads (shared with plan/notes/ktc_proxy)
NFLV = "https://github.com/nflverse/nflverse-data/releases/download"
FFO = "https://github.com/ffverse/ffopportunity/releases/download/latest-data"
SDV = "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags"
UA = "LOTG-Stats/1.0 (fantasy league stats; github.com/Oliverwkw/LOTG-Stats)"
FIRST_SEASON = 2014


def current_season(today=None):
    """the NFL season whose games are being played (or next to be, from March)"""
    import datetime as _dt
    t = today or _dt.date.today()
    return t.year if t.month >= 3 else t.year - 1


def _get(url, path, max_age_days=None, headers=None):
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        if max_age_days is None or (time.time() - path.stat().st_mtime) < max_age_days * 86400:
            return "cached"
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as e:  # not published yet, or a transient error: report and carry on
        return f"skip ({e.__class__.__name__}: {getattr(e, 'code', '')})"
    tmp = path.with_suffix(path.suffix + ".part"); tmp.write_bytes(data); tmp.replace(path)
    return "ok"


def _jobs_nflverse(last):
    j = []
    for y in range(2016, last + 1):
        age = 3 if y == last else None
        j += [(f"{FFO}/ep_weekly_{y}.parquet", CACHE / f"ep_weekly_{y}.parquet", age),
              (f"{NFLV}/weekly_rosters/roster_weekly_{y}.parquet", CACHE / f"roster_weekly_{y}.parquet", age),
              (f"{NFLV}/injuries/injuries_{y}.parquet", CACHE / f"injuries_{y}.parquet", age),
              (f"{NFLV}/pbp_participation/pbp_participation_{y}.parquet", CACHE / f"pbp_participation_{y}.parquet", age)]
    for y in range(2018, last + 1):
        age = 3 if y == last else None
        j += [(f"{NFLV}/pfr_advstats/advstats_week_{t}_{y}.parquet", CACHE / f"advstats_week_{t}_{y}.parquet", age) for t in ("pass", "rush", "rec", "def")]
    for y in range(2022, last + 1):
        j += [(f"{NFLV}/ftn_charting/ftn_charting_{y}.parquet", CACHE / f"ftn_charting_{y}.parquet", 3 if y == last else None)]
    j += [(f"{NFLV}/nextgen_stats/ngs_{t}.parquet", CACHE / f"ngs_{t}.parquet", 3) for t in ("passing", "receiving", "rushing")]
    j += [(f"{NFLV}/combine/combine.parquet", CACHE / "combine.parquet", 30), (f"{NFLV}/draft_picks/draft_picks.parquet", CACHE / "draft_picks.parquet", 30),
          (f"{NFLV}/players/players.parquet", CACHE / "players.parquet", 7), (f"{NFLV}/schedules/games.parquet", CACHE / "games.parquet", 3)]
    # the frame's stat files (same names plan/notes/ktc_proxy uses)
    for y in range(FIRST_SEASON, last + 1):
        age = 3 if y == last else None
        j += [(f"{NFLV}/stats_player/stats_player_reg_{y}.csv", FRAME_CACHE / f"sp_{y}.csv", age),
              (f"{NFLV}/stats_player/stats_player_week_{y}.csv", FRAME_CACHE / f"wk_{y}.csv", age),
              (f"{NFLV}/depth_charts/depth_charts_{y}.csv", FRAME_CACHE / f"dc_{y}.csv", age),
              (f"{NFLV}/snap_counts/snap_counts_{y}.csv", FRAME_CACHE / f"snap_{y}.csv", age)]
    j += [(f"{NFLV}/contracts/historical_contracts.parquet", FRAME_CACHE / "contracts.parquet", 7)]
    return j


def fetch_nflverse(last=None, workers=8, log=print):
    last = last or current_season()
    jobs = _jobs_nflverse(last)
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda a: (a[1].name, _get(*a)), jobs))
    bad = [(n, s) for n, s in res if s.startswith("skip")]
    log(f"nflverse/ffopportunity: {sum(s == 'ok' for _, s in res)} fetched, {sum(s == 'cached' for _, s in res)} cached, {len(bad)} skipped")
    return bad


def fetch_college(log=print):
    """sportsdataverse college player stats, rosters and ESPN usage (one release per table)"""
    n = 0
    for tag in ("ncaa_mfb_player_stats", "ncaa_mfb_rosters", "espn_cfb_usage_players"):
        try:
            req = urllib.request.Request(f"{SDV}/{tag}", headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
            assets = json.load(urllib.request.urlopen(req, timeout=60))["assets"]
        except Exception as e:
            log(f"college {tag}: skip ({e})"); continue
        for a in assets:
            if a["name"].endswith(".parquet"):
                s = _get(a["browser_download_url"], CACHE / "cfb" / a["name"], max_age_days=30)
                n += s == "ok"
    log(f"college: {n} fetched")


WIKI_PAGES = (["AP_NFL_Most_Valuable_Player", "AP_NFL_Offensive_Player_of_the_Year", "AP_NFL_Offensive_Rookie_of_the_Year",
               "AP_NFL_Comeback_Player_of_the_Year", "List_of_Heisman_Trophy_winners", "Biletnikoff_Award", "Doak_Walker_Award",
               "John_Mackey_Award", "Davey_O'Brien_Award", "Maxwell_Award", "Walter_Camp_Award"])


def wiki_pages(last):
    return WIKI_PAGES + [f"{y}_All-Pro_Team" for y in range(2012, last)] + [f"{y}_Heisman_Trophy" for y in range(2012, last + 1)]


def fetch_wiki(last=None, log=print):
    """wikitext of each award page (polite: one request at a time, backing off on 429)"""
    last = last or current_season()
    got = 0
    for p in wiki_pages(last):
        f = CACHE / "wiki" / (p.replace("/", "_").replace("'", "_") + ".json")
        if f.exists() and f.stat().st_size > 0 and (time.time() - f.stat().st_mtime) < 30 * 86400:
            continue
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(dict(action="parse", page=p, prop="wikitext", format="json", redirects=1))
        for t in range(4):
            s = _get(url, f, max_age_days=0)
            if s == "ok" or "404" in s: break
            time.sleep(10 * (t + 1))
        got += s == "ok"
        time.sleep(1.0)
    log(f"wikipedia: {got} pages fetched")


def fetch_ktc(workers=8, log=print):
    """dynasty-daddy's per-player KTC history for every QB/RB/WR/TE in today's directory (the translator's scale).
    Reuses lotg_support.ktc's cache (data/ktc_cache/, git-ignored) so the build and this share one copy."""
    sys.path.insert(0, str(ROOT / "lib"))
    from lotg_support import ktc as K
    d = K.load_directory(ROOT)
    ids = [p["name_id"] for p in d if p.get("position") in ("QB", "RB", "WR", "TE") and p.get("name_id")]
    K.prefetch_histories(ROOT, ids)
    log(f"ktc: {len(ids)} player histories ready")
    return ids


def fetch_all(last=None, log=print):
    bad = fetch_nflverse(last, log=log)
    fetch_college(log=log)
    fetch_wiki(last, log=log)
    fetch_ktc(log=log)
    return bad


if __name__ == "__main__":
    fetch_all()
