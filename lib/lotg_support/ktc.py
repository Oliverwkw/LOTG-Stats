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
import re
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
        # sleeper_ids currently in KTC's rolls (today's directory). A player NOT
        # in this set is off the rolls (retired / aged out, e.g. Drew Brees) and
        # is worth 0 — distinct from an active player who simply has no value at a
        # pre-history date. Populated by build_index.
        self.active_sids: set = set()
        # sleeper_id -> last season the player was on a real NFL roster (nflverse).
        # Used to CONFIRM retirement at a pre-floor date: a player with no KTC value
        # at a date whose season is after their last rostered NFL season was out of
        # the league by then -> 0, not N/A. Populated by build_index.
        self.last_active_season: Dict[str, int] = {}

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

# Suffixes dynasty-daddy strips from full_name when building the slug.
_NAME_SUFFIXES = (" jr", " sr", " ii", " iii", " iv", " v")


def derive_player_name_id(full_name: str, position: str) -> Optional[str]:
    """Compose dynasty-daddy's player slug from Sleeper full_name + position.

    Their convention: lowercase the name, strip apostrophes, periods,
    hyphens, and whitespace, drop common name suffixes (Jr / Sr / II
    etc.), then append the lowercase position. We use this as a fallback
    when the player isn't in today's directory (retired, switched
    leagues, untracked rookie not yet rated).

    Examples we've validated against dynasty-daddy's API:
      'Ja\\'Marr Chase' + 'WR' -> 'jamarrchasewr'
      'Amon-Ra St. Brown' + 'WR' -> 'amonrastbrownwr'
      'A.J. Brown' + 'WR' -> 'ajbrownwr'
      'Tom Brady' + 'QB' -> 'tombradyqb'
    """
    if not full_name or not position:
        return None
    n = str(full_name).lower()
    # Strip suffixes once. We don't loop; double suffixes don't happen.
    for suf in _NAME_SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    for ch in "'.- ":
        n = n.replace(ch, "")
    pos = str(position).strip().lower()
    if not n or not pos:
        return None
    return n + pos


# League size. Our picks (an 8-team draft) map onto KTC's 12-team Early/Mid/Late
# quarters by OVERALL draft position, so e.g. 2.01 (overall 9) is a "Late 1st",
# not an "Early 2nd". (KTC convention: Early = picks 1-4, Mid = 5-8, Late = 9-12.)
_TEAMS = 8


def _overall_to_ktc_quarter(overall: int) -> Tuple[int, str]:
    rnd = (overall - 1) // 12 + 1
    pos = (overall - 1) % 12 + 1
    q = "Early" if pos <= 4 else ("Mid" if pos <= 8 else "Late")
    return rnd, q


