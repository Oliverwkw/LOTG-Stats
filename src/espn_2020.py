"""
ESPN 2020 loader (Phase 13).

Parses the one-time ESPN dump in `data/espn_2020_raw/` (leagueId 34086, season
2020 — the league's first year, before Sleeper) into NORMALIZED per-season
structures the main build can fold in as the new earliest season.

Design: translate ESPN's shapes into the same vocabulary the Sleeper pipeline
already speaks (roster_id 1..8 per team, per-week starters/bench/points,
transactions as add/drop/trade, a draft) so `lotg.py` can consume 2020 like any
other season. Join ESPN playerId -> our player identity via the DynastyProcess
`espn_id` column (gsis_id / sleeper_id / name / position).

This module is import-safe and has a `__main__` self-test that validates the parse
against known facts (8 teams, 152 picks = 19 rounds, 16 weeks, and a known
email-confirmed trade).
"""

from __future__ import annotations

import csv
import glob
import html
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

LEAGUE_ID = 34086
SEASON = 2020
RAW_DIR_DEFAULT = os.path.join(os.path.dirname(__file__), "..", "data", "espn_2020_raw")
DP_IDS_DEFAULT = os.path.join(os.path.dirname(__file__), "..",
                              "exports", "snapshot", "dynastyprocess_playerids.csv")

# Verified teamId -> current manager (see plan/notes/espn_2020_backfill.md).
# Join on teamId/owner, NEVER team name (names were changed repeatedly mid-2020).
TEAM_TO_MANAGER = {
    1: "stevenb123",
    2: "shmuel256",
    3: "LWebs53",
    4: "BROsenzweig",
    5: "Oliverwkw",
    6: "JacobRosenzweig",
    7: "AceMatthew",
    8: "plehv79",
}

# Sleeper assigns each manager a stable roster_id (1..8) reused across every
# 2021+ season; ESPN used its own teamId 1..8 for the same managers in 2020 (a
# DIFFERENT ordering — e.g. LWebs53 is ESPN teamId 3 but Sleeper roster 6). Emit
# 2020 roster_ids in the SLEEPER space so an asset (a draft pick or player) that
# moves across the 2020<->2021 boundary keeps ONE consistent roster identity:
# the pick-ownership ledger keys on roster_id, so a 2021+ pick traded in a 2020
# deal must resolve to the same roster integer in both seasons. Display is
# unaffected — every sheet resolves roster_id -> manager via the per-season map.
SLEEPER_ROSTER_ID_BY_MANAGER = {
    "stevenb123": 1, "JacobRosenzweig": 2, "AceMatthew": 3, "BROsenzweig": 4,
    "plehv79": 5, "LWebs53": 6, "Oliverwkw": 7, "shmuel256": 8,
}
# ESPN teamId -> Sleeper roster_id, for the managers above.
ESPN_TO_SLEEPER_RID = {tid: SLEEPER_ROSTER_ID_BY_MANAGER[mgr]
                       for tid, mgr in TEAM_TO_MANAGER.items()}


def _rid(espn_team_id):
    """Map an ESPN teamId to the manager's stable Sleeper roster_id."""
    return ESPN_TO_SLEEPER_RID.get(espn_team_id, espn_team_id)

# ESPN lineupSlotId: starters are everything except bench(20)/IR(21).
BENCH_SLOTS = {20, 21}
SLOT_NAME = {
    0: "QB", 1: "TQB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE",
    7: "OP", 16: "D/ST", 17: "K", 20: "BE", 21: "IR", 23: "FLEX",
}
# ESPN defaultPositionId -> our position label.
POS_NAME = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
# ESPN proTeamId -> NFL abbrev (2020 map; WSH/OAK->LV etc.).
PRO_TEAM = {
    0: None, 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}


# --------------------------------------------------------------------------- #
# raw loading
# --------------------------------------------------------------------------- #
def _load(raw_dir: str, name: str) -> Any:
    with open(os.path.join(raw_dir, name)) as f:
        return json.load(f)


