"""Undo Sleeper's late listings on a finished week's matchup rosters.

Sleeper keeps updating a finished week's matchup roster until its leg rolls
over, so a move that completed AFTER the week's last game (a Tuesday trade, the
Wednesday 3am waiver run) shows on the week it did not play in:

* the incoming player joins that week's list (Nico Collins, LWebs53 2022 wk6;
  Josh Doctson, BROsenzweig 2022 wk7; Odell Beckham, Oliverwkw 2022 wk9);
* a player traded away leaves his old team's list (Rachaad White, LWebs53
  2023 wk5);
* a dropped player stays listed from 2022 on, but in 2021 he left the list too
  (Jamison Crowder, stevenb123 2021 wk6 — all four such 2021 drops were bye
  weeks).

User rule (2026-09-24): a week belongs to whoever held the player when it was
played. `undo_late_listings` reverses those moves, latest first, on a copy of
the week: the incoming player comes off the list (unless Sleeper froze him into
the starters), and a player sent away goes back on as bench with Sleeper's
points for him that week, or `points_fallback`'s, or 0.

Shared by the build (`src/lotg.py`) and the inquiry toolkit's `week()` so a
roster read from the snapshot matches the one the exports were built from.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9
    ZoneInfo = None  # type: ignore


def league_day(when: datetime) -> date:
    """The calendar day `when` falls on in league time (America/New_York)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if ZoneInfo is not None:
        when = when.astimezone(ZoneInfo("America/New_York"))
    return when.date()


def effective_ms(t: Dict[str, Any]) -> Any:
    """When a Sleeper transaction moved players: the completion (`status_updated`)
    for a waiver or a trade, else `created` (mirrors the build's
    `_tx_effective_ms`)."""
    if str(t.get("type") or "") == "trade" and t.get("_effective_ms"):
        return t["_effective_ms"]
    if str(t.get("type") or "") in ("waiver", "trade") and t.get("status_updated"):
        return t.get("status_updated")
    return t.get("created")


def undo_late_listings(
    matchups: Sequence[Dict[str, Any]],
    transactions: Sequence[Dict[str, Any]],
    week_last_game_day: str,
    *,
    when: Callable[[Dict[str, Any]], Any] = effective_ms,
    day_of: Callable[[datetime], date] = league_day,
    points_fallback: Optional[Callable[[str], Optional[float]]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(matchups, changes). `matchups` is returned untouched (same object) when
    no completed move is dated after `week_last_game_day` (ISO, league time);
    otherwise a corrected deep copy. `changes` reads "-pid@rN" / "+pid@rN"."""
    late: List[Tuple[datetime, Dict[str, Any]]] = []
    for t in transactions or []:
        if (t.get("status") or "complete") != "complete":
            continue
        try:
            ms = int(when(t))
        except (TypeError, ValueError):
            continue
        if ms <= 0:
            continue
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        if day_of(dt).isoformat() > str(week_last_game_day):
            late.append((dt, t))
    if not late:
        return list(matchups), []
    out = copy.deepcopy(list(matchups))
    by_rid: Dict[int, Dict[str, Any]] = {}
    for m in out:
        try:
            by_rid[int(m.get("roster_id"))] = m
        except (TypeError, ValueError):
            continue
    listed_pts = {str(p): v for m in out for p, v in (m.get("players_points") or {}).items()}
    changes: List[str] = []
    for _dt, t in sorted(late, key=lambda e: e[0], reverse=True):
        for p, r in (t.get("adds") or {}).items():
            m = by_rid.get(_as_int(r))
            if m is None:
                continue
            players = [str(x) for x in (m.get("players") or [])]
            if str(p) in players and str(p) not in {str(x) for x in (m.get("starters") or [])}:
                m["players"] = [x for x in (m.get("players") or []) if str(x) != str(p)]
                if isinstance(m.get("players_points"), dict):
                    m["players_points"].pop(str(p), None)
                changes.append(f"-{p}@r{r}")
        for p, r in (t.get("drops") or {}).items():
            m = by_rid.get(_as_int(r))
            if m is None:
                continue
            if str(p) not in {str(x) for x in (m.get("players") or [])}:
                m["players"] = list(m.get("players") or []) + [str(p)]
                pts = listed_pts.get(str(p))
                if pts is None and points_fallback is not None:
                    pts = points_fallback(str(p))
                if isinstance(m.get("players_points"), dict):
                    m["players_points"][str(p)] = float(pts or 0.0)
                changes.append(f"+{p}@r{r}")
    return (out if changes else list(matchups)), changes


def _as_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
