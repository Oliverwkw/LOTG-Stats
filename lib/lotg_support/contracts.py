"""Real-world NFL contracts, joined to fantasy production.

The question this exists for is "does a big NFL contract mean the player is
about to score more fantasy points". Nothing in `exports/` can answer it: the
league's sheets know what a player scored and what he cost *here*, not what an
NFL team paid him. This module supplies the missing side — Over The Cap's
contract history, as republished by nflverse — and the event study that turns
"he got paid" into a testable claim.

Three pieces:

  * **Contracts.** `load_contracts()` reads nflverse's `historical_contracts`,
    one row per contract with `apy_cap_pct` (average per year as a share of that
    season's salary cap, so 2013 money and 2024 money are comparable),
    guarantees, length, and a `gsis_id` that joins straight to nflverse stats.
    `signings()` reduces it to veteran deals ranked *within position and signing
    year*, because "big" only means anything relative to the position's market:
    the fifth-biggest RB deal of a year is ~5% of the cap, the fifth-biggest QB
    deal ~15%.

  * **Production.** `season_points()` builds a player-season panel from the
    build's own nflverse weekly stats — points, games and points per game,
    regular season only, scored with **this league's settings** rather than
    generic PPR (see `SCORING`). A player-season that does not exist is a real
    zero for a fantasy manager, not a missing value, and the event frame treats
    it as such.

  * **The comparison.** A big contract is handed to a player who just had a good
    season, so his raw before/after is dominated by regression to the mean —
    every position looks worse after signing, which says nothing about the
    contract. `study()` therefore compares each signer to **matched
    non-signers**: same position, same season, the same prior-season output
    (within a caliper) and, optionally, the same age. The reported number is the
    paired signer-minus-control gap, i.e. what the contract told you that last
    year's stat line had not already.

Every debatable choice is a named parameter with a default — what counts as
"big" (`top_n`), how close a control has to be (`caliper_sd`, `age_caliper`),
how much of a prior season a baseline needs (`min_baseline_games`), whether
near-big signings are allowed into the control pool (`control_exclude_top_n`) —
so the next question can vary it and report the sensitivity.

Guards live in `check_*` and are exercised by `tests/test_contracts.py`. The
load-bearing one, `check_scoring_reconciles()`, ties the panel this module
builds to a number the build already published: re-scored nflverse points must
reproduce `player_year["Points (full season)"]`.

Read-only and inquiry-only: nothing here is imported by `src/` or run by a
workflow, and nothing writes outside the nflverse cache directory.

## Traps

* **The `historical_contracts.csv` / `.csv.gz` asset is stale** — it stops at
  2022 and carries no `gsis_id`. Only the `.parquet` asset is maintained. That
  is why `load_contracts()` reads parquet (and needs `pyarrow`), and why it
  refuses a file whose newest signing is older than `MIN_EXPECTED_YEAR`.
* **Rookie contracts are not signings in this sense** — they are slotted by
  draft position and tell you nothing. `signings(veterans_only=True)` (the
  default) drops any deal signed in the player's draft year.
* **A one-year deal is a different animal.** Franchise tags and prove-it deals
  land in the top five at their position on money alone while representing the
  opposite of a long-term bet; `min_years` separates them.
* **`year_signed` is the calendar year, so season `Y` is the first season on the
  deal.** In-season extensions are also stamped with that year, so a handful of
  "year Y" outcomes were partly earned before the ink dried. There is no signing
  date in the data to filter on; the effect is small and pushes toward zero.
"""
from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from lotg_support import analysis as A
from lotg_support import external as X
from lotg_support import inquiry as Q

POSITIONS: Tuple[str, ...] = ("QB", "RB", "WR", "TE")

# nflverse republishes Over The Cap's contract history. The csv/csv.gz assets on
# the same release are stale (frozen in 2022, no gsis_id) — parquet only.
CONTRACTS_URLS: Tuple[str, ...] = (
    "https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet",
)
CONTRACTS_FILE = "nflverse_historical_contracts.parquet"

# A contracts file older than this is the stale asset, not a quiet season.
MIN_EXPECTED_YEAR = 2023

