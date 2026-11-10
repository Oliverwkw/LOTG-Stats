"""The FAAB speed-ups give the same answers as the plain versions they replaced.

- `faab_frame._pd_mean` (the snapshot means on cached arrays) equals pandas' Series.mean bit for bit, NaNs included;
- `faab_value.fit` over a pool of processes takes the same steps as the one-at-a-time search it replaced (kept
  below as `_fit_reference`), so it lands on the same parameters, and 1 worker equals 2;
- `faab_pipeline.formula_frames` over forked processes returns the same frames, in grid order, as a plain loop.

No scikit-learn, no network, no exports needed. Run: python tests/test_faab_speed.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import faab_frame as kp  # noqa: E402
from lotg_support import faab_pipeline as P  # noqa: E402
from lotg_support import faab_value as F  # noqa: E402


def test_pd_mean_matches_pandas():
    rng = np.random.default_rng(0)
    for n in (0, 1, 3, 4, 17, 400):
        for dt in ("float64", "float32"):
            x = (rng.normal(0, 30, n) ** 3).astype(dt)
            if n > 2: x[rng.random(n) < 0.3] = np.nan
            for y in (x, x[-4:], np.full(n, np.nan, dtype=dt)):
                a, b = kp._pd_mean(y), pd.Series(y).mean()
                assert (np.isnan(a) and np.isnan(b)) or a == b, (n, dt, a, b)
        if n:
            k = rng.integers(0, 100, n)
            assert kp._pd_mean(k) == pd.Series(k).mean()


def _fit_reference(obj, starts, restarts=8, passes=3, polish=4, seed=0):
    """faab_value.fit as it was before it scored candidates in parallel (2026-11-10)"""
    BOUNDS, _ok = F.BOUNDS, F._ok
    p = min(starts, key=obj); best = obj(p); rng = np.random.default_rng(seed)
    scale_keys = ("y200", "y450", "y650", "lvl", "vet", "vet_hi", "top_g", "spike_hi", "youth_age")

    def coord(p, best, n):
        for _ in range(n):
            for k, (lo, hi) in BOUNDS.items():
                for x in np.linspace(lo, hi, 13):
                    q = dict(p, **{k: float(x)})
                    if not _ok(q): continue
                    e = obj(q)
                    if e < best: best, p = e, q
        return p, best
    gbest, gp = best, p
    for rs in range(restarts):
        q = {k: float(np.clip(v * np.exp(rng.normal(0, 0.3)) if k in scale_keys else v + rng.normal(0, 0.25), *BOUNDS[k])) for k, v in gp.items()}
        if not _ok(q): q = dict(gp)
        q, e = coord(q, obj(q), passes)
        if e < gbest: gbest, gp = e, q
    p, best = gp, gbest
    for it in range(polish):
        p, best = coord(p, best, 1)
        for _ in range(400):
            q = {k: float(np.clip(v * np.exp(rng.normal(0, 0.08)) if k in scale_keys[:7] else v + rng.normal(0, 0.08), *BOUNDS[k])) for k, v in p.items()}
            if not _ok(q): continue
            e = obj(q)
            if e < best: best, p = e, q
    return p


def _toy_objective():
    B = F.BOUNDS; rng = np.random.default_rng(5)
    tgt = {k: lo + (hi - lo) * rng.random() for k, (lo, hi) in B.items()}

    def obj(q, detail=False):     # bumpy, so the polish both finds and misses improvements
        e = sum((q[k] - tgt[k]) ** 2 / ((B[k][1] - B[k][0]) ** 2 + 1e-9) + 0.05 * np.sin(7 * q[k]) for k in tgt)
        return dict(total=e, calls=0.0, tests=[], trades=0.0, cuts=0.0, votes=0.0) if detail else e
    return obj


def test_parallel_fit_takes_the_same_steps():
    obj = _toy_objective()
    starts = [{k: v for k, v in F.P0.items() if k in F.BOUNDS}]
    kw = dict(restarts=2, passes=1, polish=2, seed=3)
    ref = _fit_reference(obj, starts, **kw)
    one = F.fit(obj, starts, log=lambda s: None, workers=1, **kw)
    two = F.fit(obj, starts, log=lambda s: None, workers=2, **kw)
    assert list(one.items()) == list(ref.items()), "1 worker differs from the reference search"
    assert list(two.items()) == list(ref.items()), "2 workers differ from the reference search"
    assert obj(ref) < obj(starts[0])


class _FakeFormula:
    GRID = [pd.Timestamp("2025-01-01") + pd.Timedelta(days=7 * i) for i in range(9)]

    def at(self, g):
        i = (g - self.GRID[0]).days // 7
        return pd.DataFrame({"V_raw": np.arange(3, dtype=float) * i, "e_x_test": [g.day] * 3}, index=[f"s{j}" for j in range(3)])


def test_formula_frames_parallel_equals_serial():
    F_ = _FakeFormula()
    a = P.formula_frames(F_, workers=1); b = P.formula_frames(F_, workers=2)
    assert len(a) == len(b) == len(F_.GRID)
    for x, y in zip(a, b): pd.testing.assert_frame_equal(x, y)
    assert [x.date.iloc[0] for x in b] == F_.GRID and list(b[0].columns[:1]) == ["sid"]


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall faab speed checks passed")
