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

- **future trades, waivers and drops** — the roster is frozen as it stands
  (it is the current one: `roster_week`);
- **NFL-side matchup quality** — which defence a player draws in a given week.
  The committed data has no NFL schedule or team-defence table, so weekly
  opponent adjustments are out of reach here, not merely unimplemented;
- **NFL depth-chart news** the exports do not contain (holdouts, camp battles,
  a rookie's landing spot) beyond what KTC's market price already reflects;
- **correlated byes** — a roster stacked on one NFL team loses them together.
  Byes are not simulated at all, and players are injured independently of
  their teammates;
- **injury news the data cannot see** — a designated-to-return or "expected
  back this week" report, or the diagnosis behind an absence. An injured player
  returns on the league-wide curve for how long he has been out (a player on
  injured reserve: not before the NFL minimum, then on the IR curve — see
  `AvailabilityModel.ir_minimum`); the research file is the place to override
  it with a dated, sourced availability or `out_through_week`. Body part,
  a first-game-back dip (2021-25: 84-91% of the rate) and teammates' role
  changes are not modelled.

**In season** (since 2026-10-15): once weeks are played, each player's rate
is updated with this season's games (`RateModel.in_season_weight`), and
injuries are simulated as multi-week spells along one consecutive path per
simulated season (`AvailabilityModel.injury_spells`, `injury_model`) —
starting from who is out right now, per the league's own `player_week`.
Rewound to weeks 4/8/11 over 2021-2025 (each season out of its own fits),
champion log-loss moved 1.60/1.30/1.28 -> 1.57/1.22/1.23 and champion Brier
0.740/0.700/0.686 -> 0.739/0.655/0.665, while the expected-wins error rose
1.41/1.09/0.83 -> 1.45/1.18/0.86 and playoff Brier stayed within 0.003. Five
seasons is a small sample; read it as "helps the title odds a little, costs
the win totals a little", not as proof.

**Injured reserve** (since 2026-11-15, `AvailabilityModel.ir_minimum`): a
player on IR at the cutoff cannot return before the NFL minimum and then comes
back on an IR-specific curve (`ir_status`). Rewound 2021-2025 to weeks 2/4/8/11,
the IR players' predicted availability over their remaining weeks moved from
0.478 to 0.328 against 0.332 actual, and their Brier from 0.230 to 0.192 (every
season and cutoff improved; n=2,045 player-weeks). At team level it is noise:
champion log-loss at weeks 4/8/11 1.603/1.204/1.244 -> 1.600/1.205/1.243,
playoff Brier within 0.0006, wins MAE within 0.005. It matters for a player's
own outlook (trade.py, the site's predictions), not for the title odds.
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import espn_injuries as ESPN
from . import inquiry as Q
from . import ir_status as IR
from . import lineup as L
from . import replay as R

__all__ = [
    "RateModel", "AvailabilityModel", "Calibration", "TeamOdds", "Forecast",
    "Schedule", "schedule", "age_curve", "rookie_price", "rookie_class_strength", "player_rates",
    "availability_rates", "startable_pool", "player_prior_games", "in_season_evidence",
    "blend_in_season", "InjuryModel", "injury_model", "weeks_missed", "roster_week", "fielded_distribution",
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
    in_season_weight
                   once weeks are played, each of this season's available games
                   counts this many times against the preseason rate's own
                   evidence (its weighted prior games plus `shrink_games`).
                   3.0 is measured: rewinding 2022-2025 to weeks 2/4/6/8/10 and
                   predicting each player's remaining weeks-1-14 points per
                   available game, RMSE falls from 4.01/4.25/4.53/4.82/5.30
                   (0, the preseason rate alone) to 3.76/3.90/4.09/4.31/4.82,
                   and 3 is the minimum at every cutoff (2 and 4 within 0.02).
                   0 switches it off.
    drop_injury_games
                   leave out the game a player got hurt in (he played, then
                   missed his next week). Those games average 73% of the
                   player's season rate (649 of them, 2021-2025), which makes
                   dropping them look obviously right — but measured as above
                   it is slightly WORSE at every cutoff (RMSE +0.01 to +0.05):
                   the rate is points per game played, and future games get
                   cut short at the same natural frequency. Off by default;
                   kept for sensitivity checks.
    """
    weights: Tuple[float, ...] = (0.65, 0.35)
    halflife: Optional[float] = 8.0
    shrink_games: float = 6.0
    prior_games: int = 1
    age_adjust: bool = True
    age_shrink: float = 100.0
    rookie_pricing: str = "ktc"
    undrafted_ppg: float = 3.0
    in_season_weight: float = 3.0
    drop_injury_games: bool = False

    def label(self) -> str:
        w = "/".join(f"{x:g}" for x in self.weights)
        return (f"weights={w} halflife={self.halflife or 'flat'} "
                f"shrink={self.shrink_games:g} prior_games={self.prior_games} "
                f"age={'on' if self.age_adjust else 'off'} rookies={self.rookie_pricing} "
                f"in_season={self.in_season_weight:g}")


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
    injury_spells  once weeks are played, simulate injuries as multi-week
                   spells instead of independent weekly coin flips
                   (`injury_model`): a player who is out now starts the
                   forecast out and comes back on the league's own return
                   curve for however long he has already missed, and a healthy
                   player can get hurt and stay out for several weeks. Each
                   simulated season is one path, so a team that loses a star in
                   week 9 is without him in the playoffs too. Replaces
                   `reserve_availability` for flagged players while it is on;
                   the preseason keeps the independent draws.
    ir_minimum     with the spells on, a player on injured reserve cannot come
                   back before the NFL's minimum (3 games in 2021, 4 from 2022),
                   and once eligible he returns on an IR-specific curve
                   (`ir_status.ir_return_model`: 21% at the first eligible
                   game, then falling to ~4% a week — many IR stints end the
                   season) instead of the general one, which would have him
                   back 36% of the time after a single missed week. Who is on
                   IR and since when: the injury tracker from 2026, nflverse's
                   weekly rosters before that (`ir_status.on_ir`), so it is
                   rewind-safe and stays on in the backtest. 2026's tracker:
                   0 of 35 in-season placements back before missing 4 games.
    questionable_availability, doubtful_availability
                   P(he plays) in the first simulated week for a player Sleeper
                   lists Questionable / Doubtful, applied only to a live
                   forecast (the designation is today's). Measured: 2026's
                   tracker, Questionable played 84.5% (n=226); Doubtful 0 of 3,
                   and 0 of 120 rostered Doubtful player-weeks 2021-25 in
                   nflverse's injury reports. A one-week miss, not a spell.
    espn_timelines with the spells on and a LIVE forecast, ESPN's injury list
                   (data/espn_injuries.csv, captured daily by a workflow, no
                   Claude) sets how long a listed IR / Out / PUP / suspended
                   player stays out: "season-ending" (ESPN's after-season date
                   AND the reporting or an ACL/Achilles/patellar tear says so)
                   holds him out of every remaining week; an in-season
                   estimated return week holds him out of the weeks before it,
                   and from that week he returns on the curve's first-week
                   hazard. A research-file row for the player wins. Skipped
                   when the capture is older than `espn_max_age_days`. Not
                   validated against past seasons (ESPN keeps no history):
                   see espn_injuries.calibration for the check after 2026.
    """
    lookback: int = 2
    shrink_weeks: float = 10.0
    exclude_taxi: bool = True
    reserve_availability: float = 0.51
    designations: str = "auto"
    research: bool = True
    unsigned_availability: float = 0.35
    draws: int = 3000
    injury_spells: bool = True
    ir_minimum: bool = True
    questionable_availability: float = 0.85
    doubtful_availability: float = 0.0
    espn_timelines: bool = True
    espn_max_age_days: float = 10.0

    def uses_designations(self, year: int) -> bool:
        if self.designations == "always":
            return True
        if self.designations == "never":
            return False
        if self.designations != "auto":
            raise ValueError(f"designations must be auto/always/never, got {self.designations!r}")
        # in-season Sleeper keeps these current; in the preseason they are a
        # record of how last season ended, so they are ignored. In season from
        # week 1's first kickoff, not from its Tuesday finalization.
        return bool(Q.played_weeks(year, include_in_progress=True))

    def label(self) -> str:
        return (f"shrink={self.shrink_weeks:g}w taxi={'out' if self.exclude_taxi else 'in'} "
                f"reserve={self.reserve_availability:.2f} designations={self.designations} "
                f"research={'on' if self.research else 'off'} "
                f"unsigned={self.unsigned_availability:.2f} "
                f"spells={'on' if self.injury_spells else 'off'} "
                f"ir_min={'on' if self.ir_minimum else 'off'} "
                f"Q={self.questionable_availability:.2f} D={self.doubtful_availability:.2f} "
                f"espn={'on' if self.espn_timelines else 'off'}")


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
    df = df.sort_values(["Player", "Year", "Week"])
    # The game a player got hurt in: he played, and his next non-bye week he
    # was out. `NextWeek` says when that became knowable, so a cutoff before it
    # cannot use it.
    played = df[~df["Bye?"]]
    nxt = played.groupby(["Player", "Year"], sort=False)
    df["NextHurt"] = nxt["Hurt"].shift(-1).reindex(df.index).fillna(False).astype(bool)
    df["NextWeek"] = nxt["Week"].shift(-1).reindex(df.index)
    df["InjuryGame"] = df["Available"] & df["NextHurt"]
    return df


@functools.lru_cache(maxsize=None)
def _season_rates(year: int, halflife: Optional[float], root: str,
                  drop_injury_games: bool = False) -> pd.DataFrame:
    """games, recency-weighted mean points and age, per player, for one season.

    Weeks the player was unavailable are excluded: a rate is what he scores when
    he plays. How often he plays is a separate question, handled by
    `availability_rates`, because mixing the two hides which one is driving an
    answer.
    """
    df = _player_week()
    d = df[(df["Year"] == year) & df["Available"]].dropna(subset=["Points"])
    if drop_injury_games:
        d = d[~d["InjuryGame"]]
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
    rates = [(_season_rates(y, hl, root, model.drop_injury_games), w) for y, w in seasons]

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


def player_prior_games(year: int, model: RateModel = RateModel()) -> Dict[str, float]:
    """{player name: season-weighted prior games behind his `player_rates` value}.

    The weight of evidence the preseason rate already carries, so this season's
    games can be mixed in against it rather than against a fixed constant.
    """
    root = str(Q.repo_root())
    out: Dict[str, float] = {}
    for i, weight in enumerate(model.weights):
        frame = _season_rates(year - i - 1, model.halflife, root, model.drop_injury_games)
        for name in frame.index:
            out[name] = out.get(name, 0.0) + float(frame.loc[name, "count"]) * weight
    return out


@functools.lru_cache(maxsize=None)
def _in_season_cached(year: int, through_week: int, halflife: Optional[float],
                      root: str, drop_injury_games: bool = False
                      ) -> Dict[str, Tuple[int, float]]:
    df = _player_week()
    d = df[(df["Year"] == year) & (df["Week"] <= through_week) & df["Available"]]
    d = d.dropna(subset=["Points"])
    if drop_injury_games:
        # only once the missed week that marks it is itself inside the cutoff
        d = d[~(d["InjuryGame"] & (pd.to_numeric(d["NextWeek"]) <= through_week))]
    out: Dict[str, Tuple[int, float]] = {}
    for name, g in d.groupby("Player", sort=False):
        pts = g["Points"].to_numpy(float)
        n = len(pts)
        w = (0.5 ** ((n - 1 - np.arange(n)) / float(halflife))) if halflife else np.ones(n)
        out[name] = (n, float((pts * w).sum() / w.sum()))
    return out


def in_season_evidence(year: int, through_week: int,
                       model: RateModel = RateModel()) -> Dict[str, Tuple[int, float]]:
    """{player name: (available games, recency-weighted points per game)} for
    `year` weeks 1..`through_week` — what this season has shown so far.

    Only weeks up to the cutoff, so a forecast rewound to week k cannot see
    week k+1.
    """
    if through_week <= 0:
        return {}
    return _in_season_cached(int(year), int(through_week), model.halflife,
                             str(Q.repo_root()), model.drop_injury_games)


def blend_in_season(prior: float, prior_games: float, games: int, mean: float,
                    model: RateModel = RateModel()) -> float:
    """The preseason rate updated with this season's games (`in_season_weight`)."""
    if games <= 0 or model.in_season_weight <= 0:
        return prior
    evidence = prior_games + model.shrink_games
    added = model.in_season_weight * games
    return float((prior * evidence + mean * added) / (evidence + added))


# ---------------------------------------------------------------------------
# Layer 3b: injuries last more than a week
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InjuryModel:
    """How long injuries last in this league, fitted from `player_week`.

    recovery[d-1]  P(a player who has missed d straight weeks plays the next
                   one), d = 1..len(recovery); `tail` beyond that. Falls with
                   d: a one-week knock is back 36% of the time next week, a
                   player out eight weeks 5%. Censored at season end, so a
                   spell still running in week 17 counts as at risk, not
                   ended.
    mean_duration  weeks missed per spell *inside a season* (hurt weeks /
                   spells, ~3.3). This, not the curve's own expectation (~7, a
                   long IR tail no season is long enough to finish), is what
                   sets the new-injury rate: measured on 2022-2025 rewound to
                   weeks 2/4/8 (each season left out of its own fit), the
                   in-season figure predicts healthy players' remaining
                   availability at 0.854/0.860/0.874 against 0.858/0.858/0.877
                   actual, where the curve's figure says 0.93.
    spells         spells the fit saw; seasons the seasons it used.

    Measured the same way, against the flat model it replaces (independent
    weeks, flagged players capped at 0.51): Brier on every remaining
    player-week 0.1436/0.1460/0.1380 -> 0.1395/0.1429/0.1326 at weeks 2/4/8,
    and for players out at the cutoff 0.248/0.248/0.250 -> 0.216/0.224/0.224,
    with their predicted availability 0.596/0.541/0.487 against 0.597/0.596/
    0.500 actual (the flat cap said 0.51 throughout).
    """
    recovery: Tuple[float, ...]
    tail: float
    mean_duration: float
    spells: int
    seasons: Tuple[int, ...]

    def hazard(self, missed: np.ndarray) -> np.ndarray:
        """P(return this week) for players who have missed `missed` weeks (0 -> 0)."""
        table = np.array((0.0,) + self.recovery + (self.tail,))
        return table[np.clip(missed, 0, len(self.recovery) + 1)]

    def new_injury_hazard(self, availability: float) -> float:
        """Weekly P(a healthy player gets hurt) that keeps long-run availability at
        `availability`: healthy spells average 1/h weeks, hurt spells
        `mean_duration`, so availability = (1/h) / (1/h + mean_duration)."""
        a = min(max(float(availability), 0.05), 0.995)
        return float(min((1.0 - a) / (a * self.mean_duration), 1.0))

    def return_curve(self, missed: int, weeks: int) -> np.ndarray:
        """P(available) in each of the next `weeks` weeks for a player who has
        missed `missed` straight weeks, before any re-injury."""
        out = np.empty(weeks)
        still_out = 1.0
        d = int(missed)
        for t in range(weeks):
            r = float(self.hazard(np.array([d]))[0])
            out[t] = 1.0 - still_out * (1.0 - r)
            still_out *= 1.0 - r
            d += 1
        return out


@functools.lru_cache(maxsize=None)
def _injury_model_cached(exclude: Optional[int], root: str, cap: int) -> InjuryModel:
    df = _player_week()
    seasons = tuple(y for y in Q.completed_seasons()
                    if y >= 2021 and y != exclude)
    d = df[df["Year"].isin(seasons) & ~df["Bye?"]]
    at_risk = np.zeros(cap + 2)
    ended = np.zeros(cap + 2)
    n_spells = 0
    for _, g in d.groupby(["Player", "Year"], sort=False):
        hurt = g["Hurt"].to_numpy(bool)
        weeks = g["Week"].to_numpy(int)
        i = 0
        while i < len(hurt):
            if not hurt[i]:
                i += 1
                continue
            j = i
            # a spell is consecutive rostered weeks; a gap (dropped, re-added) ends it
            while j + 1 < len(hurt) and hurt[j + 1] and weeks[j + 1] - weeks[j] <= 2:
                j += 1
            length = j - i + 1
            censored = j == len(hurt) - 1 or weeks[j + 1] - weeks[j] > 2
            n_spells += 1
            for k in range(1, length + 1):
                b = min(k, cap + 1)
                if k < length or not censored:
                    at_risk[b] += 1
                if k == length and not censored:
                    ended[b] += 1
            i = j + 1
    rec = tuple(float(ended[k] / at_risk[k]) if at_risk[k] else 0.0 for k in range(1, cap + 1))
    tail = float(ended[cap + 1] / at_risk[cap + 1]) if at_risk[cap + 1] else 0.05
    tail = max(tail, 0.01)
    mean_dur = float(d["Hurt"].sum()) / max(n_spells, 1)
    return InjuryModel(recovery=rec, tail=tail, mean_duration=float(mean_dur),
                       spells=n_spells, seasons=seasons)


def injury_model(exclude_from_fits: Optional[int] = None, cap: int = 8) -> InjuryModel:
    """The league's injury-return curve, leaving `exclude_from_fits` out."""
    return _injury_model_cached(exclude_from_fits, str(Q.repo_root()), int(cap))


@functools.lru_cache(maxsize=None)
def _weeks_missed_cached(year: int, through_week: int, root: str) -> Dict[str, int]:
    df = _player_week()
    d = df[(df["Year"] == year) & (df["Week"] <= through_week) & ~df["Bye?"]]
    out: Dict[str, int] = {}
    for name, g in d.groupby("Player", sort=False):
        hurt = g["Hurt"].to_numpy(bool)
        n = 0
        for h in hurt[::-1]:
            if not h:
                break
            n += 1
        if n:
            out[name] = n
    return out


def weeks_missed(year: int, through_week: int) -> Dict[str, int]:
    """{player name: straight weeks missed to injury/suspension, as of `through_week`}
    — only players whose latest non-bye week was missed. Built from the
    league's own `player_week`, so it is history, not today's news, and a
    rewound forecast may use it."""
    if through_week <= 0:
        return {}
    return _weeks_missed_cached(int(year), int(through_week), str(Q.repo_root()))


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
    """One researched, sourced, dated statement about a player's season.

    player_id          the Sleeper id the row is about (the key; `player` is
                       for people). A row without one is resolved from its name
                       and `check_research_file` asks for the id to be written in.
    availability       P(available) each week the row applies, as flat draws; blank
                       = leave availability to the model.
    out_through_week   he cannot play through this week (a season-ending injury
                       is the last week); after it he returns on the model's curve.
    valid_through_week the last week the row describes: a forecast that already
                       knows results after it ignores the row and lets this
                       season's evidence speak. Blank = the preseason only (0),
                       or `out_through_week` if that is given. Until 2026-11-15
                       a row applied forever, so an August note held George
                       Kittle to 70% availability in November with 8 of 9 games
                       played.
    """
    player: str
    availability: Optional[float]
    rate_multiplier: float
    note: str
    source: str
    as_of: str
    player_id: str = ""
    out_through_week: Optional[int] = None
    valid_through_week: Optional[int] = None

    def applies(self, through_week: int) -> bool:
        """Whether a forecast that knows results through `through_week` uses it."""
        last = self.valid_through_week
        if last is None:
            last = self.out_through_week if self.out_through_week is not None else 0
        return int(through_week) <= int(last)


def research_path(year: int) -> "Path":
    from pathlib import Path
    return Path(Q.repo_root()) / "plan" / "notes" / f"forecast_status_{int(year)}.csv"


@functools.lru_cache(maxsize=None)
def _research_cached(year: int, root: str) -> Tuple[ResearchNote, ...]:
    path = research_path(year)
    if not path.exists():
        return ()
    frame = pd.read_csv(path, dtype={"player_id": str})
    out = []

    def num(row, col):
        v = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
        return None if pd.isna(v) else float(v)

    for _, row in frame.iterrows():
        avail, mult = num(row, "availability"), num(row, "rate_multiplier")
        out_through, valid = num(row, "out_through_week"), num(row, "valid_through_week")
        pid = row.get("player_id")
        out.append(ResearchNote(
            player=str(row["player"]).strip(),
            availability=avail,
            rate_multiplier=mult if mult is not None else 1.0,
            note=str(row.get("note", "")).strip(),
            source=str(row.get("source", "")).strip(),
            as_of=str(row.get("as_of", "")).strip(),
            player_id="" if pid is None or pd.isna(pid) else str(pid).strip().split(".")[0],
            out_through_week=None if out_through is None else int(out_through),
            valid_through_week=None if valid is None else int(valid)))
    return tuple(out)


def _note_id(note: ResearchNote) -> str:
    """The row's Sleeper id, or its name resolved (unambiguous only), or ''."""
    if note.player_id:
        return note.player_id
    try:
        return Q.players().resolve(note.player)
    except Exception:
        return ""


def research_overrides(year: int) -> Dict[str, ResearchNote]:
    """Curated outside reporting for a season, keyed by Sleeper player id.

    Keyed by id, never by name (until 2026-11-15 it was by name, and five 2026
    rows — "Michael Penix" for "Michael Penix Jr." among them — silently moved
    nobody while the warning said they were not rostered). A row with no id is
    resolved from its name; one that resolves to nobody is left out here and
    reported by `check_research_file`.

    The file this reads is the *only* place in this module where a human
    judgement about the real world enters, and it is deliberately the most
    auditable thing here: every row carries the number, a note saying why, a
    URL and the date it was true. Nothing is inferred from it silently — the
    forecast reports how many players it moved and `check_research_file` refuses
    a row that names nobody on a roster or omits its source.
    """
    out: Dict[str, ResearchNote] = {}
    for n in _research_cached(int(year), str(Q.repo_root())):
        pid = _note_id(n)
        if pid:
            out[pid] = n
    return out


ESPN_HOLD = frozenset({"Injured Reserve", "Out", "Physically Unable to Perform", "Suspension"})


def _espn_timelines(year: int, first_sim_week: int, max_age_days: float
                    ) -> Tuple[Dict[str, "ESPN.EspnStatus"], str]:
    """({Sleeper id: ESPN status}, warning). Empty when there is no capture for
    the season or it is too old to describe the weeks being simulated. Here so
    a scenario (trade.py --healthy) can patch it."""
    rows = ESPN.current(year)
    if not rows:
        return {}, ""
    from datetime import datetime, timezone
    at = ESPN.captured_at(year)
    age = (datetime.now(timezone.utc) - at).total_seconds() / 86400 if at else float("inf")
    if age > max_age_days:
        return {}, (f"ESPN injury capture is {age:.0f} days old (limit {max_age_days:g}): "
                    f"its return dates were NOT used")
    return rows, ""


def _on_ir(year: int, through_week: int) -> Dict[str, Tuple[int, int]]:
    """`ir_status.on_ir`, here so a scenario (trade.py --healthy) can patch it."""
    return IR.on_ir(year, through_week)


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


def roster_week(year: int, as_of_week: Optional[int] = None) -> int:
    """The week whose rosters a forecast projects: the first week it does not know.

    The projection prices the rosters that will play the weeks still to be
    simulated. Week 1's rosters are right only before kickoff: once weeks are
    played, every trade, waiver claim and cut since then belongs in it. (Until
    2026-10-15 the forecast always used week 1, so mid-season odds ignored
    every move made after kickoff.)

    Live, that is the week after the last finalized one; its matchup file is
    the snapshot's current rosters. Rewound with `as_of_week`, it is the week
    after the cutoff, so a backtest sees only rosters that existed by then, and
    `as_of_week=0` is still week 1. A played-out season clamps to its last week
    with a matchup file — it is a lookup there and the projection does not
    decide anything.
    """
    meta = Q.season_meta(year)
    known = [w for w in Q.played_weeks(year)
             if as_of_week is None or w <= int(as_of_week)]
    target = min((max(known) + 1) if known else 1, meta.last_week)
    for wk in range(target, 0, -1):
        try:
            Q.week(year, wk)
        except FileNotFoundError:
            continue
        return wk
    return 1


@dataclass
class FieldedDistribution:
    """What a roster is expected to field, week to week, once injuries bite."""
    year: int
    teams: Dict[int, str]
    mean: Dict[int, float]
    sd: Dict[int, float]
    samples: Dict[int, np.ndarray]
    healthy: Dict[int, float]                     # best lineup with everyone up
    week_mean: Dict[int, np.ndarray] = field(default_factory=dict)  # per simulated week
    rookies: Dict[int, int] = field(default_factory=dict)
    sidelined: Dict[int, int] = field(default_factory=dict)
    unsigned: Dict[int, int] = field(default_factory=dict)
    researched: Dict[int, int] = field(default_factory=dict)
    unplaced: Dict[int, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    # {player id: P(available) per simulated week, from first_week on}; one
    # number (independent weekly draws) in the preseason
    availability: Dict[str, np.ndarray] = field(default_factory=dict)
    # {player id: what ESPN's timeline did to him}, live forecasts only
    espn: Dict[str, str] = field(default_factory=dict)
    # {player id: (ESPN's timeline or "", what the forecast assumed)} for every
    # hurt, tagged or ESPN-listed startable player
    basis: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    first_week: int = 1

    def depth_cost(self, rid: int) -> float:
        """Points a week the roster loses to unavailability — the depth tax."""
        return self.healthy[rid] - self.mean[rid]


def _injury_paths(rng: np.random.Generator, draws: int, weeks: int, p: np.ndarray,
                  flat: np.ndarray, start: np.ndarray, model: InjuryModel,
                  ir_games: Optional[np.ndarray] = None,
                  ir_model: Optional["IR.IRReturnModel"] = None, year: int = 0,
                  lock: Optional[np.ndarray] = None,
                  first_week_p: Optional[np.ndarray] = None,
                  reset: Optional[np.ndarray] = None) -> np.ndarray:
    """(draws, weeks, players) availability, one consecutive path per draw.

    `start` is -1 for a player healthy at the cutoff, else the weeks he has
    already missed (0 = hurt but not yet missed a game). Healthy players get
    hurt at the rate that keeps their long-run availability at `p`; hurt ones
    return on the fitted curve. `flat` players (researched, unsigned) keep
    independent weekly draws at `p`.

    Optional, per player:
      ir_games      -1, or the games he has already missed on injured reserve:
                    he returns on `ir_model` (0 before the minimum) instead of
                    the general curve, and is an ordinary player once back;
      lock          the first `lock` weeks he cannot play at all (a dated,
                    sourced "out through week N");
      first_week_p  P(he plays) in the first week only, on top of the rest (a
                    Questionable / Doubtful tag), as a one-week miss;
      reset         at week `lock` his absence restarts: he returns that week
                    with the curve's first-week hazard (the IR curve's first
                    eligible game if on IR) rather than the hazard for however
                    long the lock made him miss (an estimated return date).
    """
    n = len(p)
    hazard = np.array([model.new_injury_hazard(x) for x in p]) if n else np.zeros(0)
    hurt = np.broadcast_to(start >= 0, (draws, n)).copy()
    dur = np.broadcast_to(np.maximum(start, 0), (draws, n)).copy()
    irg0 = np.full(n, -1) if ir_games is None else np.asarray(ir_games, dtype=int)
    on_ir = np.broadcast_to(irg0 >= 0, (draws, n)).copy() & hurt
    irg = np.broadcast_to(np.maximum(irg0, 0), (draws, n)).copy()
    lock = np.zeros(n, dtype=int) if lock is None else np.asarray(lock, dtype=int)
    out = np.empty((draws, weeks, n), dtype=bool)
    reset = np.zeros(n, dtype=bool) if reset is None else np.asarray(reset, dtype=bool)
    for t in range(weeks):
        at = reset & (lock == t)
        if at.any():
            dur = np.where(at & hurt, 1, dur)
            if ir_model is not None:
                # back to the first eligible game, but never before the minimum
                m = IR.ir_min_games(year)
                irg = np.where(at & on_ir & (irg >= m), m, irg)
        u = rng.random((draws, n))
        if ir_model is not None and on_ir.any():
            r = np.where(on_ir, ir_model.hazard(irg, year), model.hazard(dur))
        else:
            r = model.hazard(dur)
        back = hurt & (u < r) & (t >= lock)
        new = ~hurt & (u < hazard) & (t >= lock)
        still = hurt & ~back
        dur = np.where(still, dur + 1, np.where(new, 1, 0))
        irg = np.where(on_ir & still, irg + 1, irg)
        on_ir = on_ir & still
        hurt = still | new
        up = np.where(flat, u < p, ~hurt) & (t >= lock)
        if t == 0 and first_week_p is not None:
            up &= rng.random((draws, n)) < np.asarray(first_week_p, dtype=float)
        out[:, t, :] = up
    return out


def fielded_distribution(year: int, model: RateModel = RateModel(),
                         availability: AvailabilityModel = AvailabilityModel(),
                         week: int = 1, seed: int = 12026,
                         exclude_from_fits: Optional[int] = None,
                         through_week: int = 0, horizon: int = 1) -> FieldedDistribution:
    """Simulate who is available each week and refill the lineup from the rest.

    This is where depth stops being a word. Each draw knocks players out and
    the lineup is rebuilt from whoever is left using the build's own
    `compute_optimal_lineup` — so a team that loses a starter and has nobody
    behind him drops further than a team that does not, and its weekly spread
    is wider.

    `through_week` is how much of `year` is known. 0 (preseason, and every
    calibration fit) projects from prior seasons alone with independent weekly
    draws. Once weeks are known, two things change:

      * each player's rate is updated with this season's games
        (`RateModel.in_season_weight`);
      * with `AvailabilityModel.injury_spells`, availability is simulated as
        `horizon` consecutive weeks per draw: a player out now starts out and
        returns on `injury_model`'s curve, and new injuries last several
        weeks. `samples` is then draws x weeks and `week_mean` the per-week
        projection (it rises as injured players come back).
    """
    rates = player_rates(year, model, exclude_from_fits)
    through_week = max(int(through_week), 0)
    current = in_season_evidence(year, through_week, model) if through_week else {}
    prior_games = player_prior_games(year, model) if current else {}
    spells = bool(through_week) and availability.injury_spells
    injuries = injury_model(exclude_from_fits=year) if spells else None
    missed = weeks_missed(year, through_week) if spells else {}
    horizon = max(int(horizon), 1) if spells else 1
    use_ir = spells and availability.ir_minimum
    on_ir = _on_ir(year, through_week) if use_ir else {}
    ir_model = (IR.ir_return_model(exclude_from_fits=year if Q.season_meta(year).is_complete else None)
                if on_ir else None)
    # today's Questionable / Doubtful tags describe the first simulated week only
    # when the forecast is live (knows every played week)
    live = spells and through_week >= max(Q.played_weeks(year) or [0])
    price = rookie_price(exclude_from_fits, model)
    board = _draft_board(str(Q.repo_root()))
    class_board = board[board.year == year].set_index("player")
    avail, base = availability_rates(year, availability)
    use_flags = availability.uses_designations(year)
    designations = _designations(str(Q.repo_root())) if use_flags else {}
    unsigned = _unsigned(str(Q.repo_root()))
    notes = research_overrides(year) if availability.research else {}
    espn, espn_note = (_espn_timelines(year, through_week + 1, availability.espn_max_age_days)
                       if live and availability.espn_timelines else ({}, ""))
    espn_applied: Dict[str, str] = {}
    basis: Dict[str, Tuple[str, str]] = {}
    state = _roster_state(year, str(Q.repo_root()))
    players = Q.players()
    teams = Q.teams(year)
    pool = startable_pool(year, week, availability)
    rng = np.random.default_rng(seed)

    mean: Dict[int, float] = {}
    sd: Dict[int, float] = {}
    samples: Dict[int, np.ndarray] = {}
    healthy: Dict[int, float] = {}
    week_mean: Dict[int, np.ndarray] = {}
    rookies: Dict[int, int] = {}
    sidelined: Dict[int, int] = {}
    unsigned_count: Dict[int, int] = {}
    researched: Dict[int, int] = {}
    unplaced: Dict[int, int] = {}
    warnings: List[str] = []
    applied: set = set()
    expired: set = set()
    first_sim_week = through_week + 1
    player_avail: Dict[str, np.ndarray] = {}
    n_ir_total = n_tagged_total = 0

    for rid, pids in pool.items():
        values: Dict[str, float] = {}
        pos_map: Dict[str, str] = {}
        probs: List[float] = []
        flats: List[bool] = []
        starts: List[int] = []
        ir_list: List[int] = []
        locks: List[int] = []
        firsts: List[float] = []
        resets: List[bool] = []
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
            if name in current:
                games, ppg = current[name]
                values[pid] = blend_in_season(values[pid], prior_games.get(name, 0.0),
                                              games, ppg, model)
            p = avail.get(name, base.get(pos, base.get("_default", 0.82)))
            flagged = use_flags and (pid in reserve
                                     or designations.get(pid, "") in OUT_DESIGNATIONS)
            out_now = -1                      # -1 healthy, else weeks already missed
            if spells:
                if name in missed:
                    out_now = missed[name]
                    # Sleeper has him active with no designation at all: he is back
                    if use_flags and not flagged and not designations.get(pid, ""):
                        out_now = -1
                if flagged and out_now < 0:
                    out_now = 0               # hurt since the last played week
                if out_now >= 0:
                    n_out += 1
            elif flagged:
                p = min(p, availability.reserve_availability)
                n_out += 1
            ir_games, lock, first = -1, 0, 1.0
            if use_ir and pid in on_ir:
                # on injured reserve: the NFL minimum, then the IR curve — unless
                # Sleeper has already activated him (no designation, not in the slot)
                if not (use_flags and not flagged and not designations.get(pid, "")):
                    ir_games = on_ir[pid][1]
                    out_now = max(out_now, 0)
                    n_ir_total += 1
            if live and out_now < 0:
                tag = designations.get(pid, "")
                if tag == "Questionable":
                    first = availability.questionable_availability
                elif tag == "Doubtful":
                    first = availability.doubtful_availability
                if first < 1.0:
                    n_tagged_total += 1
            flat = not spells
            if pid in unsigned and availability.unsigned_availability < 1.0:
                # no NFL team: he cannot score for anyone until he signs
                p = min(p, availability.unsigned_availability)
                n_unsigned += 1
                flat, out_now, ir_games = True, -1, -1
            note = notes.get(pid)
            if note is not None and not note.applies(through_week):
                expired.add(pid)
                note = None
            if note is not None:
                if note.out_through_week is not None:
                    weeks_out = note.out_through_week - first_sim_week + 1
                    if spells:
                        lock = max(weeks_out, 0)
                        out_now = max(out_now, 0)
                    elif weeks_out > 0:
                        # preseason draws are per week, not per path: scale by the
                        # share of the season he can still play
                        last = Q.season_meta(year).last_week
                        p *= max(0.0, (last - note.out_through_week) / max(last - first_sim_week + 1, 1))
                if note.availability is not None:
                    p = note.availability if note.out_through_week is None or spells else p
                    flat, out_now, ir_games = True, -1, -1  # dated outside reporting wins
                values[pid] *= note.rate_multiplier
                n_researched += 1
                applied.add(pid)
            reset = False
            es = espn.get(pid)
            # a dated research row (out-through-week / availability) wins; a row
            # that only scales his rate does not block ESPN's timeline
            dated_note = note is not None and (note.out_through_week is not None
                                               or note.availability is not None)
            if (es is not None and spells and not dated_note and not flat
                    and es.status in ESPN_HOLD):
                if es.season_ending:
                    lock, out_now = max(lock, horizon), max(out_now, 0)
                    espn_applied[pid] = es.label()
                elif es.return_week and es.return_week > first_sim_week:
                    weeks_out = es.return_week - first_sim_week
                    if weeks_out > lock:
                        lock, reset, out_now = weeks_out, True, max(out_now, 0)
                        espn_applied[pid] = es.label()
            # what the forecast assumed for every hurt or listed player, and why
            # (the site's injury card lists all of them, not just ESPN's)
            used = ""
            if dated_note:
                used = (f"research file: out through wk {note.out_through_week}"
                        if note.out_through_week is not None and spells
                        else f"research file: {p:.0%} a week")
            elif pid in espn_applied:
                used = ("out for the season (ESPN)" if es.season_ending
                        else "out for the season (ESPN: back after the regular season)"
                        if es.return_week > Q.season_meta(year).last_week
                        else f"out until wk {es.return_week} (ESPN), then return curve")
            elif ir_games >= 0:
                back = first_sim_week + max(IR.ir_min_games(year) - ir_games, 0)
                used = f"IR: not before wk {back}, then IR return curve"
            elif out_now >= 0 and spells:
                used = "missed his last game: league return curve"
            elif first < 1.0:
                used = f"{designations.get(pid, '')} this week: plays {first:.0%}"
            elif flat and pid in unsigned:
                used = "no NFL team"
            if used or es is not None:
                basis[pid] = (es.label().replace("ESPN: ", "") if es is not None else "",
                              used or "treated as healthy")
            probs.append(p)
            flats.append(flat)
            starts.append(out_now)
            ir_list.append(ir_games)
            locks.append(lock)
            firsts.append(first)
            resets.append(reset)

        pid_list = list(values)
        healthy[rid] = float(L.compute_optimal_lineup(values, pos_map, year))
        p_arr = np.array(probs, dtype=float)
        if spells:
            up = _injury_paths(rng, availability.draws, horizon, p_arr,
                               np.array(flats, dtype=bool), np.array(starts, dtype=int),
                               injuries, ir_games=np.array(ir_list, dtype=int),
                               ir_model=ir_model, year=year,
                               lock=np.array(locks, dtype=int),
                               first_week_p=np.array(firsts, dtype=float),
                               reset=np.array(resets, dtype=bool))
            share = up.mean(axis=0)                     # (weeks, players)
            for j, pid in enumerate(pid_list):
                player_avail[pid] = share[:, j]
        else:
            up = (rng.random((availability.draws, len(pid_list))) < p_arr)[:, None, :]
            for j, pid in enumerate(pid_list):
                player_avail[pid] = np.array([p_arr[j]])
        cache: Dict[bytes, float] = {}
        vals = np.empty(up.shape[:2], dtype=float)
        for i in range(up.shape[0]):
            for t in range(up.shape[1]):
                row = up[i, t]
                key = np.packbits(row).tobytes()
                hit = cache.get(key)
                if hit is None:
                    sub = {pid: values[pid] for pid, ok in zip(pid_list, row) if ok}
                    hit = cache[key] = float(L.compute_optimal_lineup(sub, pos_map, year))
                vals[i, t] = hit
        if not spells:
            vals = vals[:, 0]
        mean[rid] = float(vals.mean())
        sd[rid] = float(vals.std(ddof=1))
        samples[rid] = vals
        week_mean[rid] = vals.mean(axis=0) if vals.ndim == 2 else np.array([mean[rid]])
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
        if n_out and spells:
            warnings.append(
                f"{teams.get(rid, rid)}: {n_out} player(s) out as of week {through_week} — "
                f"returning on the league's injury curve ({injuries.spells} past spells)")
        elif n_out:
            warnings.append(
                f"{teams.get(rid, rid)}: {n_out} player(s) carrying a reserve/IR-class "
                f"designation — capped at {availability.reserve_availability:.0%} availability")
        if n_unsigned:
            warnings.append(
                f"{teams.get(rid, rid)}: {n_unsigned} rostered player(s) with no NFL team — "
                f"capped at {availability.unsigned_availability:.0%} availability")
    all_rostered = set()
    for row in Q.week(year, week).values():
        all_rostered.update(row.players)
    unused = set(notes) - applied - expired
    missing = sorted(notes[i].player for i in unused if i not in all_rostered)
    benched = sorted(notes[i].player for i in unused if i in all_rostered)
    if expired:
        warnings.append(
            f"{len(expired)} research note(s) describe weeks this forecast already knows "
            f"(valid through an earlier week) and were not applied: "
            f"{', '.join(sorted(notes[i].player for i in expired)[:8])}")
    if n_ir_total:
        warnings.append(
            f"{n_ir_total} player(s) on injured reserve: no return before the "
            f"{IR.ir_min_games(year)}-game minimum, then the IR return curve "
            f"({ir_model.runs} past IR runs)")
    if espn_note:
        warnings.append(espn_note)
    if espn_applied:
        ending = sum("out for season" in v for v in espn_applied.values())
        warnings.append(
            f"ESPN timelines ({ESPN.current_path().name}): {ending} player(s) out for the "
            f"season, {len(espn_applied) - ending} held out until ESPN's estimated return "
            f"week, then the curve (estimates not yet validated)")
    if n_tagged_total:
        warnings.append(
            f"{n_tagged_total} player(s) tagged Questionable/Doubtful: week {first_sim_week} "
            f"availability {availability.questionable_availability:.0%} / "
            f"{availability.doubtful_availability:.0%}")
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
                               healthy=healthy, week_mean=week_mean,
                               rookies=rookies, sidelined=sidelined,
                               unsigned=unsigned_count, researched=researched,
                               unplaced=unplaced, warnings=sorted(set(warnings)),
                               availability=player_avail, first_week=first_sim_week,
                               espn=espn_applied, basis=basis)


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
    is out of the league in 2026. Injury spells stay as set: their starting
    state is read from `player_week` up to the cutoff, not from today's flags.
    """
    return AvailabilityModel(lookback=model.lookback, shrink_weeks=model.shrink_weeks,
                             exclude_taxi=model.exclude_taxi,
                             reserve_availability=model.reserve_availability,
                             designations="never", research=False,
                             # 1.0 = disabled: see AvailabilityModel.unsigned_availability
                             unsigned_availability=1.0,
                             # who was out at the cutoff comes from the league's own
                             # player_week, which is history, so the spells stay on
                             injury_spells=model.injury_spells,
                             # IR placements come from nflverse's weekly rosters, read
                             # only up to the cutoff (ir_status.on_ir), so it stays on
                             ir_minimum=model.ir_minimum,
                             questionable_availability=model.questionable_availability,
                             doubtful_availability=model.doubtful_availability,
                             # today's ESPN list would leak the future into a rewind
                             espn_timelines=False,
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
    next_week: Optional[float] = None             # fielded projection, first simulated week
    playoff_weeks: Optional[float] = None         # ... averaged over the playoff weeks


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
    roster_week: int = 1                          # whose rosters the projection used
    # {Sleeper id: P(available) in each simulated week from availability_from_week}
    # for every startable rostered player — what the injury model assumed
    player_availability: Dict[str, Tuple[float, ...]] = field(default_factory=dict)
    availability_from_week: int = 1
    # {Sleeper id: "ESPN: out for season (acl tear)" / "ESPN: est. back wk 13"}
    espn_timelines: Dict[str, str] = field(default_factory=dict)
    # {Sleeper id: (ESPN's timeline or "", what the forecast assumed)}
    injury_basis: Dict[str, Tuple[str, str]] = field(default_factory=dict)

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


def _week_shape(proj: "FieldedDistribution", rid: int, sim_weeks: Sequence[int],
                meta) -> Dict[str, Optional[float]]:
    """Next simulated week and the playoff weeks, from the per-week projection
    (only distinct when injury spells are on)."""
    wm = proj.week_mean.get(rid)
    if wm is None or len(wm) < 2 or not sim_weeks:
        return {}
    col = {w: min(j, len(wm) - 1) for j, w in enumerate(sim_weeks)}
    po = [float(wm[col[w]]) for w in meta.playoff_weeks if w in col]
    return {"next_week": float(wm[0]), "playoff_weeks": float(np.mean(po)) if po else None}


def forecast(year: int, sims: int = 20000, model: RateModel = RateModel(),
             availability: AvailabilityModel = AvailabilityModel(),
             calibration: Optional[Calibration] = None, seed: int = 20260807,
             strength_model: str = "roster", as_of_week: Optional[int] = None,
             rules: Optional[Any] = None) -> Forecast:
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

    `rules` (default None = the league's real rules) is a rule-change hook,
    `lotg_support.rules.ForecastRules`: its `observed` replaces the played
    weeks' scores, its `shift` (roster id -> points/week) moves each team's
    simulated weeks, and its `standings` / `bracket` / `playoff_teams` replace
    the table, the bracket and the playoff count.
    """
    meta = Q.season_meta(year)
    teams = Q.teams(year)
    rids = sorted(teams)
    calib = calibration or calibrate(model=model, availability=availability)
    warnings: List[str] = []

    rweek = roster_week(year, as_of_week)
    cutoff = meta.last_week if as_of_week is None else int(as_of_week)
    played = _observed_scores(year)
    if rules is not None and getattr(rules, "observed", None) is not None:
        played = {w: dict(rules.observed.get(w, s)) for w, s in played.items()}
    observed = {w: s for w, s in played.items() if w <= min(cutoff, meta.last_week)}
    sim_weeks = [w for w in range(1, meta.last_week + 1) if w not in observed]
    known = max(observed) if observed else 0
    proj = fielded_distribution(year, model, availability, week=rweek, seed=seed + 1,
                                through_week=known, horizon=max(len(sim_weeks), 1))
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

    # A rule change's shift moves the prior (relative part) and the league level
    # (common part); the posterior then weighs it against the observed weeks,
    # which the hook has already re-scored — so it is not counted twice.
    level = 0.0
    if rules is not None and getattr(rules, "shift", None):
        sh = {r: float(rules.shift.get(r, 0.0)) for r in rids}
        level = float(np.mean(list(sh.values())))
        prior = {r: v + sh[r] - level for r, v in prior.items()}
    strength = _posterior(prior, sd_true, calib.sd_week, observed, meta.regular_season_weeks)
    mean = {r: calib.league_mean + level + strength[r] for r in rids}
    sched = schedule(year, mean)
    if not sched.balanced:
        warnings.append(f"{year}: {sched.describe()}")

    pairs = {w: Q.pairings(year, w) for w in range(1, meta.regular_season_weeks + 1)}
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
    #
    # With injury spells the samples are whole paths (draws x weeks): each
    # simulated season follows ONE path per team, so a star who is out in week
    # 7 is still likely out in week 8, and an injured player's return lifts the
    # weeks after it. Centred on the path average, so the per-week shape moves
    # the score while the level stays the calibrated strength.
    if strength_model == "roster":
        avail_sd = np.array([proj.sd[r] for r in rids])
        centred = {r: proj.samples[r] - proj.samples[r].mean() for r in rids}
        if not n_weeks:
            avail_draw = np.zeros((sims, 0, n_teams))
        elif all(centred[r].ndim == 2 for r in rids):
            cols = [min(j, centred[rids[0]].shape[1] - 1) for j in range(n_weeks)]
            avail_draw = np.stack(
                [centred[r][rng.integers(0, centred[r].shape[0], size=sims)][:, cols]
                 for r in rids], axis=2)
        else:
            avail_draw = np.stack(
                [centred[r][rng.integers(0, len(centred[r]), size=(sims, n_weeks))]
                 for r in rids], axis=2)
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
    n_playoff = int(getattr(rules, "playoff_teams", None) or meta.playoff_teams)

    for i in range(sims):
        level = base + true_shift[i]
        scores: Dict[int, Dict[int, float]] = {w: dict(s) for w, s in observed.items()}
        for j, wk in enumerate(sim_weeks):
            row = level + avail_draw[i, j] + week_shock[i, j] + idio[i, j]
            scores[wk] = {rid: float(row[k]) for k, rid in enumerate(rids)}
        table = (rules.standings if rules is not None else R._standings)(scores, pairs, teams, meta)
        bracket = (rules.bracket if rules is not None else R._bracket)(scores, table, teams, meta)
        for place, standing in enumerate(table):
            seed_counts[standing.roster_id][place] += 1
            wins[standing.roster_id] += standing.wins
            pf[standing.roster_id] += standing.points_for
            if place < n_playoff:
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
            **_week_shape(proj, r, sim_weeks, meta),
        )
        for r in rids
    ]
    return Forecast(year=year, model_name=strength_model, rate_model=model,
                    availability_model=availability, calibration=calib, sims=sims, seed=seed,
                    played_weeks=tuple(sorted(observed)), as_of_week=as_of_week, odds=odds,
                    roster_week=rweek,
                    rookie_price=rookie_price(None, model),
                    age_curve=age_curve(None, model) if model.age_adjust else None,
                    rookie_class=rookie_class_strength(year), schedule=sched,
                    warnings=sorted(set(warnings)),
                    player_availability={pid: tuple(round(float(x), 4) for x in v)
                                         for pid, v in proj.availability.items()},
                    availability_from_week=proj.first_week,
                    espn_timelines=dict(proj.espn),
                    injury_basis=dict(proj.basis))


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
    """Every researched row must name a real player, by id, and cite a source.

    The research file is the one hand-written input to this module, so it gets
    the strictest check: a typo'd name, a missing or mismatched id, a missing
    URL, an undated claim, an availability outside [0, 1] or a week outside the
    season is a defect, not a judgement call.
    """
    rows = _research_cached(int(year), str(Q.repo_root()))
    if not rows:
        return []
    problems: List[str] = []
    players = Q.players()
    seen: Dict[str, str] = {}
    last_week = 18
    for note in sorted(rows, key=lambda n: n.player):
        name = note.player
        # What this catches is a TYPO — a row that is nobody. It used to
        # demand the player also be on a roster, which is a different and
        # wrong test: an unsigned free agent is exactly the kind of player
        # worth a research note, and a rostered one can be cut mid-season
        # without the note becoming a mistake. (Nick Chubb, researched as
        # "unsigned free agent at 30", failed the roster form the week he
        # went unrostered.) A note about a player nobody rosters simply
        # moves nobody's projection.
        if not note.player_id:
            problems.append(f"{year} research: {name} has no player_id — write the Sleeper id in "
                            f"(names collide and get re-spelled)")
            try:
                players.resolve(name)
            except KeyError:
                problems.append(f"{year} research: {name!r} matches no NFL player — typo?")
            except Exception as exc:  # AmbiguousPlayer — a partial name, so which one?
                problems.append(f"{year} research: {name!r} is ambiguous — {exc}")
        else:
            try:
                real = players.name(note.player_id)
            except Exception:
                real = None
            if not real:
                problems.append(f"{year} research: {name} player_id {note.player_id} is no NFL player")
            elif Q._normalize(name) not in Q._normalize(real):
                problems.append(f"{year} research: {name} player_id {note.player_id} is {real}")
            if note.player_id in seen:
                problems.append(f"{year} research: {name} repeats player_id {note.player_id} "
                                f"({seen[note.player_id]})")
            seen[note.player_id] = name
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
        for col in ("out_through_week", "valid_through_week"):
            v = getattr(note, col)
            if v is not None and not 0 <= v <= last_week:
                problems.append(f"{year} research: {name} {col} {v} is not a week")
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
        f"{fc.year} championship odds — {fc.model_name} model, {fc.sims:,} sims ({played}, "
        f"week {fc.roster_week} rosters)",
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
        shaped = [o for o in fc.by_champion() if o.next_week is not None]
        if shaped:
            lines += ["", "injury timeline — fielded projection as injured players return "
                          "and new injuries land", "",
                      f"{'team':<18}{'next wk':>9}{'playoffs':>10}{'out now':>9}"]
            for o in shaped:
                po = f"{o.playoff_weeks:>10.1f}" if o.playoff_weeks is not None else f"{'-':>10}"
                lines.append(f"{o.team:<18}{o.next_week:>9.1f}{po}{o.sidelined:>9}")
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
