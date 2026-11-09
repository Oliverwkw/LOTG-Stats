"""Testing a rule change against the evidence before it goes in a PR (`scripts/faab_value.py try-rule`).

A change is a set of parameter overrides (a new rule's strength, a constant). `trial` scores it against the current
params on the committed inputs and reports what a rule PR has to show (plan/notes/FAAB_VALUE_SYSTEM.md, "The noise
bar"):

  - the objective's parts (calls, trades, cuts, votes) and the calls it loses or gains;
  - trade error in the early and late halves of the trades (split at the median trade date);
  - how many trades get better / worse by more than 0.02 in log error;
  - far-off trades (one side over 2x the other, +$25 and +$100 on each side);
  - 5 random folds of the trades (how many improve) and a paired bootstrap P(worse) (2,000 draws).

`passes(result)` is the bar: trade error down by 0.007+, each half down by 0.003+, more trades better than worse,
and the total down. A shuffled-feature null run (2026-11-08, 1,372 random features) passed 0 times under this bar
and about 1 in 40 times under the old one (trade error down and total down). The bar says the evidence supports a
rule; it does not supply the reason, and every rule needs one (Oliver, 2026-11-09).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import faab_value as F

BAR_TRADES, BAR_HALF, BAR_MOVE = -0.007, -0.003, 0.02


def far_off(V, trades, pad=25.0):
    """trades with one side worth over twice the other (each side + pad)"""
    n = 0
    for _, sd in trades:
        a = [x[0] + V[x[1]].sum() for x in sd]
        n += (max(a) + pad) / (min(a) + pad) > 2
    return n


def score(ev, obj, p):
    d = obj(p, True); V = ev.values(p)[ev.pE]
    r = F.trade_err(V, ev.trades)[1]
    return dict(d=d, r=r, V=V, failed={n for n, x in d["tests"] if x}, far25=far_off(V, ev.trades), far100=far_off(V, ev.trades, 100.0))


class constants:
    """faab_value module constants set for the length of a `with` block (a rule's fixed shape: a floor, a gate)"""
    def __init__(self, cs): self.cs = dict(cs or {}); self.old = {}
    def __enter__(self):
        for k, v in self.cs.items(): self.old[k] = getattr(F, k); setattr(F, k, type(self.old[k])(v) if not isinstance(self.old[k], tuple) else tuple(str(v).split(",")))
    def __exit__(self, *a):
        for k, v in self.old.items(): setattr(F, k, v)


def trial(ev, obj, p, q, cs=None, seed=1, boot=2000):
    """q: the changed params (p with overrides), cs: faab_value constants changed with them. Returns a dict of the
    bar's numbers (q against p)."""
    a = score(ev, obj, p); V0 = ev.values(p)
    cache = getattr(obj, "cache", None)
    with constants(cs):
        if cs and cache is not None: cache.clear()      # characteristics() reads some constants (e.g. SUMMER_TO_DRAFT)
        b = score(ev, obj, q); V1 = ev.values(q)
    if cs and cache is not None: cache.clear()
    dates = np.array([str(t[0])[:10] for t in ev.trades]); split = sorted(dates)[len(dates) // 2]
    ea, eb = np.abs(a["r"]), np.abs(b["r"]); d = eb - ea
    rng = np.random.default_rng(seed); n = len(d)
    folds = [d[ix].mean() for ix in np.array_split(rng.permutation(n), 5)]
    bs = np.array([d[rng.integers(0, n, n)].mean() for _ in range(boot)])
    moved = int((np.abs(V1 - V0) > 1).sum())
    return dict(total=b["d"]["total"] - a["d"]["total"], calls=b["d"]["calls"] - a["d"]["calls"], trades=b["d"]["trades"] - a["d"]["trades"],
                cuts=b["d"]["cuts"] - a["d"]["cuts"], votes=b["d"]["votes"] - a["d"]["votes"],
                early=eb[dates < split].mean() - ea[dates < split].mean(), late=eb[dates >= split].mean() - ea[dates >= split].mean(),
                better=int((d < -BAR_MOVE).sum()), worse=int((d > BAR_MOVE).sum()),
                far25=(a["far25"], b["far25"]), far100=(a["far100"], b["far100"]),
                lost=sorted(b["failed"] - a["failed"]), gained=sorted(a["failed"] - b["failed"]),
                calls_passed=(len(a["d"]["tests"]) - len(a["failed"]), len(b["d"]["tests"]) - len(b["failed"])),
                folds_better=int(sum(f < 0 for f in folds)), p_worse=float(np.mean(bs >= 0)), rows_moved=moved,
                trade_moves=sorted(zip(d, dates, ea, eb), key=lambda x: x[0])[:5] + sorted(zip(d, dates, ea, eb), key=lambda x: x[0])[-5:])


def passes(t):
    return t["trades"] <= BAR_TRADES and t["early"] <= BAR_HALF and t["late"] <= BAR_HALF and t["better"] > t["worse"] and t["total"] < 0


def report(t, name=""):
    ok = "PASS" if passes(t) else "fail"
    lines = [f"{ok} {name}: total {t['total']:+.3f}  calls {t['calls']:+.3f} ({t['calls_passed'][0]} -> {t['calls_passed'][1]} pass)  "
             f"trades {t['trades']:+.4f} (early {t['early']:+.4f}, late {t['late']:+.4f}; {t['better']} better / {t['worse']} worse)  "
             f"cuts {t['cuts']:+.4f}  votes {t['votes']:+.4f}",
             f"     far-off trades +$25 {t['far25'][0]} -> {t['far25'][1]}, +$100 {t['far100'][0]} -> {t['far100'][1]}; "
             f"folds better {t['folds_better']}/5, bootstrap P(worse) {t['p_worse']:.3f}; rows moved {t['rows_moved']}"]
    if t["lost"]: lines.append(f"     calls lost: {'; '.join(t['lost'])}")
    if t["gained"]: lines.append(f"     calls gained: {'; '.join(t['gained'])}")
    return "\n".join(lines)


def parse_overrides(items):
    """['vet_floor=0.8', 'F.VET_FLOOR_PPG=8'] -> (params, module constants)"""
    ps, cs = {}, {}
    for it in items:
        k, v = it.split("=", 1)
        (cs if k.startswith("F.") else ps)[k[2:] if k.startswith("F.") else k] = float(v) if v.replace(".", "", 1).replace("-", "", 1).isdigit() else v
    return ps, cs
