"""One-call answers to the stat checks that get asked most, finished weeks and
the live week alike. `scripts/fast.py` is the command line over it.

The questions this exists for (from the inquiry history): "most starters over
18 in a loss", "anyone ever left 4+ players over 20 on the bench, with or
without QBs", "I'm at 5 over 18 — would that tie the record", "is X close to it
before the late window", "where does 44.2 rank", "when did I last have a 40".
Every one of them is a per-team-week COUNT of players meeting a condition, or a
RANK of one value among a column, optionally with the live week mixed in.

    from lotg_support import fast, live
    pw = fast.player_weeks()                              # typed, team result joined
    c = fast.count_over(18, role="starter", result="loss")
    c = fast.count_over(18, entering="Sunday late", result="loss", live=live.fetch())
    fast.place(c[~c.Live]["n"], 5)                        # rank 5 among history

Conventions (each printed by the CLI so an answer carries its own caveats):

- `strict=True` means "over N" is `> N`; rows at exactly N are counted in
  `at_threshold` so a `>=` reading is one glance away, never silently chosen.
- Every week in the exports counts: regular season, playoffs, consolation and
  toilet-bowl games alike (each has an opponent and a result). Filter on
  `Week Name` to narrow.
- Lineups grew from 9 starters (2020-23) to 10 (2024 on), so a count record
  is not lineup-size neutral; `starters` is on every row and the CLI prints
  the per-season sizes from the data.
- `entering=<stage>` counts only players whose game kicked off before that
  stage's first kickoff, and replaces `Margin` with the margin at that moment
  — computed the build's way (`gametime`: PF minus points from that kickoff
  on, so a semifinal's +5 is in from the start). Stages: any game slot
  ('Sunday early', 'Sunday late', 'SNF', ...) or 'Monday'.
- The live week is raw Sleeper points, `Win?` = leading now (`lotg_support.live`).
- Acquisition columns on every player-week (`acquisition_columns`): `Acquired
  via` is how the player's CURRENT stint on that team began (the latest
  player_additions row for Player+Team on or before the week's last NFL game
  day: Waiver / Free agency / Trade / Draft / Commissioner; "Not in exports
  yet" for a live-week player whose add the exports do not hold), `Acquired`
  its date, `Acquired season` its Season. `Season source` is how he joined
  this team THIS season: "Week-1 roster" if he was on it in week 1, else
  `Acquired via`. `In-season pickup` = Season source is Waiver / Free agency.
- `corr` prints Pearson and Spearman with two-sided p-values and n, optionally
  holding controls constant (partial correlation) — no scipy needed.
  `starter_share` turns a player-week condition into a per-team-season share
  of starter points; `team_seasons` is typed team_year plus a regular-season
  all-play win %.
"""
from __future__ import annotations

import functools
import math
from datetime import datetime
from typing import Iterable, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from lotg_support import inquiry as Q
from lotg_support import player_ids

STAGE_ALIASES = {
    "late": "Sunday late", "sunday late": "Sunday late", "4pm": "Sunday late",
    "early": "Sunday early", "sunday early": "Sunday early", "1pm": "Sunday early",
    "morning": "Sunday morning", "sunday morning": "Sunday morning", "london": "Sunday morning",
    "snf": "SNF", "sunday night": "SNF", "night": "SNF",
    "mnf": "Monday", "monday": "Monday", "monday night": "Monday",
    "thursday": "Thursday", "tnf": "Thursday", "friday": "Friday", "saturday": "Saturday",
}


def stage_name(s: str) -> str:
    return STAGE_ALIASES.get(str(s).strip().lower(), str(s).strip())


# `Game slot` values as player_week writes them ("MNF", not the stage name "Monday")
SLOT_ALIASES = {**STAGE_ALIASES, "mnf": "MNF", "monday": "MNF", "monday night": "MNF"}


def slot_name(s: str) -> str:
    return SLOT_ALIASES.get(str(s).strip().lower(), str(s).strip())


