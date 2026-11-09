"""The FAAB value pipeline, end to end: downloads -> features -> walk-forward base -> formula on every grid date ->
the rule layer's committed inputs (data/faab_value/inputs.csv, evidence.json) and the build's dated values
(data/faab_value/history.csv, pick_prices.csv: lotg_support.faab_history).

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


# Same-day events a board reads by DATE only, so a trade earlier that day could see them before they happened: the
# NFL draft's rounds (rounds 1-2 rookies count from the Thursday, e_x_draft_comp; day-3 picks price rookies) and the
# league's own rookie draft (draft prices and rookies count from the day of the pick, faab_formula). Anything else a
# board reads was known before its day: league prices strictly before it (smooth_route), KTC the day before
# (add_anchor), weekly stats from the Tuesday after the games (add_x).
NFL_DRAFT_ROUNDS_ET = {0: 20, 1: 19, 2: 12}       # hour (US Eastern) each NFL draft day starts: Thu 8pm, Fri 7pm, Sat noon


def league_draft_days(pa):
    """every day the league made a rookie-draft pick (player_additions 'Draft' rows)"""
    d = pa[pa["Addition type"] == "Draft"].Date.astype(str).str[:10]
    return {pd.Timestamp(x) for x in d.unique()}


def board_day(ts, draft_days=frozenset()):
    """the board a trade or cut at `ts` is valued on: its own day's board (every board reads only what was known
    before its day, see above), else the day before when a same-day event the board counts by date could have come
    after it. `ts`: 'YYYY-MM-DD HH:MM:SS' in US Eastern (exports' trade times; a bare date = time unknown). The NFL
    draft: before that day's round starts (NFL_DRAFT_ROUNDS_ET); the league's rookie-draft days: always the day before
    (the picks have no time)."""
    t = pd.Timestamp(str(ts)); day = t.normalize(); timed = len(str(ts)) > 10
    nd = X.NFL_DRAFT.get(day.year)
    if nd is not None:
        k = (day - pd.Timestamp(nd)).days
        if k in NFL_DRAFT_ROUNDS_ET and (not timed or t.hour < NFL_DRAFT_ROUNDS_ET[k]):
            return day - pd.Timedelta(days=1)
    if day in draft_days: return day - pd.Timedelta(days=1)
    return day


EVIDENCE_SLACK = 7         # a player missing from the chosen board is read from the latest board up to 7 days before it


def evidence_rows(R, TR, pa, picks, drops, draft_days=None):
    """trades (both sides' players on the trade's own board, `board_day`: the trade day's unless a same-day event
    could post-date it; FAAB + picks at their price that day) and cuts (same rule, by day), as row positions in R.
    Before 2026-11-09 every row was the latest board strictly before the day: up to 7 days stale in the offseason."""
    dates = np.array(sorted(R.date.unique()), dtype="datetime64[ns]")
    key = {(s, d): i for i, (s, d) in enumerate(zip(R.sid.values, R.date.values.astype("datetime64[ns]")))}
    dd = league_draft_days(pa) if draft_days is None else draft_days

    def row(sid, day):
        g = dates[dates <= np.datetime64(day)]
        for x in g[::-1]:
            if x < np.datetime64(day) - np.timedelta64(EVIDENCE_SLACK, "D"): break
            i = key.get((sid, x))
            if i is not None: return i
        return None
    tr = []
    for k, sides in TR.items():
        if len(sides) != 2: continue
        day = board_day(k, dd)
        if not len(dates[dates <= np.datetime64(day)]): continue
        ok, S_ = True, []
        for tm, side in sides.items():
            if not side: ok = False
            pk, idx = 0.0, []
            for kind, x, lab in side:
                if kind == "faab": pk += x
                elif kind == "pick":
                    v = picks.value(lab, pd.Timestamp(str(k)[:10])); ok &= not np.isnan(v); pk += np.nan_to_num(v)
                elif kind == "player":
                    i = row(str(pa.loc[x, "sid"]), day)
                    if i is None: ok = False
                    else: idx.append(i)
                else: ok = False
            S_.append((pk, idx))
        if ok and (S_[0][1] or S_[1][1]): tr.append((pd.Timestamp(str(k)[:10]), S_))
    cut = []
    for r in drops.itertuples():
        i = row(r.sid, board_day(pd.Timestamp(r.date).strftime("%Y-%m-%d"), dd))
        if i is not None: cut.append(i)
    return tr, np.array(cut, dtype=int)


def evidence_dates(TR, pa):
    """the boards the evidence is read on that the grid does not have (offseason days other than Tuesdays): each
    trade's board day (see board_day), added to the grid for every player so a trade is valued on its own day"""
    dd = league_draft_days(pa)
    return sorted({board_day(k, dd) for k, s in TR.items() if len(s) == 2})


MODEL_COLS = ("L", "S")


def refresh_block(b, F_all, R0, R1):
    """a cached snapshot block brought up to the current features: its models never change (fit on data before R0),
    but the stats a rule reads (e_x_*) are re-read from today's feature frame, and grid rows the block lacks (a new
    evidence date) are added with the model's output carried from the player's latest earlier row in the block.
    Returns (block, rows added). Before 2026-11-09 a cached block kept the e_x_* columns of the run that fit it, so a
    column added since was empty on every cached row (14 game-log columns in the 2026-11-08 rebuild)."""
    F = F_all[(F_all.date >= R0) & (F_all.date < R1)].copy(); F["date"] = F.date.astype("datetime64[ns]")
    b = b.copy(); b["date"] = b.date.astype("datetime64[ns]")
    ex = [c for c in F.columns if c.startswith("e_x_")]
    keys = F[["sid", "date"] + ex].drop_duplicates(["sid", "date"])
    have = pd.MultiIndex.from_frame(b[["sid", "date"]]); new = keys[~pd.MultiIndex.from_frame(keys[["sid", "date"]]).isin(have)]
    m = b[["sid", "date"]].merge(keys.assign(_in=True), on=["sid", "date"], how="left")
    hit = m._in.fillna(False).values.astype(bool)
    for c in ex:                 # today's stats where the frame has the row; a row it lacks keeps what it had
        old = b[c].values if c in b else np.full(len(b), np.nan)
        b[c] = np.where(hit, m[c].values, old)
    if not len(new): return b, 0
    model = [c for c in b.columns if c not in F.columns or c in MODEL_COLS]
    src = b[["sid", "date"] + [c for c in model if c not in ("sid", "date")]].sort_values("date")
    n = F.merge(new[["sid", "date"]], on=["sid", "date"]).drop_duplicates(["sid", "date"])
    n = pd.merge_asof(n.drop(columns=[c for c in model if c in n.columns and c not in ("sid", "date")]).sort_values("date"),
                      src.rename(columns={"date": "_from"}).assign(date=lambda x: x._from).sort_values("date"),
                      on="date", by="sid", direction="backward").dropna(subset=["_from"]).drop(columns="_from")
    return pd.concat([b, n.reindex(columns=b.columns)], ignore_index=True), len(n)


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


def qb_base(R, idx):
    """for each kept WR/TE row (positions in R), the base value (V_raw) of his team's best QB that day (tgt_lead's QB
    gate); NaN when the team or its QB is not known"""
    out = np.full(len(idx), np.nan)
    if "gsis" not in R or getattr(X, "RW", None) is None or not len(idx): return out
    sel = np.asarray(idx)[np.isin(R.pos.values[idx], ("WR", "TE"))]
    if not len(sel): return out
    days = np.unique(R.date.values[sel])
    Q = np.where((R.pos.values == "QB") & np.isin(R.date.values, days))[0]
    qt = X.team_on(R.gsis.values[Q], R.date.values[Q], X.RW)
    best = pd.DataFrame(dict(date=R.date.values[Q], team=qt, v=R.V_raw.values[Q])).dropna(subset=["team"]).groupby(["date", "team"]).v.max()
    st = X.team_on(R.gsis.values[sel], R.date.values[sel], X.RW)
    look = dict(zip(sel, [best.get((d, t), np.nan) if t is not None and not (isinstance(t, float) and np.isnan(t)) else np.nan for d, t in zip(R.date.values[sel], st)]))
    return np.array([look.get(i, np.nan) for i in idx], dtype=float)


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
    dc1 = X.nfl_draft_comp(rows, dp, X.RW, max_round=1, gone=X.departed(dp, X.RW, X.GL) if X.GL is not None else None)
    E = E.assign(e_x_rookie_backup=np.round(sp, 5), e_x_rookie_backup_held=np.round(sn, 5), e_x_draft_comp=dc, e_x_draft_comp_r1=dc1)
    E = E.assign(e_x_league_undrafted=np.round(X.league_undrafted(rows, adds), 5))
    E = E.assign(e_x_league_draft_done=X.league_draft_done(rows, adds))
    if X.GL is not None:
        E = E.assign(e_x_te_one_off=X.te_one_off(rows, X.GL, X.RW), e_x_ypc_3s=np.round(X.ypc_with_current(rows, X.GL), 5),
                     e_x_overtaken=np.round(X.overtaken_by_rookie(rows, X.GL, X.RW, dp), 5), e_x_te_top3=X.te_top3(rows, X.GL, pos=dp.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index(dp.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").gsis_id.astype(str)).position))
        pos_of = dp.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index(dp.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").gsis_id.astype(str)).position
        E = E.assign(**{k: (np.round(v, 5) if np.asarray(v).dtype.kind == "f" else v) for k, v in X.round5_columns(rows, X.GL, pos_of, adds).items()})
        rk, cp = X.rb_room(rows, X.GL, X.RW, dp, pos_of)
        E = E.assign(e_x_rb_prev_rank=rk, e_x_rb_comp=cp)
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
    E["e_x_qb_base"] = np.round(qb_base(R, idx), 5)
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
    ED = evidence_dates(TR, pa)
    F_all = X.add_x(I.grid_frame(pa, E, end=end, dates=ED))
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
                b, k = refresh_block(b, F_all, R0, R1)
                if k: log(f"snapshot {R0.date()}: cached block, {k} new evidence-date rows carried from earlier rows")
                blocks.append(b); continue
        fb = B.Football(seasons).fit(B.season_done(R0))
        b = B.bagged_block(FC, fb, R0, R1, F_all, LR, Fd, log=log)
        b.to_parquet(p); blocks.append(b)
    Bk = pd.concat(blocks, ignore_index=True)
    # rows that exist only for an evidence date's full board are smoothed after the others, so adding them changes no
    # other row's value (each is smoothed with the rows before it)
    old = set(zip(E.sid.astype(str), pd.to_datetime(E.date).values.astype("datetime64[ns]")))
    gd = set(I.grid_dates(end=end).values.astype("datetime64[ns]"))
    bd = Bk.date.values.astype("datetime64[ns]")
    xtra = np.array([(d not in gd) and ((s_, d) not in old) for s_, d in zip(Bk.sid.astype(str).values, bd)], dtype=bool)
    tl = B.smooth_route(Bk.loc[~xtra, ["sid", "date", "L"]].copy(), LR[["sid", "date", "y"]])
    if xtra.any():
        t2 = B.smooth_route(Bk[["sid", "date", "L"]].copy(), LR[["sid", "date", "y"]])
        k2 = set(zip(Bk.sid.astype(str).values[xtra], bd[xtra]))
        tl = pd.concat([tl, t2[[(a, d) in k2 for a, d in zip(t2.sid.astype(str).values, t2.date.values.astype("datetime64[ns]"))]]], ignore_index=True)
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
    write_history(R, pa, picks, out or V.DATA, log=log)
    return R


def write_history(R, pa, picks, out=V.DATA, log=print):
    """the build's dated FAAB values (lotg_support.faab_history): every grid row valued with the committed params.
    A failure here never blocks the inputs: the previous history stays committed."""
    from . import faab_history as FH
    t1 = time.time()
    try:
        H = FH.finished_values(R, pa, V.load_params())
        n = FH.write(H, FH.pick_price_table(picks), out)
        log(f"history: {n} player-date values, {H.date.nunique()} dates, {H.sid.nunique()} players ({time.time() - t1:.0f}s)")
        return n
    except Exception as e:      # noqa: BLE001 - logged, the inputs are already written
        log(f"history NOT written ({type(e).__name__}: {e})")
        return None


def history_only(out=None, log=print):
    """refresh the dated FAAB values from the cached grid frame (after a params.json change; no refit, no fetch)"""
    p = WORK / "raw.parquet"
    if not p.exists():
        log(f"no cached grid frame at {p}: run the full rebuild first")
        return None
    X.load_store()
    pa = I.player_additions_sid(); picks = I.Picks(pa)
    R = pd.read_parquet(p)
    return write_history(R, pa, picks, out or V.DATA, log=log)
