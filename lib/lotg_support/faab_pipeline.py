"""The FAAB value pipeline, end to end: downloads -> features -> walk-forward base -> formula on every grid date ->
the rule layer's committed inputs (data/faab_value/inputs.csv, evidence.json).

  rebuild(full=False)   everything; a finished quarterly snapshot's block is reused from the cache unless full=True
                        (blocks of finished snapshots never change: their models were fit on data before them)

Stages cache to .cache/faab/ (git-ignored). The rules' strengths (params.json) are NOT refit here: a refit is a
deliberate `scripts/faab_value.py fit` reviewed in a PR. The new inputs move values only through the stats.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import faab_data as D
from . import faab_features as X
from . import faab_frame as kp
from . import faab_inputs as I
from . import faab_value as V
from . import faab_votes as FV
from . import faab_calls as LC

ROOT = Path(__file__).resolve().parents[2]
WORK = D.CACHE / "pipeline"
KEEP = ["sid", "date", "gsis", "name", "pos", "age", "exp", "injury", "V_raw", "un_x", "d_rank"]


def line_n(dates):
    """league replacement line = roster spots x 8 teams (less 8 from 2025): 184 (2021-23), 208 (2024), 200 (2025+)"""
    d = pd.to_datetime(dates); s_ = np.where(d.month >= 3, d.year, d.year - 1)
    return np.select([s_ <= 2023, s_ == 2024], [184, 208], 200)


def excused_fallback(R):
    """a player out for non-performance reasons (exempt / personal leave) this season is valued at his preseason
    level, like an injury"""
    if "e_x_cur_exempt" not in R: return R
    d = pd.to_datetime(R.date); s_ = np.where(d.dt.month >= 3, d.dt.year, d.dt.year - 1)
    ko = pd.to_datetime([str(kp.KO.get(int(y), f"{int(y)}-09-08")) for y in s_])
    pre = R[d.values < ko.values].assign(season=s_[d.values < ko.values]).sort_values("date").groupby(["sid", "season"]).V_raw.last()
    pv = pre.reindex(pd.MultiIndex.from_arrays([R.sid.values, s_])).values
    m = (np.nan_to_num(R.e_x_cur_exempt.values.astype(float)) >= 2) & ~np.isnan(pv)
    R.loc[m, "V_raw"] = np.fmax(R.V_raw.values[m], pv[m]).astype("float32")
    return R


def add_rank(R):
    R = excused_fallback(R)
    R["rank_raw"] = R.groupby("date").V_raw.rank(ascending=False, method="first").astype("float32")
    R["line_n"] = line_n(R.date.values).astype("float32")
    return R


def latest_status(R, players):
    """the latest date reads Sleeper's current injury status (the weekly tracker runs a week behind)"""
    now = R.date.max(); m = (R.date == now).values
    st = R.loc[m, "sid"].astype(str).map(lambda s_: (players.get(s_, {}) or {}).get("injury_status") or "")
    R.loc[m, "injury"] = np.where(st.isin(["IR", "PUP", "Out", "Doubtful"]), st, "")
    return R


def evidence_rows(R, TR, pa, picks, drops):
    """trades (both sides' players valued the day before; FAAB + picks at their price that day) and cuts (day before),
    as row positions in R"""
    dates = np.array(sorted(R.date.unique()), dtype="datetime64[ns]")
    key = {(s, d): i for i, (s, d) in enumerate(zip(R.sid.values, R.date.values.astype("datetime64[ns]")))}
    tr = []
    for k, sides in TR.items():
        d = np.datetime64(pd.Timestamp(str(k)[:10])); g = dates[dates < d]
        if not len(g) or len(sides) != 2: continue
        ok, S_ = True, []
        for tm, side in sides.items():
            if not side: ok = False
            pk, idx = 0.0, []
            for kind, x, lab in side:
                if kind == "faab": pk += x
                elif kind == "pick":
                    v = picks.value(lab, pd.Timestamp(str(k)[:10])); ok &= not np.isnan(v); pk += np.nan_to_num(v)
                elif kind == "player":
                    i = key.get((str(pa.loc[x, "sid"]), g[-1]))
                    if i is None: ok = False
                    else: idx.append(i)
                else: ok = False
            S_.append((pk, idx))
        if ok and (S_[0][1] or S_[1][1]): tr.append((pd.Timestamp(str(k)[:10]), S_))
    cut = []
    for r in drops.itertuples():
        g = dates[dates < np.datetime64(r.date)]
        if len(g):
            i = key.get((r.sid, g[-1]))
            if i is not None: cut.append(i)
    return tr, np.array(cut, dtype=int)


