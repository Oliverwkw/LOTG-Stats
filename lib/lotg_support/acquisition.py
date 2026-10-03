"""Points above expectation for a player addition, and the price paid for it.

Two columns on `player_additions`, each "what he produced here minus what a
player bought at the same price would have produced over the same weeks":

* **Points above expectation (total)** — X minus Y, where Y is the sum, over
  the weeks he was rostered here (counted as elapsed weeks since acquisition),
  of what same-price, same-position acquisitions ACTUALLY scored in that elapsed
  week, whether or not their team still held them (assume nobody was ever cut
  or traded: a peer's week off the roster counts what he scored elsewhere —
  another league roster, or the NFL via nflverse — and 0 if he did not play).
  Answers "did this buy produce more than the average player bought at that
  price really did over the same span?".
* **Points above expectation (rate)** — the same, per rostered week: the total
  / weeks rostered.

X is every point he scored for this team during this tenure (started and
benched), position-adjusted with the build's per-season position factor and put
on one scoring scale across seasons (each week x the all-seasons league starter
average / that season's). A tenure with no rostered week is 0 in both columns.

Price, per channel, in that channel's own units (the model never compares one
channel with another):

=========  ==========================================  =====================
channel    model price                                 `Price paid (FAAB)`
=========  ==========================================  =====================
free       0 (free agency, and a $0 waiver claim)      0
waiver     log(1 + winning bid)                        the bid
rookie     log(overall pick)                           slot curve (draft-day KTC, isotonic) / KTC-per-$;
                                                       a 5.0X (a FAAB buy) is locked at $20
startup    log(overall pick); 2021 vet picks continue  same
           the startup board (#153+)
trade      log(1 + price / 1000)                       price / KTC-per-$
=========  ==========================================  =====================

A trade's price is the depth-taxed KTC of everything SENT (the build's own
`_depth_adjusted_value`), split across what was received by depth-taxed share:
each received asset's value x 0.6^(its rank on the side), over the side's total
of the same. Received picks take their share, so a player does not carry the
cost of draft capital that came back with him. (Chosen 2026-10 over a plain
KTC share, an equal split, Shapley over the depth-taxed value and no split:
best calibrated out of sample.)

Y's weekly rate is a Poisson regression fitted per channel on the whole
dataset (numpy IRLS, ridge 1.0), one row per addition per elapsed week from its
acquisition to the last week played: the elapsed week (log, with bends at
2/4/8/17/34/68 weeks), offseasons crossed, a piecewise-linear price ramp between
price quintiles constrained to move the right way (a better pick / a bigger bid
/ a bigger trade price never predicts less), price x time, and position x time.
Past the 95th percentile of a channel's elapsed weeks the rate is carried
forward ("if more players existed it would extend so").

The model refits every build, so every row moves slightly whenever a new week
lands — the columns are registered in `volatile_columns`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

RATE_COLUMN = "Points above expectation (rate)"
TOTAL_COLUMN = "Points above expectation (total)"
PRICE_COLUMN = "Price paid (FAAB)"
COLUMNS = (PRICE_COLUMN, RATE_COLUMN, TOTAL_COLUMN)

CHANNELS = ("free", "waiver", "rookie", "startup", "trade")
POSITIONS = ("QB", "RB", "WR", "TE")
DEPTH_FACTOR = 0.6
# A rookie-draft round-5 pick (5.0X) is a FAAB buy, locked at this price (user
# rule 2026-10-03). Not the 2020 startup's round 5, a real pick of a 19-round
# draft, which is priced off the slot curve like the rest of that board.
ROUND5_PICK_FAAB = 20.0
RIDGE = 1.0
TIME_KNOTS = np.log([2, 4, 8, 17, 34, 68])
PRICE_QUANTILES = (0, .2, .4, .6, .8, 1.0)
TAIL_QUANTILE = 0.95
MIN_KMAX = 8
# A better price moves the expectation this way: down the pick number, up the
# bid / trade price.
_PRICE_SIGN = {"rookie": -1, "startup": -1, "waiver": 1, "trade": 1}


# ---------------------------------------------------------------------------
# channel / price
# ---------------------------------------------------------------------------
def channel(addition_type: str, faab: Optional[float] = None,
            draft_kind: Optional[str] = None) -> Optional[str]:
    """Model channel of one addition, or None (a commissioner move has no
    price). `draft_kind` is "rookie" / "startup" / "vet" for a Draft row."""
    t = str(addition_type or "").strip().lower()
    if t == "commissioner":
        return None
    if t == "draft":
        return "rookie" if str(draft_kind or "").lower() == "rookie" else "startup"
    if t == "trade":
        return "trade"
    if t == "waiver" and (faab or 0) > 0:
        return "waiver"
    return "free"


def price_feature(ch: str, *, faab: Optional[float] = None, overall: Optional[float] = None,
                  trade_ktc: Optional[float] = None) -> Optional[float]:
    """The model's price for one addition (None = unpriceable)."""
    if ch == "free":
        return 0.0
    if ch == "waiver":
        return math.log1p(max(float(faab or 0.0), 0.0))
    if ch in ("rookie", "startup"):
        return math.log(max(float(overall), 1.0)) if overall is not None else None
    if ch == "trade":
        return math.log1p(max(float(trade_ktc), 0.0) / 1000.0) if trade_ktc is not None else None
    return None