def pick_label_candidates(asset: str, teams: int = _TEAMS) -> List[str]:
    """Translate a LOTG pick label ('2027 2.01' / '2027 3.??') to dynasty-daddy
    pick full_name candidates, mapping by OVERALL draft position onto KTC's 12-team
    Early/Mid/Late quarters. A specific slot -> the one quarter it lands in; an
    unknown slot ('??') -> every quarter the round spans (caller averages them, e.g.
    a 3rd-round pick covers overall 17-24 = Mid 2nd + Late 2nd).

    Defensive on the input shape: display labels carry a parenthetical rider
    naming the player or original owner ('2026 3.05(T. Hurst)', '2027 4(LWebs53)')
    and a round can arrive bare, with no slot at all ('2027 4'). The live build
    normalises labels before calling here (see `_pick_val_label`), but callers
    that pass a display string straight through used to silently get [] — an
    unvalued asset that reads as N/A rather than an error. Strip the rider and
    treat a bare round as an unknown slot spanning the whole round."""
    # Drop any '(...)' rider and anything after it, then keep the leading
    # '<year> <round>[.<slot>]' tokens.
    cleaned = re.sub(r"\(.*", " ", str(asset)).strip()
    parts = cleaned.split()
    if len(parts) < 2:
        return []
    year_s, rest = parts[0], parts[1]
    if "." in rest:
        rd_s, slot_s = rest.split(".", 1)
    else:
        rd_s, slot_s = rest, "??"   # bare round -> unknown slot (whole-round avg)
    try:
        year = int(year_s)
        rd = int(rd_s)
    except Exception:
        return []
    slot_s = slot_s.strip()
    # The 2.09 toilet-reward pick is valued as its 2.08 equivalent everywhere
    # (per league convention — see the picks sheet). It reaches this function
    # two ways: the sentinel round 209 (emitted by the trade valuation labeler)
    # and the literal "2.09" display slot. The latter is overall pick 17 in an
    # 8-team draft, which would otherwise misprice as a Mid 2nd rather than the
    # intended Early 2nd, so normalise BOTH forms to round 2, slot 8 here.
    if rd == 209 or (rd == 2 and slot_s in ("09", "9")):
        rd, slot_s = 2, "08"
    # The 5.0X FAAB-buy picks are valued as a 4.08 everywhere, the same way the
    # 2.09 is valued as a 2.08 (see the (_R, _S) mapping on the picks sheet).
    # Real drafts are 4 rounds, so a round 5 is always one of these synthetic
    # draft-day buys and KTC has no listing for it at all — without the mapping
    # it resolved to a Late 3rd that does not exist and the asset went unvalued.
    # Reaches here the same two ways as the 2.09: the sentinel rounds 501-508
    # (5.01 -> 501, emitted by the trade valuation labeler) and the literal
    # "5.0N" display slot.
    if rd == 5 or 500 < rd <= 508:
        rd, slot_s = 4, "08"
    if slot_s.isdigit():
        first = last = (rd - 1) * teams + int(slot_s)
    else:  # unknown slot -> the whole round's overall range
        first, last = (rd - 1) * teams + 1, rd * teams
    labels: List[str] = []
    for ov in range(first, last + 1):
        kr, q = _overall_to_ktc_quarter(ov)
        lab = f"{year} {q} {_ORD.get(kr, f'{kr}th')}"
        if lab not in labels:
            labels.append(lab)
    return labels


# --------------------------------------------------------------------------
# Bulk index builder
# --------------------------------------------------------------------------