# Study defaults. Each is a documented knob, not a constant in a loop.
FIRST_SIGNING_YEAR = 2011        # before this, OTC's coverage of mid-tier deals thins out
BIG_CONTRACT_TOP_N = 5           # "big" = top N deals at the position that year
CONTROL_EXCLUDE_TOP_N = 15       # a control must not have signed a notable deal himself
MIN_BASELINE_GAMES = 6           # a baseline season shorter than this is noise
MATCH_K = 5                      # controls per signer
MATCH_CALIPER_SD = 0.25          # |base points gap| <= this * sd of the position-season
MATCH_AGE_CALIPER = 2.0          # years; None to match on production alone
PERMUTATIONS = 20_000

# "Startable" in a 12-team league: one QB and one TE, two RB and two WR-ish
# slots per team. Deliberately coarse — the point is a role, not a ranking.
STARTABLE_CUTOFF: Dict[str, int] = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}

SCORING = ("lotg", "ppr")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def _config() -> X.ExternalConfig:
    return X.ExternalConfig(cache_dir=Q.repo_root() / ".cache")


def contracts_path() -> Path:
    return _config().cache_dir / CONTRACTS_FILE


def have_contracts() -> bool:
    """True when the contracts file is already cached (tests skip without it)."""
    p = contracts_path()
    return p.exists() and p.stat().st_size > 0


def load_contracts(force_refresh: bool = False) -> pd.DataFrame:
    """Over The Cap's contract history via nflverse, one row per contract.

    Downloads to the same `.cache/` the build's other nflverse pulls use. Needs
    `pyarrow`: the maintained asset is parquet, and the csv variant on that
    release has been frozen since 2022 (see the trap list).
    """
    cfg = _config()
    path = contracts_path()
    if force_refresh or not have_contracts():
        X._download_best_effort(list(CONTRACTS_URLS), path, cfg.timeout_seconds)
    try:
        df = pd.read_parquet(path)
    except ImportError as e:  # pragma: no cover - environment dependent
        raise ImportError(
            "reading the contracts file needs pyarrow (pip install pyarrow); the "
            "csv asset on that release is stale and cannot be substituted"
        ) from e
    newest = int(pd.to_numeric(df["year_signed"], errors="coerce").max())
    if newest < MIN_EXPECTED_YEAR:
        raise ValueError(
            f"contracts file stops at {newest} — that is the stale csv-era asset, "
            f"not the maintained parquet; delete {path} and refresh"
        )
    return df


def _weekly_stats(season: int) -> pd.DataFrame:
    """The build's own nflverse weekly stats loader, one season."""
    return X.load_nflverse_stats_player_week(_config(), season)


def lotg_points(weekly: pd.DataFrame) -> pd.Series:
    """Re-score nflverse's PPR column into this league's settings.

    The league's scoring is standard PPR with one difference that matters: it
    charges -1 for *any* fumble and another -1 when it is lost, where nflverse
    charges -2 only for a lost fumble. So league points = PPR points minus the
    fumbles a player put on the ground and got back.

    `check_scoring_reconciles()` holds this against the build's published
    `player_year["Points (full season)"]`.
    """
    def col(name: str) -> pd.Series:
        if name in weekly.columns:
            return pd.to_numeric(weekly[name], errors="coerce").fillna(0.0)
        return pd.Series(0.0, index=weekly.index)

    fumbles = col("rushing_fumbles") + col("receiving_fumbles") + col("sack_fumbles")
    lost = (col("rushing_fumbles_lost") + col("receiving_fumbles_lost")
            + col("sack_fumbles_lost"))
    return col("fantasy_points_ppr") - (fumbles - lost)


@functools.lru_cache(maxsize=8)
def _panel_cached(seasons: Tuple[int, ...], scoring: str, root: str) -> pd.DataFrame:
    frames = []
    for year in seasons:
        w = _weekly_stats(year)
        w = w[w["season_type"].astype(str).str.upper() == "REG"]
        w = w[w["position"].isin(POSITIONS)].copy()
        w["_points"] = (lotg_points(w) if scoring == "lotg"
                        else pd.to_numeric(w["fantasy_points_ppr"], errors="coerce"))
        frames.append(w[["player_id", "player_display_name", "position", "season",
                         "week", "_points"]])
    weekly = pd.concat(frames, ignore_index=True)
    panel = (weekly.groupby(["player_id", "season"])
             .agg(player=("player_display_name", "last"),
                  position=("position", lambda s: s.mode().iat[0]),
                  games=("week", "nunique"),
                  points=("_points", "sum"))
             .reset_index())
    panel["ppg"] = panel["points"] / panel["games"]
    panel["pos_rank"] = panel.groupby(["season", "position"])["points"].rank(
        ascending=False, method="min")
    panel["startable"] = [float(r <= STARTABLE_CUTOFF[p])
                          for r, p in zip(panel["pos_rank"], panel["position"])]
    return panel


