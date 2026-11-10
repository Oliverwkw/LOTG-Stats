"""FAAB values on any date: the committed history the build's "FAAB Value" columns read.

The rebuild (`faab_pipeline.rebuild`) values every rostered player on every grid date (daily Sept 1 - Feb 15,
Tuesdays otherwise, from 2021) but commits only the rows the rule fit needs (inputs.csv). This module writes the
finished values (every rule applied, with the committed params.json) for all of them, plus the league's rookie-pick
prices, and reads them back for the build:

  data/faab_value/history.csv   sid, date, value     (finished FAAB $ per player per grid date)
  data/faab_value/pick_prices.csv  draft_day, slot, price   (median price of each slot over the drafts held up to
                                                         and including draft_day: valid for dates AFTER it)

`FaabIndex` mirrors what the KTC index does for the KTC columns:
  player(sid, d)   the value on the last grid date on or before d (at most MAX_GAP days back; past the history's
                   last date it carries the last value up to CARRY days). 0 when the player was valued before and
                   is no longer on the board that day; None when he has no value yet (or d is before the history).
  player_entering(sid, d)  the same, but a player with no value yet takes his first one within MAX_GAP days
                   (the draft-day columns: a draftee joins the board on the next grid date)
  pick(label, d)   the FAAB system's own pick price (faab_inputs.Picks.value), from the exported slot table.
                   None after the pick's draft (the caller values the drafted player instead); before the first
                   league draft it takes that draft's slot prices.

The values are point-in-time: every row is computed from what was known on its date. The history goes stale when
params.json changes until the next rebuild (`scripts/faab_rebuild.py --history-only` refreshes it from the cache).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "faab_value"
HISTORY = DATA / "history.csv"
PICK_PRICES = DATA / "pick_prices.csv"
MAX_GAP = 8          # days: the grid is daily in season, weekly (Tuesdays) otherwise
CARRY = 14           # days past the history's last date a value is carried (the trailing edge, until the next rebuild)
PICK = re.compile(r"^(\d{4}) (\d)(?:\.(\d\d))?")


# --------------------------------------------------------------------------------------------- writing (rebuild)

def finished_values(R: pd.DataFrame, pa: pd.DataFrame, params: dict) -> pd.DataFrame:
    """every (sid, date) row of the rebuild's grid frame R valued exactly as the board values it: the rule columns,
    each WR's top teammate (wr_mate), the league-spend / NFL-draft columns, then every rule incl. post_rules"""
    from . import faab_pipeline as P
    from . import faab_value as V
    R = R.drop_duplicates(["sid", "date"]).reset_index(drop=True)
    idx = np.arange(len(R))
    mates = P.wr_mates(R, idx)
    need = [c for c in P.rule_columns() if c in R]
    E = R[need].copy()
    E["wr_mate"] = [str(R.sid.values[mates[i]]) if i in mates else "" for i in idx]
    E["e_x_qb_base"] = P.qb_base(R, idx)
    if pa is not None and "gsis" in R:
        E = P.backup_columns(E, R.gsis.values, pa)
    E["date"] = pd.to_datetime(E.date)
    E["injury"] = E.injury.fillna("").astype(str) if "injury" in E else ""
    for c in E.columns:          # the same rounding the committed inputs get, so a row values the same either way
        if E[c].dtype.kind == "f":
            E[c] = E[c].astype("float64").round(5)
    E = E.reset_index(drop=True)
    v = V.with_links(E, params)
    return pd.DataFrame(dict(sid=E.sid.astype(str).values, date=E.date.dt.strftime("%Y-%m-%d").values,
                             value=np.round(np.asarray(v, dtype=float), 1)))


def pick_price_table(picks) -> pd.DataFrame:
    """the slot medians faab_inputs.Picks uses, one block per league draft day (valid for dates after it)"""
    rows = []
    for y, dd in sorted(picks.draft_day.items()):
        sv = picks.slot_values(pd.Timestamp(dd) + pd.Timedelta(days=1))
        for slot, price in sv.items():
            rows.append((pd.Timestamp(dd).strftime("%Y-%m-%d"), str(slot), round(float(price), 3)))
    return pd.DataFrame(rows, columns=["draft_day", "slot", "price"])


def write(H: pd.DataFrame, picks_table: pd.DataFrame, out: Path = DATA) -> int:
    out = Path(out)
    # plain text sorted by date: finished quarters never change, so git stores each weekly rebuild as a small delta
    # (a gzip would be a fresh ~3 MB blob every week)
    H = H.dropna(subset=["value"]).sort_values(["date", "sid"], kind="stable")
    H.to_csv(out / "history.csv", index=False)
    picks_table.to_csv(out / "pick_prices.csv", index=False)
    return len(H)