def load_raw(raw_dir: str = RAW_DIR_DEFAULT) -> Dict[str, Any]:
    """Load the dump's JSON files into a dict of parsed views + per-week files."""
    raw_dir = os.path.abspath(raw_dir)
    out: Dict[str, Any] = {"_dir": raw_dir}
    out["settings"] = _load(raw_dir, "view_mSettings.json").get("settings", {})
    out["teams"] = _load(raw_dir, "view_mTeam.json")
    out["draft"] = _load(raw_dir, "view_mDraftDetail.json").get("draftDetail", {})
    out["matchup"] = _load(raw_dir, "view_mMatchup.json").get("schedule", [])
    out["transactions"] = _load(raw_dir, "transactions_all.json").get("transactions", [])
    # Optional/heavy files — not needed once player_id_map.csv is baked (trimmed
    # out of the committed dump to keep CI small).
    for opt in ("league_combined.json", "player_universe.json"):
        try:
            key = "combined" if "combined" in opt else "player_universe"
            data = _load(raw_dir, opt)
            out[key] = data.get("players", data) if key == "player_universe" else data
        except FileNotFoundError:
            out[key] = [] if key == "player_universe" else {}
    weeks = {}
    for wf in sorted(glob.glob(os.path.join(raw_dir, "week_*.json"))):
        wk = int(os.path.basename(wf).split("_")[1].split(".")[0])
        weeks[wk] = json.load(open(wf))
    out["weeks"] = weeks
    return out


# --------------------------------------------------------------------------- #
# player identity bridge: ESPN playerId -> {gsis_id, sleeper_id, name, position}
# --------------------------------------------------------------------------- #
def _clean_id(x: Any) -> Optional[str]:
    """Sleeper player ids are integer strings ('6007'). The committed
    player_id_map.csv stores them as float-strings ('6007.0') because the map was
    serialized from a pandas float column. A '6007.0' key matches NOTHING in the
    build's pid_meta / players_nfl, so names, positions, ages, Max PF and KTC all
    silently break for 2020. Normalize to a bare integer string."""
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def build_player_bridge(raw: Dict[str, Any], dp_path: str = DP_IDS_DEFAULT) -> Dict[int, Dict[str, Any]]:
    """ESPN playerId -> identity. Prefer the committed, pre-resolved
    `data/espn_2020_raw/player_id_map.csv` (so the build is self-contained and does
    NOT depend on the DP file being downloaded yet at injection time). If that map is
    absent (local dev), fall back to DynastyProcess espn_id + the ESPN player objects."""
    baked = os.path.join(raw.get("_dir", "."), "player_id_map.csv")
    if os.path.exists(baked):
        bridge: Dict[int, Dict[str, Any]] = {}
        for r in csv.DictReader(open(baked)):
            pid = int(r["espn_id"])
            bridge[pid] = {"espn_id": pid,
                           "sleeper_id": _clean_id(r.get("sleeper_id")),
                           "gsis_id": r.get("gsis_id") or None,
                           "name": r.get("name") or None,
                           "position": r.get("position") or None,
                           "nfl_team": r.get("nfl_team") or None}
        return bridge
    dp_by_espn: Dict[str, Dict[str, str]] = {}
    if os.path.exists(dp_path):
        for r in csv.DictReader(open(dp_path)):
            eid = (r.get("espn_id") or "").strip()
            if eid:
                # DP stores espn_id as float-like "12345.0" sometimes
                eid = eid.split(".")[0]
                dp_by_espn[eid] = r
    # ESPN player objects (from the universe + embedded roster objects) for fallback
    espn_player: Dict[int, Dict[str, Any]] = {}
    for p in raw.get("player_universe", []):
        pl = p.get("player", p)
        pid = p.get("id") or pl.get("id")
        if pid is not None:
            espn_player[int(pid)] = pl
    bridge: Dict[int, Dict[str, Any]] = {}
    seen = set(espn_player) | {int(float(k)) for k in dp_by_espn}
    for pid in seen:
        dp = dp_by_espn.get(str(pid))
        pl = espn_player.get(pid, {})
        bridge[pid] = {
            "espn_id": pid,
            "gsis_id": (dp or {}).get("gsis_id") or None,
            "sleeper_id": _clean_id((dp or {}).get("sleeper_id")),
            "name": (dp or {}).get("name") or pl.get("fullName"),
            "position": (dp or {}).get("position") or POS_NAME.get(pl.get("defaultPositionId")),
            "nfl_team": PRO_TEAM.get(pl.get("proTeamId")) if pl else None,
        }
    return bridge