def typed_sheet(name: str) -> pd.DataFrame:
    """An export sheet with every all-numeric column converted (blanks / N/A
    become NaN; `Year`, `Week` become Int64; Yes/No and True/False columns
    become bool). Text columns stay text, and so do the id columns (an id is a
    label: '4034', never 4034.0)."""
    df = Q.load_sheet(name).copy()
    for c in df.columns:
        col = df[c]
        if c in player_ids.ID_COLUMNS:
            df[c] = col.map(player_ids.clean_id).astype(object)
            continue
        if not (col.dtype == object or pd.api.types.is_string_dtype(col)):
            continue
        v = col.astype(str).str.strip()
        blank = v.isin(["", "nan", "None", "N/A", "NA", "-"])
        num = pd.to_numeric(v.where(~blank), errors="coerce")
        if (num.notna() | blank).all() and num.notna().any():
            df[c] = num.astype("Int64") if c in ("Year", "Week") else num
            continue
        low = v[~blank].str.lower()
        if len(low) and low.isin(["true", "false", "yes", "no"]).all():
            df[c] = v.str.lower().map({"true": True, "yes": True, "false": False, "no": False})
    return df


def find_columns(regex: str) -> pd.DataFrame:
    """Every export sheet column whose name matches `regex` (case-insensitive)."""
    import re
    rx = re.compile(regex, re.I)
    rows = []
    for sheet in Q.SHEETS:
        try:
            cols = Q.load_sheet(sheet).columns
        except Exception:   # noqa: BLE001 - a missing sheet just has no columns
            continue
        rows += [{"sheet": sheet, "column": c} for c in cols if rx.search(str(c))]
    return pd.DataFrame(rows, columns=["sheet", "column"])


@functools.lru_cache(maxsize=1)
def _schedule():
    from lotg_support.gametime import load_schedule
    g = Q.schedule()
    return load_schedule(g) if not g.empty else None


