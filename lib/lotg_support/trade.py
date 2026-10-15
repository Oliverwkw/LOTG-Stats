"""Trade checks in one call: who moves, what each side's lineup and depth look
like before and after, and what the forecast says about title odds. Read-only.

Built so a question like "should Sam take McCaffrey for A.J. Brown and
Hubbard?" starts from one printout instead of a scratch script. The pieces:

- `resolve` turns names into the two rosters involved, from the forecast's
  own roster week (the snapshot's current rosters).
- `player_table` puts each moving player's 2026 output next to what the
  forecast assumes for him (rate, availability, IR / designation, research
  note), so a disagreement between the two is visible at a glance.
- `run` forecasts the league as it is and with the trade applied, optionally
  with per-player rate / availability overrides, all from one calibration.

The swap wraps `forecast` from outside — it never edits it. It replaces the
roster pool for the roster week only, and computes the calibration first on
the untouched past seasons, so the past the model calibrates on is never
traded. (Patching rosters globally also rewrites the calibration seasons,
which is how a first attempt on 2026-10-15 got the odds wrong.)
"""
from __future__ import annotations

import contextlib
import hashlib
import pickle
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from . import fast
from . import forecast as F
from . import inquiry as Q


@dataclass
class Trade:
    year: int
    week: int                       # roster week the forecast projects
    team: str                       # the side we are advising
    partner: str
    give: Dict[str, str]            # {player_id: name} `team` sends
    get: Dict[str, str]             # {player_id: name} `team` receives
    picks_give: Tuple[str, ...] = ()
    picks_get: Tuple[str, ...] = ()


def _rosters(year: int, week: int) -> Dict[str, Tuple[str, ...]]:
    teams = Q.teams(year)
    return {teams[rid]: row.players for rid, row in Q.week(year, week).items()}


def _find(name: str, rosters: Dict[str, Tuple[str, ...]]) -> Tuple[str, str]:
    """(player_id, team) for a rostered player, by name (case/punctuation-insensitive)."""
    players = Q.players()
    key = _norm(name)
    hits = [(pid, t) for t, pids in rosters.items() for pid in pids if _norm(players.name(pid)) == key]
    if not hits:
        hits = [(pid, t) for t, pids in rosters.items() for pid in pids
                if key in _norm(players.name(pid))]
    if len(hits) != 1:
        found = ", ".join(f"{players.name(p)} ({t})" for p, t in hits) or "nobody"
        raise LookupError(f"{name!r} matches {found} on the current rosters")
    return hits[0]


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def resolve(team: str, give: Sequence[str], get: Sequence[str], year: Optional[int] = None,
            picks_give: Sequence[str] = (), picks_get: Sequence[str] = ()) -> Trade:
    year = year or max(Q.export_seasons())
    week = F.roster_week(year)
    rosters = _rosters(year, week)
    team = Q.canonical_team(team)
    players = Q.players()
    g, r, partners = {}, {}, set()
    for n in give:
        pid, t = _find(n, rosters)
        if t != team:
            raise LookupError(f"{players.name(pid)} is on {t}, not {team}")
        g[pid] = players.name(pid)
    for n in get:
        pid, t = _find(n, rosters)
        if t == team:
            raise LookupError(f"{players.name(pid)} is already on {team}")
        r[pid] = players.name(pid)
        partners.add(t)
    if len(partners) != 1:
        raise LookupError(f"the players received come from {sorted(partners) or 'no team'}; "
                          "a two-team trade needs exactly one partner")
    return Trade(year, week, team, partners.pop(), g, r, tuple(picks_give), tuple(picks_get))