def season_points(seasons: Sequence[int], scoring: str = "lotg") -> pd.DataFrame:
    """Player-season fantasy panel: points, games, ppg, positional finish.

    Regular season only — the fantasy season ends before the NFL playoffs, so
    postseason production is not what a manager bought. `scoring="lotg"` uses
    the league's settings (`lotg_points`); `"ppr"` leaves nflverse's standard
    PPR column alone, which is the sensitivity run.

    Note `games` counts weeks in which the player recorded a stat line, which is
    the availability a fantasy roster actually saw; a healthy scratch and an
    injury look the same here, deliberately.
    """
    if scoring not in SCORING:
        raise ValueError(f"scoring must be one of {SCORING}, got {scoring!r}")
    return _panel_cached(tuple(sorted(seasons)), scoring, str(Q.repo_root())).copy()


@functools.lru_cache(maxsize=1)
def _ages_cached(root: str) -> Dict[str, float]:
    """Birth year per gsis_id, from the build's cached nflverse player file."""
    ids = X.load_nflverse_player_ids(_config())
    out: Dict[str, float] = {}
    born = pd.to_datetime(ids.get("birth_date"), errors="coerce", format="mixed")
    rookie = pd.to_numeric(ids.get("rookie_season"), errors="coerce")
    for gsis, b, r in zip(ids["gsis_id"], born.dt.year, rookie):
        if not isinstance(gsis, str):
            continue
        if pd.notna(b):
            out[gsis] = float(b)
        elif pd.notna(r):
            # No birth date: assume a 22-year-old rookie. Only ever used for the
            # age caliper, never reported as an age.
            out[gsis] = float(r) - 22.0
    return out


def age_in(gsis: str, year: int) -> float:
    born = _ages_cached(str(Q.repo_root())).get(gsis)
    return float(year - born) if born is not None else float("nan")