def slot_price_curve(picks: Iterable[Tuple[float, float]]) -> Dict[int, float]:
    """{overall pick: price} from (overall pick, draft-day KTC of whoever went
    there) pairs: the mean per slot, made non-increasing in the pick number by
    isotonic regression (pool-adjacent-violators, weighted by picks per slot),
    so an earlier pick never costs less than a later one. Each pick's own value
    is in (unlike the leave-one-out pick-adjustment baseline, which priced
    1.04 above 1.01 in the 2020 startup). Slots with no value read off the
    curve by linear interpolation, held flat beyond its ends."""
    by: Dict[int, List[float]] = {}
    for s, v in picks:
        if s is None or v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        by.setdefault(int(s), []).append(float(v))
    if not by:
        return {}
    slots = sorted(by)
    # PAVA for a non-increasing fit: blocks of (sum, weight, first slot index).
    blocks: List[List[float]] = []
    for s in slots:
        blocks.append([sum(by[s]), float(len(by[s])), 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]:
            t = blocks.pop()
            blocks[-1][0] += t[0]
            blocks[-1][1] += t[1]
            blocks[-1][2] += t[2]
    fitted: List[float] = []
    for tot, w, n in blocks:
        fitted.extend([tot / w] * int(n))
    out = dict(zip(slots, fitted))
    for s in range(slots[0], slots[-1] + 1):
        if s not in out:
            out[s] = float(np.interp(s, slots, fitted))
    return out


def slot_price(curve: Dict[int, float], overall: Optional[float]) -> Optional[float]:
    """The curve's price for one pick (flat beyond the curve's ends)."""
    if not curve or overall is None:
        return None
    s = int(overall)
    if s in curve:
        return curve[s]
    return curve[min(curve)] if s < min(curve) else curve[max(curve)]


def depth_value(values: Iterable[float], factor: float = DEPTH_FACTOR) -> float:
    """The build's package value: best asset in full, each next x factor^i."""
    return sum(v * factor ** i for i, v in enumerate(sorted((float(x) for x in values), reverse=True)))


def depth_shares(values: Sequence[Optional[float]], factor: float = DEPTH_FACTOR) -> Optional[List[float]]:
    """Each received asset's share of the price: its value x factor^(rank on the
    side) over the side's total of the same. Shares sum to 1. None when any
    asset is unvalued (the split would be a guess); an all-zero side splits
    equally."""
    if not values or any(v is None for v in values):
        return None
    vals = [max(float(v), 0.0) for v in values]
    order = sorted(range(len(vals)), key=lambda i: -vals[i])
    w = [0.0] * len(vals)
    for rank, i in enumerate(order):
        w[i] = vals[i] * factor ** rank
    tot = sum(w)
    if tot <= 0:
        return [1.0 / len(vals)] * len(vals)
    return [x / tot for x in w]


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------
def _poisson(X: np.ndarray, y: np.ndarray, lam: float = RIDGE, it: int = 60) -> np.ndarray:
    b = np.zeros(X.shape[1])
    b[0] = math.log(max(float(np.mean(y)), 1e-6))
    for _ in range(it):
        eta = np.clip(X @ b, -20, 10)
        mu = np.exp(eta)
        z = eta + (y - mu) / mu
        nb = np.linalg.solve(X.T @ (X * mu[:, None]) + lam * np.eye(X.shape[1]), X.T @ (mu * z))
        if np.max(np.abs(nb - b)) < 1e-8:
            return nb
        b = nb
    return b


def _monotone_poisson(X: np.ndarray, y: np.ndarray, ramp_cols: Sequence[int], sign: int) -> np.ndarray:
    """Poisson fit whose price-ramp coefficients all point `sign`'s way: the
    most wrong-signed ramp is pinned at 0 and the fit repeated until none is."""
    keep = np.ones(X.shape[1], bool)
    b = np.zeros(X.shape[1])
    for _ in range(len(ramp_cols) + 1):
        b = np.zeros(X.shape[1])
        b[keep] = _poisson(X[:, keep], y)
        bad = [i for i in ramp_cols if keep[i] and sign * b[i] < 0]
        if not bad:
            break
        keep[min(bad, key=lambda i: sign * b[i])] = False
    return b


def _edges(p: np.ndarray) -> np.ndarray:
    return np.unique(np.quantile(p, PRICE_QUANTILES)) if len(p) else np.array([0.0])


def _ramps(p: np.ndarray, edges: np.ndarray) -> List[np.ndarray]:
    return [np.clip(p - lo, 0, hi - lo) for lo, hi in zip(edges[:-1], edges[1:])]


def _pos_cols(pos: np.ndarray) -> List[np.ndarray]:
    return [(pos == P).astype(float) for P in POSITIONS[1:]]


def _total_design(ch: str, k: np.ndarray, noff: np.ndarray, p: np.ndarray, pos: np.ndarray,
                  edges: np.ndarray, kmax: int) -> Tuple[np.ndarray, List[int]]:
    lk = np.minimum(np.log(k), math.log(kmax))
    no = np.minimum(noff, 3)
    cols = [np.ones(len(k)), lk] + [np.maximum(lk - c, 0) for c in TIME_KNOTS]
    cols += [(no == i).astype(float) for i in (1, 2, 3)]
    ramp_idx: List[int] = []
    if ch != "free":
        r = _ramps(p, edges)
        ramp_idx = list(range(len(cols), len(cols) + len(r)))
        cols += r + [p * lk, p * no]
    pc = _pos_cols(pos)
    cols += pc + [c * lk for c in pc]
    return np.column_stack(cols), ramp_idx


@dataclass
class Addition:
    """One priced addition and its weeks. `held` = [(elapsed week, X points)]
    for every rostered week of the tenure (elapsed week 1 = the first league
    week that ended on/after the pickup); `cf` = the counterfactual
    ("never cut") points for elapsed weeks 1..len(cf), the held weeks included;
    `noff` = offseasons crossed by each of those weeks (same length as cf).
    Held weeks lie within 1..len(cf)."""
    key: object
    ch: Optional[str]
    p: Optional[float]
    pos: str
    held: List[Tuple[int, float]] = field(default_factory=list)
    cf: List[float] = field(default_factory=list)
    noff: List[int] = field(default_factory=list)


def _norm_pos(pos: object) -> str:
    p = str(pos or "").upper()
    if p in POSITIONS:
        return p
    return "RB" if p == "FB" else "WR"


def points_above_expectation(additions: Sequence[Addition]) -> Dict[object, Dict[str, Optional[float]]]:
    """{key: {RATE_COLUMN, TOTAL_COLUMN}} for every addition. Both None when it
    has no channel or no price; both 0.0 with no rostered week."""
    out: Dict[object, Dict[str, Optional[float]]] = {}
    usable = [a for a in additions if a.ch in CHANNELS and a.p is not None]
    for a in additions:
        if a.ch not in CHANNELS or a.p is None:
            out[a.key] = {RATE_COLUMN: None, TOTAL_COLUMN: None}
        elif not a.held:
            out[a.key] = {RATE_COLUMN: 0.0, TOTAL_COLUMN: 0.0}
    for ch in CHANNELS:
        group = [a for a in usable if a.ch == ch]
        if not group:
            continue
        sign = _PRICE_SIGN.get(ch, 1)
        # --- total: one row per elapsed week, held or not ------------------
        tk, tn, tp, tpos, ty = [], [], [], [], []
        for a in group:
            n = len(a.cf)
            tk.extend(range(1, n + 1))
            tn.extend(a.noff[:n])
            tp.extend([a.p] * n)
            tpos.extend([_norm_pos(a.pos)] * n)
            ty.extend(a.cf)
        tot_b = None
        if tk:
            tk_a = np.array(tk, float)
            kmax = max(MIN_KMAX, int(np.quantile(tk_a, TAIL_QUANTILE)))
            tedges = _edges(np.array(tp, float))
            Xt, tidx = _total_design(ch, tk_a, np.array(tn, float), np.array(tp, float),
                                     np.array(tpos), tedges, kmax)
            tot_b = _monotone_poisson(Xt, np.array(ty, float), tidx, sign)
        for a in group:
            if not a.held:
                continue
            pos = _norm_pos(a.pos)
            x = sum(pts for _k, pts in a.held)
            n_held = len(a.held)
            total = None
            if tot_b is not None:
                ks = np.array([k for k, _ in a.held], float)
                no = np.array([a.noff[int(k) - 1] if int(k) - 1 < len(a.noff) else a.noff[-1]
                               for k in ks], float)
                Xa, _ = _total_design(ch, ks, no, np.full(len(ks), a.p), np.full(len(ks), pos),
                                      tedges, kmax)
                total = x - float(np.exp(np.clip(Xa @ tot_b, -20, 10)).sum())
            rate = round(total / n_held, 2) if total is not None else None
            total = round(total, 2) if total is not None else None
            out[a.key] = {RATE_COLUMN: rate, TOTAL_COLUMN: total}
    return out


# ---------------------------------------------------------------------------
# scale helpers shared by the build and recomputes
# ---------------------------------------------------------------------------
def season_scale(starter_avg_by_season: Dict[int, float], source_by_season: Dict[int, int]) -> Dict[int, float]:
    """{season: all-seasons league starter average / that season's}, so a point
    in any season is worth the same. The all-seasons average is over seasons on
    their own baseline (a season still borrowing the previous one's is left
    out of it)."""
    own = [v for y, v in starter_avg_by_season.items() if source_by_season.get(y, y) == y and v]
    overall = float(np.mean(own)) if own else 1.0
    return {int(y): (overall / v if v else 1.0) for y, v in starter_avg_by_season.items()}


def elapsed_calendar(weeks: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """League weeks in order — the clock 'elapsed week' counts on (offseason
    days are not weeks)."""
    return sorted({(int(y), int(w)) for y, w in weeks})


def first_elapsed_index(calendar: Sequence[Tuple[int, int]], week_end_day: Dict[Tuple[int, int], str],
                        pickup_day: str) -> int:
    """Index into `calendar` of the first week that ended on/after the pickup
    day (the tenure rule: a week counts once its last game is on/after the
    pickup). len(calendar) when none has yet."""
    for i, yw in enumerate(calendar):
        if str(week_end_day.get(yw, "")) >= str(pickup_day)[:10]:
            return i
    return len(calendar)