@functools.lru_cache(maxsize=None)
def _player_weeks_cached(root: str) -> pd.DataFrame:
    pw = Q.load_sheet("player_week")
    tw = Q.load_sheet("team_week")
    keep = ["Player", "Team", "Year", "Week", "Week Name", "Starter/Bench", "Position",
            "Position started in (if starter)", "NFL team", "Game slot", "Points"]
    out = pw[[c for c in keep if c in pw.columns]].copy()
    out["Year"] = pd.to_numeric(out["Year"], errors="coerce").astype("Int64")
    out["Week"] = pd.to_numeric(out["Week"], errors="coerce").astype("Int64")
    out["Points"] = pd.to_numeric(out["Points"], errors="coerce")
    t = tw[["Team", "Year", "Week", "Opponent", "Win?", "Margin", "PF", "Points against"]].copy()
    t["Year"] = pd.to_numeric(t["Year"], errors="coerce").astype("Int64")
    t["Week"] = pd.to_numeric(t["Week"], errors="coerce").astype("Int64")
    for c in ("Margin", "PF", "Points against"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t["Win?"] = t["Win?"].astype(str).str.lower().eq("true")
    out = out.merge(t, on=["Team", "Year", "Week"], how="left")
    out["Live"] = False
    out = acquisition_columns(out)
    # The Sleeper id last, so the columns before it read as they always have.
    if ID in pw.columns:
        out[ID] = pw[ID].map(_clean_id).astype(object).values
    return out


PICKUP_TYPES = ("Waiver", "Free agency")
ID = player_ids.PLAYER_ID
_clean_id = player_ids.clean_id


def _ids_on() -> bool:
    """Do the exports carry Player ID on both sheets the stint join reads?"""
    return ID in _additions_columns(str(Q.repo_root()))


@functools.lru_cache(maxsize=None)
def _additions_columns(root: str) -> tuple:
    return tuple(Q.load_sheet("player_additions").columns)


def _who(df: pd.DataFrame) -> pd.Series:
    """The player key for a join: his Sleeper id when the exports carry ids
    (names are not keys — renames, namesakes), else his name."""
    if _ids_on() and ID in df.columns:
        ids = df[ID].map(_clean_id)
        return ("id:" + ids.astype(str)).where(ids.notna(), "name:" + df["Player"].astype(str))
    return "name:" + df["Player"].astype(str)
ACQ_COLUMNS = ["Acquired via", "Acquired", "Acquired season", "Season source", "In-season pickup"]


@functools.lru_cache(maxsize=None)
def _additions(root: str) -> pd.DataFrame:
    a = Q.load_sheet("player_additions")
    a = a[[c for c in ("Player", ID) if c in a.columns]
          + ["Team", "Addition type", "Date", "Season", "Date dropped/traded"]].copy()
    a["_who"] = _who(a)
    a["_at"] = pd.to_datetime(a["Date"], errors="coerce").astype("datetime64[ns]")
    a["_gone"] = pd.to_datetime(a["Date dropped/traded"], errors="coerce").astype("datetime64[ns]")
    a["Acquired season"] = pd.to_numeric(a["Season"], errors="coerce").astype("Int64")
    # same-day stints (dropped and re-added that day: Lazard LWebs53 2021-12-29)
    # tie on _at; merge_asof takes the last one, so order them by exit (still
    # on the team last) with a stable sort, or the pick follows file order
    return a.dropna(subset=["_at"]).sort_values(["_at", "_gone"], na_position="last", kind="mergesort")


@functools.lru_cache(maxsize=1)
def _week_dates() -> pd.DataFrame:
    """First and last game day of every NFL regular-season week (the league's
    `Week` is the NFL week, playoffs included)."""
    g = Q.schedule()
    if g.empty:
        return pd.DataFrame(columns=["Year", "Week", "_first", "_last"])
    g = g[g["game_type"] == "REG"]
    d = pd.DataFrame({"Year": pd.to_numeric(g["season"]).astype("Int64"),
                      "Week": pd.to_numeric(g["week"]).astype("Int64"),
                      "_d": pd.to_datetime(g["gameday"])})
    return d.groupby(["Year", "Week"])["_d"].agg(_first="min", _last="max").reset_index()


def acquisition_columns(df: pd.DataFrame, week1: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Add ACQ_COLUMNS to a player-week frame (Player, Team, Year, Week).

    The stint is the latest player_additions row for the player+Team dated on or
    before the end of the week's last NFL game day (an add during the week,
    Friday's included, is the stint that week's lineup used). A matched stint
    already dropped/traded before the week's first game is stale (the player
    left and came back via an add the exports do not hold yet: the live week)
    and reads "Not in exports yet". 2021-25 history matches every row.
    `week1` = the frame whose Week 1 rows define the week-1 rosters
    (default `df` itself). The player is matched by Player ID when both the
    frame and player_additions carry it, else by name (exports before ids)."""
    out = df.copy()
    wd = _week_dates()
    k = out[["Team", "Year", "Week"]].assign(_who=_who(out)).merge(wd, on=["Year", "Week"], how="left")
    k.index = out.index
    # a week the schedule lacks (no .cache schedule): Thursday-Monday estimate,
    # week 1 kicking off the Thursday after the first Monday of September
    miss = k["_last"].isna()
    if miss.any():
        def kick(y):
            sept1 = pd.Timestamp(int(y), 9, 1)
            return sept1 + pd.Timedelta(days=(0 - sept1.weekday()) % 7 + 3)
        est = [kick(y) + pd.Timedelta(days=7 * (int(w) - 1)) if pd.notna(y) and pd.notna(w) else pd.NaT
               for y, w in zip(k.loc[miss, "Year"], k.loc[miss, "Week"])]
        k.loc[miss, "_first"] = est
        k.loc[miss, "_last"] = [e + pd.Timedelta(days=4) if pd.notna(e) else pd.NaT for e in est]
    k["_first"] = pd.to_datetime(k["_first"]).astype("datetime64[ns]")
    k["_end"] = (pd.to_datetime(k["_last"]) + pd.Timedelta(hours=23, minutes=59, seconds=59)).astype("datetime64[ns]")
    k["_row"] = np.arange(len(k))
    a = _additions(str(Q.repo_root()))
    have = k[k["_end"].notna()].sort_values("_end")
    m = pd.merge_asof(have, a[["_who", "Team", "_at", "_gone", "Addition type", "Date", "Acquired season"]],
                      left_on="_end", right_on="_at", by=["_who", "Team"], direction="backward")
    m = m.set_index("_row").reindex(k["_row"])
    m.index = out.index
    stale = m["_gone"].notna() & (m["_gone"] < m["_first"])
    via = m["Addition type"].astype(object).where(m["Addition type"].notna() & ~stale, "Not in exports yet")
    out["Acquired via"] = via
    out["Acquired"] = m["Date"].where(~stale)
    out["Acquired season"] = m["Acquired season"].where(~stale)
    base = df if week1 is None else week1
    first = base[base["Week"] == 1]
    on_w1 = pd.MultiIndex.from_frame(first[["Team", "Year"]].assign(_who=_who(first))).unique()
    key = pd.MultiIndex.from_frame(out[["Team", "Year"]].assign(_who=_who(out)))
    out["Season source"] = np.where(key.isin(on_w1), "Week-1 roster", via)
    out["In-season pickup"] = out["Season source"].isin(PICKUP_TYPES)
    return out


def player_weeks(live=None) -> pd.DataFrame:
    """player_week (key columns, typed: Year/Week ints, Points float, Win? bool)
    with the team's Opponent / Win? / Margin / PF / Points against joined on.
    `live` (a `live.LiveWeek`) appends the live week's rows, `Live=True`.
    Cached — copy before mutating."""
    base = _player_weeks_cached(str(Q.repo_root()))
    if live is None or live.player_week.empty:
        return base
    lp = live.player_week.copy()
    t = live.team_week.set_index("Team")
    lp["Week Name"] = f"Week {live.week}"
    lp["Opponent"] = lp["Team"].map(t["Opponent"])
    lp["Margin"] = lp["Team"].map(t["Margin"])
    lp["PF"] = lp["Team"].map(t["PF"])
    lp["Points against"] = lp["Team"].map(t["Points against"])
    lp["Live"] = True
    # a live week the build has already finalized would double count
    done = base[(base["Year"] == live.season) & (base["Week"] == live.week)]
    if len(done):
        base = base.drop(done.index)
    if ID in base.columns and ID in lp.columns:
        lp[ID] = lp[ID].map(_clean_id).astype(object)
        lp = lp[[c for c in lp.columns if c != ID] + [ID]]
    else:
        lp = lp.drop(columns=[ID], errors="ignore")
    for c in ("Year", "Week"):
        lp[c] = pd.to_numeric(lp[c], errors="coerce").astype("Int64")
    _k = [c for c in ("Player", ID) if c in lp.columns]
    w1 = pd.concat([base[_k + ["Team", "Year", "Week"]], lp[_k + ["Team", "Year", "Week"]]])
    lp = acquisition_columns(lp.drop(columns=ACQ_COLUMNS, errors="ignore"), week1=w1)
    return pd.concat([base, lp], ignore_index=True)


def _kickoffs(df: pd.DataFrame) -> pd.Series:
    if "Kickoff" in df.columns:
        have = df["Kickoff"]
    else:
        have = pd.Series([None] * len(df), index=df.index, dtype=object)
    sched = _schedule()
    if sched is None:
        return have
    need = have.isna()
    if need.any():
        sub = df.loc[need]
        have = have.astype(object)
        have.loc[need] = [sched.team_kickoff(y, w, t) if pd.notna(y) and pd.notna(w) and t else None
                          for y, w, t in zip(sub["Year"], sub["Week"], sub["NFL team"])]
    return have


def _roles(df: pd.DataFrame, role: str) -> pd.Series:
    sb = df["Starter/Bench"].astype(str).str.lower()
    if role == "starter":
        return sb.eq("starter")
    if role == "bench":
        return sb.eq("bench")
    return pd.Series(True, index=df.index)


def count_over(threshold: float, role: str = "starter", strict: bool = True,
               positions: Optional[Sequence[str]] = None, exclude: Optional[Sequence[str]] = None,
               result: Optional[str] = None, entering: Optional[str] = None,
               team: Optional[str] = None, years: Optional[Iterable[int]] = None,
               live=None, frame: Optional[pd.DataFrame] = None,
               slots: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Per team-week: how many players (`role` = starter / bench / any) scored
    over `threshold`, sorted most first.

    `positions` / `exclude` filter on `Position` (the player's listed position;
    for starters `Position started in` is on the frame if you need the slot).
    `result` = 'loss' / 'win' filters on the final result — or, with
    `entering`, on the margin at that stage (< 0 loss / > 0 win). Every
    team-week is returned, n = 0 included, so a distribution is honest.
    `slots` keeps only players whose game is in those `Game slot`s (MNF, SNF,
    Thursday, ...); a threshold of -inf counts every player.
    Columns: Team, Year, Week, Week Name, Opponent, Live, Win?, Margin, PF,
    Points against, starters, n, at_threshold, who."""
    df = (frame if frame is not None else player_weeks(live)).copy()
    if years is not None:
        df = df[df["Year"].isin(list(years))]
    keys = ["Team", "Year", "Week"]
    starters = df[_roles(df, "starter")].groupby(keys).size().rename("starters")
    pool = df[_roles(df, role)]
    if positions:
        pool = pool[pool["Position"].isin([p.upper() for p in positions])]
    if exclude:
        pool = pool[~pool["Position"].isin([p.upper() for p in exclude])]
    if slots:
        slots = [slot_name(x) for x in slots]
        pool = pool[pool["Game slot"].isin(slots)]

    tw = df.drop_duplicates(keys)[keys + ["Week Name", "Opponent", "Live", "Win?", "Margin", "PF",
                                          "Points against"]].set_index(keys)
    stage = None
    if entering:
        stage = stage_name(entering)
        tw, pool = _at_stage(df, tw, pool, stage)

    over = pool["Points"] > threshold if strict else pool["Points"] >= threshold
    hit = pool[over].sort_values("Points", ascending=False)
    n = hit.groupby(keys).size().rename("n")
    eq = pool[pool["Points"] == threshold].groupby(keys).size().rename("at_threshold")
    who = hit.groupby(keys).apply(
        lambda g: ", ".join(f"{p} {pos} {pts:g}" for p, pos, pts in zip(g["Player"], g["Position"], g["Points"])),
        include_groups=False).rename("who") if len(hit) else pd.Series(dtype=str, name="who")
    out = tw.join(starters).join(n).join(eq).join(who).reset_index()
    out["n"] = out["n"].fillna(0).astype(int)
    out["at_threshold"] = out["at_threshold"].fillna(0).astype(int)
    out["who"] = out["who"].fillna("")
    out["starters"] = out["starters"].fillna(0).astype(int)
    if stage:
        out = out.dropna(subset=["Margin"])
    if result:
        r = result.lower()
        if stage:
            out = out[out["Margin"] < 0] if r.startswith("l") else out[out["Margin"] > 0]
        else:
            out = out[~out["Win?"]] if r.startswith("l") else out[out["Win?"]]
            if r.startswith("l"):
                out = out[out["Margin"].fillna(-1) != 0]      # a tie is not a loss
    if team:
        out = out[out["Team"].str.lower() == Q.canonical_team(team).lower()]
    out.attrs.update(threshold=threshold, strict=strict, role=role, stage=stage,
                     positions=positions, exclude=exclude, result=result, slots=slots)
    return out.sort_values(["n", "PF"], ascending=[False, False]).reset_index(drop=True)


