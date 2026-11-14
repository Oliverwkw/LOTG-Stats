"""One fixed rookie-pick price schedule for the FAAB values: slot x weeks to that class's NFL draft (Oliver, 2026-11-11).

"For picks/faab, choose a standard value that they are worth at each time as is currently based on KTC (ex 1.01 in
June vs in January the year before are different etc), and keep that standard across all years." / "Do weeks not
months. As close to current values as possible."

A pick's price on date d is

    base[slot] * exp(shape(overall pick, w))      w = whole weeks from d to the NFL draft of the pick's class

- `base` (data/faab_value/pick_schedule_base.csv) is today's draft-day slot price: the median league price of each
  slot over every rookie draft held (2021-2026), the same numbers faab_inputs.Picks used for picks traded after the
  2026 draft. Frozen, so a 1.01 in 2022 and a 1.01 in 2026 at the same point of their cycles cost the same.
- `shape` (data/faab_value/pick_schedule_weeks.csv) is 0 at the league's usual draft week (NFL draft + 11 weeks,
  mid-July) and is KTC's pick history (dynasty-daddy's Early/Mid/Late 1st-4th, classes 2021-2029, 2021-04 to
  2026-11) reduced to one weekly curve per band of the board: band A = overall picks 1-12 (KTC's 1st-round
  quarters), band B = 13-32. Between the two band centres (overall 6.5 and 22.5) it is interpolated.
  * Within a year of the draft (w -52..+20) it is the class's own weekly series, de-trended by that tier's secular
    KTC drift (estimated across classes at the NFL draft week), median over the band's tiers, 5-week mean.
  * Further out it is chained from same-day quotes: the class one year later, on the same day, sits at
    f(w - 52) = f(w) + gap(w) (median of the band, 9-week mean), so KTC's year-to-year drift cancels.
  * Made non-decreasing up to the NFL draft (further from the draft is never worth more); after the NFL draft the
    KTC shape is kept as it is (the pre-draft bump eases off into the league draft).
  Football reason: a pick far from its draft is an unknown class at an unknown slot and a long wait, so it trades
  below the same pick close to its draft; the NFL draft fixes landing spots and the value peaks; it then settles to
  the drafted player's price by the league draft.
- Beyond the table (more than 156 weeks out) the shape keeps falling at its last year's step; after w = +20 it
  holds.

KTC is read only to DESIGN the curve (`fit_shape`, scripts/faab_pick_schedule.py). At run time the module reads the
two committed CSVs: if KTC vanished no price would change. A refit is a reviewed PR.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "faab_value"
BASE_CSV = "pick_schedule_base.csv"
WEEKS_CSV = "pick_schedule_weeks.csv"

LEAGUE_DRAFT_WEEK = 11          # weeks after the NFL draft where shape = 0 (league drafts 2023-26: +7, +11, +12, +11)
BAND_CENTRE = {"A": 6.5, "B": 22.5}
TEAMS = 8
NFL_DRAFT = {2020: "2020-04-23", 2021: "2021-04-29", 2022: "2022-04-28", 2023: "2023-04-27", 2024: "2024-04-25",
             2025: "2025-04-24", 2026: "2026-04-23"}
SLOT = re.compile(r"^(\d)\.(\d\d)$")


def nfl_draft(year: int) -> pd.Timestamp:
    """the NFL draft's first day; after the known ones, the Thursday in Apr 23-29 (every draft 2020-26 fits that)"""
    if int(year) in NFL_DRAFT:
        return pd.Timestamp(NFL_DRAFT[int(year)])
    d = pd.Timestamp(f"{int(year)}-04-23")
    return d + pd.Timedelta(days=(3 - d.dayofweek) % 7)


def weeks_to_draft(year: int, d) -> int:
    """whole weeks from the class's NFL draft to d (negative before it)"""
    return int(math.floor((pd.Timestamp(d).normalize() - nfl_draft(year)).days / 7))


def overall(slot: str) -> Optional[float]:
    """overall pick of an 'r.ss' slot in the 8-team draft (2.09, the toilet-bowl pick, sits at the 2.08's place)"""
    m = SLOT.match(str(slot))
    if m is None:
        return None
    r, s = int(m.group(1)), min(int(m.group(2)), TEAMS)
    return float((r - 1) * TEAMS + s)


