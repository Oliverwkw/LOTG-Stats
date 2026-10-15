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
"""
from __future__ import annotations

import functools
from datetime import datetime
from typing import Iterable, Optional, Sequence, Tuple

import pandas as pd

from lotg_support import inquiry as Q

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
    return pd.concat([base, lp.drop(columns=["Player ID"], errors="ignore")], ignore_index=True)


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
               live=None, frame: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Per team-week: how many players (`role` = starter / bench / any) scored
    over `threshold`, sorted most first.

    `positions` / `exclude` filter on `Position` (the player's listed position;
    for starters `Position started in` is on the frame if you need the slot).
    `result` = 'loss' / 'win' filters on the final result — or, with
    `entering`, on the margin at that stage (< 0 loss / > 0 win). Every
    team-week is returned, n = 0 included, so a distribution is honest.
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
                     positions=positions, exclude=exclude, result=result)
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
    out = [f"'over {a.get('threshold'):g}' = {'>' if a.get('strict') else '>='} {a.get('threshold'):g}; "
           f"role={a.get('role')}" + (f"; positions={','.join(a['positions'])}" if a.get('positions') else "")
           + (f"; excluding {','.join(a['exclude'])}" if a.get('exclude') else "")]
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
