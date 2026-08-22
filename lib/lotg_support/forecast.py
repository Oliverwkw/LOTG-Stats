"""Championship odds for a season that has not finished yet.

Inquiry-only, like `inquiry`, `analysis` and `replay`: nothing the build runs
imports this module, and it writes nothing.

The question is "what is each team's % chance of winning this year", asked
before or during a season. That is a forecast, not a lookup, so every step is
built to be inspectable and falsifiable — and every judgement in it is a
parameter fitted from this league's own history rather than a constant someone
liked the look of.

## The five things a fantasy forecast has to get right

**1. What a player is worth** (`player_rates`). His scoring rate in this league
over the previous two seasons, over *available* weeks only — the build's own
`Bye?`, `Injury?` and `Suspension?` flags — weighted toward the recent end of
each season (`RateModel.halflife`), shrunk toward the median rate of a rostered
player at his position, then adjusted for **age** by a curve fitted from the
league's own year-over-year changes (`age_curve`). A 30-year-old WR and a
24-year-old WR with the same rate are not the same asset, and the data says so:
about -0.28 points a week per year of age at WR, -0.18 at RB, -0.10 at QB.

**2. What a rookie is worth** (`rookie_price`). A drafted rookie has no rate at
all, and pricing him at zero quietly penalises whoever holds the most picks. He
is priced instead from his **draft-day KTC**, fitted against what past classes
actually returned in year one. That is what makes a weak class read as weak
without anyone having to assert it: the market prices the class, the fit turns
the price into points. Pick slot is the fallback when KTC is missing.

**3. Who can actually play** (`availability_rates`, `fielded_distribution`,
`research_overrides`). Four separate things:

  - **Taxi-squad players cannot be started at all.** They sit in the roster's
    player list and an optimal-lineup routine will happily start them.
  - **A rostered player with no NFL team cannot score for anyone.** Read
    straight from the snapshot; no judgement needed.
  - **In the preseason, Sleeper's injury flags are worthless.** A manager parks
    a player in the IR slot in December and never moves him, so an August
    snapshot records how *last* season ended. Of the fifteen players flagged on
    2026 rosters, **eleven were injured in the closing weeks of 2025** — and the
    flags are wrong in both directions: three are now fully healthy, while one
    is an unsigned free agent who may never play again. So
    `AvailabilityModel.designations="auto"` believes them only once the season
    has started, and the empty 2026 `nflverse_injuries.csv` confirms why: there
    are no official injury reports before any game is played.
  - **What replaces them is dated, sourced outside reporting**
    (`plan/notes/forecast_status_<year>.csv`) — per-player availability and rate
    adjustments, each with a note, a URL and the date it was true. This is the
    only place a human judgement about the real world enters this module, and it
    is deliberately the most auditable thing in it. `check_research_file`
    refuses a row that names nobody on a roster or omits its source.
  - **Everyone else misses time too**, at a rate that is mildly predictable
    per player (year-over-year r ≈ 0.2), so availability is shrunk hard toward
    the positional base rate of ~82%.

  Availability is then *simulated*, not averaged: each draw knocks players out
  and the lineup is refilled from whoever is left. That is what makes **depth**
  worth something — a team whose stars have no backup loses more when they sit,
  and the spread of its weekly scores is wider.

**4. Who plays whom** (`schedule`, `_bracket`). Every week is simulated over
the season's **real pairings**, so strength of schedule is handled whether or
not it matters — and whether it matters is a fact about the season, not an
assumption: 2026's fourteen weeks are a clean double round-robin (every pair
exactly twice, so no team has an easier draw by construction), while 2021-2025
ran fifteen weeks, where some pairs met three times and some twice.
`schedule(year, strength).sos` prices each team's draw in points of opponent
strength per week. Where matchups always bite is the bracket: 1v4 / 2v3, +5 to
the higher seed, and from 2026 a two-week final — from `replay._standings` /
`replay._bracket`, the same code a counterfactual replay uses.

**5. How much of this is knowable at all** (`calibrate`). Every completed
season's preseason roster is projected the same way and regressed on what the
team actually averaged. That fit — its out-of-sample correlation, and the split
of its residual into "wrong about the team" and "fantasy football is noisy" —
is what the simulation's spread is made of. A forecast that does not report
this is asserting its own confidence.

What is still *not* modelled, and no answer from here may pretend otherwise:

- **in-season trades, waivers and drops** — the roster is frozen as it stands;
- **NFL-side matchup quality** — which defence a player draws in a given week.
  The committed data has no NFL schedule or team-defence table, so weekly
  opponent adjustments are out of reach here, not merely unimplemented;
- **NFL depth-chart news** the exports do not contain (holdouts, camp battles,
  a rookie's landing spot) beyond what KTC's market price already reflects;
- **correlated byes** — a roster stacked on one NFL team loses them together.
  Availability draws are independent, so that cost is missed.
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import inquiry as Q
from . import lineup as L
from . import replay as R

__all__ = [
    "RateModel", "AvailabilityModel", "Calibration", "TeamOdds", "Forecast",
    "Schedule", "schedule", "age_curve", "rookie_price", "rookie_class_strength", "player_rates",
    "availability_rates", "startable_pool", "fielded_distribution",
    "ResearchNote", "research_overrides", "research_path", "check_research_file",
    "roster_projection", "calibrate", "forecast",
    "Backtest", "BacktestRow", "backtest", "render_backtest", "check_beats_uniform",
    "check_bracket_pipeline", "check_completed_season_certainty",
    "check_schedule_is_balanced", "validate", "render",
]

_POSITIONS = ("QB", "RB", "WR", "TE")

#: Sleeper designations that mean "not playing for a while", as opposed to
#: `Questionable`, which in an August snapshot is stale week-17 noise.
OUT_DESIGNATIONS = frozenset({"IR", "PUP", "NA", "DNR", "Out", "Sus", "COV"})


# ---------------------------------------------------------------------------
# Assumptions, all named and defaulted (playbook rule 6)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RateModel:
    """Every debatable choice in turning history into a per-player rate.

    weights        how much each prior season counts, most recent first.
    halflife       weeks of half-life for recency *inside* a season, so a
                   player who finished strong projects above one who faded.
                   `None` weights every week equally.
    shrink_games   pseudo-games of the positional prior mixed into every rate;
                   6 means a six-game sample weighs equally against the prior.
    prior_games    minimum games to count toward the positional prior. 1 means
                   "a randomly rostered player at this position", which is what
                   a backup should be shrunk toward; raising it shrinks
                   everyone toward *starter* level, which in a superflex league
                   quietly promotes backup QBs.
    age_adjust     apply the fitted age curve.
    age_shrink     pseudo-observations pulling each position's age slope toward
                   the pooled slope, so a thin position (TE) cannot invent a
                   curve of its own.
    rookie_pricing "ktc" prices a rookie from his draft-day market value;
                   "slot" uses the historical mean for his pick range.
    undrafted_ppg  a player with neither history nor a draft slot.
    """
    weights: Tuple[float, ...] = (0.65, 0.35)
    halflife: Optional[float] = 8.0
    shrink_games: float = 6.0
    prior_games: int = 1
    age_adjust: bool = True
    age_shrink: float = 100.0
    rookie_pricing: str = "ktc"
    undrafted_ppg: float = 3.0

    def label(self) -> str:
        w = "/".join(f"{x:g}" for x in self.weights)
        return (f"weights={w} halflife={self.halflife or 'flat'} "
                f"shrink={self.shrink_games:g} prior_games={self.prior_games} "
                f"age={'on' if self.age_adjust else 'off'} rookies={self.rookie_pricing}")


@dataclass(frozen=True)
class AvailabilityModel:
    """Who can be started, and how often.

    lookback       seasons of history behind a player's own availability rate.
    shrink_weeks   pseudo-weeks of the positional base rate mixed in. Injury
                   proneness repeats year to year at only r ~= 0.2, so this is
                   deliberately heavy.
    exclude_taxi   taxi-squad players cannot be started. Structural, set in the
                   preseason, and applied to backtest and live season alike.
    reserve_availability
                   availability for a player carrying an IR/PUP-class
                   designation, *when that designation means something*.
                   Default 0.51 is measured: every player this league had
                   injured in a week 1, 2021-2025, was available in 51% of his
                   remaining weeks (against an 82% base rate).
    designations   when to believe Sleeper's `injury_status` and the reserve
                   list. "auto" (the default) believes them only once the
                   season has started, because **in the preseason they are
                   stale**: a manager parks a player in the IR slot in December
                   and never moves him, so an August snapshot is a record of how
                   *last* season ended. Of the fifteen players flagged on 2026
                   rosters, eleven were injured in the closing weeks of 2025 —
                   including three who are now fully healthy and one who is a
                   free agent unlikely to play again. "always" and "never"
                   override.
    research       apply the curated status file for the season if one exists
                   (`plan/notes/forecast_status_<year>.csv`) — dated,
                   sourced, per-player availability and rate adjustments from
                   outside reporting, which is the only thing that *can* replace
                   a stale preseason designation. Off for the backtest: past
                   seasons have no such file and could not have had one.
    unsigned_availability
                   a rostered player with no NFL team cannot score for anyone.
                   He may yet sign, so this is low rather than zero. Read
                   straight from the snapshot, no research needed — but the
                   snapshot only knows *today's* free agents, so like the
                   designations this is live-season-only. Applying it to a
                   backtest would be asking a 2022 projection to know who would
                   be out of the league by 2026, and it shows: it lifts
                   out-of-sample r from 0.68 to 0.73, which is leakage, not
                   skill. 1.0 disables it.
    draws          availability draws per team when building the fielded-lineup
                   distribution.
    """
    lookback: int = 2
    shrink_weeks: float = 10.0
    exclude_taxi: bool = True
    reserve_availability: float = 0.51
    designations: str = "auto"
    research: bool = True
    unsigned_availability: float = 0.35
    draws: int = 3000

    def uses_designations(self, year: int) -> bool:
        if self.designations == "always":
            return True
        if self.designations == "never":
            return False
        if self.designations != "auto":
            raise ValueError(f"designations must be auto/always/never, got {self.designations!r}")
        # in-season Sleeper keeps these current; in the preseason they are a
        # record of how last season ended, so they are ignored.
        return bool(Q.played_weeks(year))

    def label(self) -> str:
        return (f"shrink={self.shrink_weeks:g}w taxi={'out' if self.exclude_taxi else 'in'} "
                f"reserve={self.reserve_availability:.2f} designations={self.designations} "
                f"research={'on' if self.research else 'off'} "
                f"unsigned={self.unsigned_availability:.2f}")


# ---------------------------------------------------------------------------
# Layer 0: the sheets, shaped once
# ---------------------------------------------------------------------------
def _player_week() -> pd.DataFrame:
    df = Q.load_sheet("player_week").copy()
    for col in ("Bye?", "Injury?", "Suspension?"):
        df[col] = df[col].astype(str).str.lower().isin(("true", "1", "yes"))
    df["Hurt"] = df["Injury?"] | df["Suspension?"]
    df["Available"] = ~(df["Bye?"] | df["Hurt"])
    df["Points"] = pd.to_numeric(df["Points"], errors="coerce")
    df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df["Week"] = pd.to_numeric(df["Week"], errors="coerce").astype("Int64")
    return df.sort_values(["Player", "Year", "Week"])


@functools.lru_cache(maxsize=None)
def _season_rates(year: int, halflife: Optional[float], root: str) -> pd.DataFrame:
    """games, recency-weighted mean points and age, per player, for one season.

    Weeks the player was unavailable are excluded: a rate is what he scores when
    he plays. How often he plays is a separate question, handled by
    `availability_rates`, because mixing the two hides which one is driving an
    answer.
    """
    df = _player_week()
    d = df[(df["Year"] == year) & df["Available"]].dropna(subset=["Points"])
    rows = {}
    for name, g in d.groupby("Player", sort=False):
        pts = g["Points"].to_numpy(float)
        n = len(pts)
        if halflife:
            w = 0.5 ** ((n - 1 - np.arange(n)) / float(halflife))
        else:
            w = np.ones(n)
        rows[name] = (n, float((pts * w).sum() / w.sum()), float(np.nanmax(g["Age"])))
    return pd.DataFrame.from_dict(rows, orient="index", columns=["count", "mean", "age"])


@functools.lru_cache(maxsize=None)
def _season_positions(year: int, root: str) -> Dict[str, str]:
    df = _player_week()
    d = df[df["Year"] == year]
    if d.empty:
        return {}
    return d.groupby("Player")["Position"].agg(lambda s: s.mode().iloc[0]).to_dict()


_PICK_RE = re.compile(r"^(\d+)\.(\d+)$")


@functools.lru_cache(maxsize=None)
def _draft_board(root: str) -> pd.DataFrame:
    """Every rookie-draft pick that actually named a player.

    The startup draft and 2021's veteran draft carry text years and drop out;
    so does a future pick, which is written `1.??` because its slot is not known
    yet. Overall pick number assumes the league's eight teams.
    """
    picks = Q.load_sheet("picks")
    rows = []
    for _, row in picks.iterrows():
        year_text = str(row.get("Year", "")).strip()
        if not (len(year_text) == 4 and year_text.isdigit()):
            continue
        m = _PICK_RE.match(str(row.get("Number", "")).strip())
        name = str(row.get("Player Picked", "")).strip()
        if not m or not name or name.lower() == "unknown":
            continue
        ktc = pd.to_numeric(pd.Series([row.get("KTC on draft day")]), errors="coerce").iloc[0]
        rows.append(dict(year=int(year_text), player=name,
                         overall=(int(m.group(1)) - 1) * 8 + int(m.group(2)),
                         ktc=float(ktc) if pd.notna(ktc) else np.nan))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Layer 1: trends — the age curve
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AgeCurve:
    """Points per week gained or lost per year of age, by position."""
    slope: Dict[str, float]
    reference: Dict[str, float]
    pooled: float
    n: Dict[str, int]

    def adjust(self, position: str, age: float) -> float:
        if position not in self.slope or not np.isfinite(age):
            return 0.0
        return self.slope[position] * (age - self.reference[position])


@functools.lru_cache(maxsize=None)
def _age_curve_cached(exclude_year: Optional[int], halflife: Optional[float],
                      shrink: float, root: str) -> AgeCurve:
    seasons = Q.export_seasons()
    rows = []
    for year in seasons:
        if exclude_year is not None and year == exclude_year:
            continue
        prev, cur = year - 1, year
        if prev not in seasons:
            continue
        a = _season_rates(prev, halflife, root)
        b = _season_rates(cur, halflife, root)
        pos = _season_positions(prev, root)
        for name in a.index:
            if name not in b.index or b.loc[name, "count"] < 4 or a.loc[name, "count"] < 6:
                continue
            rows.append((pos.get(name, ""), float(a.loc[name, "mean"]),
                         float(a.loc[name, "age"]) + 1.0, float(b.loc[name, "mean"])))
    frame = pd.DataFrame(rows, columns=["pos", "prev", "age", "now"]).dropna()
    if len(frame) < 40:
        return AgeCurve({}, {}, 0.0, {})

    def fit(sub: pd.DataFrame) -> float:
        X = np.column_stack([sub.prev, sub.age, np.ones(len(sub))])
        coef, *_ = np.linalg.lstsq(X, sub.now.to_numpy(float), rcond=None)
        return float(coef[1])

    pooled = fit(frame)
    slope, reference, counts = {}, {}, {}
    for pos in _POSITIONS:
        sub = frame[frame.pos == pos]
        counts[pos] = len(sub)
        reference[pos] = float(sub.age.mean()) if len(sub) else float(frame.age.mean())
        if len(sub) < 20:
            slope[pos] = pooled
            continue
        # shrink each position toward the pooled slope: TE alone would otherwise
        # invent a positive curve out of a hundred observations.
        raw = fit(sub)
        slope[pos] = (raw * len(sub) + pooled * shrink) / (len(sub) + shrink)
    return AgeCurve(slope, reference, pooled, counts)


def age_curve(exclude_year: Optional[int] = None,
              model: RateModel = RateModel()) -> AgeCurve:
    """Fit "points per week per year of age", per position, from this league.

    Fitted as the age coefficient in `next_year_rate ~ this_year_rate + age`, so
    it is the part of ageing that is *not* just regression to the mean, and each
    position is shrunk toward the pooled slope.
    """
    return _age_curve_cached(exclude_year, model.halflife, model.age_shrink,
                             str(Q.repo_root()))


# ---------------------------------------------------------------------------
# Layer 2: rookies, priced by the market
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RookiePrice:
    """Rookie-year points per week, as a function of draft-day KTC or pick."""
    ktc_slope: float
    ktc_intercept: float
    ktc_r: float
    ktc_n: int
    slot_bins: Tuple[Tuple[int, float], ...]
    undrafted: float

    def price(self, ktc: Optional[float], overall: Optional[int], how: str) -> float:
        if how == "ktc" and ktc is not None and np.isfinite(ktc) and self.ktc_n:
            return max(self.ktc_slope * ktc + self.ktc_intercept, 0.0)
        if overall is not None:
            for edge, val in self.slot_bins:
                if overall <= edge:
                    return val
        return self.undrafted


@functools.lru_cache(maxsize=None)
def _rookie_price_cached(exclude_year: Optional[int], halflife: Optional[float],
                         undrafted: float, root: str) -> RookiePrice:
    board = _draft_board(root)
    rows = []
    for year, group in board.groupby("year"):
        if exclude_year is not None and year == exclude_year:
            continue
        rates = _season_rates(int(year), halflife, root)
        if rates.empty:
            continue
        for _, row in group.iterrows():
            ppg = float(rates.loc[row.player, "mean"]) if row.player in rates.index else 0.0
            rows.append((row.overall, row.ktc, ppg))
    if not rows:
        return RookiePrice(0.0, 0.0, 0.0, 0, ((10 ** 6, 5.3),), undrafted)
    frame = pd.DataFrame(rows, columns=["overall", "ktc", "ppg"])

    priced = frame.dropna(subset=["ktc"])
    if len(priced) >= 30:
        slope, intercept = np.polyfit(priced.ktc, priced.ppg, 1)
        r = float(np.corrcoef(priced.ktc, priced.ppg)[0, 1])
        n = len(priced)
    else:
        slope = intercept = r = 0.0
        n = 0

    bins, low = [], 0
    for edge in (4, 8, 16, 24, 10 ** 6):
        sel = frame[(frame.overall > low) & (frame.overall <= edge)]
        if len(sel):
            bins.append((int(edge), float(sel.ppg.mean())))
        low = edge
    return RookiePrice(float(slope), float(intercept), r, n,
                       tuple(bins) or ((10 ** 6, 5.3),), undrafted)


def rookie_price(exclude_year: Optional[int] = None,
                 model: RateModel = RateModel()) -> RookiePrice:
    """Fit rookie-year scoring against draft-day KTC, from past classes.

    Zeros are kept: a rookie who never suits up is part of what a pick is worth.
    `exclude_year` drops one class, which is what the backtest uses so a season
    is never calibrated partly on itself.
    """
    return _rookie_price_cached(exclude_year, model.halflife, model.undrafted_ppg,
                                str(Q.repo_root()))


def rookie_class_strength(year: int) -> Dict[str, float]:
    """How this year's rookie class prices against the classes before it.

    Compares draft-day KTC over the same pick range, so a class that the market
    rates poorly reads as weak here without anyone asserting it.
    """
    board = _draft_board(str(Q.repo_root())).dropna(subset=["ktc"])
    this = board[board.year == year]
    past = board[board.year < year]
    if this.empty or past.empty:
        return {}
    overlap = this.overall.max()
    past = past[past.overall <= overlap]
    out = {
        "year": float(year),
        "picks": float(len(this)),
        "mean_ktc": float(this.ktc.mean()),
        "median_ktc": float(this.ktc.median()),
        "past_mean_ktc": float(past.ktc.mean()),
        "past_median_ktc": float(past.ktc.median()),
        "top4_mean_ktc": float(this.nsmallest(4, "overall").ktc.mean()),
        "past_top4_mean_ktc": float(past[past.overall <= 4].ktc.mean()),
    }
    out["ratio"] = out["mean_ktc"] / out["past_mean_ktc"] if out["past_mean_ktc"] else float("nan")
    by_year = board[board.overall <= overlap].groupby("year").ktc.mean()
    out["rank_of_classes"] = float(by_year.rank(ascending=False).get(year, float("nan")))
    out["classes"] = float(len(by_year))
    return out


# ---------------------------------------------------------------------------
# Layer 3: player rates
# ---------------------------------------------------------------------------
def player_rates(year: int, model: RateModel = RateModel(),
                 exclude_from_fits: Optional[int] = None) -> Dict[str, float]:
    """{player name: projected points per available week} for `year`.

    Built only from seasons strictly before `year`, so it is a genuine preseason
    projection and the backtest cannot see the future.
    """
    root = str(Q.repo_root())
    hl = model.halflife
    seasons = [(year - i - 1, w) for i, w in enumerate(model.weights)]
    rates = [(_season_rates(y, hl, root), w) for y, w in seasons]

    positions: Dict[str, str] = {}
    ages: Dict[str, float] = {}
    for offset, (y, _) in enumerate(seasons):
        for name, pos in _season_positions(y, root).items():
            positions.setdefault(name, pos)
        frame = rates[offset][0]
        for name in frame.index:
            # age at the start of `year`, from the last season we saw him in
            ages.setdefault(name, float(frame.loc[name, "age"]) + offset + 1)

    recent = rates[0][0]
    established = recent[recent["count"] >= model.prior_games] if not recent.empty else recent
    pos_prior: Dict[str, float] = {}
    for pos in _POSITIONS:
        names = [n for n in established.index if positions.get(n) == pos]
        pos_prior[pos] = (float(established.loc[names, "mean"].median())
                          if names else model.undrafted_ppg)
    default_prior = (float(np.median(list(pos_prior.values()))) if pos_prior
                     else model.undrafted_ppg)
    curve = age_curve(exclude_from_fits, model) if model.age_adjust else None

    out: Dict[str, float] = {}
    names = set()
    for frame, _ in rates:
        names |= set(frame.index)
    for name in names:
        games = points = 0.0
        for frame, weight in rates:
            if name in frame.index:
                games += float(frame.loc[name, "count"]) * weight
                points += float(frame.loc[name, "count"]) * float(frame.loc[name, "mean"]) * weight
        pos = positions.get(name, "")
        value = ((points + model.shrink_games * pos_prior.get(pos, default_prior))
                 / (games + model.shrink_games))
        if curve is not None:
            value += curve.adjust(pos, ages.get(name, float("nan")))
        out[name] = max(value, 0.0)
    return out


# ---------------------------------------------------------------------------
# Layer 4: availability, eligibility and depth
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _roster_state(year: int, root: str) -> Dict[int, Dict[str, frozenset]]:
    """{roster_id: {taxi, reserve}} from the snapshot's roster file."""
    try:
        raw = Q._snap(f"season_{int(year)}/rosters.json")
    except FileNotFoundError:
        return {}
    return {int(r["roster_id"]): {"taxi": frozenset(str(p) for p in (r.get("taxi") or ())),
                                  "reserve": frozenset(str(p) for p in (r.get("reserve") or ()))}
            for r in raw}