def _at_stage(df: pd.DataFrame, tw: pd.DataFrame, pool: pd.DataFrame, stage: str):
    """Restrict `pool` to games kicked off before `stage` and set `Margin` to
    the margin entering it (the build's arithmetic: PF minus starters' points
    from the stage's first kickoff on, both sides)."""
    sched = _schedule()
    if sched is None:
        raise RuntimeError(".cache/nfldata_games.csv missing: no schedule, no stage")
    kick = _kickoffs(df)
    starts = {}
    for y, w in tw.index.droplevel(0).unique():
        starts[(y, w)] = sched.stage_start(int(y), int(w), stage)
    t = pd.Series([starts.get((y, w)) for y, w in zip(df["Year"], df["Week"])], index=df.index, dtype=object)
    later = pd.Series([k is not None and s is not None and k >= s for k, s in zip(kick, t)], index=df.index)
    st = _roles(df, "starter")
    after = df[st & later].groupby(["Team", "Year", "Week"])["Points"].sum()
    tw = tw.copy()
    own_after = after.reindex(tw.index).fillna(0.0)
    tw["PF in"] = (tw["PF"] - own_after).round(2)
    opp_idx = pd.MultiIndex.from_arrays([tw["Opponent"].values, tw.index.get_level_values(1),
                                         tw.index.get_level_values(2)])
    opp_after = after.reindex(opp_idx).fillna(0.0).values
    tw["PA in"] = (tw["Points against"] - opp_after).round(2)
    no_stage = pd.Series([starts.get((y, w)) is None for _, y, w in tw.index], index=tw.index)
    tw["Margin"] = (tw["PF in"] - tw["PA in"]).round(2).where(~no_stage)
    tw["Stage kickoff"] = [starts.get((y, w)) for _, y, w in tw.index]
    pool = pool[~later.reindex(pool.index).fillna(False)]
    return tw, pool


