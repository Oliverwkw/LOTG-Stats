"""The frozen FAAB base (`lotg_support.faab_frozen`): fit once, stored, applied without KTC.

- feature audit: no stored feature list holds absolute time (a date, the year, a season number, a snapshot, `e_t`),
  a weight on time, or KTC itself; time of year (month, e_doy) is allowed (football's calendar);
- identical player: a row copied to a date five years later, with every input identical (its stats and its context:
  replacement level, supply rank, anchors), gets the same base value to 1e-9; and in a whole league shifted five years
  (stats, seasons, universe), the same player gets the same value through the full apply;
- KTC removed: with the stored base, applying it needs no KTC loader (they are patched to raise) and the values do
  not change when the league rows' KTC at pickup is blanked;
- freeze stability: applying twice, or applying to more rows (a later date), changes no stored file and no earlier
  row's value;
- the committed base's manifest (data/faab_value/frozen/, when present) passes the same audit.

Synthetic data with tiny models (no network, no exports, ~20 s). Run: python tests/test_faab_frozen.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import faab_frame as kp  # noqa: E402

try:
    import sklearn  # noqa: F401
    from lotg_support import faab_base as B  # noqa: E402
    from lotg_support import faab_frozen as FZ  # noqa: E402
    from lotg_support import faab_inputs as I  # noqa: E402
except ImportError:                       # the build's CI has no scikit-learn: these checks run in the FAAB workflows
    B = FZ = I = None

POS = ["QB", "RB", "WR", "TE"]
TOKENS_BANNED = {"t", "year", "date", "era", "recency", "season", "ktc", "yp", "lcs", "dyear"}   # "snap" alone is FORBIDDEN (the old snapshot); s_snap_* are snap shares
FAST = dict(ens=[("sqrt", dict(max_iter=15)), ("raw", dict(max_iter=15))], ld_kw=dict(max_iter=15),
            supply_kw=dict(max_iter=15, min_samples_leaf=10))


def _audit(names):
    bad = [c for c in names if c in kp.FORBIDDEN or (set(c.split("_")) & TOKENS_BANNED and c not in ("e_doy",))]
    assert not bad, f"time / KTC inputs in a model: {bad}"


def _seasons(shift=0, n=120, seed=0):
    rng = np.random.default_rng(seed); rows = []
    for i in range(n):
        p = POS[i % 4]; a0 = rng.uniform(21, 30)
        for y in range(2016, 2022):
            ppg = max(1.0, rng.normal(12, 5)); g = int(rng.integers(0, 18))
            rows.append((f"g{i}", y + shift, p, g, ppg * g, ppg if g else np.nan, a0 + (y - 2016)))
    return pd.DataFrame(rows, columns=["player_id", "season", "position", "games", "fantasy_points_ppr", "ppg", "age"])


def _sh(d, shift):
    """the same day of the year, `shift` years later (so month and day-of-year inputs match)"""
    d = pd.Timestamp(d)
    return pd.Timestamp(d.year + shift, 1, 1) + pd.Timedelta(days=d.dayofyear - 1)


def _rows(sids, dates, seed=1, ktc=True, rookie=False):
    """frame-like rows: one per (player, date), every column the base reads. rookie: drafted the row's year (so no
    earlier NFL season counts toward availability, whose 16 / 17-game seasons are real calendar context)"""
    rng = np.random.default_rng(seed); out = []
    for s in sids:
        i = int(s[1:]); p = POS[i % 4]; skill = (i * 7919 % 97) / 97
        for d in dates:
            d = pd.Timestamp(d)
            r = dict(sid=s, date=d, gsis=f"g{i}", pos=p, posc=kp.POS[p], age=22 + (i % 12),
                     dyear=float(d.year if rookie else 2010), dovr=float(1 + i % 250),
                     dround=float(1 + i % 7), undrafted=False, exp=float(1 + i % 10), month=d.month, e_doy=d.dayofyear,
                     lcs=d.year - 1, c_gp=float(i % 9), c_ppg=8 + 10 * skill, c_weeks=9.0, e_career_games=float(10 + i % 60),
                     e_x_usage=skill + 0.05 * (i % 3), k_gtd=0.05 * skill)
            for L in range(3):
                r[f"n_gp_l{L}"] = float(10 + (i + L) % 7); r[f"n_ppg_l{L}"] = 6 + 14 * skill - L
            if ktc: r["ktc"] = float(np.clip(9000 * skill ** 2 + rng.normal(0, 150), 50, 9999))
            out.append(r)
    return pd.DataFrame(out)


def _world(shift=0, rookie=False):
    sids = [f"s{i}" for i in range(120)]
    tue = [_sh(pd.Timestamp("2020-10-06") + pd.Timedelta(days=7 * w), shift) for w in range(0, 30, 3)]
    Fd = _rows(sids, tue)
    lr = _rows(sids[::3], [_sh("2020-09-20", shift), _sh("2020-10-20", shift)], seed=2)
    lr["price"] = np.round(np.exp(lr.ktc / 1500), 1); lr["ch"] = np.where(np.arange(len(lr)) % 4, "trade", "draft")
    lr["y"] = np.log1p(lr.price); lr["w"] = 1.0
    U = _rows(sids, tue, ktc=False, rookie=rookie)
    return Fd, lr, U, _seasons(shift)


def _fit(Fd, lr, U, seasons):
    fb = B.Football(seasons).fit(2020)
    return FZ.FrozenBase.fit(Fd, lr, U, fb, bags=2, workers=1, log=lambda m: None, **FAST)


def test_feature_audit():
    if FZ is None: print("  [SKIP] no scikit-learn"); return
    Fd, lr, U, seasons = _world()
    fz = _fit(Fd, lr, U, seasons)
    for k in ("FC", "COLS", "SUPPLY_COLS"): _audit(fz.meta[k])
    assert "e_doy" in fz.meta["FC"] and "month" in fz.meta["FC"]          # time of year is football context
    assert "ktc" not in fz.meta["FC"] and "e_t" not in kp.features(Fd.assign(e_t=1.0))


def test_identical_player_same_value_five_years_later():
    if FZ is None: print("  [SKIP] no scikit-learn"); return
    Fd, lr, U, seasons = _world()
    fz = _fit(Fd, lr, U, seasons); fb = fz.football(seasons)
    Uc = fb.add_pv(U.copy()); UP = fz.universe_values(Uc); hist = fz.league_history(lr, Uc, UP, fb)
    rows = _rows([f"s{i}" for i in range(0, 120, 5)], ["2020-11-03"], ktc=False)
    C = fz.context(rows, hist, Uc, UP, fb).drop(columns=[f"_S1_{b}" for b in range(2)])
    L0, S0 = fz.apply_rows(C)
    later = C.assign(date=C.date + pd.DateOffset(years=5), lcs=C.lcs + 5)
    L1, S1 = fz.apply_rows(later)
    assert np.max(np.abs(L1 - L0)) < 1e-9 and np.max(np.abs(S1 - S0)) < 1e-9
    L2, _ = fz.apply_rows(C.drop(columns=["date", "lcs"]))                  # the date is never read
    assert np.max(np.abs(L2 - L0)) < 1e-9
    # a whole league five years later (its stats, past seasons and supply universe, day of year kept): the same
    # player, with no league price of his own to anchor on, gets the same value through the full apply()
    _, _, U0, _ = _world(rookie=True); _, lr5, U5, seasons5 = _world(shift=5, rookie=True)
    who = [f"s{i}" for i in range(120) if i % 3][::4]                      # no league row (no anchor) for these
    r0 = _rows(who, ["2020-11-03"], ktc=False, rookie=True); r5 = _rows(who, [_sh("2020-11-03", 5)], ktc=False, rookie=True)
    a = fz.apply(r0, lr, U0, seasons, log=lambda m: None)
    b = fz.apply(r5, lr5, U5, seasons5, log=lambda m: None)
    assert len(a) == len(b) == len(who) and np.max(np.abs(a.L.values - b.L.values)) < 1e-9, np.max(np.abs(a.L.values - b.L.values))
    assert a.date.iloc[0].year == 2020 and b.date.iloc[0].year == 2025


def test_ktc_removed_changes_nothing():
    if FZ is None: print("  [SKIP] no scikit-learn"); return
    Fd, lr, U, seasons = _world()
    with tempfile.TemporaryDirectory() as td:
        _fit(Fd, lr, U, seasons).save(td)
        rows = _rows([f"s{i}" for i in range(0, 120, 4)], ["2020-11-03", "2021-01-12"], ktc=False)
        a = FZ.FrozenBase.load(td).apply(rows, lr, U, seasons, log=lambda m: None)

        def gone(*a, **k): raise RuntimeError("KTC was read")
        saved = (I.ktc_panel, kp.load_ktc)
        I.ktc_panel = gone; kp.load_ktc = gone
        try:
            b = FZ.FrozenBase.load(td).apply(rows, lr.assign(ktc=np.nan), U, seasons, log=lambda m: None)
        finally:
            I.ktc_panel, kp.load_ktc = saved
    assert np.array_equal(a.L.values, b.L.values) and np.array_equal(a.S.values, b.S.values)


def test_freeze_is_stable():
    if FZ is None: print("  [SKIP] no scikit-learn"); return
    Fd, lr, U, seasons = _world()
    with tempfile.TemporaryDirectory() as td:
        _fit(Fd, lr, U, seasons).save(td)
        h0 = FZ.file_hashes(td)
        rows = _rows([f"s{i}" for i in range(0, 120, 4)], ["2020-11-03", "2020-12-01"], ktc=False)
        fz = FZ.FrozenBase.load(td)
        a = fz.apply(rows, lr, U, seasons, log=lambda m: None)
        b = FZ.FrozenBase.load(td).apply(rows, lr, U, seasons, log=lambda m: None)
        more = pd.concat([rows, _rows([f"s{i}" for i in range(0, 120, 4)], ["2021-03-02"], ktc=False)], ignore_index=True)
        U2 = pd.concat([U, _rows([f"s{i}" for i in range(120)], ["2021-03-02"], ktc=False)], ignore_index=True)
        c = FZ.FrozenBase.load(td).apply(more, lr, U2, seasons, log=lambda m: None)
        assert FZ.file_hashes(td) == h0, "applying changed a stored file"
    assert np.array_equal(a.L.values, b.L.values)
    k = ["sid", "date"]
    m = a[k + ["L"]].merge(c[k + ["L"]], on=k, suffixes=("", "_c"))
    assert len(m) == len(a) and np.array_equal(m.L.values, m.L_c.values)


def test_supply_context_counts_and_classes():
    """the supply step's football context: depth counts leave the row's own player out and read only the latest
    Tuesday at or before the row; draft classes count NFL rounds 1-2 at the position in the last three drafts held"""
    if FZ is None: print("  [SKIP] no scikit-learn"); return
    U = pd.DataFrame(dict(sid=["a", "b", "c", "d", "a", "b"], pos=["WR"] * 4 + ["WR", "WR"],
                          date=pd.to_datetime(["2024-10-01"] * 4 + ["2024-10-08"] * 2)))
    uval = np.array([5000.0, 3500.0, 2000.0, 100.0, 4000.0, 1000.0])
    rows = pd.DataFrame(dict(sid=["a", "z"], pos=["WR", "WR"], date=pd.to_datetime(["2024-10-03", "2024-10-03"])))
    c = FZ.supply_ctx(rows, np.array([5000.0, 2500.0]), U, uval, levels=(4500.0, 3000.0, 1500.0))
    assert c[0].tolist() == [1, 0, 1, 2]           # a: first; above 4500 none but himself, 3000: b, 1500: b, c
    assert c[1].tolist() == [3, 1, 2, 3]           # z (not in the universe): a and b above him
    assert np.array_equal(FZ.supply_rank(rows, np.array([5000.0, 2500.0]), U, uval), c[:, 0])
    tab = FZ.class_table(pd.DataFrame(dict(season=[2022, 2023, 2024, 2024, 2024, 2025], round=[1, 2, 1, 3, 2, 1],
                                           position=["WR", "WR", "WR", "WR", "RB", "WR"])))
    r = pd.DataFrame(dict(pos=["WR", "WR", "RB"], dyear=[2024.0, np.nan, 2024.0],
                          date=pd.to_datetime(["2024-10-01", "2025-03-01", "2024-10-01"])))
    cls3, own = FZ.class_ctx(r, tab)
    assert cls3.tolist() == [3.0, 3.0, 1.0] and own[0] == 1.0 and np.isnan(own[1]) and own[2] == 1.0
    later = r.assign(date=pd.to_datetime(["2025-10-01", "2026-03-01", "2025-10-01"]))
    assert FZ.class_ctx(later, tab)[0].tolist() == [3.0, 3.0, 1.0]   # 2023-2025 at WR: 2023 + 2024 + 2025


def test_role_this_season_weighted_by_games():
    """this season's share counts a sixth per game played (full from 6), against last season's; no current share =
    last season's; the change column is games-weighted and NaN without both seasons"""
    if FZ is None: print("  [SKIP] no scikit-learn"); return
    r = pd.DataFrame(dict(c_gp=[0.0, 3.0, 9.0, 4.0], e_x_cur_tgt_share=[np.nan, 0.30, 0.30, 0.20],
                          e_x_l0_tgt_share=[0.10, 0.10, 0.10, np.nan]))
    o = FZ.add_role(r)
    assert np.allclose(o.r_tgt.values, [0.10, 0.20, 0.30, 0.20])
    assert np.isnan(o.r_tgt_d[0]) and np.isclose(o.r_tgt_d[1], 0.10) and np.isclose(o.r_tgt_d[2], 0.20) and np.isnan(o.r_tgt_d[3])
    assert o.r_snap.isna().all()                     # a share the rows do not carry stays empty
    _audit(FZ.ROLE_COLS)


def test_committed_manifest_passes_the_audit():
    p = _ROOT / "data" / "faab_value" / "frozen" / "manifest.json"
    if not p.exists(): print("  [SKIP] no committed frozen base"); return
    m = json.loads(p.read_text())
    for k in ("FC", "COLS", "SUPPLY_COLS"): _audit(m[k])
    assert m["bags"] >= 1 and m.get("holding") and len(m["holding"]["xs"]) == len(m["holding"]["ys"])
    assert set(m["files"]) == {f"bag{b}.joblib" for b in range(m["bags"])}


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall frozen-base checks passed")