def build_index(
    repo_root: Path,
    sleeper_ids: Iterable[str],
    pick_labels: Iterable[str],
    value_col: str = "trade_value",
    sid_to_meta: Optional[Dict[str, Dict[str, str]]] = None,
    last_active_season: Optional[Dict[str, int]] = None,
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
    # Current KTC rolls (active assets in today's directory), so the query can
    # tell "off the rolls -> value 0" from "active but pre-history -> unknown".
    idx.active_sids = {str(p.get("sleeper_id")) for p in directory if p.get("sleeper_id")}
    idx.last_active_season = {str(k): int(v) for k, v in (last_active_season or {}).items()}

    # Players we actually use. Retired and aged-out players aren't in
    # dynasty-daddy's 'today' directory, so we derive the name_id slug
    # from Sleeper's full_name + position when present. Their backend
    # still serves the full history for those slugs.
    wanted_sids = {str(s) for s in sleeper_ids if s}
    for sid in sorted(wanted_sids):
        nm = sid_to_name.get(sid)
        if not nm and sid_to_meta:
            meta = sid_to_meta.get(sid) or {}
            nm = derive_player_name_id(meta.get("full_name") or "", meta.get("pos") or "")
        if not nm:
            continue
        hist = load_history(repo_root, nm)
        if hist:
            idx.add_player(sid, hist, value_col)

    # Merge the one-time KTC.com / Wayback backfill (data/ktc_backfill/
    # <sleeper_id>.json = [{"date","sf_trade_value"}]). dynasty-daddy only goes
    # back to 2021-04-16; the backfill supplies the earlier (2020 + early-2021)
    # superflex values for the players we need, so value_at sees them. Same source
    # (KTC), so it just extends each series earlier; dynasty-daddy wins on overlap.
    backfill_dir = repo_root / "data" / "ktc_backfill"
    if backfill_dir.exists():
        merged_n = 0
        for sid in wanted_sids:
            bf = backfill_dir / f"{sid}.json"
            if not bf.exists():
                continue
            try:
                rows = json.loads(bf.read_text())
            except Exception:
                continue
            pairs = [(r["date"], float(r["sf_trade_value"]))
                     for r in rows if r.get("date") and r.get("sf_trade_value") is not None]
            if not pairs:
                continue
            existing = idx.player.get(sid, [])
            seen = {d for d, _ in existing}
            combined = existing + [(d, v) for d, v in pairs if d not in seen]
            combined.sort(key=lambda kv: kv[0])
            idx.player[sid] = combined
            merged_n += 1
        if merged_n:
            _HTTP_ERRORS.append(f"info: merged KTC backfill for {merged_n} players")

    # Picks: expand each '?? slot' label to its generic candidates, fetch
    # their histories once.
    wanted_pick_names: set = set()
    for label in pick_labels:
        for cand in pick_label_candidates(str(label)):
            wanted_pick_names.add(cand)
        # Also pull the NEARER draft classes for the same round. A pick further
        # out than KTC lists is priced off the furthest class KTC does quote
        # (see _furthest_listed_pick_value), and that lookup can only see what
        # is in this index. Fetching solely the requested year made the answer
        # depend on which OTHER trades happened to reference a nearer class —
        # a 2030 4th resolved to a 2028 value or a 2026 one depending on the
        # rest of the league's trade history. Fetch the whole ladder so the
        # substitute is a property of the pick, not of unrelated rows.
        _m = re.match(r"\s*(\d{4})\s+(.*)$", str(label))
        if _m:
            try:
                _y0 = int(_m.group(1))
            except Exception:
                _y0 = None
            if _y0:
                for _back in range(1, 9):
                    for cand in pick_label_candidates(f"{_y0 - _back} {_m.group(2)}"):
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

# Earliest date any KTC value exists. From this date on, a player with NO value
# is genuinely unranked (too obscure / out of the league) and worth 0 — not
# "unknown".
#
# This is 2020-04-01, NOT dynasty-daddy's 2021-04-16. dynasty-daddy is only a
# mirror and its per-player series starts a year late; keeptradecut.com itself
# serves daily history from 2020-04-01, for retired players too. Treating the
# mirror's start as the floor blanked everything before it — the whole 2020
# season, including the startup draft. `scripts/ktc_direct_backfill.py` pulls
# the real pre-mirror values from KTC directly into data/ktc_backfill/, so the
# index has genuine data below the old floor.
#
# Caveat: KTC ranked ~500 players in 2020 vs ~1000 today, so a 2020 absence is
# weaker evidence of worthlessness than a 2024 one. The backfill script covers
# every player who actually appears in a pre-2021 row, so in practice absence
# here means KTC never ranked them at all — which is the 0 case, not the
# unknown case.
KTC_FLOOR = date(2020, 4, 1)


def _furthest_listed_pick_value(
    asset_label: str,
    target: date,
    idx: ValueIndex,
    max_step_back: int = 8,
) -> Optional[float]:
    """Value a pick whose own draft class KTC doesn't list yet.

    Substitutes the FURTHEST-out class that is actually quoted at `target`,
    keeping the round/quarter. E.g. a 2031 3rd valued in 2026, when KTC's most
    distant listed class is 2029, is priced as a 2029 3rd. Returns None if no
    year in range has a quote (nothing to anchor to).
    """
    m = re.match(r"\s*(\d{4})\s+(.*)$", str(asset_label))
    if not m:
        return None
    try:
        want_year = int(m.group(1))
    except Exception:
        return None
    rest = m.group(2)
    # Step DOWN from the requested year: the first year with a live quote is by
    # construction the furthest-out class KTC prices at this date.
    for step in range(1, max_step_back + 1):
        yr = want_year - step
        # Substitute only a class that is still FUTURE at `target`. The
        # target-year class is excluded on purpose: once its draft runs, those
        # picks are consumed and their quote stops describing an unexercised
        # future pick — pricing a 2030 4th off a 2026 4th on 2026 draft day is
        # not a stale answer, it is a different asset.
        if yr <= target.year:
            break
        cands = pick_label_candidates(f"{yr} {rest}")
        vals = [idx.value_at(c, target, is_pick=True) for c in cands]
        vals = [v for v in vals if v is not None]
        if vals:
            return sum(vals) / len(vals)
    return None


def asset_value_at(
    asset_label: Optional[str],
    sleeper_id: Optional[str],
    target: date,
    idx: ValueIndex,
) -> Optional[float]:
    """Resolve a single asset's KTC value at `target`.

    asset_label is set for picks ('2026 1.??' / '2026 2.01'); sleeper_id is set for
    players. pick_label_candidates maps the slot by OVERALL position onto KTC's
    quarters: a specific slot -> the one quarter it lands in (2.01 -> Late 1st); an
    unknown '??' slot -> every quarter the round spans, averaged.
    """
    # Pick path
    if asset_label and len(asset_label) >= 5 and asset_label[:4].isdigit() and asset_label[4] == " ":
        candidates = pick_label_candidates(asset_label)
        vals = [idx.value_at(c, target, is_pick=True) for c in candidates]
        vals = [v for v in vals if v is not None]
        if vals:
            return sum(vals) / len(vals)
        # KTC only lists a draft class from roughly three years out (2026 picks
        # first appear 2023-09-08, 2027 from 2024-08-31, 2028 from 2025-08-15).
        # A pick further out than that has no quote of its own yet, but it is not
        # valueless — the league trades it, and its worth tracks the most distant
        # class KTC *does* price. Walk the year back toward `target` and use the
        # furthest-out class that has a quote, holding the same round/quarter.
        # Once the pick's own year starts being listed, the exact match above
        # wins and this fallback stops firing.
        return _furthest_listed_pick_value(asset_label, target, idx)

    # Player path
    if not sleeper_id:
        return None
    sid = str(sleeper_id)
    pairs = idx.player.get(sid)
    off_rolls = sid not in idx.active_sids
    # When there's NO KTC value at the target, return 0 (genuinely valueless)
    # rather than N/A (unknown) IF we can affirm the player had no legitimate
    # dynasty value then:
    #   (1) target is POST-FLOOR — dynasty-daddy is comprehensive from KTC_FLOOR
    #       on, so absence = genuinely unranked (too obscure / out of the league).
    #   (2) target's season is AFTER the player's last rostered NFL season — we've
    #       CONFIRMED they were retired / out of the league by then.
    # Otherwise (a pre-floor date for someone active/unconfirmed) the value is
    # truly unknown -> N/A, pending backfill. We must NOT zero a 2020 checkpoint
    # for a then-active, now-retired player.
    las = idx.last_active_season.get(sid)
    confirmed_zero = (target >= KTC_FLOOR) or (las is not None and target.year > las)

    # KTC = 0 ONLY when the player has demonstrably dropped off the rolls BY the
    # target date (off the current rolls AND target is after their last recorded
    # KTC value), OR when absence is confirmed valueless per the rule above.
    if not pairs:
        return 0.0 if confirmed_zero else None
    v = idx.value_at(sid, target, is_pick=False)  # latest value on/before target
    if v is None:
        # target precedes their first recorded value: 0 if confirmed valueless,
        # else unknown (active pre-tracking) -> N/A.
        return 0.0 if confirmed_zero else None
    # v carries the last known value forward. If the player is off the current rolls
    # AND target is LONG after their last recorded value, they've genuinely dropped
    # off KTC by then -> 0 (don't carry a stale value forward for months). A SHORT
    # gap (e.g. an end-of-rookie checkpoint two weeks after a sparse Wayback point)
    # carries the real value forward.
    last_ds = pairs[-1][0]
    if off_rolls and target.isoformat() > last_ds:
        try:
            ly, lm, ld = (int(x) for x in last_ds.split("-"))
            if (target - date(ly, lm, ld)).days > 120:
                return 0.0
        except Exception:
            pass
    return v
