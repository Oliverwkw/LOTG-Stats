"""FAAB versions of the columns that take their value from KTC, kept OFF the build.

The build carries a FAAB Value twin beside every column in KTC units (PR #568). The columns DERIVED from those
(O-Score, Trade impact score, the manager skills, Wins added's lineage shares, Price paid (FAAB) and Points above
expectation) still read KTC. This module recomputes each of them with FAAB values in place of KTC, from the
build's own exports, and writes them to exports/raw/faab_derived/ (an artifact: .gitignore keeps it out of the
committed exports, and no sheet, page or digest reads it).

Every recompute is checked against the build: run with the KTC inputs it must reproduce the exported column, and
run with the FAAB inputs at the identity transform it must reproduce the exported FAAB Value twins. `summary.json`
records both checks, so a FAAB version is only as trusted as its KTC reproduction.

`Values(fidx, transform)` is the value source. A transform maps every FAAB $ value (players and picks) through
v -> scale * v ** power, the one global transform the follow-up search (`search_transform`) fits; FAAB moved in a
trade stays $1 = $1 unless `cash=True`.

  twins(...)            the 53 FAAB Value twins, recomputed from the exports (the identity reproduces the build)
  oscores(...)          O-Score on the four sheets (+ pure drops, the pick pools, the non-rookie de-trend)
  trade_impact(...)     Trade impact score
  skills(...)           Drafting / Trading / Add/Drop skill (team_year, team_all_time)
  wins_added_faab(...)  Wins added with the lineage shares in FAAB values (lotg_support.wins_added)
  trade_prices(...)     Price paid (FAAB) with every traded asset at its FAAB value; drafts at the FAAB pick price
  pae(...)              Points above expectation refit on those prices (needs the build's additions dump)
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import faab_history as FH

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "exports"
OUT = EXPORTS / "raw" / "faab_derived"
SUFFIX = " (FAAB values)"

FA_RE = re.compile(r"^\$(\d+(?:\.\d+)?) FAAB$")
PICK_RE = re.compile(r"^(\d{4}) (\d+)(?:\.(\d+))?\s*(?:\((.*)\))?\s*$")
TX_LABELS = ("at deal time", "at end of season", "1 year later", "2 years later")
PICK_CKPTS = ("on draft day", "at end of rookie year", "1 year after draft day", "2 years after draft day",
              "3 years after draft day", "4 years after draft day")
PA_CKPTS = ("at pickup", "at end of season", "1 year after pickup", "2 years after pickup",
            "3 years after pickup", "4 years after pickup")
ROOKIE_OSCORE_MIN_WEEK = 8


# ------------------------------------------------------------------------------------------- dates (the build's)

def week_tuesday(season: int, week: int) -> date:
    """lotg._week_tuesday: week 1's Tuesday is the day after Labor Day"""
    import lotg  # noqa: WPS433 (the build's own calendar)
    return lotg._week_tuesday(int(season), int(week))


def season_start(season: int) -> date:
    return week_tuesday(season, 1)


def championship_monday(y: int) -> date:
    sept1 = date(int(y), 9, 1)
    first_monday = sept1 + timedelta(days=(7 - sept1.weekday()) % 7)
    return first_monday + timedelta(days=6) + timedelta(weeks=16) + timedelta(days=1)


def plus_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def _day(x) -> Optional[date]:
    try:
        return pd.Timestamp(str(x)[:10]).date()
    except Exception:
        return None


def _utc_day(x) -> Optional[date]:
    """the build values a move on its UTC date (the raw Sleeper stamp); the exports show Eastern time"""
    try:
        t = pd.Timestamp(str(x))
        if len(str(x)) <= 10:
            return t.date()
        return t.tz_localize("America/New_York", ambiguous=True, nonexistent="shift_forward").tz_convert("UTC").date()
    except Exception:
        return _day(x)


def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _ids(cell) -> List[str]:
    s = str(cell or "").strip()
    if not s or s.lower() == "nan":
        return []
    return [re.sub(r"\.0$", "", x.strip()) for x in s.split(";") if x.strip()]


# ------------------------------------------------------------------------------------------- the value source

