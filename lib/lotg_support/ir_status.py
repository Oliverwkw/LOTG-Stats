"""NFL injured reserve: who is on it, since when, and how long it keeps them out.

Inquiry-only, like `forecast` (its one caller): nothing the build runs imports
this module, and it writes nothing except through `scripts/ir_history.py`.

Why it exists. The forecast's injury model (`forecast.InjuryModel`) has one
return curve for every absence, fitted from the league's `player_week`: a player
who has missed one week is back the next about 36% of the time. That is right
for a player listed Out (2026: 37% played the next week) and wrong for a player
on injured reserve, who by rule cannot play until he has missed a minimum number
of games:

  * **3 games in 2021, 4 from 2022** — read off nflverse's weekly rosters, not
    assumed: of the in-season IR runs of QB/RB/WR/TE that ended in a return,
    2021's shortest was 3 games and 2022-2025's was 4 (one 2025 run of 3 is a
    roster-status glitch: Mecole Hardman is coded RES/A01 the week before his
    R01 rows begin). 2026's own injury tracker agrees: 0 of 35 in-season IR
    placements came back before missing 4 games.
  * Once eligible, players do not come back on the general curve either: many
    IR stints are season-ending. `ir_return_model` fits P(back) per game past
    the minimum from the same runs.

Two sources say who is on IR and since when, chosen per season:

  * **2026 on: `data/injury_tracker.csv`**, the build's own gameday captures of
    Sleeper's `injury_status` (one row per rostered player-week, byes marked).
  * **2021-2025: `plan/notes/ir_spells.csv`**, every IR run of an NFL QB/RB/WR/
    TE from nflverse's weekly rosters (`status_description_abbr` R01 / R48 =
    reserve/injured, and reserve/injured designated for return), written by
    `scripts/ir_history.py`. Committed so the forecast and its tests stay
    offline. It is what makes a rewound forecast (`forecast.backtest`) able to
    use the IR rule without seeing the future: a run is used only for the weeks
    up to the cutoff.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import inquiry as Q

__all__ = ["IR_CODES", "TRACKER_IR", "SKILL", "ir_min_games", "history_path", "build_history",
           "history", "IRReturnModel", "ir_return_model", "on_ir", "check_history"]

#: nflverse `status_description_abbr` codes for injured reserve.
IR_CODES = ("R01", "R48")
#: Sleeper `injury_status` values in the tracker that mean injured reserve.
TRACKER_IR = frozenset({"IR"})
SKILL = ("QB", "RB", "WR", "TE")
#: First season read from the tracker rather than the nflverse history file.
TRACKER_FIRST_SEASON = 2026


def ir_min_games(year: int) -> int:
    """Games a player placed on IR in season must miss (3 through 2021, 4 from 2022)."""
    return 3 if int(year) <= 2021 else 4


def history_path(root: Optional[Path] = None) -> Path:
    return Path(root or Q.repo_root()) / "plan" / "notes" / "ir_spells.csv"


# ---------------------------------------------------------------------------
# The history file (2021-2025), from nflverse weekly rosters
# ---------------------------------------------------------------------------
def _runs_from_rosters(rosters: pd.DataFrame) -> pd.DataFrame:
    """One row per IR run in one season's weekly rosters.

    A run is consecutive roster rows coded IR; a gap of up to two weeks between
    rows is a bye (teams have no row on their bye), so it does not end the run.
    `games_on_ir` counts the rows, i.e. the team's games the player sat out on
    IR. The run's outcome is `returned` when the next row (within two weeks)
    has him active, `season_end` when the season's rows run out, and `other`
    (released, traded, moved to another list) otherwise — censored, not a
    return.
    """
    d = rosters[(rosters["game_type"] == "REG") & rosters["position"].isin(SKILL)].copy()
    d["week"] = pd.to_numeric(d["week"], errors="coerce").astype(int)
    d = d.sort_values(["gsis_id", "week"]).drop_duplicates(["gsis_id", "week"], keep="last")
    rows = []
    for gsis, g in d.groupby("gsis_id", sort=False):
        wk = g["week"].to_numpy(int)
        ir = g["status_description_abbr"].isin(IR_CODES).to_numpy(bool)
        status = g["status"].astype(str).to_numpy()
        i = 0
        while i < len(wk):
            if not ir[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(wk) and ir[j + 1] and wk[j + 1] - wk[j] <= 2:
                j += 1
            nxt = j + 1 if j + 1 < len(wk) and wk[j + 1] - wk[j] <= 2 else None
            if nxt is not None and status[nxt] == "ACT":
                outcome, ret = "returned", int(wk[nxt])
            elif j + 1 >= len(wk):
                outcome, ret = "season_end", None
            else:
                outcome, ret = "other", None
            r = g.iloc[i]
            rows.append({"season": int(r["season"]), "gsis_id": str(gsis),
                         "sleeper_id": "" if pd.isna(r.get("sleeper_id")) else str(r.get("sleeper_id")).split(".")[0],
                         "player": str(r["full_name"]), "position": str(r["position"]),
                         "team": str(r["team"]), "start_week": int(wk[i]), "last_week": int(wk[j]),
                         "games_on_ir": int(j - i + 1), "weeks": " ".join(str(int(w)) for w in wk[i:j + 1]),
                         "outcome": outcome, "return_week": ret})
            i = j + 1
    return pd.DataFrame(rows)


def build_history(seasons: Sequence[int], cache_dir: Optional[Path] = None) -> pd.DataFrame:
    """Every IR run of an NFL QB/RB/WR/TE in `seasons` (downloads weekly rosters)."""
    from . import external as X
    cfg = X.ExternalConfig(cache_dir=Path(cache_dir) if cache_dir else Path(Q.repo_root()) / ".cache")
    frames = [_runs_from_rosters(X.load_nflverse_weekly_rosters(cfg, int(y))) for y in seasons]
    out = pd.concat(frames, ignore_index=True)
    out["return_week"] = out["return_week"].astype("Int64")
    return out.sort_values(["season", "start_week", "player"]).reset_index(drop=True)


@functools.lru_cache(maxsize=None)
def _history_cached(root: str) -> pd.DataFrame:
    path = history_path(Path(root))
    if not path.exists():
        return pd.DataFrame(columns=["season", "gsis_id", "sleeper_id", "player", "position", "team",
                                     "start_week", "last_week", "games_on_ir", "weeks", "outcome",
                                     "return_week"])
    df = pd.read_csv(path, dtype={"gsis_id": str, "sleeper_id": str, "weeks": str})
    df["sleeper_id"] = df["sleeper_id"].fillna("").astype(str).str.split(".").str[0]
    return df


def history() -> pd.DataFrame:
    """The committed nflverse IR runs (`plan/notes/ir_spells.csv`); empty if absent."""
    return _history_cached(str(Q.repo_root()))


# ---------------------------------------------------------------------------
# How long IR keeps a player out once he is eligible
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IRReturnModel:
    """P(an IR player plays) by games already missed on IR.

    recovery[k]   P(he plays the next game | he has missed min + k games on IR
                  and not yet come back), k = 0..len-1; `tail` beyond that.
    runs          in-season IR runs the fit used; returned how many came back.
    Rate after eligibility, 2021-25 rostered players: 21% at the first
    eligible game, then 17%, 8%, 11%, 7%, 6%, about 4% a week after that —
    many IR stints are season-ending.
    """
    recovery: Tuple[float, ...]
    tail: float
    runs: int
    returned: int
    seasons: Tuple[int, ...]

    def hazard(self, games_missed: np.ndarray, year: int) -> np.ndarray:
        """P(back this week) for IR players who have missed `games_missed` games on IR."""
        k = np.asarray(games_missed, dtype=int) - ir_min_games(year)
        table = np.array(self.recovery + (self.tail,))
        out = table[np.clip(k, 0, len(self.recovery))]
        return np.where(k < 0, 0.0, out)

    def return_curve(self, games_missed: int, weeks: int, year: int) -> np.ndarray:
        """P(he has played by each of the next `weeks` weeks)."""
        out = np.empty(weeks)
        still_out = 1.0
        for t in range(weeks):
            r = float(self.hazard(np.array([games_missed + t]), year)[0])
            still_out *= 1.0 - r
            out[t] = 1.0 - still_out
        return out


@functools.lru_cache(maxsize=None)
def _rostered(root: str) -> frozenset:
    """{(season, Sleeper id)} of every player-week in the league's player_week."""
    path = Path(root) / "exports" / "player_week.csv"
    if not path.exists():
        return frozenset()
    d = pd.read_csv(path, usecols=["Year", "Player ID"], dtype=str).dropna()
    return frozenset(zip(pd.to_numeric(d["Year"], errors="coerce").astype(int),
                         d["Player ID"].astype(str).str.split(".").str[0]))