@functools.lru_cache(maxsize=None)
def _designations(root: str) -> Dict[str, str]:
    """{player_id: Sleeper injury_status} as of the snapshot capture."""
    blob = Q._snap("sleeper_players_nfl.json")
    return {pid: str(meta.get("injury_status") or "")
            for pid, meta in blob.items() if meta.get("injury_status")}


@functools.lru_cache(maxsize=None)
def _unsigned(root: str) -> frozenset:
    """Player ids with no NFL team in the snapshot — they cannot score for anyone."""
    blob = Q._snap("sleeper_players_nfl.json")
    return frozenset(pid for pid, meta in blob.items() if not meta.get("team"))


@dataclass(frozen=True)
class ResearchNote:
    """One researched, sourced, dated statement about a player's season."""
    player: str
    availability: Optional[float]
    rate_multiplier: float
    note: str
    source: str
    as_of: str


def research_path(year: int) -> "Path":
    from pathlib import Path
    return Path(Q.repo_root()) / "plan" / "notes" / f"forecast_status_{int(year)}.csv"


@functools.lru_cache(maxsize=None)
def _research_cached(year: int, root: str) -> Tuple[ResearchNote, ...]:
    path = research_path(year)
    if not path.exists():
        return ()
    frame = pd.read_csv(path)
    out = []
    for _, row in frame.iterrows():
        avail = pd.to_numeric(pd.Series([row.get("availability")]), errors="coerce").iloc[0]
        mult = pd.to_numeric(pd.Series([row.get("rate_multiplier", 1.0)]), errors="coerce").iloc[0]
        out.append(ResearchNote(
            player=str(row["player"]).strip(),
            availability=float(avail) if pd.notna(avail) else None,
            rate_multiplier=float(mult) if pd.notna(mult) else 1.0,
            note=str(row.get("note", "")).strip(),
            source=str(row.get("source", "")).strip(),
            as_of=str(row.get("as_of", "")).strip()))
    return tuple(out)