def place(history: pd.Series, value: float, higher_is_better: bool = True) -> Tuple[int, int, int]:
    """(rank, tied, out of): where `value` would sit among `history`
    (1 = best). `tied` counts existing values equal to it."""
    h = pd.to_numeric(history, errors="coerce").dropna()
    better = (h > value).sum() if higher_is_better else (h < value).sum()
    return int(better) + 1, int((h == value).sum()), int(len(h))


def ordinal(n: int) -> str:
    return Q._ordinal(n)


def caveats(c: pd.DataFrame) -> list:
    a = c.attrs
    line = ("counting every player (no points line)" if a.get("threshold") == float("-inf") else
            f"'over {a.get('threshold'):g}' = {'>' if a.get('strict') else '>='} {a.get('threshold'):g}")
    out = [f"{line}; role={a.get('role')}" + (f"; positions={','.join(a['positions'])}" if a.get('positions') else "")
           + (f"; excluding {','.join(a['exclude'])}" if a.get('exclude') else "")]
    if a.get("slots"):
        out.append(f"only players whose game is in slot {','.join(a['slots'])} (player_week `Game slot`; "
                   "a game moved off its usual day takes its real slot)")
    if a.get("role") in ("bench", "any"):
        out.append("bench = every non-starter row, taxi and IR included (Sleeper lists them in the matchup, "
                   "and so does player_week)")
    if a.get("stage"):
        out.append(f"counted only games kicked off before the first {a['stage']} kickoff; Margin = margin "
                   "entering it (build arithmetic, semifinal +5 in from the start)")
    if a.get("result"):
        out.append(f"result={a['result']}" + (" at that stage" if a.get("stage") else " (final; ties excluded)"))
    if "starters" in c.columns and len(c):
        sizes = c.groupby("Year")["starters"].agg(lambda x: int(x.mode().iloc[0]))
        runs, prev = [], None
        for y, n in sizes.items():
            if n != prev:
                runs.append([y, y, n])
                prev = n
            else:
                runs[-1][1] = y
        out.append("all export weeks count (playoffs, consolation, toilet bowl); lineup size "
                   + ", ".join(f"{a}-{b}: {n}" if a != b else f"{a}: {n}" for a, b, n in runs))
    if "at_threshold" in c.columns and a.get("strict"):
        top = c.head(15)
        border = top[top["at_threshold"] > 0]
        if len(border):
            out.append("borderline: " + "; ".join(f"{r.Team} {r.Year} wk{r.Week} has {r.at_threshold} at exactly "
                                                   f"{a['threshold']:g}" for r in border.itertuples()))
    cur = max(Q.export_seasons() or [0])
    if cur:
        out.append(f"exports finalized through {cur} week {Q.finalized_week(cur)}")
    return out