# --------------------------------------------------------------------------------------------- reading (build)

def _d(x) -> date:
    return x if isinstance(x, date) else pd.Timestamp(x).date()


class FaabIndex:
    def __init__(self, history: pd.DataFrame, pick_prices: Optional[pd.DataFrame] = None):
        h = history.copy()
        h["sid"] = h.sid.astype(str).str.replace(r"\.0$", "", regex=True)
        h["d"] = pd.to_datetime(h.date)
        h = h.sort_values(["sid", "d"], kind="stable")
        self.grid = np.unique(h.d.values.astype("datetime64[D]"))
        self.first = self.grid[0] if len(self.grid) else None      # numpy datetime64[D]
        self.last = self.grid[-1] if len(self.grid) else None
        self._p: Dict[str, tuple] = {s: (g.d.values.astype("datetime64[D]"), g.value.values.astype(float))
                                     for s, g in h.groupby("sid", sort=False)}
        self._odds = None               # faab_pick_slots.SlotOdds, built on first use (False = unavailable)
        self._slots: list = []          # [(draft_day, {slot: price})], ascending
        self.draft_days: Dict[int, date] = {}
        if pick_prices is not None and len(pick_prices):
            for dd, g in pick_prices.groupby("draft_day"):
                self._slots.append((_d(dd), dict(zip(g.slot.astype(str), g.price.astype(float)))))
                self.draft_days[_d(dd).year] = _d(dd)
            self._slots.sort(key=lambda t: t[0])

    @classmethod
    def load(cls, data: Path = DATA) -> Optional["FaabIndex"]:
        data = Path(data)
        if not (data / "history.csv").exists():
            return None
        H = pd.read_csv(data / "history.csv", dtype={"sid": str, "date": str})
        P = pd.read_csv(data / "pick_prices.csv", dtype={"slot": str, "draft_day": str}) if (data / "pick_prices.csv").exists() else None
        return cls(H, P)

    def grid_day(self, d) -> Optional[np.datetime64]:
        """the grid date a lookup on d reads, or None (before the history, in a gap, or past the carry window)"""
        if self.first is None:
            return None
        t = np.datetime64(_d(d), "D")
        if t < self.first:
            return None
        if t > self.last:
            return self.last if (t - self.last).astype(int) <= CARRY else None
        g = self.grid[np.searchsorted(self.grid, t, side="right") - 1]
        return g if (t - g).astype(int) <= MAX_GAP else None

    def player(self, sid, d) -> Optional[float]:
        if sid is None:
            return None
        s = str(sid).strip()
        if s.endswith(".0"):
            s = s[:-2]
        g = self.grid_day(d)
        if g is None or s not in self._p:
            return None
        ds, vs = self._p[s]
        i = np.searchsorted(ds, g, side="right") - 1
        if i < 0:
            return None                 # not valued yet (e.g. before his NFL draft)
        return float(vs[i]) if ds[i] == g else 0.0      # valued before, not on the board that day

    def player_entering(self, sid, d) -> Optional[float]:
        """player(sid, d), or, when he has no value yet on d, his first value within MAX_GAP days after it.
        For the day a player ENTERS the league (a rookie on his draft day): the board values rostered players
        only, so a draftee's first value lands on the next grid date (1-3 days after the draft in 2021-26)."""
        v = self.player(sid, d)
        if v is not None or sid is None:
            return v
        s = str(sid).strip()
        if s.endswith(".0"):
            s = s[:-2]
        if s not in self._p:
            return None
        ds, vs = self._p[s]
        t = np.datetime64(_d(d), "D")
        if ds[0] >= t and (ds[0] - t).astype(int) <= MAX_GAP:     # never valued before d: his first value
            return float(vs[0])
        return None

    def slot_values(self, d) -> Dict[str, float]:
        t = _d(d); out: Dict[str, float] = {}
        for dd, sv in self._slots:
            if dd < t:
                out = sv
        if not out and self._slots:     # before the first rookie draft: that draft's prices (faab_inputs.Picks)
            out = min(self._slots, key=lambda x: x[0])[1]
        return out

    def pick(self, label, d, pid=None) -> Optional[float]:
        """faab_inputs.Picks.value on the exported table: the exact slot once the order is set, the odds-weighted slot
        price while its deciding season is next up or under way (faab_pick_slots), else its round's average; 5th round on $20; 5% off a year per draft further out. None once the
        pick's own draft has been held (value the drafted player); before the first league draft, that draft's prices. pid = the player later
        taken with it, used only to find its original team (the build masks a future pick's slot to "??")."""
        mm = PICK.match(str(label).strip())
        t = _d(d)
        sv = self.slot_values(t)
        if mm is None or not sv:
            return None
        y, rn, sl = int(mm.group(1)), int(mm.group(2)), mm.group(3)
        dd = self.draft_days.get(y)
        if dd is not None and t > dd:
            return None
        if y < t.year or (y == t.year and t.month > 8):
            return None
        if rn >= 5:
            return 20.0
        rnd: Dict[int, list] = {}
        for k, v in sv.items():
            rnd.setdefault(int(k[0]), []).append(v)
        ravg = {r: float(np.mean(v)) for r, v in rnd.items()}
        nxt = t.year if t.month <= 8 else t.year + 1
        if sl and y == t.year and t.month <= 8:
            v = sv.get(f"{rn}.{sl}", ravg.get(rn))
        else:
            v = ravg.get(rn)
        if v is None:
            return None
        o = self.slot_odds()
        f = o.price(label, pd.Timestamp(t), sv, ravg, pid=pid) if o is not None else None
        if f is not None:
            v = f
        return float(v) * 0.95 ** max(0, y - nxt)

    def slot_odds(self):
        """the pick-slot fade-in (faab_pick_slots) on the committed exports, roster strength from this history"""
        if self._odds is None:
            from . import faab_pick_slots as PS
            self._odds = PS.load(value=self.player) or False
        return self._odds or None