# ---------------------------------------------------------------------------
# Signings
# ---------------------------------------------------------------------------
def signings(first_year: int = FIRST_SIGNING_YEAR, last_year: Optional[int] = None,
             positions: Sequence[str] = POSITIONS, veterans_only: bool = True,
             contracts: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Veteran contracts, one row per player-year, ranked within position-year.

    Ranked on `apy_cap_pct` because "big" is only meaningful against the
    position's own market. A player who signed twice in one year keeps the
    bigger deal.
    """
    df = load_contracts() if contracts is None else contracts.copy()
    df = df[df["position"].isin(list(positions))]
    df = df[df["gsis_id"].notna() & (df["gsis_id"].astype(str) != "")]
    df = df[pd.to_numeric(df["year_signed"], errors="coerce").notna()]
    df["year_signed"] = df["year_signed"].astype(int)
    if last_year is None:
        last_year = int(df["year_signed"].max())
    df = df[(df["year_signed"] >= first_year) & (df["year_signed"] <= last_year)]
    if veterans_only:
        rookie_deal = df["draft_year"].notna() & (df["year_signed"] <= df["draft_year"])
        df = df[~rookie_deal]
    df = (df.sort_values("apy_cap_pct", ascending=False)
          .drop_duplicates(["gsis_id", "year_signed"]))
    df["rank_in_position_year"] = df.groupby(["position", "year_signed"])[
        "apy_cap_pct"].rank(ascending=False, method="first")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# The event frame: what a player did before and after
# ---------------------------------------------------------------------------
def _lookup(panel: pd.DataFrame) -> Dict[Tuple[str, int], Tuple[float, float, float, float]]:
    return {(g, int(s)): (float(p), float(gm), float(pg), float(st))
            for g, s, p, gm, pg, st in zip(panel["player_id"], panel["season"],
                                           panel["points"], panel["games"],
                                           panel["ppg"], panel["startable"])}


def _window(look, gsis: str, year: int) -> Dict[str, float]:
    """Baseline year `year-1` and the two seasons on the deal, `year` and `year+1`.

    A season with no row is a real zero: the player took the field for nobody,
    which is exactly what a fantasy roster got out of him. `ppg` stays NaN
    there, so the rate measures never average a zero that no game produced.
    """
    out: Dict[str, float] = {}
    base = look.get((gsis, year - 1))
    out["base_points"], out["base_games"], out["base_ppg"], out["base_startable"] = (
        base if base else (float("nan"),) * 4)
    for key, yr in (("y0", year), ("y1", year + 1)):
        hit = look.get((gsis, yr))
        pts, games, ppg, startable = hit if hit else (0.0, 0.0, float("nan"), 0.0)
        out[f"{key}_points"], out[f"{key}_games"] = pts, games
        out[f"{key}_ppg"], out[f"{key}_startable"] = ppg, startable
    out["two_year_points"] = out["y0_points"] + out["y1_points"]
    return out


def event_frame(rows: pd.DataFrame, panel: pd.DataFrame, gsis_column: str,
                year_column: str) -> pd.DataFrame:
    """Attach the before/after window to any frame carrying a player and a year."""
    look = _lookup(panel)
    windows = [_window(look, g, int(y))
               for g, y in zip(rows[gsis_column], rows[year_column])]
    return pd.concat([rows.reset_index(drop=True),
                      pd.DataFrame(windows)], axis=1)


def control_pool(panel: pd.DataFrame, all_signings: pd.DataFrame,
                 exclude_top_n: int = CONTROL_EXCLUDE_TOP_N,
                 min_baseline_games: int = MIN_BASELINE_GAMES) -> pd.DataFrame:
    """Every player-season that could stand in for a signer.

    A control is a player entering season Y off a real prior season who did
    *not* sign a notable deal that year. "Notable" is wider than "big"
    (`exclude_top_n` > `top_n`) on purpose: letting the sixth-biggest deal at a
    position count as an untouched control would blunt the contrast.
    """
    notable = {(g, int(y)) for g, y in zip(
        all_signings[all_signings["rank_in_position_year"] <= exclude_top_n]["gsis_id"],
        all_signings[all_signings["rank_in_position_year"] <= exclude_top_n]["year_signed"])}
    candidates = panel[["player_id", "position", "season"]].copy()
    candidates["year"] = candidates["season"] + 1        # entering the next season
    candidates = candidates.rename(columns={"player_id": "gsis_id"})
    frame = event_frame(candidates[["gsis_id", "position", "year"]], panel,
                        "gsis_id", "year")
    frame = frame[frame["base_games"] >= min_baseline_games]
    keep = [(g, int(y)) not in notable for g, y in zip(frame["gsis_id"], frame["year"])]
    frame = frame[keep].copy()
    frame["age"] = [age_in(g, int(y)) for g, y in zip(frame["gsis_id"], frame["year"])]
    return frame.reset_index(drop=True)


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------
# Season points is the outcome a fantasy manager lives on; games and ppg are
# there to say *which* of the two moved, because "played more" and "played
# better" are different claims about what a contract buys.
OUTCOMES: Tuple[str, ...] = ("y0_points", "y1_points", "two_year_points",
                             "y0_games", "y1_games", "y0_ppg", "y1_ppg",
                             "y0_startable", "y1_startable")


@dataclass(frozen=True)
class ContractStudy:
    """Matched signers, the per-position summary, and what got dropped."""
    matched: pd.DataFrame
    summary: pd.DataFrame
    params: Dict[str, object]
    warnings: Tuple[str, ...] = ()
    unmatched: pd.DataFrame = field(default_factory=pd.DataFrame)

    def describe(self, outcomes: Sequence[str] = ("two_year_points",)) -> str:
        lines = [f"big contracts: top {self.params['top_n']} per position-year, "
                 f"{self.params['first_year']}-{self.params['last_year']}, "
                 f"{self.params['scoring']} scoring",
                 f"matched {len(self.matched)} signers to <= {self.params['k']} controls "
                 f"each (prior-season points within {self.params['caliper_sd']} sd"
                 + (f", age within {self.params['age_caliper']}y)"
                    if self.params["age_caliper"] is not None else ")")]
        sub = self.summary[self.summary["outcome"].isin(list(outcomes))]
        lines.append(sub.to_string(index=False))
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return "\n".join(lines)


def _sign_permutation_p(diffs: Sequence[float], permutations: int = PERMUTATIONS,
                        seed: int = 0) -> float:
    """Two-sided randomisation test for paired differences.

    Each signer is paired with his own controls, so the null is "the sign of the
    gap is a coin flip", not "the two cohorts are exchangeable". Deterministic
    for a given seed, like everything else in this repo that quotes a p-value.
    """
    import numpy as np

    d = np.asarray([x for x in diffs if x == x], dtype=float)
    if len(d) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    observed = abs(float(d.mean()))
    flips = rng.choice([-1.0, 1.0], size=(permutations, len(d)))
    means = (flips * d).mean(axis=1)
    hits = int((abs(means) >= observed - 1e-12).sum())
    return (hits + 1) / (permutations + 1)


def match_signers(signers: pd.DataFrame, pool: pd.DataFrame, k: int = MATCH_K,
                  caliper_sd: float = MATCH_CALIPER_SD,
                  age_caliper: Optional[float] = MATCH_AGE_CALIPER,
                  min_baseline_games: int = MIN_BASELINE_GAMES
                  ) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Pair every signer with the closest non-signers of the same position-season.

    Closest on prior-season points — the one number that already contains
    everything the market knew — inside a caliper of `caliper_sd` standard
    deviations of that position-season, and inside `age_caliper` years if given.
    A signer with nobody inside the caliper is dropped and reported, never
    matched to whoever happened to be nearest. Returns the matched signers, the
    dropped ones with the reason each fell out, and the warnings a caller should
    print — the drops are part of the answer, not tidy-up.
    """
    rows: List[Dict[str, object]] = []
    dropped: List[Dict[str, object]] = []
    for s in signers.itertuples():
        row_id = {"player": s.player, "position": s.position, "year": s.year,
                  "base_points": s.base_points, "base_games": s.base_games}
        if not (s.base_games == s.base_games) or s.base_games < min_baseline_games:
            dropped.append({**row_id, "reason": "no qualifying prior season"})
            continue
        same = pool[(pool["position"] == s.position) & (pool["year"] == s.year)
                    & (pool["gsis_id"] != s.gsis_id)]
        if same.empty:
            dropped.append({**row_id, "reason": "no controls that position-season"})
            continue
        sd = float(same["base_points"].std(ddof=1)) or 1.0
        near = same.assign(_dist=(same["base_points"] - s.base_points).abs())
        if age_caliper is not None and s.age == s.age:
            near = near[(near["age"] - s.age).abs() <= age_caliper]
        near = near[near["_dist"] <= caliper_sd * sd].nsmallest(k, "_dist")
        if near.empty:
            dropped.append({**row_id, "reason": "no control inside the caliper"})
            continue
        row: Dict[str, object] = {
            "player": s.player, "gsis_id": s.gsis_id, "position": s.position,
            "year": s.year, "rank_in_position_year": s.rank_in_position_year,
            "apy": s.apy, "apy_cap_pct": s.apy_cap_pct, "years": s.years,
            "guaranteed": s.guaranteed, "age": s.age,
            "base_points": s.base_points, "base_games": s.base_games,
            "base_ppg": s.base_ppg, "n_controls": len(near),
            "control_base_points": float(near["base_points"].mean()),
            "control_age": float(near["age"].mean()),
        }
        for outcome in OUTCOMES:
            row[outcome] = float(getattr(s, outcome))
            # A rate outcome (`ppg`) is NaN for a season nobody played, on both
            # sides: the control mean is over the controls who took the field,
            # and a signer who did not leaves that pair out of the rate test
            # rather than contributing a zero no game produced.
            row[f"control_{outcome}"] = float(near[outcome].mean())
            row[f"gap_{outcome}"] = row[outcome] - row[f"control_{outcome}"]
        rows.append(row)
    warnings = [f"{len(dropped)} of {len(signers)} signings unmatched: "
                + "; ".join(f"{reason} ({count})" for reason, count in
                            sorted(pd.Series([str(d["reason"]) for d in dropped])
                                   .value_counts().items()))] if dropped else []
    return pd.DataFrame(rows), pd.DataFrame(dropped), warnings


def summarise(matched: pd.DataFrame, outcomes: Sequence[str] = OUTCOMES,
              permutations: int = PERMUTATIONS, seed: int = 0) -> pd.DataFrame:
    """Per position and outcome: signer vs matched control, with FDR control.

    The q-value spans the whole table because this is a family of tests — four
    positions times every outcome asked for. Quoting one row's p-value alone
    would overstate it, the same rule the sweeps follow.
    """
    rows: List[Dict[str, object]] = []
    if matched.empty:      # every signer fell outside the caliper; say so, don't crash
        return pd.DataFrame(columns=["position", "outcome", "n", "signer", "control",
                                     "gap", "gap_sd", "p", "q"])
    for position in POSITIONS:
        sub = matched[matched["position"] == position]
        if sub.empty:
            continue
        for outcome in outcomes:
            gaps = pd.Series(sub[f"gap_{outcome}"].tolist()).dropna()
            rows.append({
                # n is the pairs the gap is actually computed from: a rate
                # outcome has no value for a season the player never played.
                "position": position, "outcome": outcome, "n": int(len(gaps)),
                "signer": round(float(sub[outcome].mean()), 2),
                "control": round(float(sub[f"control_{outcome}"].mean()), 2),
                "gap": round(float(gaps.mean()), 2),
                "gap_sd": round(float(gaps.std(ddof=1)), 2),
                "p": round(_sign_permutation_p(gaps.tolist(), permutations, seed), 4),
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["q"] = A.fdr_q_values(out["p"].tolist())
    return out


def study(top_n: int = BIG_CONTRACT_TOP_N, first_year: int = FIRST_SIGNING_YEAR,
          last_year: Optional[int] = None, positions: Sequence[str] = POSITIONS,
          scoring: str = "lotg", k: int = MATCH_K,
          caliper_sd: float = MATCH_CALIPER_SD,
          age_caliper: Optional[float] = MATCH_AGE_CALIPER,
          min_baseline_games: int = MIN_BASELINE_GAMES,
          control_exclude_top_n: int = CONTROL_EXCLUDE_TOP_N,
          min_years: Optional[float] = None, rank_from: int = 1,
          outcomes: Sequence[str] = OUTCOMES, permutations: int = PERMUTATIONS,
          seed: int = 0, panel: Optional[pd.DataFrame] = None,
          all_signings: Optional[pd.DataFrame] = None) -> ContractStudy:
    """Did the big contracts beat comparable players who did not get one?

    `last_year` defaults to the newest signing year with two complete seasons
    behind it, since the second outcome year has to exist to be measured.
    `rank_from`/`top_n` select a tier (`rank_from=6, top_n=10` is the second five
    deals at each position), and `min_years` drops one-year deals — franchise
    tags clear the money bar while meaning the opposite of a long-term bet.
    """
    if all_signings is None:
        all_signings = signings(first_year=first_year, positions=positions)
    if last_year is None:
        # Y+1 must be a completed season.
        last_year = int(min(all_signings["year_signed"].max(),
                            max(Q.completed_seasons()) - 1))
    span = range(first_year - 1, last_year + 2)
    if panel is None:
        panel = season_points(list(span), scoring=scoring)

    big = all_signings[(all_signings["rank_in_position_year"] >= rank_from)
                       & (all_signings["rank_in_position_year"] <= top_n)
                       & (all_signings["year_signed"] >= first_year)
                       & (all_signings["year_signed"] <= last_year)].copy()
    warnings: List[str] = []
    if min_years is not None:
        before = len(big)
        big = big[pd.to_numeric(big["years"], errors="coerce") >= min_years]
        warnings.append(f"min_years={min_years:g} dropped {before - len(big)} "
                        f"short deals (tags and prove-it years)")
    big = big.rename(columns={"year_signed": "year"})
    big = event_frame(big, panel, "gsis_id", "year")
    big["age"] = [age_in(g, int(y)) for g, y in zip(big["gsis_id"], big["year"])]

    pool = control_pool(panel, all_signings, exclude_top_n=control_exclude_top_n,
                        min_baseline_games=min_baseline_games)
    matched, unmatched, match_warnings = match_signers(
        big, pool, k=k, caliper_sd=caliper_sd, age_caliper=age_caliper,
        min_baseline_games=min_baseline_games)
    warnings.extend(match_warnings)
    summary = summarise(matched, outcomes=outcomes, permutations=permutations, seed=seed)
    params = {"top_n": top_n, "rank_from": rank_from, "first_year": first_year,
              "last_year": last_year, "scoring": scoring, "k": k,
              "caliper_sd": caliper_sd, "age_caliper": age_caliper,
              "min_baseline_games": min_baseline_games,
              "control_exclude_top_n": control_exclude_top_n,
              "min_years": min_years, "permutations": permutations, "seed": seed}
    return ContractStudy(matched=matched, summary=summary, params=params,
                         warnings=tuple(warnings), unmatched=unmatched)


def raw_before_after(top_n: int = BIG_CONTRACT_TOP_N,
                     first_year: int = FIRST_SIGNING_YEAR,
                     last_year: Optional[int] = None, scoring: str = "lotg",
                     panel: Optional[pd.DataFrame] = None,
                     all_signings: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Signers against *themselves* — no control group.

    This is the number everyone quotes and it is the misleading one: it is
    dominated by the fact that a big contract follows a career year. Reported so
    the write-up can show the gap between it and the matched answer.
    """
    if all_signings is None:
        all_signings = signings(first_year=first_year)
    if last_year is None:
        last_year = int(min(all_signings["year_signed"].max(),
                            max(Q.completed_seasons()) - 1))
    if panel is None:
        panel = season_points(list(range(first_year - 1, last_year + 2)), scoring=scoring)
    big = all_signings[(all_signings["rank_in_position_year"] <= top_n)
                       & (all_signings["year_signed"] >= first_year)
                       & (all_signings["year_signed"] <= last_year)].rename(
        columns={"year_signed": "year"})
    ev = event_frame(big, panel, "gsis_id", "year")
    ev = ev[ev["base_games"] >= MIN_BASELINE_GAMES]
    out = []
    for position in POSITIONS:
        s = ev[ev["position"] == position]
        if s.empty:
            continue
        out.append({
            "position": position, "n": len(s),
            "apy_cap_pct": round(float(s["apy_cap_pct"].mean()), 3),
            "prior_season": round(float(s["base_points"].mean()), 1),
            "year_Y": round(float(s["y0_points"].mean()), 1),
            "year_Y1": round(float(s["y1_points"].mean()), 1),
            "change_Y": round(float((s["y0_points"] - s["base_points"]).mean()), 1),
            "change_Y1": round(float((s["y1_points"] - s["base_points"]).mean()), 1),
            "improved_Y": round(float((s["y0_points"] > s["base_points"]).mean()), 3),
            "improved_Y1": round(float((s["y1_points"] > s["base_points"]).mean()), 3),
        })
    return pd.DataFrame(out)


def by_signing_year(matched: pd.DataFrame, outcome: str = "two_year_points"
                    ) -> pd.DataFrame:
    """The gap, one signing class at a time.

    Same rule as `analysis.compare`'s per-season breakdown: a pooled gap that
    exists in three signing years and reverses in the rest is a different claim
    from one that holds throughout, and the pooled mean cannot tell you which.
    """
    return matched.pivot_table(index="year", columns="position",
                               values=f"gap_{outcome}", aggfunc="mean").round(1)


def dose_response(matched: pd.DataFrame, edges: Sequence[int] = (2, 5, 10),
                  outcome: str = "two_year_points") -> pd.DataFrame:
    """Does a bigger deal carry more information? Gap by rank tier."""
    def tier(rank: float) -> str:
        low = 1
        for e in edges:
            if rank <= e:
                return f"{low}-{e}" if low != e else str(e)
            low = e + 1
        return f"{low}+"

    frame = matched.assign(tier=[tier(r) for r in matched["rank_in_position_year"]])
    return (frame.groupby(["position", "tier"])
            .agg(n=(f"gap_{outcome}", "size"),
                 apy_cap_pct=("apy_cap_pct", "mean"),
                 gap=(f"gap_{outcome}", "mean"))
            .round(2).reset_index())


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def check_scoring_reconciles(seasons: Optional[Sequence[int]] = None,
                             min_exact_rate: float = 0.70,
                             min_close_rate: float = 0.88,
                             tolerance: float = 1.0) -> List[str]:
    """Re-scored nflverse points must reproduce the build's own season totals.

    `player_year["Points (full season)"]` is the build's re-scoring of nflverse
    into league settings across every NFL game — so it is the independent number
    this module's panel has to agree with. Compared over the regular season *and*
    postseason, because that column spans both.

    It is not an identity: a residual sits on return specialists, whose return
    touchdowns the build scores from Sleeper's own keys and this reconstruction
    does not, so the guard asserts rates rather than equality.
    """
    if seasons is None:
        seasons = [y for y in Q.completed_seasons() if y >= 2020]
    problems: List[str] = []
    built = Q.load_sheet("player_year")
    for season in seasons:
        try:
            weekly = _weekly_stats(season)
        except Exception as e:  # pragma: no cover - network/cache dependent
            problems.append(f"{season}: no nflverse weekly stats ({e})")
            continue
        weekly = weekly[weekly["position"].isin(POSITIONS)].copy()
        weekly["_points"] = lotg_points(weekly)
        totals = weekly.groupby("player_display_name")["_points"].sum()
        rows = built[pd.to_numeric(built["Year"], errors="coerce") == season]
        deltas = []
        for name, value in zip(rows["Player"], rows["Points (full season)"]):
            want = Q.to_number(value)
            if want is None or name not in totals.index:
                continue
            deltas.append(abs(want - float(totals.loc[name])))
        if len(deltas) < 50:
            problems.append(f"{season}: only {len(deltas)} player-seasons joined")
            continue
        s = pd.Series(deltas)
        exact, close = float((s <= 0.01).mean()), float((s <= tolerance).mean())
        if exact < min_exact_rate or close < min_close_rate:
            problems.append(f"{season}: re-scored points match the build exactly for "
                            f"{exact:.1%} of {len(deltas)} player-seasons and within "
                            f"{tolerance:g} for {close:.1%} — below the guard")
    return problems


def check_contract_join(min_rate: float = 0.95, top_n: int = BIG_CONTRACT_TOP_N
                        ) -> List[str]:
    """Big signings must join to a real player-season, or the study is measuring gaps.

    A signer with no season row anywhere in the window is either a bad id join
    or a player who never took a snap; below `min_rate` the first is likely.
    """
    all_signings = signings()
    last = int(min(all_signings["year_signed"].max(), max(Q.completed_seasons()) - 1))
    panel = season_points(list(range(FIRST_SIGNING_YEAR - 1, last + 2)))
    seen = set(panel["player_id"])
    big = all_signings[(all_signings["rank_in_position_year"] <= top_n)
                       & (all_signings["year_signed"] <= last)]
    hit = [g in seen for g in big["gsis_id"]]
    rate = sum(hit) / len(hit) if hit else 1.0
    if rate < min_rate:
        missing = sorted(big[[not h for h in hit]]["player"])[:5]
        return [f"only {rate:.1%} of the top-{top_n} signings join to a season "
                f"({len(hit) - sum(hit)} missing, e.g. {missing})"]
    return []


def check_controls_are_balanced(tolerance: float = 5.0) -> List[str]:
    """Matched controls must start from the same place as the signers.

    The whole claim rests on the two sides being level at baseline; if the mean
    prior-season points differ by more than `tolerance`, the reported gap is
    partly just a better starting point.
    """
    result = study()
    problems: List[str] = []
    for position in POSITIONS:
        sub = result.matched[result.matched["position"] == position]
        if sub.empty:
            continue
        gap = float(sub["base_points"].mean() - sub["control_base_points"].mean())
        if abs(gap) > tolerance:
            problems.append(f"{position}: signers entered {gap:+.1f} points ahead of "
                            f"their matched controls — matching did not balance")
    return problems


def validate() -> List[str]:
    """Every guard. Empty means the contract layer reconciles with the build."""
    return check_scoring_reconciles() + check_contract_join() + check_controls_are_balanced()