# ---------------------------------------------------------------------------
# The players
# ---------------------------------------------------------------------------
def player_table(tr: Trade, pw: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """One row per moving player: this season and the last two, next to the
    forecast's assumptions for him."""
    pw = fast.player_weeks() if pw is None else pw
    players = Q.players()
    rates = F.player_rates(tr.year)
    avail, base = F.availability_rates(tr.year)
    desig = F._designations(str(Q.repo_root()))
    state = F._roster_state(tr.year, str(Q.repo_root()))
    teams = Q.teams(tr.year)
    rid_of = {v: k for k, v in teams.items()}
    notes = F.research_overrides(tr.year)
    rows = []
    for side, d, owner in (("gives", tr.give, tr.team), ("gets", tr.get, tr.partner)):
        for pid, name in d.items():
            mine = pw[pw["Player"] == name]
            pos = players.position(pid)
            row = {"side": f"{tr.team} {side}", "Player": name, "Pos": pos,
                   "NFL": players.meta(pid).nfl_team or "FA"}
            row["Age"] = _age(name)
            for y in (tr.year, tr.year - 1, tr.year - 2):
                s = mine[(mine["Year"] == y) & (mine["Points"] != 0)]
                row[f"{y} G"] = len(s)
                row[f"{y} PPG"] = round(float(s["Points"].mean()), 1) if len(s) else None
            cur = mine[mine["Year"] == tr.year]
            row[f"{tr.year} started"] = f"{int((cur['Starter/Bench'] == 'Starter').sum())}/{len(cur)}"
            row["fcst rate"] = round(_fcst_rate(tr, name, rates), 1)
            p = avail.get(name, base.get(pos, base.get("_default")))
            flag = desig.get(pid, "")
            reserve = pid in state.get(rid_of.get(owner), {}).get("reserve", frozenset())
            note = notes.get(name)
            capped = (reserve or flag in F.OUT_DESIGNATIONS)
            if capped and not _injury_curve():
                p = min(p, F.AvailabilityModel().reserve_availability)
            if note is not None and note.availability is not None:
                p = note.availability
            row["fcst avail"] = (round(p, 2) if p is not None else None) if not (capped and _injury_curve()) \
                else "return curve"
            row["status"] = ", ".join(x for x in (flag, "IR slot" if reserve else "",
                                                  f"research note x{note.rate_multiplier:g}" if note else "") if x) or "-"
            rows.append(row)
    return pd.DataFrame(rows)


def _injury_curve() -> bool:
    """True once the forecast models flagged players with an injury return
    curve instead of a flat availability cap."""
    return hasattr(F, "injury_model") and getattr(F.AvailabilityModel(), "injury_spells", False)


def _fcst_rate(tr: Trade, name: str, rates: Dict[str, float]) -> float:
    """The forecast's per-week rate for `name`: the preseason rate, blended
    with this season's games when the forecast does that (falls back to the
    preseason rate if the blend API is absent or changes shape)."""
    base = rates.get(name, float("nan"))
    if not all(hasattr(F, f) for f in ("blend_in_season", "player_prior_games", "in_season_evidence")):
        return base
    try:
        wk = Q.finalized_week(tr.year) or 0
        ev = F.in_season_evidence(tr.year, wk)
        if name not in ev:
            return base
        return float(F.blend_in_season(base, F.player_prior_games(tr.year)[name], *ev[name]))
    except Exception:   # noqa: BLE001 - display only; the forecast itself is unaffected
        return base


def _age(name: str) -> Optional[float]:
    py = fast.typed_sheet("player_year") if not hasattr(_age, "_py") else _age._py
    _age._py = py
    a = py[py["Player"] == name].sort_values("Year")["Age"].dropna()
    return float(a.iloc[-1]) if len(a) else None


def ktc_values(tr: Trade) -> Tuple[pd.DataFrame, str]:
    """KTC superflex value now and a month ago for every moving asset, plus
    the injury status and depth-chart slot KTC's feed carries (fresher than
    the snapshot). One small input, not the basis of a call. Best effort:
    returns (empty, reason) when the feed cannot be reached."""
    try:
        from . import ktc
        d = ktc.load_directory(Q.repo_root())
    except Exception as exc:   # noqa: BLE001 - offline is a caveat, not a failure
        return pd.DataFrame(), f"KTC unavailable ({type(exc).__name__})"
    by_id = {str(x.get("sleeper_id")): x for x in d if x.get("sleeper_id")}
    by_name = {_norm(x.get("full_name", "")): x for x in d}
    rows, quoted = [], ""
    assets = [(f"{tr.team} gives", pid, n) for pid, n in tr.give.items()] + \
             [(f"{tr.team} gets", pid, n) for pid, n in tr.get.items()] + \
             [(f"{tr.team} gives", None, p) for p in tr.picks_give] + \
             [(f"{tr.team} gets", None, p) for p in tr.picks_get]
    for side, pid, name in assets:
        x = by_id.get(str(pid)) if pid else None
        if x is None:
            x = by_name.get(_norm(name)) or by_name.get(_norm(_mid_pick(name)))
        if x is None:
            rows.append({"side": side, "asset": name, "KTC sf": None, "month ago": None})
            continue
        quoted = quoted or str(x.get("date", ""))[:10]
        rows.append({"side": side, "asset": x.get("full_name", name),
                     "KTC sf": x.get("sf_trade_value"), "month ago": x.get("last_month_value_sf"),
                     "injury (KTC feed)": x.get("injury_status") or "-",
                     "depth chart": x.get("depth_chart") or "-"})
    df = pd.DataFrame(rows)
    if len(df) and df["KTC sf"].notna().any():
        tot = df.groupby("side")["KTC sf"].sum()
        quoted += "; totals " + ", ".join(f"{k} {int(v):,}" for k, v in tot.items())
    return df, f"KTC (dynasty-daddy) as of {quoted}"


def _mid_pick(label: str) -> str:
    """'2029 3rd' -> '2029 Mid 3rd' (KTC lists picks by tier)."""
    parts = str(label).split()
    return f"{parts[0]} Mid {parts[-1]}" if len(parts) == 2 else label


# ---------------------------------------------------------------------------
# The forecast, with and without the trade
# ---------------------------------------------------------------------------
def _calibration() -> F.Calibration:
    """F.calibrate(), cached on disk against the inputs it reads (7-8 s saved)."""
    root = Q.repo_root()
    h = hashlib.sha1()
    for p in (root / "lib" / "lotg_support" / "forecast.py", root / "exports" / "player_week.csv",
              root / "exports" / "team_week.csv"):
        if p.exists():
            st = p.stat()
            h.update(f"{p}:{st.st_size}:{st.st_mtime_ns}".encode())
    cache = root / ".cache" / f"trade_calibration_{h.hexdigest()[:16]}.pkl"
    if cache.exists():
        try:
            return pickle.loads(cache.read_bytes())
        except Exception:   # noqa: BLE001 - a bad cache is just a miss
            pass
    calib = F.calibrate()
    try:
        cache.parent.mkdir(exist_ok=True)
        cache.write_bytes(pickle.dumps(calib))
    except OSError:
        pass
    return calib


@contextlib.contextmanager
def _patched(tr: Optional[Trade], rate: Dict[str, float], healthy: Iterable[str]):
    """Apply the trade to the roster week, and any overrides, for one forecast."""
    healthy_names = {_norm(n) for n in healthy}
    players = Q.players()
    orig = (F.startable_pool, F.player_rates, F._designations, F._roster_state,
            None, F.research_overrides)
    teams = Q.teams(tr.year) if tr else {}
    rid_of = {v: k for k, v in teams.items()}

    def pool(year, week=1, model=F.AvailabilityModel()):
        out = orig[0](year, week, model)
        if tr is None or (year, week) != (tr.year, tr.week):
            return out
        out = {rid: list(pids) for rid, pids in out.items()}
        a, b = rid_of[tr.team], rid_of[tr.partner]
        out[a] = [p for p in out[a] if p not in tr.give] + [p for p in tr.get if p not in out[a]]
        out[b] = [p for p in out[b] if p not in tr.get] + [p for p in tr.give if p not in out[b]]
        return out

    def rates(year, model=F.RateModel(), exclude_from_fits=None):
        out = orig[1](year, model, exclude_from_fits)
        if rate and tr is not None and year == tr.year:
            out = dict(out)
            out.update(rate)
        return out

    def is_healthy(pid):
        return _norm(players.name(pid)) in healthy_names

    def designations(root):
        return {k: v for k, v in orig[2](root).items() if not is_healthy(k)}

    def roster_state(year, root):
        s = orig[3](year, root)
        if tr is None:
            return s
        # a traded player's IR slot moves with him; healthy overrides clear it
        moved = {**tr.give, **tr.get}
        res = {rid: set(v.get("reserve", ())) for rid, v in s.items()}
        if year == tr.year and moved:
            a, b = rid_of[tr.team], rid_of[tr.partner]
            for pid in tr.give:
                if pid in res.get(a, set()):
                    res[a].discard(pid); res.setdefault(b, set()).add(pid)
            for pid in tr.get:
                if pid in res.get(b, set()):
                    res[b].discard(pid); res.setdefault(a, set()).add(pid)
        return {rid: {"taxi": v.get("taxi", frozenset()),
                      "reserve": frozenset(p for p in res.get(rid, ()) if not is_healthy(p))}
                for rid, v in s.items()}

    def research(year):
        out = orig[5](year)
        if not healthy_names:
            return out
        return {n: (_no_avail(v) if _norm(n) in healthy_names else v) for n, v in out.items()}

    F.startable_pool, F.player_rates = pool, rates
    F._designations, F._roster_state = designations, roster_state
    F.research_overrides = research
    _clear()
    try:
        yield
    finally:
        (F.startable_pool, F.player_rates, F._designations, F._roster_state) = orig[:4]
        F.research_overrides = orig[5]
        _clear()


def _clear() -> None:
    """Drop any cached fielded distribution so the swapped rosters are used."""
    for fn in (F.fielded_distribution, getattr(F, "roster_projection", None)):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()


def _no_avail(note):
    import dataclasses
    return dataclasses.replace(note, availability=None)


@dataclass
class TradeRun:
    trade: Trade
    before: pd.DataFrame            # per team: projection, healthy, depth cost, champion, finals, playoffs
    after: pd.DataFrame
    overrides: Dict[str, object] = field(default_factory=dict)

    def delta(self) -> pd.DataFrame:
        """Per team, each metric as `before -> after (change)`; odds in %."""
        cols = {"projection": "pts/wk", "depth_cost": "depth cost", "champion": "title %",
                "finals": "finals %", "playoffs": "playoffs %", "expected_wins": "exp wins"}
        b, a = self.before.set_index("team"), self.after.set_index("team").reindex(self.before["team"])
        out = pd.DataFrame(index=b.index)
        for c, label in cols.items():
            out[label] = [f"{x:.1f} -> {y:.1f} ({y - x:+.1f})" for x, y in zip(b[c], a[c])]
        order = [self.trade.team, self.trade.partner] + [t for t in b.sort_values("champion", ascending=False).index
                                                        if t not in (self.trade.team, self.trade.partner)]
        out = out.loc[order]
        out.index.name = None
        return out


def _odds(fc) -> pd.DataFrame:
    return pd.DataFrame([{"team": o.team, "projection": o.projection, "healthy": o.healthy,
                          "depth_cost": o.depth_cost, "champion": o.champion, "finals": o.finals,
                          "playoffs": o.playoffs, "expected_wins": o.expected_wins} for o in fc.odds])


def run(tr: Trade, sims: int = 5000, seed: int = 20260807, rate: Optional[Dict[str, float]] = None,
        healthy: Sequence[str] = ()) -> TradeRun:
    """Forecast the league as it stands and with the trade, same seed and
    calibration. `rate` / `healthy` apply to BOTH runs, so the change is the
    trade's alone under those assumptions."""
    calib = _calibration()
    rate = dict(rate or {})
    with _patched(None if not (rate or healthy) else Trade(tr.year, tr.week, tr.team, tr.partner, {}, {}),
                  rate, healthy):
        before = F.forecast(tr.year, sims=sims, calibration=calib, seed=seed)
    with _patched(tr, rate, healthy):
        after = F.forecast(tr.year, sims=sims, calibration=calib, seed=seed)
    return TradeRun(tr, _odds(before), _odds(after), {"rate": rate, "healthy": list(healthy), "sims": sims})


# ---------------------------------------------------------------------------
# Context: standings and depth
# ---------------------------------------------------------------------------
def standings(year: int) -> pd.DataFrame:
    tw = fast.typed_sheet("team_week")
    t = tw[(tw["Year"] == year) & tw["Win?"].notna()]
    g = t.groupby("Team").agg(W=("Win?", "sum"), G=("Win?", "size"), PF=("PF", "sum"))
    g["L"] = g["G"] - g["W"]
    g["PF rank"] = g["PF"].rank(ascending=False, method="min").astype(int)
    return g.sort_values(["W", "PF"], ascending=False)[["W", "L", "PF", "PF rank"]]


def depth(tr: Trade, team: str, after: bool, pw: Optional[pd.DataFrame] = None, top: int = 6) -> pd.DataFrame:
    """The team's QB/RB/WR/TE depth by forecast rate, with 2026 PPG, before or after."""
    pw = fast.player_weeks() if pw is None else pw
    players = Q.players()
    rates = F.player_rates(tr.year)
    pids = list(_rosters(tr.year, tr.week)[team])
    if after:
        if team == tr.team:
            pids = [p for p in pids if p not in tr.give] + list(tr.get)
        elif team == tr.partner:
            pids = [p for p in pids if p not in tr.get] + list(tr.give)
    cur = pw[pw["Year"] == tr.year]
    ppg = cur[cur["Points"] != 0].groupby("Player")["Points"].mean()
    rows = []
    moved = set(tr.give) | set(tr.get)
    for pid in pids:
        n = players.name(pid)
        rows.append({"Pos": players.position(pid), "Player": n + (" *" if pid in moved else ""),
                     "fcst": round(rates.get(n, float("nan")), 1),
                     f"{tr.year} PPG": round(float(ppg.get(n, float("nan"))), 1)})
    df = pd.DataFrame(rows)
    df = df[df["Pos"].isin(["QB", "RB", "WR", "TE"])]
    df["_k"] = df[f"{tr.year} PPG"].fillna(df["fcst"])
    return (df.sort_values(["Pos", "_k"], ascending=[True, False]).groupby("Pos").head(top)
            .drop(columns="_k").reset_index(drop=True))


def caveats(tr: Trade, run_: Optional[TradeRun], table: pd.DataFrame,
            ktc_table: Optional[pd.DataFrame] = None) -> List[str]:
    out = [f"rosters = the snapshot's week-{tr.week} rosters ({tr.year}); results through week "
           f"{Q.finalized_week(tr.year)}"]
    model = F.RateModel()
    yrs = [tr.year - i - 1 for i in range(len(model.weights))]
    blended = hasattr(F, "blend_in_season")
    out.append(f"forecast rates come from {min(yrs)}-{max(yrs)} (weights {', '.join(f'{w:g}' for w in model.weights)})"
               f" plus an age curve" + (f", blended with {tr.year} games ('fcst rate' shows the blend; --rate sets the"
                                        " preseason rate the blend starts from)" if blended else
                                        f"; {tr.year} games are NOT used — compare 'fcst rate' with {tr.year} PPG"))
    big = table[(table[f"{tr.year} PPG"].notna()) & ((table[f"{tr.year} PPG"] - table["fcst rate"]).abs() >= 4)]
    depth = {}
    if ktc_table is not None and len(ktc_table) and "depth chart" in ktc_table.columns:
        depth = dict(zip(ktc_table["asset"], ktc_table["depth chart"]))
    for r in big.itertuples(index=False):
        dc = depth.get(r.Player)
        out.append(f"{r.Player}: forecast {r[table.columns.get_loc('fcst rate')]} vs {tr.year} "
                   f"{r[table.columns.get_loc(f'{tr.year} PPG')]} PPG over "
                   f"{r[table.columns.get_loc(f'{tr.year} G')]} G"
                   + (f" (depth chart now: {r.Pos}{dc})" if dc not in (None, "-", "") else "")
                   + f" — search his role/injury news (who left, who is hurt), then try --rate \"{r.Player}=X\"")
    capped = table[table["status"].str.contains("IR|Out|IR slot", case=False, regex=True)]
    for r in capped.itertuples(index=False):
        if _injury_curve():
            out.append(f"{r.Player}: {r.status} -> the forecast's injury return curve; --healthy \"{r.Player}\" drops it")
            continue
        out.append(f"{r.Player}: {r.status} -> capped at {r[table.columns.get_loc('fcst avail')]} availability "
                   f"every remaining week (draws are independent weekly; 'out now, back week N' is not modelled)"
                   f" — try --healthy \"{r.Player}\"")
    if tr.picks_give or tr.picks_get:
        out.append("picks are not in the forecast: " + "; ".join(
            x for x in (f"{tr.team} also gives {', '.join(tr.picks_give)}" if tr.picks_give else "",
                        f"{tr.team} also gets {', '.join(tr.picks_get)}" if tr.picks_get else "") if x))
    if run_ is not None:
        out.append(f"{run_.overrides['sims']} sims per side, same seed — changes under ~1 pt of title odds are noise")
        if run_.overrides.get("rate") or run_.overrides.get("healthy"):
            out.append(f"overrides apply to BOTH runs: {run_.overrides}")
    return out