@functools.lru_cache(maxsize=None)
def _tracker_runs(root: str) -> pd.DataFrame:
    """The tracker's in-season IR runs, in the history file's shape.

    A run is consecutive IR weeks; it ends `returned` the first non-bye week he
    took the field, `other` if he left IR without playing, and `ongoing` (no
    opportunity yet, so censored like `season_end`) if it is still running at
    the newest capture.
    """
    t = _tracker(root)
    rows = []
    for (season, pid), g in t.sort_values("week").groupby(["season", "player_id"], sort=False):
        g = g.reset_index(drop=True)
        ir, wk = g["ir"].to_numpy(bool), g["week"].to_numpy(int)
        bye = g["bye"].to_numpy(bool)
        played = g["played"].astype(str).str.lower().eq("true").to_numpy(bool)
        i = 0
        while i < len(g):
            if not ir[i] or (i > 0 and ir[i - 1]):
                i += 1
                continue
            j, missed, outcome, weeks = i, 0, "ongoing", []
            while j < len(g):
                if bye[j]:
                    j += 1
                    continue
                if played[j]:
                    outcome = "returned"
                    break
                if not ir[j]:
                    outcome = "other"
                    break
                missed += 1
                weeks.append(int(wk[j]))
                j += 1
            rows.append({"season": int(season), "sleeper_id": str(pid), "start_week": int(wk[i]),
                         "games_on_ir": missed, "outcome": outcome,
                         "weeks": " ".join(map(str, weeks))})
            i = max(j, i + 1)
    return pd.DataFrame(rows, columns=["season", "sleeper_id", "start_week", "games_on_ir",
                                       "outcome", "weeks"])