def research_overrides(year: int) -> Dict[str, ResearchNote]:
    """Curated outside reporting for a season, keyed by player name.

    The file this reads is the *only* place in this module where a human
    judgement about the real world enters, and it is deliberately the most
    auditable thing here: every row carries the number, a note saying why, a
    URL and the date it was true. Nothing is inferred from it silently — the
    forecast reports how many players it moved and `check_research_file` refuses
    a row that names nobody on a roster or omits its source.
    """
    return {n.player: n for n in _research_cached(int(year), str(Q.repo_root()))}


def availability_rates(year: int, model: AvailabilityModel = AvailabilityModel()
                       ) -> Tuple[Dict[str, float], Dict[str, float]]:
    """({player name: P(available)}, {position: base rate}), from prior seasons.

    Injury proneness repeats year to year at only r ~= 0.2 in this league, so a
    player's own rate is shrunk hard toward his position's base.
    """
    df = _player_week()
    d = df[(df["Year"] < year) & (df["Year"] >= year - model.lookback)]
    if d.empty:
        return {}, {}
    ok = ~d["Hurt"]
    base = ok.groupby(d["Position"]).mean().to_dict()
    overall = float(ok.mean())
    grouped = ok.groupby([d["Player"], d["Position"]]).agg(["size", "mean"])
    out: Dict[str, float] = {}
    for (name, pos), row in grouped.iterrows():
        b = base.get(pos, overall)
        out[name] = float((row["mean"] * row["size"] + b * model.shrink_weeks)
                          / (row["size"] + model.shrink_weeks))
    base["_default"] = overall
    return out, base


def startable_pool(year: int, week: int = 1,
                   model: AvailabilityModel = AvailabilityModel()) -> Dict[int, List[str]]:
    """{roster_id: [player_id]} that could legally be started.

    Taxi-squad players are on the roster and in the week's player list, but the
    league cannot start them — v1 did, which is how a taxi quarterback ended up
    in a projected lineup.
    """
    state = _roster_state(year, str(Q.repo_root()))
    out: Dict[int, List[str]] = {}
    for rid, row in Q.week(year, week).items():
        taxi = state.get(rid, {}).get("taxi", frozenset()) if model.exclude_taxi else frozenset()
        out[rid] = [pid for pid in row.players if pid not in taxi]
    return out