def rule_columns():
    src = Path(V.__file__).read_text()
    cols = sorted(set(re.findall(r'col\(R, "([\w]+)"\)', src)))
    base = ["sid", "date", "name", "pos", "age", "exp", "injury", "V_raw", "un_x", "rank_raw", "line_n"]
    return base + [c for c in cols if c not in base]


def vote_rows(R, responses=None):
    """rows of every player a rating-page vote was about, on the grid date of the board he was shown on"""
    df = FV.read_responses(FV.RESPONSES if responses is None else responses)
    dates = np.array(sorted(R.date.unique()), dtype="datetime64[ns]")
    key = {(s, d): i for i, (s, d) in enumerate(zip(R.sid.astype(str).values, R.date.values.astype("datetime64[ns]")))}
    idx, vd = [], {}
    for bd, sid in FV.vote_keys(df):
        try: g = dates[dates <= np.datetime64(pd.Timestamp(bd))]
        except Exception: continue
        if not len(g): continue
        vd[bd] = str(pd.Timestamp(g[-1]).date()); i = key.get((str(sid), g[-1]))
        if i is not None: idx.append(i)
    return np.array(idx, dtype=int), vd


LAG_DAYS, LAG_SLACK = 28, 7


def lag_rows(R, idx, days=LAG_DAYS, slack=LAG_SLACK):
    """row positions in R of each kept row's player on the latest grid date at least `days` earlier (and no more
    than `slack` days before that): the 'value four weeks earlier' a cap on fast risers reads"""
    if not len(idx): return np.array([], int)
    L = pd.DataFrame(dict(sid=R.sid.astype(str).values[idx], t=pd.to_datetime(R.date.values[idx]) - pd.Timedelta(days=days)))
    G = pd.DataFrame(dict(sid=R.sid.astype(str).values, t=pd.to_datetime(R.date.values), i=np.arange(len(R))))
    m = pd.merge_asof(L.sort_values("t"), G.sort_values("t"), on="t", by="sid", direction="backward", tolerance=pd.Timedelta(days=slack))
    return np.unique(m.i.dropna().astype(int).values)


def wr_mates(R, idx):
    """for each kept WR row (positions in R), the row of his team's other WR with the highest base value that day:
    {row: mate row}. A team's top WR gets its second; nobody else on the team gets anyone but the top one."""
    if "gsis" not in R or getattr(X, "RW", None) is None: return {}
    sel = idx[R.pos.values[idx] == "WR"]
    if not len(sel): return {}
    W = np.where((R.pos.values == "WR") & np.isin(R.date.values, np.unique(R.date.values[sel])))[0]
    D = pd.DataFrame(dict(i=W, date=R.date.values[W], team=X.team_on(R.gsis.values[W], R.date.values[W], X.RW), v=R.V_raw.values[W]))
    D = D[D.team.notna()].sort_values("v", ascending=False)
    top = D.groupby(["date", "team"]).i.apply(lambda x: list(x.iloc[:2]))
    team = dict(zip(D.i, zip(D.date, D.team))); out = {}
    for i in sel:
        k = team.get(i)
        if k is None: continue
        t = top.get(k, [])
        m = t[1] if t and t[0] == i and len(t) > 1 else (t[0] if t and t[0] != i else None)
        if m is not None: out[int(i)] = int(m)
    return out