@functools.lru_cache(maxsize=None)
def _ir_model_cached(exclude: Optional[int], root: str, cap: int, population: str,
                     tracker: bool) -> IRReturnModel:
    h = _history_cached(root)
    if population == "rostered" and len(h):
        ros = _rostered(root)
        h = h[[(int(s), str(p)) in ros for s, p in zip(h["season"], h["sleeper_id"])]]
    elif population != "nfl":
        raise ValueError(f"population must be rostered/nfl, got {population!r}")
    frames = [h[["season", "start_week", "games_on_ir", "outcome"]]] if len(h) else []
    if tracker:
        tr = _tracker_runs(root)
        if len(tr):
            frames.append(tr[["season", "start_week", "games_on_ir", "outcome"]])
    runs = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["season", "start_week", "games_on_ir", "outcome"])
    runs = runs[(runs["start_week"] >= 2) & (runs["season"] != exclude)]
    at_risk = np.zeros(cap + 1)
    ended = np.zeros(cap + 1)
    for r in runs.itertuples(index=False):
        lo = ir_min_games(int(r.season))
        g = int(r.games_on_ir)
        top = g if r.outcome == "returned" else g - 1
        for j in range(lo, top + 1):
            b = min(j - lo, cap)
            at_risk[b] += 1
            if r.outcome == "returned" and j == g:
                ended[b] += 1
    rec = tuple(float(ended[k] / at_risk[k]) if at_risk[k] else 0.0 for k in range(cap))
    tail = float(ended[cap] / at_risk[cap]) if at_risk[cap] else 0.05
    seasons = tuple(sorted(int(s) for s in set(runs["season"])))
    return IRReturnModel(recovery=rec, tail=max(tail, 0.01), runs=int(len(runs)),
                         returned=int((runs["outcome"] == "returned").sum()), seasons=seasons)


def ir_return_model(exclude_from_fits: Optional[int] = None, cap: int = 6,
                    population: str = "rostered", tracker: bool = True) -> IRReturnModel:
    """The IR return curve from every in-season IR run, leaving
    `exclude_from_fits` out.

    population  "rostered" (default): only runs of players this league rostered
                that season — the population the forecast applies it to. Those
                come back more often than the NFL's IR list as a whole: at the
                first eligible game 21% (n=195) against 17.5% (n=388), 2021-25.
                "nfl": every QB/RB/WR/TE.
    tracker     also count the injury tracker's runs (2026 on). They are the
                live season's own evidence, so a forecast of 2026 may use them;
                a rewound past season has no tracker rows to see. Through 2026
                week 10, 8 of 20 tracked players were back at the first eligible
                game, about twice the 2021-25 rate: a small sample, and possibly
                the 2026 rule letting practice resume after two games. Watch it.
    """
    return _ir_model_cached(exclude_from_fits, str(Q.repo_root()), int(cap), population, bool(tracker))


