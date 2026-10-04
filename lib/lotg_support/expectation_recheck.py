"""The points-above-expectation model's re-check: replay the build as of past seasons.

The expectation (`acquisition.points_above_expectation`) refits every build and
grows its own hinges and knots, but four settings were tuned on 2020-26 data
(EXPECTATION_RIDGE, MIN_TENURE_ADDITIONS, BASE_KNOT_WEEKS, TAIL_QUANTILE). This
module asks whether they still hold, the way they were chosen (2026-10-04,
plan/notes/POINTS_ABOVE_EXPECTATION.md "Tenure curves"): replay the build as it
would have run at the end of each season — only the additions and weeks known
then — fit out of fold, and score how well the expectation matched what peers
actually scored.

The build writes the model's inputs to exports/raw/`DUMP_NAME` (artifact only);
`scripts/pae_recheck.py` runs the replay on them, and the test suite checks the
latest season every build.

The build never scores a week that has not happened, so the replay is the test
that matters — not a forward forecast of unplayed seasons.
"""
from __future__ import annotations

import gzip
import json
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from . import acquisition as ACQ

DUMP_NAME = "pae_additions.json.gz"
FOLDS = 5
MIN_CELL_ADDITIONS = 25
# 2026-10-04 baseline, replayed as of the end of each season.
BASELINE = {2022: 0.040, 2023: 0.032, 2024: 0.034, 2025: 0.031, 2026: 0.038}
# Act (re-tune the four settings) past these, or on two rises in a row.
MAX_CALIBRATION = 0.06
MAX_EDGE_ERROR = 0.10


# ---------------------------------------------------------------------------
# the inputs
# ---------------------------------------------------------------------------
def dump_additions(additions: Sequence[ACQ.Addition], path: str) -> None:
    """Write the model's inputs (no names: key, channel, price, position, weeks)."""
    rows = [{"key": a.key, "ch": a.ch, "p": a.p, "pos": a.pos, "s0": a.s0,
             "held": [[int(k), float(x)] for k, x in a.held],
             "cf": [round(float(x), 4) for x in a.cf], "noff": [int(n) for n in a.noff]}
            for a in additions]
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, separators=(",", ":"), default=str)


def load_additions(path: str) -> List[ACQ.Addition]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rows = json.load(fh)
    return [ACQ.Addition(key=r["key"], ch=r["ch"], p=r["p"], pos=r["pos"], s0=r.get("s0"),
                         held=[(int(k), float(x)) for k, x in r["held"]],
                         cf=list(r["cf"]), noff=list(r["noff"])) for r in rows]


def as_of(additions: Sequence[ACQ.Addition], season: int) -> List[ACQ.Addition]:
    """The additions and weeks known at the end of `season`: additions whose
    first week was by then, their weeks cut at that season's end."""
    out = []
    for a in additions:
        if a.s0 is None or a.s0 > season:
            continue
        n = sum(1 for o in a.noff if a.s0 + o <= season)
        out.append(ACQ.Addition(key=a.key, ch=a.ch, p=a.p, pos=a.pos, s0=a.s0,
                                held=[(k, x) for k, x in a.held if k <= n],
                                cf=a.cf[:n], noff=a.noff[:n]))
    return out