# ---------------------------------------------------------------------------
# Correlation questions ("is X linked to win %?") without scipy
# ---------------------------------------------------------------------------
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (Lentz)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_pvalue(t: float, df: int) -> float:
    """Two-sided p-value of Student's t with `df` degrees of freedom."""
    if df <= 0 or not np.isfinite(t):
        return 0.0 if np.isinf(t) else float("nan")
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def _r_p(x: np.ndarray, y: np.ndarray, k: int) -> Tuple[float, float]:
    """Pearson r of two (already residualized) vectors and its p-value with
    n - 2 - k degrees of freedom (k = number of controls)."""
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), float("nan")
    r = float(np.corrcoef(x, y)[0, 1])
    df = len(x) - 2 - k
    if abs(r) >= 1:
        return r, 0.0
    return r, t_pvalue(r * math.sqrt(df / (1 - r * r)), df)


def _residual(v: np.ndarray, z: Optional[np.ndarray]) -> np.ndarray:
    if z is None:
        return v
    Z = np.column_stack([np.ones(len(v)), z])
    beta, *_ = np.linalg.lstsq(Z, v, rcond=None)
    return v - Z @ beta


def corr(x: pd.Series, y: pd.Series, control: Union[None, pd.Series, pd.DataFrame] = None,
         where: Optional[pd.Series] = None) -> pd.DataFrame:
    """Pearson and Spearman correlation of `x` with `y`, two-sided p-values
    (t-distribution, as scipy.stats.pearsonr / spearmanr compute them) and n.

    Series are aligned on their index (e.g. Team, Year) and rows with any NaN
    are dropped. `control` (a Series, or a DataFrame of several) is held
    constant: partial correlation of the residuals after regressing both on it
    (Spearman: on the ranks), df = n - 2 - controls. `where` (a boolean Series
    on the same index) keeps only those rows — e.g. `ty.Tanking < 0.5` to drop
    tanking seasons. Returns one row: n, pearson, p, spearman, p_spearman,
    controls."""
    d = pd.concat({"x": pd.Series(x), "y": pd.Series(y)}, axis=1)
    names = []
    if control is not None:
        c = control.to_frame() if isinstance(control, pd.Series) else control
        names = [str(n) for n in c.columns]
        c = c.set_axis([f"z{i}" for i in range(c.shape[1])], axis=1)
        d = d.join(c, how="left")
    if where is not None:
        d = d[pd.Series(where).reindex(d.index).fillna(False).astype(bool)]
    d = d.apply(pd.to_numeric, errors="coerce").dropna()
    zc = [c for c in d.columns if c.startswith("z")]
    z = d[zc].to_numpy(float) if zc else None
    r, p = _r_p(_residual(d["x"].to_numpy(float), z), _residual(d["y"].to_numpy(float), z), len(zc))
    rk = d.rank()
    zr = rk[zc].to_numpy(float) if zc else None
    rs, ps = _r_p(_residual(rk["x"].to_numpy(float), zr), _residual(rk["y"].to_numpy(float), zr), len(zc))
    return pd.DataFrame([{"n": len(d), "pearson": round(r, 3), "p": round(p, 4), "spearman": round(rs, 3),
                          "p_spearman": round(ps, 4), "controls": ",".join(names) or "-"}])