class Schedule:
    def __init__(self, base: Dict[str, float], weeks: pd.DataFrame):
        self.base = {str(k): float(v) for k, v in base.items()}
        w = weeks.sort_values("week")
        self.w = w.week.to_numpy(int)
        self.f = {b: w[b].to_numpy(float) for b in BAND_CENTRE}
        lo = self.w[0]
        # beyond the table: the last year's step per week, carried on
        self.tail = {b: (self.f[b][min(52, len(self.w) - 1)] - self.f[b][0]) / 52.0 for b in BAND_CENTRE}
        self.lo, self.hi = int(lo), int(self.w[-1])

    @classmethod
    def load(cls, data: Path = DATA) -> "Schedule":
        data = Path(data)
        b = pd.read_csv(data / BASE_CSV, dtype={"slot": str})
        return cls(dict(zip(b.slot, b.price)), pd.read_csv(data / WEEKS_CSV))

    def band_shape(self, band: str, w: int) -> float:
        if w < self.lo:
            return float(self.f[band][0] - self.tail[band] * (self.lo - w))
        w = min(w, self.hi)
        return float(self.f[band][w - self.lo])

    def shape(self, ov: float, w: int) -> float:
        a, b = self.band_shape("A", w), self.band_shape("B", w)
        t = min(max((ov - BAND_CENTRE["A"]) / (BAND_CENTRE["B"] - BAND_CENTRE["A"]), 0.0), 1.0)
        return a + (b - a) * t

    def factor(self, slot: str, year: int, d) -> float:
        ov = overall(slot)
        return 1.0 if ov is None else math.exp(self.shape(ov, weeks_to_draft(year, d)))

    def table(self, year: int, d) -> Dict[str, float]:
        """{slot: price} for class `year`'s picks on date d (rounds 1-4; a 5.0X is a $20 FAAB buy, priced elsewhere)"""
        w = weeks_to_draft(year, d)
        out = {}
        for s, p in self.base.items():
            ov = overall(s)
            if ov is None or int(s[0]) >= 5:
                continue
            out[s] = p * math.exp(self.shape(ov, w))
        return out


_CACHE: Dict[str, Schedule] = {}


def load(data: Path = DATA) -> Schedule:
    k = str(Path(data))
    if k not in _CACHE:
        _CACHE[k] = Schedule.load(data)
    return _CACHE[k]


# --------------------------------------------------------------------------------------------- design (KTC, offline)

BANDS = {"A": [0, 1, 2], "B": [3, 4, 5, 6, 7]}      # KTC 12-team quarters: 0 = Early 1st ... 7 = Mid 3rd (overall 29-32)
WEEK_MIN, WEEK_MAX = -156, 20


def ktc_pick_frame(rows) -> pd.DataFrame:
    """rows of (class, 'early'|'mid'|'late', round, date, sf KTC) -> the frame fit_shape reads"""
    K = pd.DataFrame(rows, columns=["cls", "tier", "rnd", "date", "ktc"])
    K["date"] = pd.to_datetime(K.date)
    K["q"] = (K.rnd - 1) * 3 + K.tier.map({"early": 0, "mid": 1, "late": 2})
    K["w"] = [weeks_to_draft(c, d) for c, d in zip(K.cls, K.date)]
    K["lk"] = np.log(K.ktc)
    return K[K.ktc > 0]


def _smooth(s: pd.Series, k: int) -> pd.Series:
    return s.rolling(k, center=True, min_periods=1).mean()


def fit_shape(K: pd.DataFrame, done_classes=range(2021, 2027)) -> pd.DataFrame:
    """the weekly shape per band (see the module docstring); K from ktc_pick_frame"""
    W = K.groupby(["cls", "q", "w"]).lk.median().reset_index()
    done = W[W.cls.isin(list(done_classes))]
    lvl = done[done.w.between(-4, 4)].groupby(["q", "cls"]).lk.mean().reset_index()
    drift = {q: np.polyfit(x.cls, x.lk, 1)[0] for q, x in lvl.groupby("q") if x.cls.nunique() >= 3}
    inn = done[done.w.between(-52, WEEK_MAX)].copy()
    inn["lkd"] = inn.lk - inn.q.map(drift).fillna(0.0) * (inn.w / 52.0)
    ref = inn[inn.w.between(LEAGUE_DRAFT_WEEK - 1, LEAGUE_DRAFT_WEEK + 1)].groupby(["q", "cls"]).lkd.mean().rename("ref")
    inn = inn.join(ref, on=["q", "cls"]).dropna(subset=["ref"])
    f_in = (inn.lkd - inn.ref).groupby([inn.q, inn.w]).median().unstack(0)
    D = K.assign(wk=K.date.dt.to_period("W")).groupby(["q", "cls", "wk"]).agg(lk=("lk", "mean"), w=("w", "median")).reset_index()
    nxt = D.assign(cls=D.cls - 1).rename(columns={"lk": "lk1", "w": "w1"})
    J = D.merge(nxt, on=["q", "cls", "wk"])
    J["gap"], J["wb"] = J.lk1 - J.lk, J.w.round().astype(int)
    out = {}
    for b, qs in BANDS.items():
        fi = f_in[[q for q in qs if q in f_in]].median(axis=1).reindex(range(-52, WEEK_MAX + 1)).interpolate(limit_direction="both")
        fi = _smooth(fi, 5)
        fi = fi - fi.loc[LEAGUE_DRAFT_WEEK]
        g = J[J.q.isin(qs)].groupby("wb").gap.median().reindex(range(WEEK_MIN + 52, WEEK_MAX + 1))
        g = _smooth(g.interpolate(limit_direction="both"), 9)
        f = fi.to_dict()
        for w in range(-53, WEEK_MIN - 1, -1):
            f[w] = f[w + 52] + g.loc[w + 52]
        s = pd.Series(f).sort_index()
        pre = s.loc[:0].to_numpy()
        pre = np.minimum.accumulate(pre[::-1])[::-1]          # non-decreasing up to the NFL draft
        s.loc[:0] = pre
        out[b] = s.round(5)
    F = pd.DataFrame(out)
    F.index.name = "week"
    return F.reset_index()