# ---------------------------------------------------------------------------
# the replay
# ---------------------------------------------------------------------------
def out_of_fold(additions: Sequence[ACQ.Addition], folds: int = FOLDS) -> pd.DataFrame:
    """Every never-cut week of every priced addition with an out-of-fold
    expectation `mu` (folds by addition), fitted as the build fits it."""
    usable = [a for a in additions if a.ch in ACQ.CHANNELS and a.p is not None and a.cf]
    q = ACQ._price_percentile(usable)
    fold = {a.key: i % folds for i, a in enumerate(
        sorted(usable, key=lambda a: (zlib.crc32(str(a.key).encode()), str(a.key))))}
    parts = []
    for chans in (("free",), ACQ.PAID_CHANNELS):
        group = [a for a in usable if a.ch in chans]
        for f in range(folds):
            train = [a for a in group if fold[a.key] != f]
            test = [a for a in group if fold[a.key] == f]
            if not train or not test:
                continue
            predict = ACQ._fit_expectation(train, q)
            r = ACQ._rows(test, q)
            if predict is None or not len(r["k"]):
                continue
            keys = [a.key for a in test]
            parts.append(pd.DataFrame({
                "key": [keys[int(i)] for i in r["aid"]], "ch": r["ch"], "pos": r["pos"],
                "q": r["q"], "no": r["no"], "y": r["y"], "mu": predict(r)}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def calibration(rows: pd.DataFrame, min_additions: int = MIN_CELL_ADDITIONS) -> Optional[float]:
    """Expected-points-weighted RMS of log(actual / expected) over position x
    price tier (paid: the channel's dearest third vs the rest; free agency
    apart) x seasons since the move (1, 2, 3-4, 5+), over cells of at least
    `min_additions` additions. 0 is perfect; 0.04 ~ cells off by 4%."""
    if rows.empty:
        return None
    d = rows.assign(tier=np.where(rows.ch == "free", "free", np.where(rows.q > 2 / 3, "top", "rest")),
                    band=pd.cut(rows.no, [-1, 0, 1, 3, 1e9], labels=["1", "2", "3-4", "5+"]))
    g = d.groupby(["pos", "tier", "band"], observed=True)
    t = pd.DataFrame({"y": g.y.sum(), "mu": g.mu.sum(), "n": g.key.nunique()})
    t = t[(t.n >= min_additions) & (t.mu > 0)]
    if t.empty:
        return None
    lr = np.log(np.maximum(t.y, 1e-9) / t.mu)
    return float(np.sqrt(np.average(lr ** 2, weights=t.mu)))


def edge_error(rows: pd.DataFrame) -> Optional[float]:
    """The worst position's |log(actual / expected)| over the two longest
    tenures observed — the thinnest data, where a stale setting shows first."""
    if rows.empty:
        return None
    e = rows[rows.no >= rows.no.max() - 1]
    g = e.groupby("pos")
    r = (g.y.sum() / g.mu.sum()).replace(0, np.nan).dropna()
    return float(np.abs(np.log(r)).max()) if len(r) else None


@dataclass
class SeasonCheck:
    season: int
    additions: int
    calibration: Optional[float]
    edge: Optional[float]
    baseline: Optional[float]

    def ok(self) -> bool:
        return ((self.calibration is None or self.calibration <= MAX_CALIBRATION)
                and (self.edge is None or self.edge <= MAX_EDGE_ERROR))


def replay(additions: Sequence[ACQ.Addition], seasons: Optional[Sequence[int]] = None,
           folds: int = FOLDS) -> List[SeasonCheck]:
    """The re-check: one `SeasonCheck` per season, as the build would have seen
    it at that season's end. Default: every season from the third on (two
    seasons are too few for a tenure curve)."""
    known = sorted({a.s0 for a in additions if a.s0 is not None})
    if seasons is None:
        seasons = known[2:] if len(known) > 2 else known[-1:]
    out = []
    for s in seasons:
        sub = as_of(additions, s)
        rows = out_of_fold(sub, folds)
        out.append(SeasonCheck(s, len(sub), calibration(rows), edge_error(rows), BASELINE.get(s)))
    return out


def verdict(checks: Sequence[SeasonCheck]) -> str:
    """"ok", or why the settings want re-tuning: the latest season past a
    limit, or calibration rising two seasons running."""
    if not checks:
        return "no seasons to check"
    last = checks[-1]
    why = []
    if not last.ok():
        why.append(f"{last.season}: calibration {last.calibration:.3f} (limit {MAX_CALIBRATION}) / "
                   f"oldest-tenure error {last.edge:.3f} (limit {MAX_EDGE_ERROR})")
    cal = [c.calibration for c in checks if c.calibration is not None]
    if len(cal) >= 3 and cal[-1] > cal[-2] > cal[-3]:
        why.append(f"calibration rising two seasons running ({cal[-3]:.3f} -> {cal[-2]:.3f} -> {cal[-1]:.3f})")
    return "ok" if not why else "RE-TUNE: " + "; ".join(why)
