"""The FAAB speed-ups give the same answers as the plain versions they replaced.

- `faab_frame._pd_mean` (the snapshot means on cached arrays) equals pandas' Series.mean bit for bit, NaNs included;
- `faab_value.fit` over a pool of processes takes the same steps as the one-at-a-time search it replaced (kept
  below as `_fit_reference`), so it lands on the same parameters, and 1 worker equals 2;
- a parameter with no fit bounds is held at its value (the fit used to crash on one);
- `faab_pipeline.formula_frames` over forked processes returns the same frames, in grid order, as a plain loop;
- `faab_pipeline._run_jobs` (backup_columns' features side by side) returns what calling each one does, 1 worker or 3;
- `faab_features.game_form` / `since_injury` with their per-row memo give every row what it gets computed alone;
- `faab_frozen` puts quarter-chunk output back in the year-chunk row order the serial base used.

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
from lotg_support import faab_features as X  # noqa: E402


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


def test_fit_holds_unbounded_parameters():
    """a parameter with no BOUNDS entry (e.g. avail_young_floor) is held at its value; the fit used to crash on it"""
    obj = _toy_objective(); seen = []
    start = dict({k: v for k, v in F.P0.items() if k in F.BOUNDS}, held_a=0.25, held_b=-3.0)

    def obj2(q, detail=False):
        seen.append((q["held_a"], q["held_b"])); return obj(q, detail)
    kw = dict(restarts=1, passes=1, polish=1, seed=3, log=lambda s: None)
    p = F.fit(obj2, [start], workers=1, **kw)
    assert list(p) == list(start) and p["held_a"] == 0.25 and p["held_b"] == -3.0
    assert set(seen) == {(0.25, -3.0)}
    plain = F.fit(obj, [{k: v for k, v in start.items() if k in F.BOUNDS}], workers=1, **kw)
    assert all(p[k] == plain[k] for k in plain)        # holding them changes nothing else


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


def test_run_jobs_parallel_equals_serial():
    rng = np.random.default_rng(1); a = rng.normal(size=5000)
    jobs = dict(one=lambda: np.cumsum(a), two=lambda: (a.max(), a.argmin()), three=lambda: pd.Series(a).rank().values,
                err=lambda: ValueError("x"))
    ser = P._run_jobs(jobs, 1); par = P._run_jobs(jobs, 3)
    assert list(ser) == list(par) == list(jobs)
    assert np.array_equal(ser["one"], par["one"]) and ser["two"] == par["two"] and np.array_equal(ser["three"], par["three"])
    assert isinstance(par["err"], ValueError)


def _toy_games(rng, players=6):
    rows = []
    for p in range(players):
        for season in (2020, 2021, 2022):
            for week in range(1, 18):
                if rng.random() < 0.25: continue
                rows.append(dict(gsis=f"00-{p}", season=season, week=week, ppr=float(np.round(rng.gamma(2, 6), 2)),
                                 off_pct=rng.random(), rush_car=int(rng.integers(0, 25)), rush_yds=int(rng.integers(-5, 120)),
                                 known=pd.Timestamp(f"{season}-09-10") + pd.Timedelta(days=7 * week + 2)))
    return pd.DataFrame(rows)


def test_game_form_memo_equals_row_alone():
    rng = np.random.default_rng(2); gl = _toy_games(rng)
    N = 400
    gsis = rng.choice([f"00-{p}" for p in range(7)], N)                     # 00-6 has no games
    date_v = (pd.Timestamp("2020-08-01") + pd.to_timedelta(rng.integers(0, 3 * 365, N) // 7 * 7, "D")).values
    l0_s = pd.DatetimeIndex(date_v).year.values - 1 - (rng.random(N) < 0.3)
    out = X.game_form(gl, gsis, date_v, l0_s)
    for i in range(0, N, 7):
        one = X.game_form(gl, gsis[i:i + 1], date_v[i:i + 1], l0_s[i:i + 1])
        for k, v in out.items():
            assert np.array_equal(v[i:i + 1], one[k], equal_nan=True), (k, i)


def test_since_injury_memo_equals_row_alone():
    rng = np.random.default_rng(3); gl = _toy_games(rng)
    iw = gl.sample(40, random_state=3)[["gsis", "season", "week", "known"]]
    iw = pd.concat([iw, pd.DataFrame(dict(gsis=["00-7"], season=[2021], week=[3], known=[pd.Timestamp("2021-09-30")]))])
    N = 400
    gsis = rng.choice([f"00-{p}" for p in range(8)], N)
    date_v = (pd.Timestamp("2020-08-01") + pd.to_timedelta(rng.integers(0, 3 * 365, N) // 7 * 7, "D")).values
    ppg, gp = X.since_injury(gl, iw, gsis, date_v)
    assert np.isfinite(gp).any()
    for i in range(N):
        a, b = X.since_injury(gl, iw, gsis[i:i + 1], date_v[i:i + 1])
        assert np.array_equal(ppg[i:i + 1], a, equal_nan=True) and np.array_equal(gp[i:i + 1], b, equal_nan=True), i


def test_quarter_chunks_come_back_in_year_chunk_order():
    from lotg_support import faab_frozen as FZ
    rng = np.random.default_rng(4); N = 3000
    d = pd.Series(pd.Timestamp("2020-03-05") + pd.to_timedelta(rng.integers(0, 6 * 365, N), "D"))
    Fr = pd.DataFrame(dict(date=d, i=np.arange(N), sid=rng.integers(0, 50, N)))
    _, ys = FZ._date_chunks(d, "YS"); _, qs = FZ._date_chunks(d, "QS")
    assert len(qs) > len(ys) > 1 and sum(m.sum() for m in qs) == N
    serial = pd.concat([Fr[m] for m in ys], ignore_index=True)
    par = pd.concat([Fr[m] for m in qs], ignore_index=True).iloc[FZ._serial_order(qs, ys)].reset_index(drop=True)
    pd.testing.assert_frame_equal(serial, par)


def test_polyval_by_pos_matches_np_polyval():
    from lotg_support import faab_base as B
    rng = np.random.default_rng(5)
    coefs = {"QB": np.array([-0.0021, 0.11, -1.37]), "RB": np.array([-0.004, 0.19, -2.1]), "WR": rng.normal(size=4)}
    pos = rng.choice(np.array(["QB", "RB", "WR", "TE", None], dtype=object), 3000)
    for dt in ("float64", "float32"):
        age = (rng.normal(26, 4, 3000)).astype(dt)
        for k in (0, 1, 3):
            ref = np.array([np.polyval(coefs[p], a + k) if p in coefs else 0 for p, a in zip(pos, age)])
            got = B.polyval_by_pos(coefs, pos, age + k)
            assert got.dtype == ref.dtype and np.array_equal(got, ref), (dt, k)
            ref2 = np.array([np.clip(np.polyval(coefs[p], a + k), -1.0, 0.3) if p in coefs else 0.0 for p, a in zip(pos, age)])
            assert np.array_equal(np.clip(got, -1.0, 0.3), ref2)


def test_prediction_cache_returns_the_same_floats():
    import tempfile
    from lotg_support import faab_predict_cache as PCM
    rng = np.random.default_rng(6)
    X = pd.DataFrame(dict(a=rng.normal(size=500), b=rng.integers(0, 5, 500).astype(float), c=rng.normal(size=500)))
    X.loc[::7, "a"] = np.nan
    calls = []
    def fn(d):
        calls.append(len(d)); return np.nan_to_num(d.a.values) * 3.1 + d.b.values ** 2 - np.sin(d.c.values)
    ref = fn(X); calls.clear()
    with tempfile.TemporaryDirectory() as tmp:
        pc = PCM.PredictCache(tmp, "t1")
        assert np.array_equal(pc.predict(("t", 0, 1), fn, X), ref) and calls == [500]
        pc.save()
        pc = PCM.PredictCache(tmp, "t1"); calls.clear()
        Y = pd.concat([X.iloc[100:300], X.iloc[:50].assign(c=lambda d: d.c + 1e-12)])      # 200 seen rows, 50 changed
        got = pc.predict(("t", 0, 1), fn, Y)
        assert np.array_equal(got, fn(Y)) and calls == [50, 250], calls
        assert pc.hits == 200 and pc.misses == 50
        pc.save()                                       # keeps what this run used: rows 100-300 and the 50 changed
        pc = PCM.PredictCache(tmp, "t1"); calls.clear()
        assert np.array_equal(pc.predict(("t", 0, 1), fn, X), ref) and calls == [300] and pc.hits == 200
        assert np.array_equal(pc.predict(("t", 0, 1), fn, Y), fn(Y)) and pc.hits == 200 + 250
        calls.clear()
        assert np.array_equal(pc.predict(("t", 0, 2), fn, X), ref) and calls == [500]          # another model: its own store
        pc2 = PCM.PredictCache(tmp, "t2"); calls.clear()                                            # another tag: cold
        assert np.array_equal(pc2.predict(("t", 0, 1), fn, X), ref) and calls == [500]


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall faab speed checks passed")