def backup_columns(E, gsis, pa):
    """e_x_rookie_backup (league spend on this season's same-team, same-position rookies) and e_x_rookie_backup_use
    (the player's own usage so far over his last season) and e_x_draft_comp (same-team, same-position rookies the NFL
    took in rounds 1-2 this season) for the exported rows; needs the feature store (load_store)"""
    if getattr(X, "RW", None) is None: return E
    adds = pd.DataFrame(dict(sid=pa.sid.astype(str), date=pd.to_datetime(pa.Date.astype(str).str[:10]), type=pa["Addition type"],
                             price=pa["Price paid (FAAB)"])).dropna(subset=["sid"])
    info = kp.player_info(sorted(set(adds.sid)))
    rows = pd.DataFrame(dict(sid=E.sid.astype(str).values, gsis=pd.Series(gsis).astype(str).values, date=pd.to_datetime(E.date).values, pos=E.pos.values))
    sp, sn = X.rookie_backup_spend(rows, adds, info, X.RW, X.GL)
    dp = pd.read_csv(ROOT / "exports" / "snapshot" / "dynastyprocess_playerids.csv", low_memory=False)
    dc = X.nfl_draft_comp(rows, dp, X.RW, gone=X.departed(dp, X.RW, X.GL) if X.GL is not None else None)
    E = E.assign(e_x_rookie_backup=np.round(sp, 5), e_x_rookie_backup_held=np.round(sn, 5), e_x_draft_comp=dc)
    E = E.assign(e_x_league_undrafted=np.round(X.league_undrafted(rows, adds), 5))
    if X.GL is not None:
        E = E.assign(e_x_te_one_off=X.te_one_off(rows, X.GL, X.RW), e_x_ypc_3s=np.round(X.ypc_with_current(rows, X.GL), 5),
                     e_x_overtaken=np.round(X.overtaken_by_rookie(rows, X.GL, X.RW, dp), 5))
    try:
        from . import contracts as CT
        E = E.assign(e_x_vet_deal_cap=X.vet_deal_cap(rows, CT.load_contracts()))
    except Exception as e:      # no contracts file (offline, no pyarrow): the rule reads NaN and stays off
        print(f"contracts unavailable ({type(e).__name__}): e_x_vet_deal_cap left empty")
    return E


def export(R, tr, cut, out=V.DATA, responses=None, pa=None):
    """the committed inputs: the as-of board + every evidence row + every voted row, and the evidence structure"""
    now = R.date.max(); latest = np.where(R.date.values == np.datetime64(now))[0]
    vi, vd = vote_rows(R, responses)
    cd = R.date[R.date <= pd.Timestamp(LC.CALLS_DATE)].max()          # the board the league's calls were about, kept for good
    # and the board of each day a group of calls was made (each group is judged on its own day's board)
    cds = {d: R.date[R.date <= pd.Timestamp(d)].max() for d in LC.CALL_DATES}; cds = {d: x for d, x in cds.items() if pd.notna(x)}
    keep = [np.datetime64(x) for x in ([cd] if pd.notna(cd) else []) + list(cds.values())]
    calls = np.where(np.isin(R.date.values.astype("datetime64[ns]"), np.array(keep, dtype="datetime64[ns]")))[0]
    idx = np.unique(np.r_[cut, [i for _, s in tr for side in s for i in side[1]], latest, vi, calls].astype(int))
    mates = wr_mates(R, idx)                                          # each WR's top teammate WR that day (and his row)
    idx = np.unique(np.r_[idx, list(mates.values())].astype(int))
    idx = np.unique(np.r_[idx, lag_rows(R, idx)].astype(int))          # and each one's row four weeks earlier
    need = [c for c in rule_columns() if c in R]
    E = R.iloc[idx][need].copy()
    E["wr_mate"] = [str(R.sid.values[mates[i]]) if i in mates else "" for i in idx]
    if pa is not None and "gsis" in R: E = backup_columns(E, R.gsis.values[idx], pa)
    E["date"] = pd.to_datetime(E.date).dt.strftime("%Y-%m-%d")
    for c in E.columns:
        if E[c].dtype.kind == "f": E[c] = E[c].astype("float64").round(5)
    E.to_csv(out / "inputs.csv", index=False)
    key = lambda i: [str(R.sid.values[i]), pd.Timestamp(R.date.values[i]).strftime("%Y-%m-%d")]
    json.dump(dict(as_of=str(pd.Timestamp(now).date()), calls_date=str(pd.Timestamp(cd).date()) if pd.notna(cd) else None,
                   call_dates={d: str(pd.Timestamp(x).date()) for d, x in cds.items()},
                   trades=[dict(date=str(d.date()), sides=[dict(other_value=round(float(pk), 3), players=[key(i) for i in ix]) for pk, ix in s]) for d, s in tr],
                   cuts=[key(i) for i in cut], vote_dates=dict(sorted(vd.items()))), open(out / "evidence.json", "w"), indent=0)
    return len(E)