# ---------------------------------------------------------------------------
# Who is on IR at a cutoff
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _tracker(root: str) -> pd.DataFrame:
    path = Path(root) / "data" / "injury_tracker.csv"
    if not path.exists():
        return pd.DataFrame(columns=["season", "week", "player_id", "injury_status", "on_bye"])
    t = pd.read_csv(path, dtype=str)
    t["season"] = pd.to_numeric(t["season"], errors="coerce").astype("Int64")
    t["week"] = pd.to_numeric(t["week"], errors="coerce").astype("Int64")
    t["ir"] = t["injury_status"].fillna("").isin(TRACKER_IR)
    t["bye"] = t["on_bye"].astype(str).str.lower().eq("true")
    return t


@functools.lru_cache(maxsize=None)
def _on_ir_cached(year: int, through_week: int, root: str) -> Dict[str, Tuple[int, int]]:
    out: Dict[str, Tuple[int, int]] = {}
    if year >= TRACKER_FIRST_SEASON:
        t = _tracker(root)
        # what is known while week through_week + 1 is being played: its gameday
        # captures exist, nothing after it does
        t = t[(t["season"] == year) & (t["week"] <= through_week + 1)]
        for pid, g in t.sort_values("week").groupby("player_id", sort=False):
            ir = g["ir"].to_numpy(bool)
            if not ir[-1]:
                continue
            weeks = g["week"].to_numpy(int)
            byes = g["bye"].to_numpy(bool)
            i = len(ir) - 1
            while i > 0 and ir[i - 1] and weeks[i] - weeks[i - 1] <= 2:
                i -= 1
            missed = int(sum(1 for w, b in zip(weeks[i:], byes[i:]) if w <= through_week and not b))
            out[str(pid)] = (int(weeks[i]), missed)
        return out
    h = _history_cached(root)
    if not len(h):
        return out
    # strictly as of the cutoff: on IR for week through_week, games counted to it
    h = h[(h["season"] == year) & (h["start_week"] <= through_week) & (h["last_week"] >= through_week)]
    for r in h.itertuples(index=False):
        if not r.sleeper_id:
            continue
        weeks = [int(w) for w in str(r.weeks).split()]
        out[str(r.sleeper_id)] = (int(r.start_week), sum(1 for w in weeks if w <= through_week))
    return out


def on_ir(year: int, through_week: int) -> Dict[str, Tuple[int, int]]:
    """{Sleeper player id: (week placed, games already missed on IR)} for players
    on injured reserve as of `through_week`, i.e. entering week through_week + 1.

    2026 on, from the injury tracker, including the gameday captures of week
    through_week + 1 (live, that is the week being played). Earlier seasons,
    from the nflverse history file and strictly to the cutoff, so a rewound
    forecast sees no placement it could not have known about.
    """
    if through_week <= 0:
        return {}
    return _on_ir_cached(int(year), int(through_week), str(Q.repo_root()))


def check_history() -> list:
    """The IR minimum the forecast enforces must hold in the history it reads.

    Returns problems (empty = fine): a season with too few runs, or more than one
    returned run shorter than that season's minimum (one known glitch allowed).
    """
    h = history()
    problems = []
    if not len(h):
        return [f"{history_path().name} is missing: run scripts/ir_history.py"]
    for season, g in h.groupby("season"):
        inseason = g[g["start_week"] >= 2]
        if len(inseason) < 100:
            problems.append(f"{season}: only {len(inseason)} in-season IR runs")
        short = inseason[(inseason["outcome"] == "returned")
                         & (inseason["games_on_ir"] < ir_min_games(int(season)))]
        if len(short) > 1:
            problems.append(f"{season}: {len(short)} IR returns before the {ir_min_games(int(season))}-game "
                            f"minimum: {', '.join(short['player'].head(5))}")
    return problems