@dataclass
class FieldedDistribution:
    """What a roster is expected to field, week to week, once injuries bite."""
    year: int
    teams: Dict[int, str]
    mean: Dict[int, float]
    sd: Dict[int, float]
    samples: Dict[int, np.ndarray]
    healthy: Dict[int, float]                     # best lineup with everyone up
    rookies: Dict[int, int] = field(default_factory=dict)
    sidelined: Dict[int, int] = field(default_factory=dict)
    unsigned: Dict[int, int] = field(default_factory=dict)
    researched: Dict[int, int] = field(default_factory=dict)
    unplaced: Dict[int, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def depth_cost(self, rid: int) -> float:
        """Points a week the roster loses to unavailability — the depth tax."""
        return self.healthy[rid] - self.mean[rid]


def fielded_distribution(year: int, model: RateModel = RateModel(),
                         availability: AvailabilityModel = AvailabilityModel(),
                         week: int = 1, seed: int = 12026,
                         exclude_from_fits: Optional[int] = None) -> FieldedDistribution:
    """Simulate who is available each week and refill the lineup from the rest.

    This is where depth stops being a word. Each draw knocks players out
    independently at their own availability rate, and the lineup is rebuilt from
    whoever is left using the build's own `compute_optimal_lineup` — so a team
    that loses a starter and has nobody behind him drops further than a team
    that does not, and its weekly spread is wider.
    """
    rates = player_rates(year, model, exclude_from_fits)
    price = rookie_price(exclude_from_fits, model)
    board = _draft_board(str(Q.repo_root()))
    class_board = board[board.year == year].set_index("player")
    avail, base = availability_rates(year, availability)
    use_flags = availability.uses_designations(year)
    designations = _designations(str(Q.repo_root())) if use_flags else {}
    unsigned = _unsigned(str(Q.repo_root()))
    notes = research_overrides(year) if availability.research else {}
    state = _roster_state(year, str(Q.repo_root()))
    players = Q.players()
    teams = Q.teams(year)
    pool = startable_pool(year, week, availability)
    rng = np.random.default_rng(seed)

    mean: Dict[int, float] = {}
    sd: Dict[int, float] = {}
    samples: Dict[int, np.ndarray] = {}
    healthy: Dict[int, float] = {}
    rookies: Dict[int, int] = {}
    sidelined: Dict[int, int] = {}
    unsigned_count: Dict[int, int] = {}
    researched: Dict[int, int] = {}
    unplaced: Dict[int, int] = {}
    warnings: List[str] = []
    applied: set = set()

    for rid, pids in pool.items():
        values: Dict[str, float] = {}
        pos_map: Dict[str, str] = {}
        probs: List[float] = []
        n_rookie = n_out = n_unplaced = n_unsigned = n_researched = 0
        reserve = state.get(rid, {}).get("reserve", frozenset())
        for pid in pids:
            name = players.name(pid)
            pos = players.position(pid)
            pos_map[pid] = pos
            if name in rates:
                values[pid] = rates[name]
            elif name in class_board.index:
                row = class_board.loc[name]
                values[pid] = price.price(row.ktc, int(row.overall), model.rookie_pricing)
                n_rookie += 1
            else:
                values[pid] = model.undrafted_ppg
                n_unplaced += 1
            p = avail.get(name, base.get(pos, base.get("_default", 0.82)))
            if use_flags and (pid in reserve or designations.get(pid, "") in OUT_DESIGNATIONS):
                p = min(p, availability.reserve_availability)
                n_out += 1
            if pid in unsigned and availability.unsigned_availability < 1.0:
                # no NFL team: he cannot score for anyone until he signs
                p = min(p, availability.unsigned_availability)
                n_unsigned += 1
            note = notes.get(name)
            if note is not None:
                if note.availability is not None:
                    p = note.availability
                values[pid] *= note.rate_multiplier
                n_researched += 1
                applied.add(name)
            probs.append(p)

        pid_list = list(values)
        healthy[rid] = float(L.compute_optimal_lineup(values, pos_map, year))
        p_arr = np.array(probs, dtype=float)
        draws = rng.random((availability.draws, len(pid_list))) < p_arr
        vals = np.empty(availability.draws, dtype=float)
        for i, row in enumerate(draws):
            sub = {pid: values[pid] for pid, up in zip(pid_list, row) if up}
            vals[i] = L.compute_optimal_lineup(sub, pos_map, year)
        mean[rid] = float(vals.mean())
        sd[rid] = float(vals.std(ddof=1))
        samples[rid] = vals
        rookies[rid] = n_rookie
        sidelined[rid] = n_out
        unsigned_count[rid] = n_unsigned
        researched[rid] = n_researched
        unplaced[rid] = n_unplaced
        if n_unplaced:
            warnings.append(
                f"{teams.get(rid, rid)}: {n_unplaced} rostered player(s) with no history in "
                f"this league and no {year} draft slot — projected at the undrafted prior "
                f"({model.undrafted_ppg:g} ppg)")
        if n_out:
            warnings.append(
                f"{teams.get(rid, rid)}: {n_out} player(s) carrying a reserve/IR-class "
                f"designation — capped at {availability.reserve_availability:.0%} availability")
        if n_unsigned:
            warnings.append(
                f"{teams.get(rid, rid)}: {n_unsigned} rostered player(s) with no NFL team — "
                f"capped at {availability.unsigned_availability:.0%} availability")
    all_rostered = set()
    for row in Q.week(year, week).values():
        all_rostered.update(players.name(pid) for pid in row.players)
    missing = sorted(n for n in set(notes) - applied if n not in all_rostered)
    benched = sorted(n for n in set(notes) - applied if n in all_rostered)
    if benched:
        warnings.append(
            f"{len(benched)} researched player(s) are rostered but not startable (taxi "
            f"squad), so the research did not apply: {', '.join(benched[:6])}")
    if missing:
        warnings.append(
            f"{len(missing)} researched player(s) are not on any {year} roster and were "
            f"ignored: {', '.join(missing[:6])}")
    if notes and not use_flags:
        warnings.append(
            f"{year} preseason: Sleeper's own injury flags are stale carry-over from the end "
            f"of the previous season and are NOT used; {sum(researched.values())} player(s) "
            f"adjusted from dated outside reporting instead ({research_path(year).name})")
    return FieldedDistribution(year=year, teams=teams, mean=mean, sd=sd, samples=samples,
                               healthy=healthy, rookies=rookies, sidelined=sidelined,
                               unsigned=unsigned_count, researched=researched,
                               unplaced=unplaced, warnings=sorted(set(warnings)))


def roster_projection(year: int, model: RateModel = RateModel(),
                      availability: AvailabilityModel = AvailabilityModel(),
                      **kw) -> FieldedDistribution:
    """The projection a forecast runs on: `fielded_distribution` under a plainer name."""
    return fielded_distribution(year, model, availability, **kw)


# ---------------------------------------------------------------------------
# Layer 5: calibration against seasons that actually happened
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Calibration:
    """What the projection is worth, measured on completed seasons.

    slope/intercept  realised centred weekly PF regressed on centred projection.
    sd_resid         residual spread of that regression (points per week).
    sd_week          spread of one team's week around its own level, with the
                     league-wide week effect removed — the noise that decides a
                     head-to-head.
    sd_league_week   the league-wide week effect: every team up or down
                     together. Cancels in a head-to-head; kept so simulated
                     scores look like real ones.
    sd_true          how wrong the projection is about a team's true level.
    corr/corr_oos    in-sample and leave-one-season-out correlation.
    """
    seasons: Tuple[int, ...]
    n: int
    slope: float
    intercept: float
    sd_resid: float
    sd_week: float
    sd_league_week: float
    sd_true: float
    corr: float
    corr_oos: float
    rmse_oos: float
    league_mean: float
    per_season_corr: Tuple[Tuple[int, float], ...] = ()
    table: Optional[pd.DataFrame] = None


def _regular_season_frame(year: int) -> pd.DataFrame:
    tw = Q.load_sheet("team_week")
    meta = Q.season_meta(year)
    d = tw[(Q.numeric(tw, "Year") == year) & (Q.numeric(tw, "Week") <= meta.regular_season_weeks)]
    return d.assign(PF=Q.numeric(d, "PF"), Week=Q.numeric(d, "Week"))


def _variance_split(seasons: Sequence[int]) -> Tuple[float, float]:
    """(sd of one team's week around its own level, sd of the league-wide week effect)."""
    league, idio = [], []
    for year in seasons:
        d = _regular_season_frame(year)
        if d.empty:
            continue
        week_mean = d.groupby("Week")["PF"].mean()
        team_mean = d.groupby("Team")["PF"].mean()
        league.append(float(week_mean.std(ddof=1)))
        resid = d["PF"] - d["Week"].map(week_mean) - d["Team"].map(team_mean) + d["PF"].mean()
        idio.append(float(resid.std(ddof=1)))
    if not idio:
        return 22.0, 10.0
    return float(np.mean(idio)), float(np.mean(league))


def _strength_sd(sd_resid: float, sd_week: float, weeks: float, n_teams: int) -> float:
    """Split a prediction residual into "wrong about the team" and "noisy season".

    A season's realised mean is itself only a `weeks`-week sample of the team, so
    part of any residual is noise the forecast could never have removed. Centring
    each season on its own league mean also removes the league-wide week effect,
    at the cost of a 1/n_teams factor — hence the (1 - 1/n).
    """
    sampling = sd_week ** 2 / max(weeks, 1.0) * (1.0 - 1.0 / max(n_teams, 2))
    return float(math.sqrt(max(sd_resid ** 2 - sampling, 0.0)))


def _backtest_availability(model: AvailabilityModel) -> AvailabilityModel:
    """The availability model a *past* season may legally be projected with.

    A past season's snapshot carries its final IR designations, not its week-1
    ones, so using them would be hindsight. There is no contemporaneous research
    file for a season that is already over either, so that is off too. Taxi
    membership is preseason and stable, so it stays; so does the unsigned check,
    which reads today's free agents and would be telling a 2022 projection who
    is out of the league in 2026.
    """
    return AvailabilityModel(lookback=model.lookback, shrink_weeks=model.shrink_weeks,
                             exclude_taxi=model.exclude_taxi,
                             reserve_availability=model.reserve_availability,
                             designations="never", research=False,
                             # 1.0 = disabled: see AvailabilityModel.unsigned_availability
                             unsigned_availability=1.0,
                             draws=max(model.draws // 4, 250))


def calibrate(seasons: Optional[Sequence[int]] = None,
              model: RateModel = RateModel(),
              availability: AvailabilityModel = AvailabilityModel()) -> Calibration:
    """Fit the projection against realised scoring on every completed season."""
    seasons = tuple(seasons if seasons is not None
                    else [y for y in Q.completed_seasons() if y - 1 in Q.export_seasons()])
    back = _backtest_availability(availability)
    rows = []
    for year in seasons:
        proj = fielded_distribution(year, model, back, exclude_from_fits=year)
        d = _regular_season_frame(year)
        actual = d.groupby("Team")["PF"].mean()
        for rid, value in proj.mean.items():
            team = proj.teams[rid]
            if team in actual.index:
                rows.append(dict(Year=year, Team=team, proj=value, actual=float(actual[team])))
    table = pd.DataFrame(rows)
    if table.empty:
        raise LookupError("no completed season has both a snapshot roster and prior-season rates")
    table["proj_c"] = table.proj - table.groupby("Year").proj.transform("mean")
    table["act_c"] = table.actual - table.groupby("Year").actual.transform("mean")

    slope, intercept = np.polyfit(table.proj_c, table.act_c, 1)
    resid = table.act_c - (slope * table.proj_c + intercept)
    sd_resid = float(resid.std(ddof=2))
    corr = float(np.corrcoef(table.proj_c, table.act_c)[0, 1])

    preds = np.empty(len(table))
    for year in seasons:
        tr = table[table.Year != year]
        te = (table.Year == year).to_numpy()
        b = np.polyfit(tr.proj_c, tr.act_c, 1)
        preds[te] = np.polyval(b, table.loc[te, "proj_c"])
    rmse_oos = float(np.sqrt(((table.act_c - preds) ** 2).mean()))
    corr_oos = float(np.corrcoef(preds, table.act_c)[0, 1])

    sd_week, sd_league_week = _variance_split(seasons)
    n_teams = int(table.groupby("Year").size().max())
    weeks = float(np.mean([Q.season_meta(y).regular_season_weeks for y in seasons]))
    sd_true = _strength_sd(sd_resid, sd_week, weeks, n_teams)

    per_season = tuple((int(year), float(np.corrcoef(g.proj_c, g.act_c)[0, 1]))
                       for year, g in table.groupby("Year") if len(g) > 2)
    return Calibration(
        seasons=seasons, n=len(table), slope=float(slope), intercept=float(intercept),
        sd_resid=sd_resid, sd_week=sd_week, sd_league_week=sd_league_week, sd_true=sd_true,
        corr=corr, corr_oos=corr_oos, rmse_oos=rmse_oos,
        league_mean=float(table.actual.mean()), per_season_corr=per_season, table=table)


# ---------------------------------------------------------------------------
# Layer 6: simulate the season
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TeamOdds:
    roster_id: int
    team: str
    projection: float
    healthy: float
    depth_cost: float
    availability_sd: float
    strength: float
    champion: float
    finals: float
    playoffs: float
    expected_wins: float
    expected_pf: float
    seed_pct: Tuple[float, ...]
    rookies: int = 0
    sidelined: int = 0
    unsigned: int = 0
    researched: int = 0


@dataclass
class Forecast:
    year: int
    model_name: str
    rate_model: RateModel
    availability_model: AvailabilityModel
    calibration: Calibration
    sims: int
    seed: int
    played_weeks: Tuple[int, ...]
    as_of_week: Optional[int]
    odds: List[TeamOdds]
    rookie_price: Optional[RookiePrice] = None
    age_curve: Optional[AgeCurve] = None
    rookie_class: Dict[str, float] = field(default_factory=dict)
    schedule: Optional[Schedule] = None
    warnings: List[str] = field(default_factory=list)

    def by_champion(self) -> List[TeamOdds]:
        return sorted(self.odds, key=lambda o: -o.champion)

    def champion_pct(self) -> Dict[str, float]:
        return {o.team: o.champion for o in self.by_champion()}


def _observed_scores(year: int) -> Dict[int, Dict[int, float]]:
    """Raw Sleeper points for weeks already played — no +5, `_bracket` adds it."""
    return {wk: {rid: row.points for rid, row in Q.week(year, wk).items()}
            for wk in Q.played_weeks(year)}


def _posterior(prior_mean: Dict[int, float], sd_true: float, sd_week: float,
               observed: Dict[int, Dict[int, float]], reg_weeks: int) -> Dict[int, float]:
    """Update each team's strength with the regular-season weeks already played."""
    played = [w for w in observed if w <= reg_weeks]
    if not played or sd_true <= 0:
        return dict(prior_mean)
    out = {}
    for rid, mean in prior_mean.items():
        devs = [observed[w][rid] - float(np.mean(list(observed[w].values()))) for w in played]
        n = len(devs)
        w = (n / sd_week ** 2) / (n / sd_week ** 2 + 1.0 / sd_true ** 2)
        centred = mean - float(np.mean(list(prior_mean.values())))
        out[rid] = (1 - w) * centred + w * float(np.mean(devs))
    shift = float(np.mean(list(prior_mean.values()))) - float(np.mean(list(out.values())))
    return {rid: v + shift for rid, v in out.items()}


@functools.lru_cache(maxsize=None)
def _history_slope() -> Tuple[float, float]:
    """Regress a team's centred weekly PF on its own previous season's."""
    rows = []
    for year in Q.completed_seasons():
        if year - 1 not in Q.export_seasons():
            continue
        now, before = _regular_season_frame(year), _regular_season_frame(year - 1)
        if now.empty or before.empty:
            continue
        a = now.groupby("Team")["PF"].mean()
        b = before.groupby("Team")["PF"].mean()
        for team in a.index:
            if team in b.index:
                rows.append((float(b[team] - b.mean()), float(a[team] - a.mean())))
    if len(rows) < 4:
        return 0.3, 12.0
    arr = np.array(rows)
    slope, intercept = np.polyfit(arr[:, 0], arr[:, 1], 1)
    resid = arr[:, 1] - (slope * arr[:, 0] + intercept)
    return float(slope), float(resid.std(ddof=2))


def forecast(year: int, sims: int = 20000, model: RateModel = RateModel(),
             availability: AvailabilityModel = AvailabilityModel(),
             calibration: Optional[Calibration] = None, seed: int = 20260807,
             strength_model: str = "roster", as_of_week: Optional[int] = None) -> Forecast:
    """Monte-Carlo the rest of `year` and return each team's championship odds.

    strength_model:
      roster   — the calibrated roster projection, with depth and availability;
      history  — each team's own previous-season scoring, regressed. What you
                 would say knowing only last year's table;
      uniform  — every team identical. The no-information floor, 1/n each, which
                 the other two have to beat to be worth anything.

    `as_of_week` rewinds the clock: only weeks up to and including it count as
    known, and everything after is simulated. 0 is a pure preseason forecast.
    This is what makes a *finished* season answerable as though it had not
    happened yet, which is the only honest way to ask whether these
    probabilities have ever been any good — see `backtest`.
    """
    meta = Q.season_meta(year)
    teams = Q.teams(year)
    rids = sorted(teams)
    calib = calibration or calibrate(model=model, availability=availability)
    warnings: List[str] = []

    proj = fielded_distribution(year, model, availability, seed=seed + 1)
    warnings.extend(proj.warnings)

    if strength_model == "roster":
        centre = float(np.mean([proj.mean[r] for r in rids]))
        prior = {r: calib.slope * (proj.mean[r] - centre) + calib.intercept for r in rids}
        sd_true = calib.sd_true
    elif strength_model == "history":
        prev = _regular_season_frame(year - 1)
        if prev.empty:
            raise LookupError(f"no {year - 1} regular season to build a history baseline from")
        means = prev.groupby("Team")["PF"].mean()
        centre = float(means.mean())
        hist_slope, hist_resid = _history_slope()
        prior = {r: hist_slope * (float(means.get(teams[r], centre)) - centre) for r in rids}
        sd_true = _strength_sd(hist_resid, calib.sd_week, meta.regular_season_weeks, len(rids))
    elif strength_model == "uniform":
        prior = {r: 0.0 for r in rids}
        sd_true = 0.0
    else:
        raise ValueError(f"unknown strength_model {strength_model!r}; "
                         "pick roster, history or uniform")

    cutoff = meta.last_week if as_of_week is None else int(as_of_week)
    observed = {w: s for w, s in _observed_scores(year).items() if w <= min(cutoff, meta.last_week)}
    strength = _posterior(prior, sd_true, calib.sd_week, observed, meta.regular_season_weeks)
    mean = {r: calib.league_mean + strength[r] for r in rids}
    sched = schedule(year, mean)
    if not sched.balanced:
        warnings.append(f"{year}: {sched.describe()}")

    pairs = {w: Q.pairings(year, w) for w in range(1, meta.regular_season_weeks + 1)}
    sim_weeks = [w for w in range(1, meta.last_week + 1) if w not in observed]
    if not sim_weeks:
        warnings.append(f"{year} is fully played — the forecast is a lookup, not a projection")
    if as_of_week is not None and Q.played_weeks(year) and cutoff < meta.last_week:
        warnings.append(
            f"{year} rewound to as-of week {cutoff}: weeks {cutoff + 1}+ are simulated even "
            "though they were actually played")

    rng = np.random.default_rng(seed)
    n_teams = len(rids)
    n_weeks = len(sim_weeks)

    # Availability is simulated per team-week from its own fielded distribution,
    # centred so it adds spread without moving the mean. The residual weekly
    # noise is then reduced by exactly that much, because the historical
    # `sd_week` already contains whatever injuries did to real scores — adding
    # availability on top without this would double-count it.
    if strength_model == "roster":
        avail_sd = np.array([proj.sd[r] for r in rids])
        centred = {r: proj.samples[r] - proj.samples[r].mean() for r in rids}
        avail_draw = np.stack(
            [centred[r][rng.integers(0, len(centred[r]), size=(sims, n_weeks))] for r in rids],
            axis=2) if n_weeks else np.zeros((sims, 0, n_teams))
    else:
        avail_sd = np.zeros(n_teams)
        avail_draw = np.zeros((sims, n_weeks, n_teams))
    resid_sd = np.sqrt(np.maximum(calib.sd_week ** 2 - avail_sd ** 2, 1.0))

    true_shift = (rng.normal(0.0, sd_true, size=(sims, n_teams)) if sd_true > 0
                  else np.zeros((sims, n_teams)))
    week_shock = rng.normal(0.0, calib.sd_league_week, size=(sims, n_weeks))
    idio = rng.normal(0.0, 1.0, size=(sims, n_weeks, n_teams)) * resid_sd
    base = np.array([mean[r] for r in rids])

    champ = {r: 0 for r in rids}
    runner = {r: 0 for r in rids}
    playoff = {r: 0 for r in rids}
    seed_counts = {r: np.zeros(n_teams, dtype=np.int64) for r in rids}
    wins = {r: 0.0 for r in rids}
    pf = {r: 0.0 for r in rids}
    by_name = {name: rid for rid, name in teams.items()}

    for i in range(sims):
        level = base + true_shift[i]
        scores: Dict[int, Dict[int, float]] = {w: dict(s) for w, s in observed.items()}
        for j, wk in enumerate(sim_weeks):
            row = level + avail_draw[i, j] + week_shock[i, j] + idio[i, j]
            scores[wk] = {rid: float(row[k]) for k, rid in enumerate(rids)}
        table = R._standings(scores, pairs, teams, meta)
        bracket = R._bracket(scores, table, teams, meta)
        for place, standing in enumerate(table):
            seed_counts[standing.roster_id][place] += 1
            wins[standing.roster_id] += standing.wins
            pf[standing.roster_id] += standing.points_for
            if place < meta.playoff_teams:
                playoff[standing.roster_id] += 1
        if bracket.champion:
            champ[by_name[bracket.champion]] += 1
            runner[by_name[bracket.runner_up]] += 1

    odds = [
        TeamOdds(
            roster_id=r, team=teams[r], projection=proj.mean[r], healthy=proj.healthy[r],
            depth_cost=proj.depth_cost(r), availability_sd=proj.sd[r], strength=mean[r],
            champion=100.0 * champ[r] / sims,
            finals=100.0 * (champ[r] + runner[r]) / sims,
            playoffs=100.0 * playoff[r] / sims,
            expected_wins=wins[r] / sims,
            expected_pf=pf[r] / sims / meta.regular_season_weeks,
            seed_pct=tuple(100.0 * seed_counts[r] / sims),
            rookies=proj.rookies.get(r, 0), sidelined=proj.sidelined.get(r, 0),
            unsigned=proj.unsigned.get(r, 0), researched=proj.researched.get(r, 0),
        )
        for r in rids
    ]
    return Forecast(year=year, model_name=strength_model, rate_model=model,
                    availability_model=availability, calibration=calib, sims=sims, seed=seed,
                    played_weeks=tuple(sorted(observed)), as_of_week=as_of_week, odds=odds,
                    rookie_price=rookie_price(None, model),
                    age_curve=age_curve(None, model) if model.age_adjust else None,
                    rookie_class=rookie_class_strength(year), schedule=sched,
                    warnings=sorted(set(warnings)))


# ---------------------------------------------------------------------------
# Did any of this ever work? Backtesting the probabilities, not the projection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BacktestRow:
    """One (season, as-of week) forecast, scored against what actually happened."""
    season: int
    as_of_week: int
    model: str
    champion: str
    champion_p: float                  # probability the forecast gave the real champion
    champion_rank: int                 # 1 = the forecast's favourite actually won
    champion_logloss: float
    champion_brier: float              # over all n teams, one-hot on the real champion
    self_logloss: float                # the log-loss the forecast expects of ITSELF
    self_playoff_brier: float          # ditto for playoff berths
    playoff_brier: float
    playoff_hits: int                  # of the real playoff field, how many were forecast top-4
    wins_mae: float
    wins_corr: float
    seed_rho: float
    rows: Tuple[Tuple[str, float, float, float, int], ...] = ()
    # (team, p_champion, p_playoff, expected_wins, actual_wins)


@dataclass
class Backtest:
    """Every scored forecast, plus the summary that says whether it beat guessing."""
    rows: List[BacktestRow]
    n_teams: int

    def by_model(self, model: str) -> List[BacktestRow]:
        return [r for r in self.rows if r.model == model]

    def summary(self, model: str = "roster") -> Dict[str, float]:
        rows = self.by_model(model)
        if not rows:
            return {}
        uniform_ll = math.log(self.n_teams)
        return {
            "n": float(len(rows)),
            "champion_logloss": float(np.mean([r.champion_logloss for r in rows])),
            "champion_logloss_uniform": uniform_ll,
            "champion_brier": float(np.mean([r.champion_brier for r in rows])),
            "champion_brier_uniform": float((1 - 1 / self.n_teams) ** 2
                                            + (self.n_teams - 1) * (1 / self.n_teams) ** 2),
            "champion_p": float(np.mean([r.champion_p for r in rows])),
            "champion_rank": float(np.mean([r.champion_rank for r in rows])),
            "favourite_won": float(np.mean([r.champion_rank == 1 for r in rows])),
            # realised / self-expected: >1 means the forecast was more confident
            # than it turned out to deserve, <1 means it hedged more than it
            # needed to. This is the only direct test of *confidence* as opposed
            # to ranking, and it needs no baseline to compare against.
            "confidence_ratio_champion": float(np.mean([r.champion_logloss for r in rows])
                                               / max(np.mean([r.self_logloss for r in rows]), 1e-9)),
            "confidence_ratio_playoff": float(np.mean([r.playoff_brier for r in rows])
                                              / max(np.mean([r.self_playoff_brier for r in rows]), 1e-9)),
            "playoff_brier": float(np.mean([r.playoff_brier for r in rows])),
            "playoff_brier_uniform": 0.25,
            "playoff_hits": float(np.mean([r.playoff_hits for r in rows])),
            "wins_mae": float(np.mean([r.wins_mae for r in rows])),
            "wins_corr": float(np.mean([r.wins_corr for r in rows])),
            "seed_rho": float(np.mean([r.seed_rho for r in rows])),
        }

    def calibration(self, model: str = "roster", as_of_week: Optional[int] = None,
                    bins: Sequence[float] = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)
                    ) -> pd.DataFrame:
        """Predicted playoff probability against the rate teams actually made it.

        The single most important table here, because it tests *confidence* and
        not just ranking: a forecast that says 75% should be right about three
        times in four. Championship probabilities are too rare to bin over five
        seasons; playoff berths give eight observations a season.

        A model that is over-confident shows up as observed rates pulled toward
        the middle — bins near 0 coming in above their prediction and bins near
        1 below.
        """
        rows = [r for r in self.by_model(model)
                if as_of_week is None or r.as_of_week == as_of_week]
        pairs = [(p_playoff, made) for r in rows for (_, _, p_playoff, _, made) in r.rows]
        if not pairs:
            return pd.DataFrame(columns=["bucket", "n", "predicted", "observed"])
        frame = pd.DataFrame(pairs, columns=["p", "made"])
        frame["bucket"] = pd.cut(frame.p, list(bins), include_lowest=True)
        out = frame.groupby("bucket", observed=True).agg(
            n=("made", "size"), predicted=("p", "mean"), observed=("made", "mean"))
        return out.reset_index()


def _actual_outcome(season: int) -> Tuple[str, List[str], Dict[str, int], Dict[str, int]]:
    """(champion, playoff field, wins by team, seed by team) as the build recorded them."""
    meta = Q.season_meta(season)
    teams = Q.teams(season)
    scores = _observed_scores(season)
    pairs = {w: Q.pairings(season, w) for w in range(1, meta.regular_season_weeks + 1)}
    table = R._standings(scores, pairs, teams, meta)
    bracket = R._bracket(scores, table, teams, meta)
    wins = {s.team: s.wins for s in table}
    seeds = {s.team: i + 1 for i, s in enumerate(table)}
    field = [s.team for s in table[:meta.playoff_teams]]
    return bracket.champion, field, wins, seeds


def backtest(seasons: Optional[Sequence[int]] = None, as_of_weeks: Sequence[int] = (0,),
             sims: int = 4000, model: RateModel = RateModel(),
             availability: AvailabilityModel = AvailabilityModel(),
             models: Sequence[str] = ("roster", "history", "uniform"),
             seed: int = 20260807) -> Backtest:
    """Rewind each completed season and score the forecast against what happened.

    This is the only test of the *probabilities*. `calibrate` measures how well
    the projection predicts a team's mean weekly points; it says nothing about
    whether a 30% favourite wins three times in ten. Everything here is
    strictly out of sample:

      * the calibration is refitted **leaving the season out**;
      * the rookie price and age curve are refitted leaving it out;
      * availability runs in backtest mode — no designations, no research file,
        no free-agent check, because all three are facts about today.

    `as_of_weeks` is where the clock is rewound to. 0 is a preseason forecast;
    higher numbers ask the fairer question of whether the model *updates* well
    once results start arriving.
    """
    seasons = tuple(seasons if seasons is not None
                    else [y for y in Q.completed_seasons() if y - 1 in Q.export_seasons()])
    back_avail = _backtest_availability(availability)
    rows: List[BacktestRow] = []
    n_teams = 0
    for season in seasons:
        champion, field, wins, seeds = _actual_outcome(season)
        if not champion:
            continue
        others = [y for y in seasons if y != season]
        calib = calibrate(others or seasons, model=model, availability=availability)
        teams = list(Q.teams(season).values())
        n_teams = len(teams)
        for week in as_of_weeks:
            for name in models:
                fc = forecast(season, sims=sims, model=model, availability=back_avail,
                              calibration=calib, seed=seed, strength_model=name,
                              as_of_week=week)
                by_team = {o.team: o for o in fc.odds}
                p_champ = {t: by_team[t].champion / 100.0 for t in by_team}
                p_play = {t: by_team[t].playoffs / 100.0 for t in by_team}
                p_true = max(p_champ.get(champion, 0.0), 1e-6)
                order = sorted(p_champ, key=lambda t: -p_champ[t])
                brier_c = sum((p_champ[t] - (1.0 if t == champion else 0.0)) ** 2 for t in p_champ)
                brier_p = float(np.mean([(p_play[t] - (1.0 if t in field else 0.0)) ** 2
                                         for t in p_play]))
                forecast_field = {t for t in sorted(p_play, key=lambda t: -p_play[t])[:len(field)]}
                ew = np.array([by_team[t].expected_wins for t in teams])
                aw = np.array([float(wins.get(t, 0)) for t in teams])
                rank = lambda a: np.argsort(np.argsort(a))  # noqa: E731
                fs = np.array([-p_play[t] for t in teams])
                asd = np.array([float(seeds.get(t, 0)) for t in teams])
                total = sum(p_champ.values()) or 1.0
                self_ll = -sum((v / total) * math.log(max(v / total, 1e-12))
                               for v in p_champ.values())
                self_pb = float(np.mean([v * (1 - v) for v in p_play.values()]))
                rows.append(BacktestRow(
                    season=season, as_of_week=week, model=name, champion=champion,
                    champion_p=p_true, champion_rank=order.index(champion) + 1,
                    champion_logloss=-math.log(p_true), champion_brier=brier_c,
                    self_logloss=self_ll, self_playoff_brier=self_pb,
                    playoff_brier=brier_p, playoff_hits=len(forecast_field & set(field)),
                    wins_mae=float(np.mean(np.abs(ew - aw))),
                    wins_corr=float(np.corrcoef(ew, aw)[0, 1]) if aw.std() else float("nan"),
                    seed_rho=float(np.corrcoef(rank(fs), rank(asd))[0, 1]),
                    rows=tuple((t, p_champ[t], p_play[t], by_team[t].expected_wins,
                                1 if t in field else 0) for t in teams)))
    return Backtest(rows=rows, n_teams=n_teams or 8)


def render_backtest(bt: Backtest) -> str:
    lines = ["Backtest — every completed season rewound and scored against what happened",
             "  strictly out of sample: calibration, rookie price and age curve all refitted",
             "  leaving the season out; no designations, no research, no free-agent check",
             ""]
    weeks = sorted({r.as_of_week for r in bt.rows})
    lines.append(f"{'model':<10}{'as of':>7}{'champ logloss':>15}{'champ Brier':>13}"
                 f"{'P(real champ)':>15}{'fav won':>9}{'playoff Brier':>15}"
                 f"{'E[W] MAE':>10}{'seed rho':>10}{'conf ratio':>12}")
    for name in ("roster", "history", "uniform"):
        for week in weeks:
            sub = Backtest([r for r in bt.rows if r.model == name and r.as_of_week == week],
                           bt.n_teams)
            s = sub.summary(name)
            if not s:
                continue
            lines.append(f"{name:<10}{week:>7}{s['champion_logloss']:>15.3f}"
                         f"{s['champion_brier']:>13.3f}{s['champion_p']:>15.1%}"
                         f"{s['favourite_won']:>9.0%}{s['playoff_brier']:>15.3f}"
                         f"{s['wins_mae']:>10.2f}{s['seed_rho']:>10.2f}"
                         f"{s['confidence_ratio_champion']:>12.2f}")
    base = bt.summary("roster")
    if base:
        lines += ["",
                  f"  guessing at random scores {base['champion_logloss_uniform']:.3f} log-loss, "
                  f"{base['champion_brier_uniform']:.3f} champion Brier, 0.250 playoff Brier.",
                  "  Lower is better on all three. 'conf ratio' is realised log-loss over the",
                  "  log-loss the forecast expects of itself: >1 over-confident, <1 hedged."]
    lines += ["", "season by season (roster model, preseason):",
              f"{'season':<9}{'real champion':<18}{'forecast':>9}{'rank':>6}{'playoff hits':>14}"]
    for r in sorted(bt.by_model("roster"), key=lambda r: (r.as_of_week, r.season)):
        if r.as_of_week != min(weeks):
            continue
        lines.append(f"{r.season:<9}{r.champion:<18}{r.champion_p:>8.1%}{r.champion_rank:>6}"
                     f"{r.playoff_hits:>10}/4")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Schedule:
    """Who plays whom, and whether that is worth anything.

    balanced   every pair meets the same number of times, so no team has an
               easier draw than another *by construction*.
    sos        {roster_id: how much stronger its actual opponents are than the
               average opponent it *could* have drawn — the other seven teams,
               excluding itself}. Positive is a harder schedule. In a balanced
               double round-robin this is exactly zero for everyone, which is
               the precise sense in which such a season has no SoS edge.
    """
    year: int
    balanced: bool
    meetings: Tuple[int, ...]
    sos: Dict[int, float] = field(default_factory=dict)

    def describe(self) -> str:
        if self.balanced:
            return (f"balanced double round-robin (every pair meets "
                    f"{self.meetings[0]}x) — no strength-of-schedule edge exists")
        spread = "/".join(str(m) for m in self.meetings)
        hardest = max(self.sos, key=self.sos.get) if self.sos else None
        tail = ""
        if hardest is not None:
            tail = (f"; hardest draw {self.sos[hardest]:+.1f} pts/wk of opponent, "
                    f"easiest {min(self.sos.values()):+.1f}")
            return f"unbalanced (pairs meet {spread}x){tail}"
        return f"unbalanced (pairs meet {spread}x)"


def schedule(year: int, strength: Optional[Dict[int, float]] = None) -> Schedule:
    """The season's real pairings, and the strength of schedule they imply.

    The simulation always runs over the *actual* pairings, so an unbalanced
    schedule is handled whether or not anyone notices it. This exists to say how
    much it is worth: in a balanced season the answer is provably nothing, and
    in an unbalanced one `sos` puts a number on each team's draw.
    """
    meta = Q.season_meta(year)
    counts: Dict[Tuple[int, int], int] = {}
    opponents: Dict[int, List[int]] = {rid: [] for rid in Q.teams(year)}
    for wk in range(1, meta.regular_season_weeks + 1):
        for a, b in Q.pairings(year, wk):
            counts[(a, b)] = counts.get((a, b), 0) + 1
            opponents.setdefault(a, []).append(b)
            opponents.setdefault(b, []).append(a)
    meetings = tuple(sorted(set(counts.values())))
    teams = Q.teams(year)
    expected_pairs = len(teams) * (len(teams) - 1) // 2
    balanced = len(meetings) == 1 and len(counts) == expected_pairs

    sos: Dict[int, float] = {}
    if strength:
        league = float(np.mean(list(strength.values())))
        total = float(sum(strength.values()))
        for rid, opps in opponents.items():
            if not opps:
                continue
            # the average opponent this team could have drawn is the mean of the
            # *other* teams — a strong team can never draw itself, and comparing
            # against the whole-league mean would read that as an easy schedule.
            others = ((total - strength.get(rid, league)) / (len(strength) - 1)
                      if len(strength) > 1 else league)
            sos[rid] = float(np.mean([strength.get(o, league) for o in opps])) - others
    return Schedule(year=year, balanced=balanced, meetings=meetings, sos=sos)


def check_schedule_is_balanced(year: int) -> List[str]:
    """Report whether the regular season is a balanced round-robin.

    Not a pass/fail: 2026's fourteen weeks are a clean double round-robin, but
    2021-2025 ran fifteen, so some pairs met three times and some twice. Either
    is legal and both are simulated over the real pairings — this is here so an
    answer can say which one it is rather than assuming the tidy case.
    """
    meta = Q.season_meta(year)
    if not meta.has_snapshot:
        return [f"{year}: no snapshot"]
    sched = schedule(year)
    if sched.balanced:
        return []
    return [f"{year}: pairs meet {'/'.join(str(m) for m in sched.meetings)} times — the "
            "schedule is unbalanced, so strength of schedule is real. It is simulated "
            "over the actual pairings; `schedule(year, strength).sos` prices it."]


def check_research_file(year: int) -> List[str]:
    """Every researched row must name a real rostered player and cite a source.

    The research file is the one hand-written input to this module, so it gets
    the strictest check: a typo'd name, a missing URL, an undated claim or an
    availability outside [0, 1] is a defect, not a judgement call.
    """
    notes = research_overrides(year)
    if not notes:
        return []
    problems: List[str] = []
    players = Q.players()
    for name, note in sorted(notes.items()):
        # What this catches is a TYPO — a name that is nobody. It used to
        # demand the player also be on a roster, which is a different and
        # wrong test: an unsigned free agent is exactly the kind of player
        # worth a research note, and a rostered one can be cut mid-season
        # without the note becoming a mistake. (Nick Chubb, researched as
        # "unsigned free agent at 30", failed the roster form the week he
        # went unrostered.) A note about a player nobody rosters simply
        # moves nobody's projection.
        try:
            players.resolve(name)
        except KeyError:
            problems.append(f"{year} research: {name!r} matches no NFL player — typo?")
        except Exception as exc:  # AmbiguousPlayer — a partial name, so which one?
            problems.append(f"{year} research: {name!r} is ambiguous — {exc}")
        if not note.source.startswith("http"):
            problems.append(f"{year} research: {name} has no source URL")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", note.as_of):
            problems.append(f"{year} research: {name} has no valid as_of date")
        if not note.note:
            problems.append(f"{year} research: {name} has no note saying why")
        if note.availability is not None and not 0.0 <= note.availability <= 1.0:
            problems.append(f"{year} research: {name} availability {note.availability} "
                            "is not a probability")
        if not 0.0 < note.rate_multiplier <= 2.0:
            problems.append(f"{year} research: {name} rate_multiplier "
                            f"{note.rate_multiplier} is implausible")
    return problems


def check_beats_uniform(sims: int = 3000, seed: int = 20260807) -> List[str]:
    """The forecast's *probabilities* must beat guessing on seasons that happened.

    Every other guard here checks machinery. This one checks the answer: rewind
    each completed season to its preseason, forecast it out of sample, and score
    the result against what the build says actually happened. If a roster
    projection cannot beat 1/n on five seasons of champions and forty of playoff
    berths, its odds are decoration.

    Deliberately loose thresholds — five champions cannot resolve much, and the
    point is to catch a regression that breaks the model, not to police a decimal.
    """
    bt = backtest(as_of_weeks=(0,), sims=sims, models=("roster", "uniform"), seed=seed)
    roster, uniform = bt.summary("roster"), bt.summary("uniform")
    if not roster:
        return ["backtest produced no scored seasons"]
    problems = []
    if roster["champion_logloss"] >= uniform["champion_logloss"]:
        problems.append(
            f"champion log-loss {roster['champion_logloss']:.3f} does not beat guessing "
            f"({uniform['champion_logloss']:.3f})")
    if roster["playoff_brier"] >= uniform["playoff_brier"]:
        problems.append(
            f"playoff Brier {roster['playoff_brier']:.3f} does not beat guessing "
            f"({uniform['playoff_brier']:.3f})")
    if roster["wins_mae"] >= uniform["wins_mae"]:
        problems.append(f"expected-wins MAE {roster['wins_mae']:.2f} does not beat guessing "
                        f"({uniform['wins_mae']:.2f})")
    if roster["seed_rho"] < 0.3:
        problems.append(f"seed rank correlation {roster['seed_rho']:.2f} is too weak to quote")
    return problems


def check_bracket_pipeline(season: int) -> List[str]:
    """The scores -> standings -> champion path must reproduce the built season."""
    problems: List[str] = []
    meta = Q.season_meta(season)
    if not meta.has_snapshot:
        return [f"{season}: no snapshot"]
    teams = Q.teams(season)
    scores = _observed_scores(season)
    pairs = {w: Q.pairings(season, w) for w in range(1, meta.regular_season_weeks + 1)}
    table = R._standings(scores, pairs, teams, meta)
    bracket = R._bracket(scores, table, teams, meta)

    ty = Q.load_sheet("team_year")
    built = ty[Q.numeric(ty, "Year") == season]
    winner = built.loc[built["Result"].astype(str).str.lower() == "champion", "Team"]
    if len(winner) != 1:
        problems.append(f"{season}: expected exactly one champion in team_year, found {len(winner)}")
    elif bracket.champion != str(winner.iloc[0]):
        problems.append(f"{season}: bracket says {bracket.champion!r}, "
                        f"team_year says {str(winner.iloc[0])!r}")

    eliminated = "Week of playoff elimination"
    if eliminated in built.columns:
        made = set(built.loc[Q.numeric(built, eliminated) >= meta.playoff_week_start, "Team"])
        ours = {s.team for s in table[:meta.playoff_teams]}
        if made and made != ours:
            problems.append(f"{season}: playoff field {sorted(ours)} != built {sorted(made)}")
    return problems


def check_completed_season_certainty(season: int, sims: int = 200) -> List[str]:
    """Forecasting a finished season must return 100% for the real champion."""
    meta = Q.season_meta(season)
    if not meta.is_complete:
        return [f"{season} is not complete"]
    fc = forecast(season, sims=sims)
    ty = Q.load_sheet("team_year")
    built = ty[Q.numeric(ty, "Year") == season]
    winner = built.loc[built["Result"].astype(str).str.lower() == "champion", "Team"]
    if len(winner) != 1:
        return [f"{season}: expected exactly one champion in team_year, found {len(winner)}"]
    got = fc.by_champion()[0]
    if got.team != str(winner.iloc[0]) or got.champion < 100.0:
        return [f"{season}: forecast says {got.team} {got.champion:.1f}%, "
                f"build says {str(winner.iloc[0])} won"]
    return []


def validate(season: Optional[int] = None) -> List[str]:
    """Run every guard, over one season or all completed ones."""
    seasons = [season] if season else Q.completed_seasons()
    problems: List[str] = []
    for year in seasons:
        # schedule balance is reported, not asserted: an unbalanced season is
        # legal and is simulated over its real pairings either way.
        problems.extend(check_bracket_pipeline(year))
        problems.extend(check_research_file(year))
        problems.extend(check_completed_season_certainty(year))
    return problems


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render(fc: Forecast, seeds: bool = False, detail: bool = False) -> str:
    c = fc.calibration
    played = (f"weeks {min(fc.played_weeks)}-{max(fc.played_weeks)} played"
              if fc.played_weeks else "preseason, no weeks played")
    lines = [
        f"{fc.year} championship odds — {fc.model_name} model, {fc.sims:,} sims ({played})",
        f"  rates:        {fc.rate_model.label()}",
        f"  availability: {fc.availability_model.label()}",
        f"  calibration on {', '.join(str(y) for y in c.seasons)}: n={c.n} "
        f"slope={c.slope:.2f} r={c.corr:.2f} (out-of-sample r={c.corr_oos:.2f}, "
        f"RMSE={c.rmse_oos:.1f})",
        f"  spread: team strength sd={c.sd_true:.1f}, week-to-week sd={c.sd_week:.1f}, "
        f"league-wide week sd={c.sd_league_week:.1f} points",
        f"  schedule: {fc.schedule.describe() if fc.schedule else 'unknown'}",
        "",
        f"{'team':<18}{'champ%':>8}{'finals%':>9}{'playoff%':>10}{'E[wins]':>9}"
        f"{'E[PF/wk]':>10}{'proj':>8}",
    ]
    for o in fc.by_champion():
        lines.append(f"{o.team:<18}{o.champion:>8.1f}{o.finals:>9.1f}{o.playoffs:>10.1f}"
                     f"{o.expected_wins:>9.2f}{o.expected_pf:>10.1f}{o.projection:>8.1f}")
    if detail:
        lines += ["", "projection detail — what injuries and depth cost each roster", "",
                  f"{'team':<18}{'healthy':>9}{'fielded':>9}{'depth cost':>12}"
                  f"{'wk sd':>8}{'rookies':>9}{'unsigned':>10}{'researched':>12}"]
        for o in fc.by_champion():
            lines.append(f"{o.team:<18}{o.healthy:>9.1f}{o.projection:>9.1f}"
                         f"{o.depth_cost:>12.1f}{o.availability_sd:>8.1f}"
                         f"{o.rookies:>9}{o.unsigned:>10}{o.researched:>12}")
        if fc.age_curve and fc.age_curve.slope:
            curve = "  ".join(f"{p} {fc.age_curve.slope[p]:+.2f}"
                              for p in _POSITIONS if p in fc.age_curve.slope)
            lines += ["", f"age curve (points per week per year of age): {curve}"]
        if fc.rookie_price and fc.rookie_price.ktc_n:
            rp = fc.rookie_price
            lines.append(f"rookie pricing: ppg = {rp.ktc_slope:.5f} x draft-day KTC "
                         f"{rp.ktc_intercept:+.2f}  (r={rp.ktc_r:.2f}, n={rp.ktc_n})")
        rc = fc.rookie_class
        if rc:
            lines.append(
                f"{int(rc['year'])} rookie class: mean draft-day KTC {rc['mean_ktc']:.0f} vs "
                f"{rc['past_mean_ktc']:.0f} for earlier classes over the same picks "
                f"({rc['ratio']:.0%}), ranked {int(rc['rank_of_classes'])} of "
                f"{int(rc['classes'])}")
    if seeds:
        lines += ["", f"{'team':<18}" + "".join(f"{'#' + str(i + 1):>7}"
                                                for i in range(len(fc.odds)))]
        for o in fc.by_champion():
            lines.append(f"{o.team:<18}" + "".join(f"{p:>7.1f}" for p in o.seed_pct))
    if fc.warnings:
        lines += ["", "warnings:"] + [f"  - {w}" for w in fc.warnings]
    return "\n".join(lines)
