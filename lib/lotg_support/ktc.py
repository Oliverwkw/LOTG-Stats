"""
KTC (KeepTradeCut) dynasty value lookup, sourced from dynasty-daddy.com.

We previously used DynastyProcess's values.csv, but their value_1qb is
derived from FantasyPros ECR, not actual KTC market values — mid- and
lower-tier players read 5-12x lower than KTC.com's site. dynasty-daddy
scrapes KTC daily and re-publishes the real values via a public API,
with per-player history back to April 2021.

API surface used:
  GET /api/v1/player/all/today
      Directory + today's values for every active asset (players + picks).
      ~700 rows. Fields we need: name_id, sleeper_id, full_name, position,
      trade_value (1QB), sf_trade_value (superflex).

  GET /api/v1/player/{name_id}
      Full daily history (~1,800 rows per active player). Same fields per
      row plus a 'date' timestamp.

Identifiers:
  - Players: lookup by sleeper_id -> name_id -> history
  - Picks:   lookup by dynasty-daddy 'full_name' string, e.g. '2026 Early 1st'

Local cache layout (gitignored under data/ktc_cache/):
  directory.json                    today's snapshot
  players/<name_id>.json            per-player full history

Past-date data never changes; histories are cached indefinitely and only
the directory is refreshed daily.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


DD_BASE = "https://dynasty-daddy.com/api/v1"
USER_AGENT = "lotg-stats-build/1 (+https://github.com/Oliverwkw/LOTG-Stats)"

# Captured HTTP errors so the caller can surface them in build_debug.log.
_HTTP_ERRORS: List[str] = []


def _http_get_json(url: str) -> object:
    """GET a URL and return parsed JSON. Captures errors into _HTTP_ERRORS."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        _HTTP_ERRORS.append(f"{url}: {type(exc).__name__}: {exc}")
        raise


def get_http_errors() -> List[str]:
    return list(_HTTP_ERRORS)


def _cache_dir(repo_root: Path) -> Path:
    p = repo_root / "data" / "ktc_cache"
    (p / "players").mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------
# Directory + per-player history fetch (cached on disk)
# --------------------------------------------------------------------------

def load_directory(repo_root: Path) -> List[Dict]:
    """Today's snapshot of every active asset. Refreshes daily on disk."""
    cache = _cache_dir(repo_root) / "directory.json"
    refresh = True
    if cache.exists():
        age = datetime.utcnow().timestamp() - cache.stat().st_mtime
        if age < 6 * 3600:  # 6h freshness
            refresh = False
    if refresh:
        data = _http_get_json(f"{DD_BASE}/player/all/today")
        cache.write_text(json.dumps(data))
    return json.loads(cache.read_text())


def load_history(repo_root: Path, name_id: str) -> List[Dict]:
    """Per-player full history. Cached indefinitely (past values don't change)."""
    cache = _cache_dir(repo_root) / "players" / f"{name_id}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except Exception:
            cache.unlink(missing_ok=True)
    try:
        data = _http_get_json(f"{DD_BASE}/player/{name_id}")
    except Exception:
        return []
    if not isinstance(data, list):
        data = []
    cache.write_text(json.dumps(data))
    return data


# --------------------------------------------------------------------------
# In-memory indexes. Built once per build, then queried by row.
# --------------------------------------------------------------------------

class ValueIndex:
    """Holds the per-player and per-pick historical lookup tables.

    For each asset we keep a sorted list of (date_str, trade_value) so a
    binary scan can find the latest entry on or before any target date.
    Pick label resolution prefers generic round labels first, then walks
    specific-slot labels.
    """

    def __init__(self):
        # sleeper_id -> [(date_str, value), ...] sorted by date asc
        self.player: Dict[str, List[Tuple[str, float]]] = {}
        # pick full_name (dynasty-daddy labels) -> sorted history
        self.pick: Dict[str, List[Tuple[str, float]]] = {}

    @staticmethod
    def _history_to_pairs(history: List[Dict], value_col: str) -> List[Tuple[str, float]]:
        out: List[Tuple[str, float]] = []
        for row in history:
            d = (row.get("date") or "")[:10]
            v = row.get(value_col)
            if not d or v is None:
                continue
            try:
                out.append((d, float(v)))
            except Exception:
                continue
        out.sort(key=lambda kv: kv[0])
        return out

    def add_player(self, sleeper_id: str, history: List[Dict], value_col: str) -> None:
        pairs = self._history_to_pairs(history, value_col)
        if pairs:
            self.player[str(sleeper_id)] = pairs

    def add_pick(self, full_name: str, history: List[Dict], value_col: str) -> None:
        pairs = self._history_to_pairs(history, value_col)
        if pairs:
            self.pick[full_name] = pairs

    def value_at(self, key: str, target: date, *, is_pick: bool) -> Optional[float]:
        """Latest value strictly on or before target. Returns None if no entry."""
        pairs = (self.pick if is_pick else self.player).get(key)
        if not pairs:
            return None
        target_s = target.isoformat()
        # Walk reverse; histories are sorted ascending so this is a small
        # tail-scan. Picks have ~1800 entries max; players similar. Could
        # binary-search if performance ever matters.
        for ds, v in reversed(pairs):
            if ds <= target_s:
                return v
        return None


# --------------------------------------------------------------------------
# Pick label translation: '2026 1.??' -> dynasty-daddy candidate names
# --------------------------------------------------------------------------

_ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def pick_label_candidates(asset: str) -> List[str]:
    """Translate a LOTG pick label to dynasty-daddy full_name candidates,
    in fallback order: generic round (most specific first) then named
    quarters."""
    parts = asset.strip().split()
    if len(parts) != 2:
        return []
    year_s, rest = parts
    if "." not in rest:
        return []
    rd_s, slot_s = rest.split(".", 1)
    try:
        year = int(year_s)
        rd = int(rd_s)
    except Exception:
        return []
    ord_s = _ORD.get(rd, f"{rd}th")
    # Generic round labels first (dynasty-daddy publishes 'YYYY Early Nth',
    # 'YYYY Mid Nth', 'YYYY Late Nth' for unknown-slot picks). When the
    # slot is '??', average across Early/Mid/Late at the caller.
    return [
        f"{year} Early {ord_s}",
        f"{year} Mid {ord_s}",
        f"{year} Late {ord_s}",
    ]


# --------------------------------------------------------------------------
# Bulk index builder
# --------------------------------------------------------------------------

def build_index(
    repo_root: Path,
    sleeper_ids: Iterable[str],
    pick_labels: Iterable[str],
    value_col: str = "trade_value",
) -> ValueIndex:
    """Fetch + cache + index histories for every asset we'll need.

    `value_col` picks the format: 'trade_value' is KTC 1QB, 'sf_trade_value'
    is superflex. The user's league is 1QB so 'trade_value' is the default.
    """
    directory = load_directory(repo_root)

    # Map sleeper_id (str) -> name_id. Multiple players can share a Sleeper ID
    # if the directory has duplicates; take the first one with the higher
    # current trade_value as the canonical entry.
    sid_to_name: Dict[str, str] = {}
    for p in directory:
        sid = p.get("sleeper_id")
        nm = p.get("name_id")
        if not sid or not nm:
            continue
        sid_s = str(sid)
        # Prefer the entry with a non-None current value if there are dupes.
        if sid_s not in sid_to_name:
            sid_to_name[sid_s] = nm

    # Pick name_id mapping. The 'today' directory only carries picks for
    # drafts that haven't happened yet — after a draft completes,
    # dynasty-daddy retires those pick records. For historical lookups
    # we still need them, so derive the name_id from the full_name
    # directly: '2024 Early 1st' -> '2024early1stpi'.
    def _pick_full_name_to_id(fn: str) -> str:
        return fn.replace(" ", "").lower() + "pi"

    pick_name_to_name_id: Dict[str, str] = {}
    for p in directory:
        if (p.get("position") or "") != "PI":
            continue
        fn = p.get("full_name")
        nm = p.get("name_id")
        if fn and nm:
            pick_name_to_name_id[fn] = nm

    idx = ValueIndex()

    # Players we actually use
    wanted_sids = {str(s) for s in sleeper_ids if s}
    for sid in sorted(wanted_sids):
        nm = sid_to_name.get(sid)
        if not nm:
            continue
        hist = load_history(repo_root, nm)
        idx.add_player(sid, hist, value_col)

    # Picks: expand each '?? slot' label to its generic candidates, fetch
    # their histories once.
    wanted_pick_names: set = set()
    for label in pick_labels:
        for cand in pick_label_candidates(str(label)):
            wanted_pick_names.add(cand)
    for fn in sorted(wanted_pick_names):
        # Use directory mapping if present, else derive the name_id.
        nm = pick_name_to_name_id.get(fn) or _pick_full_name_to_id(fn)
        hist = load_history(repo_root, nm)
        if hist:
            idx.add_pick(fn, hist, value_col)

    return idx


# --------------------------------------------------------------------------
# Per-asset query used by the build's KTC pass
# --------------------------------------------------------------------------

def asset_value_at(
    asset_label: Optional[str],
    sleeper_id: Optional[str],
    target: date,
    idx: ValueIndex,
) -> Optional[float]:
    """Resolve a single asset's KTC value at `target`.

    asset_label is set for picks ('2026 1.??' / '2026 1.05'); sleeper_id is
    set for players. For '??'-slot picks we average across Early/Mid/Late
    of that round; for specific slots we use the named quarter that most
    closely matches the slot number.
    """
    # Pick path
    if asset_label and len(asset_label) >= 5 and asset_label[:4].isdigit() and asset_label[4] == " ":
        candidates = pick_label_candidates(asset_label)
        if not candidates:
            return None
        is_unknown_slot = "??" in asset_label
        if is_unknown_slot:
            # Average across whichever Early/Mid/Late candidates have data
            vals: List[float] = []
            for c in candidates:
                v = idx.value_at(c, target, is_pick=True)
                if v is not None:
                    vals.append(v)
            if not vals:
                return None
            return sum(vals) / len(vals)
        # Specific slot: pick the closest named quarter. dynasty-daddy
        # uses Early (1-4), Mid (5-8), Late (9-12) approximately. For a
        # 12-team league this lines up; for other team counts the mapping
        # degrades. We accept that error in V1.
        try:
            slot = int(asset_label.split()[1].split(".")[1])
        except Exception:
            return None
        if slot <= 4:
            ordered = [candidates[0], candidates[1], candidates[2]]
        elif slot <= 8:
            ordered = [candidates[1], candidates[0], candidates[2]]
        else:
            ordered = [candidates[2], candidates[1], candidates[0]]
        for c in ordered:
            v = idx.value_at(c, target, is_pick=True)
            if v is not None:
                return v
        return None

    # Player path
    if not sleeper_id:
        return None
    return idx.value_at(str(sleeper_id), target, is_pick=False)