DEPTH_FACTOR = 0.6       # the trades KTC columns' depth tax: best asset in full, the 2nd x0.6, the 3rd x0.36, ...


def depth_adjusted(vals) -> float:
    return float(sum(v * DEPTH_FACTOR ** i for i, v in enumerate(sorted(vals, reverse=True))))


# --------------------------------------------------------------------------------------------- the build's columns
# The same rules as the KTC columns they sit beside (src/lotg.py's KTC pass), with FAAB values for KTC:
# an unresolved asset is left out of its side; a side that carried assets but valued none is unknown (None);
# an empty side is 0; FAAB moved in a trade is its own dollars ($1 = $1, where the KTC columns use 100 KTC per $).

def pick_value(fidx: FaabIndex, label, drafted, target) -> Optional[float]:
    """a traded pick on a date: its FAAB pick price until its draft, then the drafted player's value.
    drafted = (Sleeper id of the player taken with it, the day from which he stands in for it) or None"""
    v = fidx.pick(label, target, pid=drafted[0] if drafted else None)    # the drafted player names its original team
    if v is not None:
        return v
    if not drafted or not drafted[0]:
        return None
    mm = PICK.match(str(label).strip())
    dd = fidx.draft_days.get(int(mm.group(1))) if mm else None
    start = dd or drafted[1]
    if start is None or _d(target) <= _d(start):
        return None
    return fidx.player(drafted[0], target)


def side_values(fidx: FaabIndex, target, ids, picks, faab=0.0) -> list:
    """per-asset values of one side; picks = [(label, drafted)]"""
    out = []
    for sid in ids or []:
        v = fidx.player(sid, target)
        if v is not None:
            out.append(float(v))
    for label, drafted in picks or []:
        v = pick_value(fidx, label, drafted, target)
        if v is not None:
            out.append(float(v))
    if faab and faab > 0:
        out.append(float(faab))
    return out


def trade_diff(fidx: FaabIndex, target, today, recv_ids, sent_ids, recv_picks, sent_picks, recv_faab=0.0, sent_faab=0.0):
    """depth-taxed received - sent on a date (the twin of 'KTC value difference ...')"""
    if _d(target) > _d(today):
        return None
    n_r = len(recv_ids or []) + len(recv_picks or []) + (1 if (recv_faab or 0) > 0 else 0)
    n_s = len(sent_ids or []) + len(sent_picks or []) + (1 if (sent_faab or 0) > 0 else 0)
    if n_r == 0 and n_s == 0:
        return None
    rv = side_values(fidx, target, recv_ids, recv_picks, recv_faab)
    sv = side_values(fidx, target, sent_ids, sent_picks, sent_faab)
    if (n_r and not rv) or (n_s and not sv):
        return None
    return round(depth_adjusted(rv) - depth_adjusted(sv), 1)


def net(added: Optional[float], dropped: Optional[float]) -> Optional[float]:
    if added is None and dropped is None:
        return None
    return round((added or 0.0) - (dropped or 0.0), 1)


def version(data: Path = DATA) -> dict:
    """a stamp of the history files a build read: their sha256 and the history's date range"""
    import hashlib
    out = {}
    for f in ("history.csv", "pick_prices.csv"):
        p = Path(data) / f
        out[f] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    return out