# --------------------------------------------------------------------------- #
# draft
# --------------------------------------------------------------------------- #
def parse_draft(raw: Dict[str, Any], bridge: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    picks = []
    for p in raw["draft"].get("picks", []):
        pid = p.get("playerId")
        ident = bridge.get(pid, {})
        picks.append({
            "round": p.get("roundId"),
            "pick_in_round": p.get("roundPickNumber"),
            "overall": p.get("overallPickNumber"),
            "team_id": p.get("teamId"),
            "manager": TEAM_TO_MANAGER.get(p.get("teamId")),
            "keeper": p.get("keeper", False),
            "espn_player_id": pid,
            "player": ident.get("name"),
            "gsis_id": ident.get("gsis_id"),
            "sleeper_id": ident.get("sleeper_id"),
            "position": ident.get("position"),
        })
    return picks


# --------------------------------------------------------------------------- #
# weekly lineups + matchups (who started, points, opponent, team PF)
# --------------------------------------------------------------------------- #
def _applied_points(player_obj: Dict[str, Any], week: int) -> Optional[float]:
    """The week's actual fantasy points = the player's real stat line
    (statSourceId 0) for that scoringPeriod with the single-week split (statSplitTypeId 1)."""
    best = None
    for s in player_obj.get("stats", []):
        if s.get("scoringPeriodId") == week and s.get("statSourceId") == 0:
            # statSplitTypeId 1 == single scoring period (vs 0 = season-to-date)
            if s.get("statSplitTypeId") in (1, None):
                return s.get("appliedTotal")
            best = s.get("appliedTotal") if best is None else best
    return best


def parse_weeks(raw: Dict[str, Any], bridge: Dict[int, Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """-> {week: [ per-team dict with team_id, manager, opponent, pf, starters[], bench[] ]}."""
    out: Dict[int, List[Dict[str, Any]]] = {}
    for wk, data in raw["weeks"].items():
        rows = []
        for m in data.get("schedule", []):
            if m.get("matchupPeriodId") != wk:
                continue
            sides = [("home", "away"), ("away", "home")]
            for me, opp in sides:
                s = m.get(me)
                o = m.get(opp)
                if not s:
                    continue
                pf = (s.get("pointsByScoringPeriod") or {}).get(str(wk))
                entries = (s.get("rosterForCurrentScoringPeriod") or {}).get("entries", [])
                starters, bench = [], []
                for e in entries:
                    pl = (e.get("playerPoolEntry") or {}).get("player", {})
                    pid = e.get("playerId") or pl.get("id")
                    ident = bridge.get(pid, {})
                    rec = {
                        "espn_player_id": pid,
                        "player": ident.get("name") or pl.get("fullName"),
                        "gsis_id": ident.get("gsis_id"),
                        "sleeper_id": ident.get("sleeper_id"),
                        "position": ident.get("position") or POS_NAME.get(pl.get("defaultPositionId")),
                        "lineup_slot": e.get("lineupSlotId"),
                        "slot_name": SLOT_NAME.get(e.get("lineupSlotId")),
                        "points": _applied_points(pl, wk),
                    }
                    (bench if e.get("lineupSlotId") in BENCH_SLOTS else starters).append(rec)
                rows.append({
                    "week": wk,
                    "team_id": s.get("teamId"),
                    "manager": TEAM_TO_MANAGER.get(s.get("teamId")),
                    "opponent_team_id": (o or {}).get("teamId"),
                    "opponent_manager": TEAM_TO_MANAGER.get((o or {}).get("teamId")),
                    "pf": pf,
                    "starters": starters,
                    "bench": bench,
                })
        out[wk] = rows
    return out


# --------------------------------------------------------------------------- #
# transactions (adds/drops + executed trades = TRADE_UPHOLD only)
# --------------------------------------------------------------------------- #
def parse_transactions(raw: Dict[str, Any], bridge: Dict[int, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """-> {'moves': [adds/drops], 'trades': [executed trades]}.
    Executed trades are TRADE_UPHOLD only (vetoes/declines/proposals excluded, per
    league rule — accepted-then-vetoed trades did not happen)."""
    moves, trades = [], []
    for t in raw["transactions"]:
        ttype = t.get("type")
        items = t.get("items", [])
        def ident(pid):
            b = bridge.get(pid, {})
            return {"espn_player_id": pid, "player": b.get("name"),
                    "gsis_id": b.get("gsis_id"), "sleeper_id": b.get("sleeper_id"),
                    "position": b.get("position")}
        if ttype in ("FREEAGENT", "WAIVER", "ROSTER"):
            # ROSTER = a direct roster move (manual cut / pre-season drop), e.g.
            # Devine Ozigbo drafted then cut before week 1, or Tyrell Williams cut
            # mid-season. These carry real ADD/DROP items (plus LINEUP items, which
            # are bench/start changes, not roster moves) but were previously skipped
            # entirely — so ~27 genuine 2020 drops were missing, leaving those
            # players' adds dangling (no drop -> teleport) and pre-week-1 cuts with
            # no record at all. Treated like a free-agency move downstream.
            # Only EXECUTED claims actually moved players. ESPN logs every waiver
            # claim as its own transaction — including the PENDING duplicates that
            # were superseded, the FAILED ones (e.g. FAILED_PLAYERALREADYDROPPED),
            # and CANCELED ones. Each carries an intended drop leg, so without this
            # filter a player reads as dropped many times but never added (e.g. Jalen
            # Richard: 1 EXECUTED drop + 2 PENDING + 1 FAILED = 4 phantom drops). Keep
            # only status == EXECUTED. (31 of 211 FA/waiver records are non-executed.)
            if t.get("status") != "EXECUTED":
                continue
            # ONE move per ESPN transaction (not per item). ESPN bundles a pickup and
            # the player it drops to make room into a single transaction (most executed
            # FA/waiver moves are such add+drop swaps); emitting each item as its own
            # add-only / drop-only Sleeper transaction was wrong — it both doubled the
            # transaction count and made every row read as "just an add" or "just a
            # drop". Group the items so a swap becomes one tx with both an add and drop,
            # matching Sleeper's own shape.
            add_pids = [it.get("playerId") for it in items if it.get("type") == "ADD"]
            drop_pids = [it.get("playerId") for it in items if it.get("type") == "DROP"]
            # Skip lineup-only ROSTER transactions (start/bench changes carry only
            # LINEUP items, no actual add or drop).
            if not add_pids and not drop_pids:
                continue
            team_id = None
            for it in items:
                team_id = it.get("toTeamId") if it.get("type") == "ADD" else it.get("fromTeamId")
                if team_id is not None:
                    break
            moves.append({
                "date": t.get("proposedDate"),
                "scoring_period": t.get("scoringPeriodId"),
                "kind": ttype,            # no FAAB in 2020 -> bidAmount always 0
                "team_id": team_id,
                "manager": TEAM_TO_MANAGER.get(team_id),
                "add_pids": add_pids,
                "drop_pids": drop_pids,
            })
        elif ttype == "TRADE_ACCEPT":
            # Accepting a trade can bundle an incidental DROP (a player cut to make
            # roster room for the incoming players; fromTeam -> team 0/waivers)
            # alongside the TRADE legs. The legs are recorded via TRADE_UPHOLD; here
            # we capture only the EXECUTED incidental DROP so the dropped player's
            # prior add closes — otherwise it dangles and mis-binds to a far-future
            # departure (e.g. Mike Williams' 2020 add was closing at 2024). TRADE
            # items are ignored. The dropping team is the DROP item's fromTeamId (the
            # trade legs involve other teams, so don't infer team from item order).
            if t.get("status") != "EXECUTED":
                continue
            drop_pids = [it.get("playerId") for it in items if it.get("type") == "DROP"]
            if not drop_pids:
                continue
            team_id = next((it.get("fromTeamId") for it in items if it.get("type") == "DROP"), None)
            moves.append({
                "date": t.get("proposedDate"),
                "scoring_period": t.get("scoringPeriodId"),
                "kind": "TRADE_ACCEPT",
                "team_id": team_id,
                "manager": TEAM_TO_MANAGER.get(team_id),
                "add_pids": [],
                "drop_pids": drop_pids,
            })
        elif ttype == "TRADE_UPHOLD":
            legs = []
            for it in items:
                legs.append({
                    "from_team_id": it.get("fromTeamId"),
                    "from_manager": TEAM_TO_MANAGER.get(it.get("fromTeamId")),
                    "to_team_id": it.get("toTeamId"),
                    "to_manager": TEAM_TO_MANAGER.get(it.get("toTeamId")),
                    **ident(it.get("playerId")),
                })
            trades.append({
                "date": t.get("proposedDate"),
                "scoring_period": t.get("scoringPeriodId"),
                "teams": sorted({l["from_manager"] for l in legs if l["from_manager"]}
                                | {l["to_manager"] for l in legs if l["to_manager"]}),
                "legs": legs,
            })
    return {"moves": moves, "trades": trades}


# --------------------------------------------------------------------------- #
# TRADE LAYER (from the saved ESPN trade emails)
# ESPN exposes a trade's player legs only on the private TRADE_PROPOSAL (visible
# to the two teams), so one manager's pull can't see every trade's players. The
# emails carry the full legs for all leagueId-34086 trades. We resolve each emailed
# player to the exact ESPN playerId by ROSTER MOVEMENT (the player who actually
# changed hands that week) — robust to name suffixes (II/Jr/V), name changes
# (Robby Anderson -> Robbie Chosen), and same-name collisions (two David Johnsons).
# Executed trades only: the lone VETOED email is dropped ("track upheld").
# --------------------------------------------------------------------------- #
_SUFFIX = re.compile(r'\b(?:jr|sr|ii|iii|iv|v)\b\.?', re.I)
# Players who changed their name after 2020 (emails use the 2020 name; the DP/bridge
# uses the current name). Map 2020-name -> current-name (normalized).
_NAME_ALIAS = {
    "robbyanderson": "robbiechosen",
}


def _nrm(s: str) -> str:
    k = re.sub(r'[^a-z]', '', _SUFFIX.sub('', (s or '')).lower())
    return _NAME_ALIAS.get(k, k)


def _ownership(weeks: Dict[int, List[Dict[str, Any]]]) -> Dict[int, Dict[int, str]]:
    """espn_player_id -> {week: manager} across full roster membership."""
    own: Dict[int, Dict[int, str]] = {}
    for wk in sorted(weeks):
        for r in weeks[wk]:
            for p in r["starters"] + r["bench"]:
                own.setdefault(p["espn_player_id"], {})[wk] = r["manager"]
    return own


def parse_email_trades(loaded: Dict[str, Any], downloads: str = "~/Downloads") -> List[Dict[str, Any]]:
    import email as _email
    import quopri
    weeks, bridge = loaded["weeks"], loaded["_bridge"]
    own = _ownership(weeks)
    name_to_ids: Dict[str, List[int]] = defaultdict(list)
    for pid, b in bridge.items():
        if b.get("name"):
            name_to_ids[_nrm(b["name"])].append(pid)

    def changes_at(pid):
        """weeks where pid's owner differs from the prior rostered week -> (week, from, to)."""
        tl = own.get(pid, {})
        wks = sorted(tl)
        out = []
        for i, wk in enumerate(wks):
            if i == 0:
                out.append((wk, None, tl[wk]))
            elif tl[wk] != tl[wks[i - 1]] or wk != wks[i - 1] + 1:
                out.append((wk, tl[wks[i - 1]], tl[wk]))
        return out

    trades = []
    for fn in sorted(glob.glob(os.path.join(os.path.expanduser(downloads), "A Trade*.eml"))):
        raw = open(fn, "rb").read()
        msg = _email.message_from_bytes(raw)
        if "vetoed" in (msg.get("Subject", "")).lower():
            continue
        body = raw.split(b"\r\n\r\n", 1)[1]
        txt = quopri.decodestring(body).decode("utf-8", "replace")
        if "34086" not in txt:
            continue
        dt = _email.utils.parsedate_to_datetime(msg.get("Date"))
        flat = html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'<br\s*/?>', ' | ', txt)))
        picks = bool(re.search(r'Overall pick number:', flat))
        # Split into the two SIDES (each "<abbr> (agreed to )?trade(s)" column lists the
        # players THAT team gave up). Keeping sides separate lets us assign a from/to to a
        # player who has no prior roster week (added + traded in the same week, e.g. Taysom).
        side_blobs = re.findall(
            r"(?:agreed to trade|trades)\s*(.*?)(?=(?:[A-Za-z0-9?\- ]+? (?:agreed to trade|trades))|Reply|$)",
            flat, re.S)
        side_names = []
        for blob in side_blobs:
            nms = re.findall(r"([A-Z][A-Za-z.'\- ]+?),\s*[A-Za-z]{2,3}\s+(?:QB|RB|WR|TE|K|D/ST)", blob)
            if nms:
                side_names.append(nms)
        all_cand = {pid for side in side_names for nm in side for pid in name_to_ids.get(_nrm(nm), [])}
        # trade week = the week where the most candidates change hands together
        wk_votes = Counter()
        for pid in all_cand:
            for wk, frm, to in changes_at(pid):
                if frm is not None:
                    wk_votes[wk] += 1
        trade_week = wk_votes.most_common(1)[0][0] if wk_votes else None

        # Per side: the side's FROM manager = the owner the side's moved players left
        # (the mode), and TO = the other side's FROM. Apply to every player on that side,
        # so same-week acquire+flip players inherit the side's from/to.
        def side_from(side):
            froms = Counter()
            for nm in side:
                for pid in name_to_ids.get(_nrm(nm), []):
                    for wk, frm, to in changes_at(pid):
                        if wk == trade_week and frm is not None:
                            froms[frm] += 1
            return froms.most_common(1)[0][0] if froms else None

        froms = [side_from(s) for s in side_names]
        legs = []
        for si, side in enumerate(side_names):
            frm = froms[si]
            to = froms[1 - si] if len(froms) == 2 else None
            for nm in side:
                ids = name_to_ids.get(_nrm(nm), [])
                # prefer the id that actually moved this week on the right side; else the
                # name match (covers same-week acquire+flip with no prior roster week)
                pid = next((p for p in ids for wk, f, t in changes_at(p)
                            if wk == trade_week and f == frm), ids[0] if ids else None)
                if pid is None:
                    continue
                legs.append({"espn_player_id": pid,
                             "player": bridge.get(pid, {}).get("name"),
                             "gsis_id": bridge.get(pid, {}).get("gsis_id"),
                             "sleeper_id": bridge.get(pid, {}).get("sleeper_id"),
                             "from_manager": frm, "to_manager": to})
        trades.append({
            "date": dt.isoformat() if dt else None,
            "trade_week": trade_week,
            "involves_picks": picks,
            "teams": sorted({l["from_manager"] for l in legs} | {l["to_manager"] for l in legs}),
            "legs": legs,
            "source_email": os.path.basename(fn),
        })
    # merge duplicate emails (accepted + later upheld for the same trade) by (week, player-set)
    seen = {}
    for t in trades:
        key = (t["trade_week"], frozenset(l["espn_player_id"] for l in t["legs"]))
        if key not in seen or len(t["legs"]) > len(seen[key]["legs"]):
            seen[key] = t
    return sorted(seen.values(), key=lambda t: t["date"] or "")


def load_trade_layer(loaded: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Executed-trade layer, build-time self-contained. Prefers the committed
    `data/espn_2020_raw/email_trades.json` (the resolved 13-trade layer, baked once
    from the emails) so CI — which has no access to the raw .eml files in
    ~/Downloads — gets the full trades. Falls back to re-parsing the emails only for
    local regeneration when the baked file is absent."""
    raw_dir = (loaded.get("_raw") or {}).get("_dir", ".")
    baked = os.path.join(raw_dir, "email_trades.json")
    if os.path.exists(baked):
        return json.load(open(baked))
    return parse_email_trades(loaded)


def load_espn_2020(raw_dir: str = RAW_DIR_DEFAULT, dp_path: str = DP_IDS_DEFAULT) -> Dict[str, Any]:
    raw = load_raw(raw_dir)
    bridge = build_player_bridge(raw, dp_path)
    return {
        "season": SEASON,
        "league_id": LEAGUE_ID,
        "team_to_manager": TEAM_TO_MANAGER,
        "draft": parse_draft(raw, bridge),
        "weeks": parse_weeks(raw, bridge),
        "transactions": parse_transactions(raw, bridge),
        "_bridge": bridge,
        "_raw": raw,
    }


# --------------------------------------------------------------------------- #
# Sleeper-shape adapter: emit 2020 in the exact shapes lotg.py's per-season
# loop consumes (sc.league / users / rosters / matchups / transactions / drafts /
# brackets), keyed by sleeper_id, so a guarded wrapper can feed 2020 to the build
# untouched. Emitted roster_id is the manager's stable SLEEPER roster_id (see
# ESPN_TO_SLEEPER_RID); player ids == sleeper_id strings.
# --------------------------------------------------------------------------- #
ESPN_START_SLOT_TO_SLEEPER = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 7: "SUPER_FLEX", 23: "FLEX"}
SLEEPER_LEAGUE_ID = "espn_2020"


def _roster_positions(raw: Dict[str, Any]) -> List[str]:
    counts = raw["settings"].get("rosterSettings", {}).get("lineupSlotCounts", {})
    order = [(0, "QB"), (2, "RB"), (4, "WR"), (6, "TE"), (23, "FLEX"), (7, "SUPER_FLEX")]
    pos = []
    for slot, name in order:
        pos += [name] * int(counts.get(str(slot), 0))
    pos += ["BN"] * int(counts.get("20", 0))
    pos += ["IR"] * int(counts.get("21", 0))
    return pos


def emit_sleeper_2020(loaded: Dict[str, Any]) -> Dict[str, Any]:
    raw, bridge = loaded["_raw"], loaded["_bridge"]
    def sid(espn_pid):  # sleeper player id (string), the build's player key
        return _clean_id(bridge.get(espn_pid, {}).get("sleeper_id"))

    owners = {t["id"]: t.get("primaryOwner") for t in raw["teams"].get("teams", [])}
    league = {
        "league_id": SLEEPER_LEAGUE_ID, "season": str(SEASON), "status": "complete",
        "previous_league_id": None, "name": raw["settings"].get("name", "The League"),
        "total_rosters": len(TEAM_TO_MANAGER), "roster_positions": _roster_positions(raw),
        "settings": {"playoff_week_start": 15, "playoff_teams": 4, "num_teams": 8,
                     "last_scored_leg": 16, "leg": 16},
        # 2020 scoring is supplied as actual per-player points on each matchup
        # (players_points), so the build's re-score path has nothing to recompute.
        "scoring_settings": {},
    }
    users = [{"user_id": owners.get(tid), "display_name": mgr,
              "metadata": {"team_name": mgr}} for tid, mgr in TEAM_TO_MANAGER.items()]

    # final rosters = last week that actually has lineups (weeks 17-18 are empty:
    # the 2020 fantasy season ends at week 16)
    last_wk = max(w for w, rows in loaded["weeks"].items() if rows)
    rosters = []
    for r in loaded["weeks"][last_wk]:
        plist = [sid(p["espn_player_id"]) for p in r["starters"] + r["bench"]]
        rosters.append({"roster_id": _rid(r["team_id"]), "owner_id": owners.get(r["team_id"]),
                        "players": [p for p in plist if p], "draft_season": str(SEASON)})

    # matchups per week (roster_id, points, starters, players, players_points, matchup_id)
    matchups_by_week: Dict[int, List[Dict[str, Any]]] = {}
    for wk, rows in loaded["weeks"].items():
        # pair opponents into matchup_ids
        mid_by_team, mid = {}, 0
        for r in rows:
            if r["team_id"] in mid_by_team:
                continue
            mid += 1
            mid_by_team[r["team_id"]] = mid
            if r["opponent_team_id"] is not None:
                mid_by_team[r["opponent_team_id"]] = mid
        out = []
        for r in rows:
            pts = {sid(p["espn_player_id"]): p["points"] for p in r["starters"] + r["bench"] if sid(p["espn_player_id"])}
            out.append({
                "roster_id": _rid(r["team_id"]),
                "matchup_id": mid_by_team.get(r["team_id"]),
                "points": r["pf"],
                "starters": [sid(p["espn_player_id"]) for p in r["starters"] if sid(p["espn_player_id"])],
                "players": [sid(p["espn_player_id"]) for p in r["starters"] + r["bench"] if sid(p["espn_player_id"])],
                "players_points": pts,
            })
        matchups_by_week[wk] = out

    # transactions per week: adds/drops (public) + executed trades (email layer)
    tx = parse_transactions(raw, bridge)
    trades = load_trade_layer(loaded)
    tx_by_week: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    tid = 0
    for m in tx["moves"]:
        wk = m["scoring_period"] or 1
        tid += 1
        adds = {sid(p): _rid(m["team_id"]) for p in m["add_pids"] if sid(p)} or None
        drops = {sid(p): _rid(m["team_id"]) for p in m["drop_pids"] if sid(p)} or None
        tx_by_week[wk].append({
            "transaction_id": f"e{tid}", "type": "waiver" if m["kind"] == "WAIVER" else "free_agent",
            "status": "complete", "roster_ids": [_rid(m["team_id"])],
            "adds": adds, "drops": drops, "draft_picks": [], "waiver_budget": [],
            "settings": None, "created": m["date"], "metadata": None,  # ESPN proposedDate (epoch ms)
        })
    import datetime as _dt
    def _iso_to_ms(s):
        try:
            return int(_dt.datetime.fromisoformat(s).timestamp() * 1000) if s else None
        except Exception:
            return None
    # Bucket each trade into a WEEKLY scoring period using the same
    # calendar-anchored rule lotg.py's `_trade_wk()` applies to every other
    # season (kickoff Sept 7, offseason trades within 7 days roll into wk 1,
    # deeper-offseason trades get 0). Previously this used the email-parser's
    # roster-vote `trade_week` heuristic instead, which can land on a
    # different week than the calendar rule — making team_week's per-week
    # trade bucket (sourced from this dict) disagree with league_week's
    # independently-recomputed `Number of trades` (sourced from each trade's
    # `Date` via the calendar rule). Using the same rule here keeps both
    # sheets in agreement for 2020 (run-2 audit Part 1).
    def _calendar_trade_wk(dt_str):
        if not dt_str:
            return 1
        try:
            d = _dt.datetime.fromisoformat(str(dt_str).replace("Z", "+00:00")).date()
            ss = _dt.date(SEASON, 9, 7)
            if d < ss:
                return 1 if (ss - d).days <= 7 else 0
            return max(1, min(17, (d - ss).days // 7 + 1))
        except Exception:
            return 1
    team_by_mgr = {mgr: _rid(tid) for tid, mgr in TEAM_TO_MANAGER.items()}
    for t in trades:
        # _calendar_trade_wk never returns None (falls back to 1 for a
        # missing date); a real 0 (deep-offseason, no weekly bucket) must
        # stay 0, not get coerced to 1, to match league_week's bucketing.
        wk = _calendar_trade_wk(t["date"])
        tid += 1
        adds, drops, rids = {}, {}, set()
        for l in t["legs"]:
            ps = sid(l["espn_player_id"])
            if not ps:
                continue
            to_rid = team_by_mgr.get(l["to_manager"]); fr_rid = team_by_mgr.get(l["from_manager"])
            if to_rid: adds[ps] = to_rid; rids.add(to_rid)
            if fr_rid: drops[ps] = fr_rid; rids.add(fr_rid)
        tx_by_week[wk].append({
            "transaction_id": f"et{tid}", "type": "trade", "status": "complete",
            "roster_ids": sorted(rids), "adds": adds or None, "drops": drops or None,
            "draft_picks": [], "waiver_budget": [], "settings": None,
            "created": _iso_to_ms(t["date"]), "metadata": None,
        })

    # draft + picks (Sleeper shape)
    picks = [{"round": p["round"], "pick_no": p["overall"], "roster_id": _rid(p["team_id"]),
              "player_id": sid(p["espn_player_id"]), "is_keeper": p["keeper"],
              "metadata": {"first_name": (p["player"] or "").split(" ")[0],
                           "last_name": " ".join((p["player"] or "").split(" ")[1:])}}
             for p in loaded["draft"]]
    # Carry the REAL startup-draft date through in Sleeper's shape (epoch ms).
    # ESPN records it two ways; `completeDate` is when the last pick landed,
    # `draftSettings.date` when it was scheduled. The build's KTC checkpoints
    # anchor on the actual draft day, so a missing date here silently falls back
    # to a guessed anchor and misprices every startup pick.
    _espn_draft = (loaded.get("_raw") or {}).get("draft") or {}
    _espn_settings = ((loaded.get("_raw") or {}).get("settings") or {}).get("draftSettings") or {}
    _draft_ms = _espn_draft.get("completeDate") or _espn_settings.get("date")
    draft = {"draft_id": "espn_2020_draft", "season": str(SEASON), "type": "snake",
             "status": "complete", "settings": {"rounds": max(p["round"] for p in loaded["draft"])}}
    if _draft_ms:
        draft["start_time"] = _draft_ms
        draft["last_picked"] = _draft_ms

    # Player metadata keyed by sleeper_id, for the build to backfill its pid_meta /
    # pid_pos. The build builds those ONLY from the live Sleeper /players/nfl feed, so
    # any 2020 player who has since left that feed would otherwise resolve to a bare
    # numeric id (breaking names, positions, Max PF). The bridge has authoritative
    # name/position/gsis/team for all 250; the build merges this in with setdefault so
    # live Sleeper data still wins for players present there.
    player_meta: Dict[str, Dict[str, Any]] = {}
    for b in bridge.values():
        s = _clean_id(b.get("sleeper_id"))
        if s and s not in player_meta:
            player_meta[s] = {"full_name": b.get("name"), "pos": (b.get("position") or ""),
                              "team": b.get("nfl_team"), "gsis_id": b.get("gsis_id")}

    return {
        "league": league, "users": users, "rosters": rosters,
        "matchups_by_week": matchups_by_week, "transactions_by_week": dict(tx_by_week),
        "draft": draft, "draft_picks": picks, "player_meta": player_meta,
        "winners_bracket": [], "losers_bracket": [],  # derived in the build from standings
    }


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    rd = sys.argv[1] if len(sys.argv) > 1 else RAW_DIR_DEFAULT
    d = load_espn_2020(rd)
    dr, wks, tx = d["draft"], d["weeks"], d["transactions"]
    print(f"draft picks: {len(dr)} (rounds={max(p['round'] for p in dr)})")
    print(f"  R1.01: {dr[0]['manager']} -> {dr[0]['player']} ({dr[0]['position']})")
    named = sum(1 for p in dr if p["player"])
    print(f"  picks with resolved player: {named}/{len(dr)}")
    print(f"weeks: {sorted(wks)}")
    wk1 = wks[1]
    print(f"  week1 teams: {len(wk1)}; sample {wk1[0]['manager']} PF={wk1[0]['pf']} "
          f"starters={len(wk1[0]['starters'])} bench={len(wk1[0]['bench'])}")
    miss_pf = [(w, r['manager']) for w in wks for r in wks[w] if r['pf'] is None]
    print(f"  team-weeks missing PF: {len(miss_pf)}")
    print(f"moves (add/drop): {len(tx['moves'])}; executed trades (UPHOLD): {len(tx['trades'])}")
    # validate a known email trade: 2020-09-15 OK<->SHMU (J.Jefferson+D.Parker for M.Brown+D.Mims)
    for t in tx["trades"]:
        names = {l["player"] for l in t["legs"]}
        if any(n and "Jefferson" in n for n in names):
            print(f"  found JJ trade: teams={t['teams']} players={sorted(n for n in names if n)}")
    unresolved = sum(1 for w in wks for r in wks[w] for p in r["starters"] + r["bench"] if not p["player"])
    print(f"unresolved player names across all lineups: {unresolved}")