def rebuild(full=False, fetch=True, log=print, end=None, out=None, max_minutes=None):
    from . import faab_base as B          # the models need scikit-learn / scipy (the rebuild workflow installs them)
    from . import faab_formula as FM
    t0 = time.time(); WORK.mkdir(parents=True, exist_ok=True)
    last = D.current_season()
    if fetch: D.fetch_all(last, log=log)
    X.build_store(last, log=log); X.load_store()
    pa = I.player_additions_sid(); TR = I.trades(pa); drops = I.drops(pa); picks = I.Picks(pa)
    o0 = X.add_x(I.league_frame(pa)); LR = B.league_rows(o0, pa)
    E = I.evidence(LR)
    Fd = X.add_x(I.ktc_panel())
    F_all = X.add_x(I.grid_frame(pa, E, end=end))
    log(f"frames: league {len(o0)}, KTC panel {len(Fd)}, grid {len(F_all)} ({time.time() - t0:.0f}s)")
    FC = list(dict.fromkeys([c for c in B.feats(Fd) if not c.startswith("e_x_")] + B.PVF + [c for c in Fd.columns if c.startswith("e_x_")]))
    seasons = B.load_seasons(last)
    today = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    snaps = list(pd.date_range("2021-01-01", today, freq="QS")) + [today + pd.Timedelta(days=1)]
    blocks = []
    for R0, R1 in zip(snaps[:-1], snaps[1:]):
        if max_minutes and (time.time() - t0) / 60 > max_minutes:   # out of budget: the cached blocks carry over to the next run
            log(f"time budget ({max_minutes} min) reached before snapshot {R0.date()}: blocks so far are cached; inputs NOT exported")
            return None
        p = WORK / f"blk_{R0.date()}{'' if end is None else '_partial'}.parquet"
        done = R1 <= today and p.exists() and not full     # a finished snapshot never changes
        if done:
            b = pd.read_parquet(p)
            if int(b["bags"].iloc[0] if "bags" in b else 1) == B.BAGS:   # refit if cached under another bag count
                blocks.append(b); continue
        fb = B.Football(seasons).fit(B.season_done(R0))
        b = B.bagged_block(FC, fb, R0, R1, F_all, LR, Fd, log=log)
        b.to_parquet(p); blocks.append(b)
    Bk = pd.concat(blocks, ignore_index=True)
    tl = B.smooth_route(Bk[["sid", "date", "L"]].copy(), LR[["sid", "date", "y"]])
    TL = Bk.merge(tl[["sid", "date", "Ls", "Lf", "a_y", "a_date"]], on=["sid", "date"], how="left")
    log(f"base: {len(TL)} rows ({time.time() - t0:.0f}s)")
    PW = pd.read_csv(ROOT / "exports" / "player_week.csv", usecols=["Player", "Year", "Week", "Injury?"], low_memory=False)
    TRK = pd.read_csv(ROOT / "data" / "injury_tracker.csv", dtype={"player_id": str})
    F = FM.Formula(TL, pa, pd.read_csv(ROOT / "exports" / "rookie_picks.csv"), E, seasons, PW, TRK)
    rows = []
    for g in F.GRID:
        d = F.at(g)
        keep = [c for c in KEEP if c in d] + [c for c in d.columns if c.startswith("e_x_")]
        rows.append(d.reset_index().rename(columns={"index": "sid"})[["sid"] + [c for c in keep if c != "sid"]].assign(date=pd.Timestamp(g)))
    R = pd.concat(rows, ignore_index=True)
    for c in R.columns:
        if R[c].dtype == "float64": R[c] = R[c].astype("float32")
    players = json.load(open(ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json"))
    R = add_rank(latest_status(R, players))
    R.to_parquet(WORK / ("raw.parquet" if end is None else "raw_partial.parquet"))
    tr, cut = evidence_rows(R, TR, pa, picks, drops)
    n = export(R, tr, cut, out or V.DATA, pa=pa)
    log(f"exported {n} input rows, {len(tr)} trades, {len(cut)} cuts as of {R.date.max().date()} ({time.time() - t0:.0f}s)")
    return R