@dataclass
class Transform:
    scale: float = 1.0
    power: float = 1.0
    cash: bool = False          # also transform FAAB dollars moved in trades

    def __call__(self, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        v = float(v)
        if self.scale == 1.0 and self.power == 1.0:
            return v
        return self.scale * (v ** self.power) if v > 0 else 0.0

    @property
    def identity(self) -> bool:
        return self.scale == 1.0 and self.power == 1.0


class Values:
    """FAAB values on any date through one global transform"""

    def __init__(self, fidx: FH.FaabIndex, transform: Optional[Transform] = None):
        self.f = fidx
        self.t = transform or Transform()

    def player(self, sid, d) -> Optional[float]:
        return self.t(self.f.player(sid, d))

    def player_entering(self, sid, d) -> Optional[float]:
        """the build's draft-day rule (FaabIndex.player_entering): a rookie's first value within days of d"""
        return self.t(self.f.player_entering(sid, d))

    def pick(self, label, drafted, d) -> Optional[float]:
        return self.t(FH.pick_value(self.f, label, drafted, d))

    def cash(self, x: float) -> float:
        return self.t(x) if self.t.cash else float(x)


# ------------------------------------------------------------------------------------------- loading

def load(exports: Path = EXPORTS) -> Dict[str, pd.DataFrame]:
    exports = Path(exports)
    out = {}
    for sh in ("trades", "add_drops", "rookie_picks", "non_rookie_picks", "player_additions", "team_year",
               "team_all_time", "team_week"):
        p = exports / f"{sh}.csv"
        if p.exists():
            out[sh] = pd.read_csv(p, low_memory=False)
    return out


def draft_days(pa: pd.DataFrame) -> Dict[int, date]:
    """each season's rookie-draft day: the first Draft row of the season (faab_inputs.Picks' rule)"""
    d = pa[pa["Addition type"] == "Draft"].copy()
    d["d"] = pd.to_datetime(d.Date.astype(str).str[:10])
    return {int(y): g.d.min().date() for y, g in d.groupby("Season")}


def drafted_ids(rp: pd.DataFrame) -> Dict[Tuple[int, str], str]:
    """(year, 'R.SS') -> the Sleeper id taken with that rookie pick"""
    out = {}
    for r in rp.to_dict("records"):
        y = re.match(r"\s*(\d{4})", str(r.get("Year")))
        pid = (_ids(r.get("Player Picked ID")) or [None])[0]
        if y is None or not pid:
            continue
        out[(int(y.group(1)), str(r.get("Number")).strip())] = pid
    return out


class Assets:
    """one trade side parsed from the export text: players (ids), picks, FAAB"""

    def __init__(self, text, ids_cell, drafted: Dict[Tuple[int, str], str], days: Dict[int, date], on: date):
        self.players = _ids(ids_cell)
        self.picks: List[Tuple[str, Optional[tuple]]] = []
        self.faab = 0.0
        self.n_player_text = 0
        for a in str(text or "").split("; "):
            a = a.strip()
            if not a or a == "nan":
                continue
            m = FA_RE.match(a)
            if m:
                self.faab += float(m.group(1))
                continue
            m = PICK_RE.match(a)
            if m:
                y, rn, sl = int(m.group(1)), int(m.group(2)), m.group(3)
                # the KTC pass's future-pick rule: round average before the season that sets the order
                # (the build reads the slot from the pick's original owner; a pick shown without "(player)" has
                # none there, so it is valued at its round average too)
                lab = (f"{y} {rn}.??" if (on < season_start(y - 1) or not sl or not m.group(4))
                       else f"{y} {rn}.{int(sl):02d}")
                pid = drafted.get((y, f"{rn}.{int(sl):02d}")) if sl else None
                dd = days.get(y)
                self.picks.append((lab, (pid, dd) if pid else None))
                continue
            self.n_player_text += 1

    @property
    def n(self) -> int:
        return len(self.players) + len(self.picks) + (1 if self.faab > 0 else 0)

    def values(self, V: Values, target) -> list:
        out = []
        for sid in self.players:
            v = V.player(sid, target)
            if v is not None:
                out.append(v)
        for lab, dk in self.picks:
            v = V.pick(lab, dk, target)
            if v is not None:
                out.append(v)
        if self.faab > 0:
            out.append(V.cash(self.faab))
        return out


def trade_sides(tr: pd.DataFrame, rp: pd.DataFrame, pa: pd.DataFrame):
    drafted = drafted_ids(rp)
    days = draft_days(pa)
    out = []
    for rd in tr.to_dict("records"):
        on = _utc_day(rd["Date"])
        out.append((Assets(rd.get("Assets received"), rd.get("Player IDs received"), drafted, days, on),
                    Assets(rd.get("Assets sent"), rd.get("Player IDs sent"), drafted, days, on)))
    return out


def _spec(cell) -> Optional[list]:
    if not isinstance(cell, str) or not cell.startswith("["):
        return None
    out = []
    for lab, dk in json.loads(cell):
        out.append((lab, (dk[0], date.fromisoformat(dk[1])) if dk else None))
    return out


def use_pick_specs(sides, tr: pd.DataFrame, side_tr: Optional[pd.DataFrame]) -> int:
    """replace the parsed picks with the build's own (label, drafted) per pick, when the side output carries them
    (`_fd_pk_recv` / `_fd_pk_sent`): the slot and drafted player come from snapshot metadata the text can omit"""
    if side_tr is None or "_fd_pk_recv" not in side_tr:
        return 0
    cols = ["Team", "Date", "Assets received"]
    m = dict(zip(_key(side_tr, cols), zip(side_tr["_fd_pk_recv"], side_tr["_fd_pk_sent"])))
    n = 0
    for k, (rs, ss) in zip(_key(tr, cols), sides):
        if k in m:
            r, s_ = _spec(m[k][0]), _spec(m[k][1])
            if r is not None and s_ is not None:
                rs.picks, ss.picks = r, s_
                n += 1
    return n


# ------------------------------------------------------------------------------------------- the twins

def _diff(V, target, today, rs: Assets, ss: Assets) -> Optional[float]:
    if target > today or (rs.n == 0 and ss.n == 0):
        return None
    rv, sv = rs.values(V, target), ss.values(V, target)
    if (rs.n and not rv) or (ss.n and not sv):
        return None
    return round(FH.depth_adjusted(rv) - FH.depth_adjusted(sv), 1)


def trade_twins(tr, sides, V: Values, today: date) -> pd.DataFrame:
    rows = []
    for rd, (rs, ss) in zip(tr.to_dict("records"), sides):
        on = _utc_day(rd["Date"])
        try:
            season = int(rd["Season"])
        except Exception:
            season = None
        o = {}
        refs = [("at deal time", on)]
        if season is not None:
            refs += [("at end of season", max(championship_monday(season), on)),
                     ("1 year later", plus_years(on, 1)), ("2 years later", plus_years(on, 2))]
        for lab, d in refs:
            o[f"FAAB Value difference {lab}"] = _diff(V, d, today, rs, ss)
        if on <= today:
            pv = [V.pick(l, dk, on) for l, dk in rs.picks]
            pv = [x for x in pv if x is not None]
            o["Pick FAAB Value received"] = round(sum(pv), 1) if pv else None
            chg, hits = 0.0, 0
            for l, dk in rs.picks:
                post = season_start(int(l[:4]))
                if post > today:
                    continue
                b, a = V.pick(l, dk, on), V.pick(l, dk, post)
                if b is None or a is None:
                    continue
                chg += a - b
                hits += 1
            o["Change in pick FAAB Value at draft time"] = round(chg, 1) if hits else None
        rows.append(o)
    return pd.DataFrame(rows, index=tr.index)


def add_drop_twins(ad, V: Values, today: date) -> pd.DataFrame:
    rows = []
    for rd in ad.to_dict("records"):
        on = _utc_day(rd["Date"])
        try:
            season = int(rd["Season"])
        except Exception:
            season = None
        a_id = (_ids(rd.get("Player Added ID")) or [None])[0]
        d_id = (_ids(rd.get("Player Dropped ID")) or [None])[0]
        o = {}
        for lab in TX_LABELS:
            if lab == "at deal time":
                ref = on
            elif lab == "at end of season":
                if season is None:
                    continue
                ref = max(championship_monday(season), on)
            else:
                ref = plus_years(on, 1 if lab == "1 year later" else 2)
            if ref > today:
                continue
            va = V.player(a_id, ref) if a_id else None
            vd = V.player(d_id, ref) if d_id else None
            o[f"FAAB Value of player added {lab}"] = round(va, 1) if va is not None else None
            o[f"FAAB Value of player dropped {lab}"] = round(vd, 1) if vd is not None else None
            o[f"Net FAAB Value {lab}"] = FH.net(va, vd)
        rows.append(o)
    return pd.DataFrame(rows, index=ad.index)


def pick_twins(picks, V: Values, today: date, days: Dict[int, date]) -> pd.DataFrame:
    rows = []
    for rd in picks.to_dict("records"):
        y = re.match(r"\s*(\d{4})", str(rd.get("Year")))
        if y is None and "startup" in str(rd.get("Year")).lower():
            y = re.match(r"(\d{4})", "2020")
        sid = (_ids(rd.get("Player Picked ID")) or [None])[0]
        o = {}
        if y and sid:
            yr = int(y.group(1))
            anchor = days.get(yr, date(yr, 8, 28))
            targets = [anchor, date(yr + 1, 2, 1)] + [plus_years(anchor, n) for n in (1, 2, 3, 4)]
            for ci, (lab, t) in enumerate(zip(PICK_CKPTS, targets)):
                if t > today:
                    continue
                v = V.player_entering(sid, t) if ci == 0 else V.player(sid, t)
                o[f"FAAB Value {lab}"] = round(v, 1) if v is not None else None
        rows.append(o)
    return pd.DataFrame(rows, index=picks.index)


def _slot(number) -> Optional[Tuple[int, int]]:
    m = re.match(r"\s*(\d+)\.(\d+)", str(number))
    return (int(m.group(1)), int(m.group(2))) if m else None


def pick_adjust_rookie(rp: pd.DataFrame, col: str, early: Optional[pd.Series] = None) -> pd.Series:
    """the build's rookie 'Pick-adjusted Difference in X': X minus the mean of X over the 3-slot window (from
    overall pick 5 on, the mean of the three slot means and the outer pair's average)"""
    vals = _num(rp[col])
    rs_of, by_slot = {}, {}
    mx_s = mx_r = 0
    for i in rp.index:
        rs = _slot(rp.at[i, "Number"])
        if rs is None:
            continue
        R, S = rs
        if (R, S) == (2, 9):
            R, S = 2, 8
        elif R == 5:
            R, S = 4, 8
        rs_of[i] = (R, S)
        mx_s, mx_r = max(mx_s, S), max(mx_r, R)
        if early is not None and bool(early.get(i, False)):
            continue
        if pd.notna(vals[i]):
            by_slot.setdefault((R, S), []).append(float(vals[i]))
    rsize = mx_s or 1
    maxpos = rsize * (mx_r or 1)

    def window(R, S):
        p = (R - 1) * rsize + S
        ps = [1, 2] if p <= 1 else ([maxpos - 2, maxpos - 1, maxpos] if p >= maxpos else [p - 1, p, p + 1])
        return [((q - 1) // rsize + 1, (q - 1) % rsize + 1) for q in ps if 1 <= q <= maxpos]

    out = pd.Series(np.nan, index=rp.index)
    for i, (R, S) in rs_of.items():
        my = vals[i]
        if pd.isna(my):
            continue
        ws = window(R, S)
        p0 = (R - 1) * rsize + S
        if p0 >= 5 and len(ws) == 3:
            means = [(sum(by_slot[w]) / len(by_slot[w])) if by_slot.get(w) else None for w in ws]
            if means[0] is not None and means[2] is not None:
                terms = [m for m in means if m is not None] + [(means[0] + means[2]) / 2.0]
                out[i] = round(my - sum(terms) / len(terms), 4)
            else:
                pres = [m for m in means if m is not None]
                if pres:
                    out[i] = round(my - sum(pres) / len(pres), 4)
        else:
            ref = [v for w in ws for v in by_slot.get(w, [])]
            if ref:
                out[i] = round(my - sum(ref) / len(ref), 4)
    return out


def pick_adjust_non_rookie(nr: pd.DataFrame, col: str, rsize: int = 8) -> pd.Series:
    """the build's non-rookie version: X minus the mean of X over the 8 nearest picks on the same side of the
    startup / vet seam (vet positions continue after the startup's last)"""
    vals = _num(nr[col])
    vet = nr.Year.astype(str).str.contains("vet", case=False)
    pos = {}
    for i in nr.index:
        rs = _slot(nr.at[i, "Number"])
        if rs:
            pos[i] = (rs[0] - 1) * rsize + rs[1]
    su_max = max([p for i, p in pos.items() if not vet[i]] or [0])
    for i in pos:
        if vet[i]:
            pos[i] += su_max
    out = pd.Series(np.nan, index=nr.index)
    items = list(pos.items())
    for i, p0 in items:
        if pd.isna(vals[i]):
            continue
        near = sorted((abs(p - p0), j) for j, p in items if j != i and vet[j] == vet[i])[:8]
        ref = [float(vals[j]) for _, j in near if pd.notna(vals[j])]
        if ref:
            out[i] = round(float(vals[i]) - sum(ref) / len(ref), 4)
    return out


def current_season_weeks(tw: pd.DataFrame) -> Tuple[int, int]:
    y = _num(tw.Year)
    cur = int(y.max())
    wk = _num(tw.Week[y == cur])
    return cur, int(wk.max()) if wk.notna().any() else 0


def early_class(rp: pd.DataFrame, tw: Optional[pd.DataFrame]) -> pd.Series:
    """the current rookie class before week 8 (held out of the pools, O-Score withheld)"""
    m = pd.Series(False, index=rp.index)
    if tw is None:
        return m
    cur, wk = current_season_weeks(tw)
    if wk >= ROOKIE_OSCORE_MIN_WEEK:
        return m
    return rp.Year.astype(str).str.extract(r"(\d{4})")[0].astype(float).eq(cur).fillna(False)


# ------------------------------------------------------------------------------------------- the derived columns
# Recomputed from the build's side output (exports/raw/faab_derived/), which carries every component exactly as
# the build's O-Score read it (the sheets lose N/A on some: a never-rostered add's '% of starts' exports as 0).

def load_side(d: Path = OUT) -> Dict[str, pd.DataFrame]:
    d = Path(d)
    return {p.stem: pd.read_csv(p, low_memory=False) for p in sorted(d.glob("*.csv"))}


def _pct(s: pd.Series) -> pd.Series:
    """the build's O-Score percentile: average ties, but an exact 0 goes to the bottom of its tie"""
    avg = s.rank(pct=True, method="average") * 100.0
    mn = s.rank(pct=True, method="min") * 100.0
    return avg.where(s != 0, mn)


def most_recent(df: pd.DataFrame, cols: Sequence[str]) -> pd.Series:
    """the latest populated value of cols (ordered latest -> earliest)"""
    out = pd.Series(np.nan, index=df.index)
    for c in cols:
        if c in df.columns:
            out = out.where(out.notna(), _num(df[c]))
    return out


def oscore(comps: Sequence[pd.Series], droppable: Sequence[int] = (), pool: Optional[pd.Series] = None) -> pd.Series:
    """the build's _add_oscore: mean of the components' percentiles (ranked inside `pool`), N/A unless every
    required component is present"""
    if pool is not None:
        comps = [c.where(pool) for c in comps]
    pcts = pd.concat([_pct(c) for c in comps], axis=1)
    req = [i for i in range(len(comps)) if i not in droppable]
    osc = pcts.mean(axis=1).where(pcts.iloc[:, req].notna().all(axis=1)).round(1)
    return osc if pool is None else osc.where(pool)


def ktc_names(kind: str) -> Dict[str, List[str]]:
    """the KTC-unit columns each O-Score reads, latest -> earliest; kind 'ktc' or 'faab' (the twins)"""
    base = {
        "trades": [f"KTC value difference {l}" for l in reversed(TX_LABELS)],
        "add_drops": [f"KTC value of player added {l}" for l in reversed(TX_LABELS)],
        "net": [f"Net KTC value {l}" for l in reversed(TX_LABELS)],
        "picks": [f"Pick-adjusted Difference in KTC {c}" for c in reversed(PICK_CKPTS)],
    }
    if kind == "faab":
        base = {k: [faab_twin(c) for c in v] for k, v in base.items()}
    return base


def faab_twin(col: str) -> str:
    from formula_equations import faab_twin as ft
    return ft(col)


def trade_impact(tr: pd.DataFrame, wins, pick_value) -> pd.Series:
    """the build's Trade impact score: 0.6 x the weighted z-composite (population sd) of Wins added (x2.0),
    Avg net points (x0.8), Trade addition value (x0.5), Pick value received (x0.5), Asset difference in average
    age (x-0.3); Wins added and Pick value received count 0 when blank, the rest drop out when blank"""
    wins = wins if wins is not None else np.nan
    pick_value = pick_value if pick_value is not None else np.nan
    specs = [(wins, 2.0, True), (tr["Avg net points"], 0.8, False), (tr["Trade addition value"], 0.5, False),
             (pick_value, 0.5, True), (tr["Asset difference in average age"], -0.3, False)]
    score = pd.Series(0.0, index=tr.index)
    for x, w, fill0 in specs:
        x = _num(pd.Series(x, index=tr.index))
        if fill0:
            x = x.fillna(0.0)
        v = x.dropna()
        mu = float(v.mean()) if len(v) else 0.0
        sd = float(np.sqrt(((v - mu) ** 2).mean())) if len(v) else 1.0
        score = score + (w * (x - mu) / (sd or 1.0)).fillna(0.0)
    return (0.6 * score).round(1)


def oscores(side: Dict[str, pd.DataFrame], kind: str, inputs: Optional[Dict[str, pd.DataFrame]] = None,
            tis: Optional[pd.Series] = None, early: Optional[pd.Series] = None) -> Dict[str, pd.Series]:
    """O-Score on trades, add_drops (pure drops in their own pool, halved) and picks (rookie and non-rookie pools,
    the non-rookie de-trend). `inputs[sheet]` overrides the KTC-unit columns (e.g. recomputed twins under a
    transform), aligned to the side rows; `tis` the Trade impact score; `early` the withheld current class."""
    import pick_history
    K = ktc_names(kind)
    src = {k: (inputs or {}).get(k, side[k]) for k in ("trades", "add_drops", "picks")}
    out = {}
    tr = side["trades"]
    out["trades"] = oscore([_num(tr["Avg net points adjusted by position"]), _num(tr["Trade addition value"]),
                            most_recent(src["trades"], K["trades"]),
                            _num(tis if tis is not None else tr["Trade impact score"])])
    ad = side["add_drops"]
    o = oscore([_num(ad["Avg net points adjusted by position"]), _num(ad["Player addition value"]),
                most_recent(src["add_drops"], K["add_drops"]), _num(ad["% of starts made while rostered"])],
               droppable=(3,))
    pure = ad["Pure drop"].astype(str).str.lower().eq("true")
    comps = [most_recent(src["add_drops"], K["net"]).fillna(0.0), -_num(ad["Dropped avg points"]),
             -_num(ad["Dropped total points"]), _num(ad["Player addition value"])]
    pc = pd.concat([c.where(pure).rank(pct=True, method="average") * 100.0 for c in comps], axis=1)
    o[pure] = (pc.mean(axis=1) / 2.0).round(1)[pure]
    out["add_drops"] = o
    pk = side["picks"]
    nr = pk["Non-rookie"].astype(str).str.lower().eq("true")
    comps = [_num(pk["Avg points added adjusted by position"]),
             _num(pk["Pick-adjusted Difference in Player addition value"]),
             most_recent(src["picks"], K["picks"]),
             _num(pk["Pick-adjusted Difference in Avg career PPG adjusted by position"])]
    o = oscore(comps, droppable=(1,), pool=~nr)
    o = o.where(~nr, oscore(comps, droppable=(1,), pool=nr))
    if early is not None:
        o[early.reindex(pk.index).fillna(False).astype(bool)] = np.nan
    q = pk.assign(**{"O-Score": o})
    pick_history.detrend_non_rookie_oscore(q, nr)
    out["picks"] = _num(q["O-Score"])
    return out


SKILL_K, SKILL_PRIOR, NONROOKIE_SKILL_WEIGHT = 5.0, 50.0, 0.5


def _skill(team, year, o, w):
    d = pd.DataFrame({"t": team.astype(str).values, "y": year.astype(str).str.extract(r"(\d{4})")[0].values,
                      "o": _num(o).values, "w": np.asarray(w, dtype=float)}).dropna(subset=["o"])
    d["wo"] = d.w * d.o
    shrink = lambda g: ((g.wo + SKILL_K * SKILL_PRIOR) / (g.w + SKILL_K)).round(1)
    ga = d.groupby("t")[["wo", "w"]].sum()
    gy = d.dropna(subset=["y"]).groupby(["t", "y"])[["wo", "w"]].sum()
    return {(t, int(y)): v for (t, y), v in shrink(gy).items()}, shrink(ga).to_dict()


def skills(side: Dict[str, pd.DataFrame], osc: Dict[str, pd.Series]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Drafting / Trading / Add/Drop skill: weighted O-Score means shrunk to 50 by 5 (non-rookie picks x0.5,
    pure drops x1/3). The 2020 startup's Year is not a season, so it reaches the all-time grade only."""
    pk, tr, ad = side["picks"], side["trades"], side["add_drops"]
    nr = pk["Non-rookie"].astype(str).str.lower().eq("true")
    pure = ad["Pure drop"].astype(str).str.lower().eq("true")
    specs = {"Drafting skill": (pk["Final Team"], pk.Year, osc["picks"], np.where(nr, NONROOKIE_SKILL_WEIGHT, 1.0)),
             "Trading skill": (tr.Team, tr.Season, osc["trades"], np.ones(len(tr))),
             "Add/Drop skill": (ad.Team, ad.Season, osc["add_drops"], np.where(pure, 1.0 / 3.0, 1.0))}
    ty, ta = side["team_year"][["Team", "Year"]].copy(), side["team_all_time"][["Team"]].copy()
    for name, (t, y, o, w) in specs.items():
        ym, am = _skill(t, y, o, w)
        yrs = _num(ty.Year)
        ty[name] = [ym.get((str(a), int(b))) if pd.notna(b) else None for a, b in zip(ty.Team, yrs)]
        ta[name] = [am.get(str(a)) for a in ta.Team]
    return ty, ta


def reproduce(side: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, int]]:
    """the check behind every FAAB version: recompute the KTC and the FAAB O-Scores, Trade impact scores and
    skills from the side output's components and count the rows that differ from what the build wrote"""
    out = {}
    tr = side["trades"]
    for kind, sfx in (("ktc", ""), ("faab", SUFFIX)):
        tis = trade_impact(tr, tr.get("Wins added" + sfx),
                           tr.get("Pick value received" if kind == "ktc" else "Pick FAAB Value received"))
        osc = oscores(side, kind, tis=tis)
        ty, ta = skills(side, osc)
        res = {"Trade impact score": _ndiff(tis, tr["Trade impact score" + sfx])}
        for sh in ("trades", "add_drops", "picks"):
            res[f"O-Score {sh}"] = _ndiff(osc[sh], side[sh]["O-Score" + sfx])
        for nm in ("Drafting skill", "Trading skill", "Add/Drop skill"):
            res[nm] = _ndiff(ty[nm], side["team_year"][nm + sfx]) + _ndiff(ta[nm], side["team_all_time"][nm + sfx])
        out[kind] = res
    return out


def _ndiff(a, b, tol: float = 0.051) -> int:
    a, b = _num(pd.Series(a).reset_index(drop=True)), _num(pd.Series(b).reset_index(drop=True))
    return int((((a - b).abs() > tol) | (a.isna() != b.isna())).sum())


# ------------------------------------------------------------------------------------------- comparing

PAIRS = {
    "trades": ["Wins added", "Wins added per season", "Trade impact score", "O-Score"],
    "add_drops": ["Wins added", "Wins added per season", "O-Score"],
    "picks": ["O-Score"],
    "player_additions": ["Price paid (FAAB)", "Points above expectation (total)", "Points above expectation (rate)"],
    "team_year": ["Drafting skill", "Trading skill", "Add/Drop skill"],
    "team_all_time": ["Drafting skill", "Trading skill", "Add/Drop skill"],
}


def _spearman(a: pd.Series, b: pd.Series) -> float:
    return float(a.rank().corr(b.rank())) if len(a) > 2 else float("nan")


def compare(side: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """each KTC-derived column against its FAAB version, on the rows where both exist"""
    rows = []
    for sh, cols in PAIRS.items():
        df = side.get(sh)
        if df is None:
            continue
        for c in cols:
            if c not in df.columns or c + SUFFIX not in df.columns:
                continue
            a, b = _num(df[c]), _num(df[c + SUFFIX])
            m = a.notna() & b.notna()
            a, b = a[m], b[m]
            sd = float(a.std()) if len(a) > 1 else float("nan")
            rows.append({"sheet": sh, "column": c, "rows": int(m.sum()),
                         "only KTC": int((_num(df[c]).notna() & _num(df[c + SUFFIX]).isna()).sum()),
                         "only FAAB": int((_num(df[c]).isna() & _num(df[c + SUFFIX]).notna()).sum()),
                         "identical": int(((a - b).abs() < 1e-9).sum()),
                         "KTC mean": round(float(a.mean()), 2), "FAAB mean": round(float(b.mean()), 2),
                         "mean |diff|": round(float((a - b).abs().mean()), 3),
                         "mean |diff| / sd": round(float((a - b).abs().mean()) / sd, 3) if sd else None,
                         "pearson": round(float(a.corr(b)), 3), "spearman": round(_spearman(a, b), 3)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- one global transform
# The search: every FAAB $ value v -> scale * v ** power, the same map for every player, pick and date, and the
# FAAB versions above recomputed under it. The twins come from the exports + history (`*_twins`, which reproduce
# the build's at the identity); Wins added keeps its identity-transform FAAB lineage (a later trade's share moves
# with the transform only through the ratio of two sides' values, and recomputing it means rerunning every
# lineup: flagged in the report, not hidden).

def _key(df: pd.DataFrame, cols: Sequence[str]) -> pd.Series:
    # blanks key as "" (pandas 3 keeps NaN through astype(str), which "|".join cannot take)
    k = df[list(cols)].apply(lambda c: c.map(lambda v: "" if pd.isna(v) else str(v))).agg("|".join, axis=1)
    return k + "#" + k.groupby(k).cumcount().astype(str)


def align(side_df: pd.DataFrame, export_df: pd.DataFrame, frame: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    """`frame` (aligned to export rows) re-indexed to the side rows, joined on `cols` (+ order within ties)"""
    ke = _key(export_df, cols)
    ks = _key(side_df, cols)
    f = frame.copy()
    f.index = ke.values
    return f.reindex(ks.values).set_axis(side_df.index)


def _pick_key(df: pd.DataFrame, nonrookie: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"n": df["Number"].astype(str).str.strip(), "p": df["Player Picked"].astype(str).str.strip(),
                         "r": nonrookie.astype(bool).astype(str).values}, index=df.index)


class Search:
    """everything a transform needs, loaded once: exports, side output, history, the PAE inputs"""

    def __init__(self, exports: Path, side_dir: Path, today: date, fidx: Optional[FH.FaabIndex] = None):
        self.X = load(exports)
        self.side = load_side(side_dir)
        self.today = today
        self.f = fidx or FH.FaabIndex.load()
        X = self.X
        self.sides = trade_sides(X["trades"], X["rookie_picks"], X["player_additions"])
        use_pick_specs(self.sides, X["trades"], self.side.get("trades"))
        self.days = draft_days(X["player_additions"])
        self.early = None
        pae = Path(exports) / "raw" / "pae_additions.json.gz"
        self.adds = None
        if pae.exists():
            from . import expectation_recheck as RC
            self.adds = RC.load_additions(str(pae))

    def twins(self, V: Values) -> Dict[str, pd.DataFrame]:
        X, S = self.X, self.side
        out = {}
        tt = trade_twins(X["trades"], self.sides, V, self.today)
        out["trades"] = align(S["trades"], X["trades"], tt, ["Team", "Date", "Assets received"])
        at = add_drop_twins(X["add_drops"], V, self.today)
        out["add_drops"] = align(S["add_drops"], X["add_drops"], at,
                                 ["Team", "Date", "Player Added", "Player Dropped"])
        frames = []
        for sh in ("rookie_picks", "non_rookie_picks"):
            p = X[sh]
            pt = pick_twins(p, V, self.today, self.days)
            for c in [f"FAAB Value {k}" for k in PICK_CKPTS]:
                if c not in pt:
                    pt[c] = np.nan
                pt[f"Pick-adjusted Difference in {c}"] = (
                    pick_adjust_rookie(p.assign(**{c: pt[c]}), c) if sh == "rookie_picks"
                    else pick_adjust_non_rookie(p.assign(**{c: pt[c]}), c))
            frames.append((p, pt, sh == "non_rookie_picks"))
        pk = S["picks"]
        nr = pk["Non-rookie"].astype(str).str.lower().eq("true")
        ks = _key(_pick_key(pk, nr), ["n", "p", "r"])
        allf = pd.concat([pt.set_axis(_key(_pick_key(p, pd.Series(flag, index=p.index)), ["n", "p", "r"]).values)
                          for p, pt, flag in frames])
        out["picks"] = allf.reindex(ks.values).set_axis(pk.index)
        return out

    def prices(self, V: Values) -> pd.Series:
        """Price paid (FAAB) with every traded asset at its (transformed) FAAB value, aligned to the side's
        player_additions rows; waiver / FA bids unchanged; rookie picks at the FAAB slot price"""
        X, S = self.X, self.side
        pa = S["player_additions"]
        out = _num(pa["Price paid (FAAB)"]).where(pa["Addition type"].isin(["Waiver", "Free agency"]))
        tr = X["trades"]
        idx = {}
        for i, (rd, (rs, ss)) in enumerate(zip(tr.to_dict("records"), self.sides)):
            on = _utc_day(rd["Date"])
            sent = []
            for sid in ss.players:
                sent.append(V.player(sid, on))
            sent += [V.pick(l, dk, on) for l, dk in ss.picks]
            if ss.faab > 0:
                sent.append(V.cash(ss.faab))
            if any(v is None for v in sent):
                continue
            recv = [(("p", sid), V.player(sid, on)) for sid in rs.players]
            recv += [(("k", l), V.pick(l, dk, on)) for l, dk in rs.picks]
            if rs.faab > 0:
                recv.append((("f", ""), V.cash(rs.faab)))
            from .acquisition import value_shares
            sh = value_shares([v for _, v in recv])
            if sh is None:
                continue
            for j, (k, v) in enumerate(recv):
                if k[0] == "p":
                    idx[(str(rd["Team"]), str(rd["Date"])[:10], k[1])] = sum(sent) * sh[j]
        pid = pa["Player ID"].astype(str).str.replace(r"\.0$", "", regex=True)
        for i in pa.index[pa["Addition type"] == "Trade"]:
            v = idx.get((str(pa.at[i, "Team"]), str(pa.at[i, "Date"])[:10], pid[i]))
            out[i] = v if v is not None else np.nan
        dr = pa.index[(pa["Addition type"] == "Draft") & (pa["Channel"] == "rookie")]
        fd = _num(pa[PRICE_FD]) if PRICE_FD in pa else None
        for i in dr:
            base = fd[i] if fd is not None else np.nan
            out[i] = V.t(base) if pd.notna(base) and base != 20.0 else base
        return out

    def pae(self, price: pd.Series) -> Optional[pd.DataFrame]:
        """points above expectation refit with the trade channel priced at `price`"""
        if self.adds is None:
            return None
        from . import acquisition as ACQ
        pa = self.side["player_additions"]
        adds = []
        for n, a in enumerate(self.adds):
            p = a.p
            if a.ch == "trade":
                v = price.iloc[n] if n < len(price) else np.nan
                p = ACQ.price_feature("trade", trade_faab=float(v)) if pd.notna(v) else None
            adds.append(ACQ.Addition(key=a.key, ch=a.ch, p=p, pos=a.pos, held=a.held, cf=a.cf, noff=a.noff, s0=a.s0))
        r = ACQ.points_above_expectation(adds)
        return pd.DataFrame({c: [(r.get(a.key) or {}).get(c) for a in self.adds]
                             for c in (ACQ.TOTAL_COLUMN, ACQ.RATE_COLUMN)}, index=pa.index[:len(self.adds)])

    def run(self, t: Transform, with_pae: bool = True) -> Dict[str, pd.DataFrame]:
        """the FAAB versions under transform t, in the side output's layout (columns '<col> (FAAB values)')"""
        V = Values(self.f, t)
        S = self.side
        tw = self.twins(V)
        tr = S["trades"]
        tis = trade_impact(tr, tr["Wins added" + SUFFIX], tw["trades"]["Pick FAAB Value received"])
        osc = oscores(S, "faab", inputs=tw, tis=tis)
        ty, ta = skills(S, osc)
        out = {"trades": pd.DataFrame({"Trade impact score": tis, "O-Score": osc["trades"]}),
               "add_drops": pd.DataFrame({"O-Score": osc["add_drops"]}),
               "picks": pd.DataFrame({"O-Score": osc["picks"]}),
               "team_year": ty, "team_all_time": ta}
        if "player_additions" in S:
            pr = self.prices(V)
            pa = pd.DataFrame({"Price paid (FAAB)": pr})
            if with_pae:
                pe = self.pae(pr)
                if pe is not None:
                    pa = pa.join(pe)
            out["player_additions"] = pa
        return out


PRICE_FD = "Price paid (FAAB)" + SUFFIX


def score(side: Dict[str, pd.DataFrame], res: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """distance of each recomputed FAAB version to today's (KTC) column: mean |diff| / the column's sd, and
    Spearman, on rows where both exist (Price paid on log1p: dollars span four orders of magnitude)"""
    rows = []
    for sh, df in res.items():
        for c in df.columns:
            if c in ("Team", "Year"):
                continue
            k = _num(side[sh][c]) if c in side[sh] else None
            if k is None:
                continue
            f = _num(df[c])
            if c == "Price paid (FAAB)":
                k, f = np.log1p(k.clip(lower=0)), np.log1p(f.clip(lower=0))
            m = k.notna() & f.notna()
            if m.sum() < 3:
                continue
            sd = float(k[m].std()) or 1.0
            rows.append({"sheet": sh, "column": c, "rows": int(m.sum()),
                         "err": float((k[m] - f[m]).abs().mean()) / sd, "spearman": _spearman(k[m], f[m])})
    return pd.DataFrame(rows)