def starter_share(mask: Union[str, pd.Series], frame: Optional[pd.DataFrame] = None,
                  regular: bool = True, years: Optional[Iterable[int]] = None,
                  by: Sequence[str] = ("Team", "Year")) -> pd.Series:
    """Per team-season (or `by`) share of STARTER points scored by rows where
    `mask` holds: a boolean column name of `frame` (e.g. "In-season pickup")
    or a boolean Series on it (e.g. `pw["Acquired via"].isin(["Waiver",
    "Free agency"])`). `regular=True` keeps weeks named "Week N" only (no
    playoffs / consolation). Live rows are left out unless `frame` has them."""
    df = player_weeks() if frame is None else frame
    m = df[mask] if isinstance(mask, str) else pd.Series(mask, index=df.index)
    keep = _roles(df, "starter")
    if regular:
        keep &= df["Week Name"].astype(str).str.startswith("Week")
    if years is not None:
        keep &= df["Year"].isin(list(years))
    s = df[keep]
    pts = s["Points"].fillna(0.0)
    g = pd.DataFrame({"hit": pts.where(m[keep].fillna(False).astype(bool), 0.0), "all": pts})
    for c in by:
        g[c] = s[c]
    t = g.groupby(list(by))[["hit", "all"]].sum()
    return (t["hit"] / t["all"]).rename("share")


@functools.lru_cache(maxsize=None)
def _team_seasons_cached(root: str) -> pd.DataFrame:
    ty = typed_sheet("team_year").set_index(["Team", "Year"]).copy()
    tw = typed_sheet("team_week")
    r = tw[tw["Week Name"].astype(str).str.startswith("Week")].copy()
    grp = r.groupby(["Year", "Week"])["PF"]
    r["ap"] = (grp.rank(method="average") - 1) / (grp.transform("size") - 1)
    ty["Regular season all-play win %"] = r.groupby(["Team", "Year"])["ap"].mean()
    return ty


def team_seasons() -> pd.DataFrame:
    """Typed team_year indexed by (Team, Year), plus `Regular season all-play
    win %` (each regular week: share of the other teams outscored, ties half;
    team_year's own `All-play win %` counts playoff weeks too). Lines up with
    `starter_share` for `corr`. Cached — copy before mutating."""
    return _team_seasons_cached(str(Q.repo_root()))
