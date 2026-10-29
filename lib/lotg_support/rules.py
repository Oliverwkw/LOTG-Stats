"""Rule-change simulator: what would history look like under a different rule?

Before the league votes on a rule change, a commissioner wants to see every
completed season replayed under it — who would have won, who makes the
playoffs, which records fall, which positions gain or lose value — and the
current season's odds under it. This module answers that from the committed
exports. It is inquiry-only, like `replay` (whose League, standings rule and
Standing type it reuses): nothing in the build imports it and it writes nothing
outside the cache directory below.

    from lotg_support import rules as RC
    spec = RC.load_spec("plan/rule_specs/te_premium.json")
    print(RC.render(RC.simulate(spec)))

WHAT A SCENARIO CAN CHANGE (a `RuleSpec`; JSON on disk, composable)
-------------------------------------------------------------------
  scoring   `set` / `scale` / `add` any Sleeper scoring key — applied, in that
            order, to EACH SEASON'S OWN table (2020 = the ESPN league's), so
            "TE premium +0.5" adds 0.5 to whatever that year already had.
  lineup    `slots` replaces the starting template, `add` / `remove` edit it
            (QB RB WR TE FLEX WRRB_FLEX REC_FLEX SUPER_FLEX), again per season.
  playoffs  `teams` (any n; byes fill the bracket to a power of two — 6 teams
            = top 2 seeds bye), `byes` (checked against that), `home_bonus`
            (the +5) and `home_bonus_round` (semifinal / all / none),
            `median_game` (an extra W/L each regular-season week against the
            league median), `seeding` (record / points),
            `regular_season_weeks`, `two_week_final`.
Composing specs (`compose`) applies them in order: scoring changes compose as
per-key affine maps, lineup edits accumulate, playoff settings later-wins.

HOW EACH KIND IS SIMULATED
--------------------------
Scoring — a DELTA on top of the real points: each rostered player-week keeps
  Sleeper's (ESPN's in 2020) own points and moves by exactly what the changed
  keys are worth on his nflverse stat line (`lotg._LEAGUE_SCORE_MAP`, the
  build's own key -> stat map, through the build's persisted sleeper -> gsis
  bridge). An empty spec therefore reproduces reality to the cent, and the
  0.06% of player-weeks where nflverse and Sleeper disagree (stat corrections)
  cannot leak into the answer. Keys the build does not map but nflverse has
  (attempts, carries, targets, sacks, per-position reception bonuses) are in
  `EXTRA_KEYS`; anything else is refused by name.

Lineups — two variants, always both, because "who would the manager have
  started" cannot be observed:
    actual  — the manager's real starters, re-scored. When the template
              changes, a removed slot benches the starter the plausibility rule
              picks, and an added slot is filled from the bench under the
              league's `Wins added` rules (memory `wins-added-lineup-rules`):
              the filler is within 5 of the h-th best option's last-3-game
              average (h = slots to fill), anyone flagged bye/injured/suspended
              or with fewer than 3 prior NFL games (a rookie's first three) is
              never moved in, a bench filler counts for at most 1.5x his last-3
              average, and hindsight picks among the plausible options. A real
              empty slot stays empty — that was the manager's choice.
    optimal — every lineup is the roster's best under the template (the build's
              Max PF definition, position pins included). Compared against the
              optimal lineups under the REAL rules, never against reality, so
              the delta is the rule's effect alone.
Playoffs — the regular-season pairings are Sleeper's; the bracket is rebuilt
  from the new seeds, starting in the real playoff week unless the format needs
  more weeks than are left, when it starts earlier (a 6-team bracket in 2021
  starts in week 15 and the regular season loses a week — the report says so).

GUARDS (`validate`)
-------------------
An empty spec must reproduce every completed season's real records, PF,
playoff field and champion (`team_year` / `team_week`, an independent source),
and the optimal routine under the real template must reproduce `team_week.Max
PF`. `scripts/rulechange.py` runs both before answering.

CACHE
-----
The heavy input is `replay`'s League (every lineup since 2020 plus the
league-scored nflverse lines, 10-70 s to build). `load_league()` pickles it under
`.rules_cache/` (gitignored; `LOTG_RULES_CACHE` moves it) keyed by a
fingerprint of everything it is built from — team_week, the gsis bridge, the
nflverse stat files, every snapshot file — so a later run loads it in about a
second and a new build, or a new week, rebuilds it. The per-season stat frames
the scoring delta reads take ~2 s and stay in-process.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from lotg_support import inquiry as Q
from lotg_support import replay as R
from lotg_support.position_pins import max_pf_positions

WeekKey = Tuple[int, int]

#: Slot names a template may use, and who can fill them (Sleeper's own pools).
SLOT_POOLS: Dict[str, Tuple[str, ...]] = {k: v for k, v in Q._FLEX_POOL.items()
                                          if k not in ("K", "DEF")}

#: Sleeper scoring keys the build does not map, scored from nflverse columns.
EXTRA_KEYS: Dict[str, Tuple[str, ...]] = {
    "pass_cmp": ("completions",),
    "pass_att": ("attempts",),
    "rush_att": ("carries",),
    "rec_tgt": ("targets",),
    "pass_sack": ("sacks_suffered",),
}
#: Incompletions = attempts - completions.
DERIVED_KEYS = ("pass_inc",)
#: Reception bonuses that only apply to one position (the league's label).
POSITION_REC_BONUS: Dict[str, str] = {
    "bonus_rec_te": "TE", "bonus_rec_rb": "RB", "bonus_rec_wr": "WR", "bonus_rec_qb": "QB",
}

VARIANTS = ("actual", "optimal")
HOME_BONUS_ROUNDS = ("semifinal", "all", "none")
SEEDINGS = ("record", "points")
PLAUSIBLE_MARGIN = 5.0
CAP_MULTIPLIER = 1.5


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------
@dataclass
class RuleSpec:
    """One rule change (or several composed). Every field optional."""
    name: str = ""
    note: str = ""
    seasons: Tuple[int, ...] = ()
    #: key -> (a, b): new = a * old + b. set c = (0, c); scale m = (m, 0); add d = (1, d).
    scoring: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    slots: Tuple[str, ...] = ()               # full replacement of the template
    slots_add: Tuple[str, ...] = ()
    slots_remove: Tuple[str, ...] = ()
    playoff_teams: Optional[int] = None
    byes: Optional[int] = None
    home_bonus: Optional[float] = None
    home_bonus_round: Optional[str] = None
    median_game: Optional[bool] = None
    seeding: Optional[str] = None
    regular_season_weeks: Optional[int] = None
    two_week_final: Optional[bool] = None

    @property
    def changes_scoring(self) -> bool:
        return bool(self.scoring)

    @property
    def changes_lineup(self) -> bool:
        return bool(self.slots or self.slots_add or self.slots_remove)

    @property
    def changes_playoffs(self) -> bool:
        return any(v is not None for v in (
            self.playoff_teams, self.byes, self.home_bonus, self.home_bonus_round,
            self.median_game, self.seeding, self.regular_season_weeks, self.two_week_final))

    @property
    def is_empty(self) -> bool:
        return not (self.changes_scoring or self.changes_lineup or self.changes_playoffs)

    def describe(self) -> List[str]:
        out = []
        for key, (a, b) in sorted(self.scoring.items()):
            if a == 0:
                out.append(f"scoring {key} = {b:g}")
            elif b == 0:
                out.append(f"scoring {key} x {a:g}")
            elif a == 1:
                out.append(f"scoring {key} {b:+g}")
            else:
                out.append(f"scoring {key} x {a:g} {b:+g}")
        if self.slots:
            out.append(f"lineup = {' '.join(self.slots)}")
        if self.slots_add:
            out.append(f"lineup + {' '.join(self.slots_add)}")
        if self.slots_remove:
            out.append(f"lineup - {' '.join(self.slots_remove)}")
        for label, val in (("playoff teams", self.playoff_teams), ("byes", self.byes),
                           ("home bonus", self.home_bonus), ("home bonus round", self.home_bonus_round),
                           ("median game", self.median_game), ("seeding", self.seeding),
                           ("regular season weeks", self.regular_season_weeks),
                           ("two-week final", self.two_week_final)):
            if val is not None:
                out.append(f"{label} = {val}")
        return out or ["no change (the real rules)"]


_TOP_KEYS = {"name", "note", "seasons", "scoring", "lineup", "playoffs"}
_SCORING_OPS = ("set", "scale", "add")
_LINEUP_KEYS = {"slots", "add", "remove"}
_PLAYOFF_KEYS = {"teams", "byes", "home_bonus", "home_bonus_round", "median_game",
                 "seeding", "regular_season_weeks", "two_week_final"}


def _seasons_of(value: Any) -> Tuple[int, ...]:
    if value in (None, "", []):
        return ()
    if isinstance(value, (int, float)):
        return (int(value),)
    if isinstance(value, str):
        out: List[int] = []
        for part in value.replace(" ", "").split(","):
            if "-" in part:
                lo, hi = part.split("-", 1)
                out.extend(range(int(lo), int(hi) + 1))
            elif part:
                out.append(int(part))
        return tuple(sorted(set(out)))
    return tuple(sorted({int(v) for v in value}))


def _slot_list(value: Any) -> Tuple[str, ...]:
    if value in (None, ""):
        return ()
    items = value.replace(",", " ").split() if isinstance(value, str) else list(value)
    out = tuple(str(s).strip().upper() for s in items if str(s).strip())
    bad = [s for s in out if s not in SLOT_POOLS]
    if bad:
        raise ValueError(f"unknown lineup slot(s) {bad}; use {sorted(SLOT_POOLS)}")
    return out


def supported_scoring_keys() -> List[str]:
    score_map, bonus = _build_scoring()
    return sorted(set(score_map) | {b[0] for b in bonus} | set(EXTRA_KEYS)
                  | set(DERIVED_KEYS) | set(POSITION_REC_BONUS))


def spec_from_dict(blob: Dict[str, Any]) -> RuleSpec:
    """A RuleSpec from its JSON form. Unknown keys are refused (typo safety)."""
    unknown = set(blob) - _TOP_KEYS
    if unknown:
        raise ValueError(f"unknown spec key(s) {sorted(unknown)}; allowed {sorted(_TOP_KEYS)}")
    spec = RuleSpec(name=str(blob.get("name") or ""), note=str(blob.get("note") or ""),
                    seasons=_seasons_of(blob.get("seasons")))
    scoring = blob.get("scoring") or {}
    bad = set(scoring) - set(_SCORING_OPS)
    if bad:
        raise ValueError(f"unknown scoring op(s) {sorted(bad)}; use {list(_SCORING_OPS)}")
    known = set(supported_scoring_keys())
    for op in _SCORING_OPS:                       # within one spec: set, then scale, then add
        for key, val in (scoring.get(op) or {}).items():
            if key not in known:
                raise ValueError(f"scoring key {key!r} cannot be re-scored from nflverse stat "
                                 f"lines; supported: {', '.join(sorted(known))}")
            a, b = spec.scoring.get(key, (1.0, 0.0))
            v = float(val)
            spec.scoring[key] = {"set": (0.0, v), "scale": (a * v, b * v), "add": (a, b + v)}[op]
    lineup = blob.get("lineup") or {}
    bad = set(lineup) - _LINEUP_KEYS
    if bad:
        raise ValueError(f"unknown lineup key(s) {sorted(bad)}; use {sorted(_LINEUP_KEYS)}")
    spec.slots = _slot_list(lineup.get("slots"))
    spec.slots_add = _slot_list(lineup.get("add"))
    spec.slots_remove = _slot_list(lineup.get("remove"))
    po = blob.get("playoffs") or {}
    bad = set(po) - _PLAYOFF_KEYS
    if bad:
        raise ValueError(f"unknown playoffs key(s) {sorted(bad)}; use {sorted(_PLAYOFF_KEYS)}")
    if po.get("teams") is not None:
        spec.playoff_teams = int(po["teams"])
        if not 2 <= spec.playoff_teams <= 8:
            raise ValueError("playoffs.teams must be between 2 and 8 (an 8-team league)")
    if po.get("byes") is not None:
        spec.byes = int(po["byes"])
    if po.get("home_bonus") is not None:
        spec.home_bonus = float(po["home_bonus"])
    if po.get("home_bonus_round") is not None:
        spec.home_bonus_round = str(po["home_bonus_round"])
        if spec.home_bonus_round not in HOME_BONUS_ROUNDS:
            raise ValueError(f"home_bonus_round must be one of {HOME_BONUS_ROUNDS}")
    if po.get("median_game") is not None:
        spec.median_game = bool(po["median_game"])
    if po.get("seeding") is not None:
        spec.seeding = str(po["seeding"])
        if spec.seeding not in SEEDINGS:
            raise ValueError(f"seeding must be one of {SEEDINGS}")
    if po.get("regular_season_weeks") is not None:
        spec.regular_season_weeks = int(po["regular_season_weeks"])
    if po.get("two_week_final") is not None:
        spec.two_week_final = bool(po["two_week_final"])
    return spec


def spec_to_dict(spec: RuleSpec) -> Dict[str, Any]:
    """The JSON form; `spec_from_dict(spec_to_dict(s))` round-trips."""
    out: Dict[str, Any] = {}
    if spec.name:
        out["name"] = spec.name
    if spec.note:
        out["note"] = spec.note
    if spec.seasons:
        out["seasons"] = list(spec.seasons)
    if spec.scoring:
        sc: Dict[str, Dict[str, float]] = {}
        for key, (a, b) in sorted(spec.scoring.items()):
            if a == 0:
                sc.setdefault("set", {})[key] = b
            else:
                if a != 1:
                    sc.setdefault("scale", {})[key] = a
                if b != 0:
                    sc.setdefault("add", {})[key] = b
        out["scoring"] = sc
    lineup = {k: list(v) for k, v in (("slots", spec.slots), ("add", spec.slots_add),
                                      ("remove", spec.slots_remove)) if v}
    if lineup:
        out["lineup"] = lineup
    po = {k: v for k, v in (("teams", spec.playoff_teams), ("byes", spec.byes),
                            ("home_bonus", spec.home_bonus),
                            ("home_bonus_round", spec.home_bonus_round),
                            ("median_game", spec.median_game), ("seeding", spec.seeding),
                            ("regular_season_weeks", spec.regular_season_weeks),
                            ("two_week_final", spec.two_week_final)) if v is not None}
    if po:
        out["playoffs"] = po
    return out


def load_spec(path: Any) -> RuleSpec:
    spec = spec_from_dict(json.loads(Path(path).read_text()))
    if not spec.name:
        spec.name = Path(path).stem
    return spec


def save_spec(spec: RuleSpec, path: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec_to_dict(spec), indent=2) + "\n")
    return path


def compose(*specs: RuleSpec, name: str = "") -> RuleSpec:
    """Apply specs in order. Scoring composes as affine maps per key (a later
    `set` wins, a later `add` stacks); lineup edits accumulate (a later full
    `slots` restarts them); playoff settings and seasons are later-wins."""
    out = RuleSpec()
    names = []
    for s in specs:
        if s.name:
            names.append(s.name)
        for key, (a2, b2) in s.scoring.items():
            a1, b1 = out.scoring.get(key, (1.0, 0.0))
            out.scoring[key] = (a2 * a1, a2 * b1 + b2)
        if s.slots:
            out.slots, out.slots_add, out.slots_remove = s.slots, (), ()
        out.slots_add += s.slots_add
        out.slots_remove += s.slots_remove
        for attr in ("playoff_teams", "byes", "home_bonus", "home_bonus_round", "median_game",
                     "seeding", "regular_season_weeks", "two_week_final"):
            if getattr(s, attr) is not None:
                setattr(out, attr, getattr(s, attr))
        if s.seasons:
            out.seasons = s.seasons
        if s.note:
            out.note = (out.note + " " + s.note).strip()
    out.scoring = {k: v for k, v in out.scoring.items() if v != (1.0, 0.0)}
    out.name = name or " + ".join(names)
    return out


# ---------------------------------------------------------------------------
# Per-season rules: real and scenario
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Format:
    """Everything that decides a season's table and bracket."""
    playoff_teams: int
    regular_season_weeks: int
    playoff_weeks: Tuple[Tuple[int, ...], ...]     # one tuple of weeks per round, final last
    home_bonus: float = Q.SEMIFINAL_HOME_BONUS
    home_bonus_round: str = "semifinal"
    median_game: bool = False
    seeding: str = "record"

    @property
    def bracket_size(self) -> int:
        return 1 << max(1, math.ceil(math.log2(max(2, self.playoff_teams))))

    @property
    def byes(self) -> int:
        return self.bracket_size - self.playoff_teams

    @property
    def last_week(self) -> int:
        return self.playoff_weeks[-1][-1] if self.playoff_weeks else self.regular_season_weeks

    def describe(self) -> str:
        rounds = " / ".join("wk " + "+".join(map(str, w)) for w in self.playoff_weeks)
        bits = [f"{self.playoff_teams} teams" + (f" ({self.byes} byes)" if self.byes else ""),
                f"{self.regular_season_weeks}-week regular season", f"rounds {rounds}"]
        if self.home_bonus and self.home_bonus_round != "none":
            bits.append(f"+{self.home_bonus:g} higher seed ({self.home_bonus_round})")
        else:
            bits.append("no home bonus")
        if self.median_game:
            bits.append("median game")
        if self.seeding != "record":
            bits.append(f"seeded by {self.seeding}")
        return ", ".join(bits)


def _season_last_week(season: int) -> int:
    return 16 if season <= 2020 else Q.season_meta(season).last_week


def real_format(season: int) -> Format:
    """The league's actual format that season (2020: 14 + semis 15 + final 16)."""
    meta = Q.season_meta(season)
    last = _season_last_week(season)
    start = meta.playoff_week_start if meta.has_snapshot else 15
    teams = meta.playoff_teams if meta.has_snapshot else 4
    rounds = max(1, math.ceil(math.log2(teams)))
    weeks = list(range(start, last + 1))
    per_round = [(w,) for w in weeks[:rounds - 1]] + [tuple(weeks[rounds - 1:])]
    return Format(playoff_teams=teams, regular_season_weeks=start - 1, playoff_weeks=tuple(per_round))


def scenario_format(season: int, spec: RuleSpec, warnings: Optional[List[str]] = None) -> Format:
    real = real_format(season)
    warnings = warnings if warnings is not None else []
    teams = spec.playoff_teams or real.playoff_teams
    rounds = max(1, math.ceil(math.log2(teams)))
    real_final_len = len(real.playoff_weeks[-1])
    final_len = real_final_len if spec.two_week_final is None else (2 if spec.two_week_final else 1)
    needed = rounds - 1 + final_len
    last = real.last_week
    if spec.regular_season_weeks is not None:
        reg = int(spec.regular_season_weeks)
        if reg + needed > last:
            raise ValueError(f"{season}: a {reg}-week regular season plus {needed} playoff "
                             f"week(s) runs past week {last}, the season's last scored week")
        if reg > real.regular_season_weeks:
            warnings.append(f"{season}: weeks {real.regular_season_weeks + 1}-{reg} become regular "
                            "season, but their pairings were playoff/consolation games")
    else:
        # keep the real playoff start; move it earlier only if the bracket
        # would not finish by the season's last scored week
        reg = min(real.regular_season_weeks, last - needed)
    if reg < 1:
        raise ValueError(f"{season}: no regular season left for that bracket")
    if reg != real.regular_season_weeks:
        warnings.append(f"{season}: regular season {real.regular_season_weeks} -> {reg} weeks"
                        + ("" if spec.regular_season_weeks is not None
                           else f" so the bracket fits by week {last}"))
    if reg + needed < last:
        warnings.append(f"{season}: the bracket ends in week {reg + needed}; week(s) "
                        f"{reg + needed + 1}-{last} are not played")
    weeks = list(range(reg + 1, reg + needed + 1))
    per_round = [(w,) for w in weeks[:rounds - 1]] + [tuple(weeks[rounds - 1:])]
    fmt = Format(
        playoff_teams=teams, regular_season_weeks=reg, playoff_weeks=tuple(per_round),
        home_bonus=real.home_bonus if spec.home_bonus is None else spec.home_bonus,
        home_bonus_round=spec.home_bonus_round or real.home_bonus_round,
        median_game=bool(spec.median_game) if spec.median_game is not None else real.median_game,
        seeding=spec.seeding or real.seeding)
    if spec.byes is not None and spec.byes != fmt.byes:
        raise ValueError(f"{teams} playoff teams gives {fmt.byes} bye(s), not {spec.byes} "
                         f"(a single-elimination bracket fills to {fmt.bracket_size})")
    return fmt


@functools.lru_cache(maxsize=None)
def _espn_slot_names() -> Tuple[str, ...]:
    from lotg_support import wins_added as W
    return tuple(p for p in W._espn_2020()["league"]["roster_positions"] if p not in ("BN", "IR", "TAXI"))


def real_slot_names(season: int) -> Tuple[str, ...]:
    if season <= 2020:
        return _espn_slot_names()
    return tuple(p for p in Q.season_meta(season).roster_positions if p not in ("BN", "IR", "TAXI"))


def scenario_slot_names(season: int, spec: RuleSpec) -> Tuple[str, ...]:
    names = list(spec.slots or real_slot_names(season))
    names.extend(spec.slots_add)
    for slot in spec.slots_remove:
        if slot not in names:
            raise ValueError(f"{season}: cannot remove {slot}; that season's lineup is "
                             f"{' '.join(names)}")
        # remove the last one (a second FLEX before the first)
        idx = len(names) - 1 - names[::-1].index(slot)
        names.pop(idx)
    if not names:
        raise ValueError(f"{season}: the lineup would have no starters")
    order = list(SLOT_POOLS)
    return tuple(sorted(names, key=order.index))


def pools(names: Sequence[str]) -> Tuple[Tuple[str, ...], ...]:
    return tuple(SLOT_POOLS[n] for n in names)


# ---------------------------------------------------------------------------
# Scoring: the delta on top of the real points
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _build_scoring():
    """The build's key -> nflverse columns map and threshold bonuses."""
    from lotg_support import wins_added as W
    W._src_on_path()
    import lotg  # noqa: E402
    return lotg._LEAGUE_SCORE_MAP, lotg._LEAGUE_SCORE_BONUS


@functools.lru_cache(maxsize=None)
def scoring_table(season: int) -> Dict[str, float]:
    """The league's scoring settings for `season` (2020: the ESPN league's)."""
    from lotg_support import boldness as B
    return dict(B.scoring_table(int(season)))


def scenario_table(season: int, spec: RuleSpec) -> Dict[str, float]:
    table = dict(scoring_table(season))
    for key, (a, b) in spec.scoring.items():
        table[key] = a * float(table.get(key, 0.0)) + b
    return table


def _columns_for(key: str) -> Tuple[str, ...]:
    score_map, bonus = _build_scoring()
    if key in score_map:
        return tuple(score_map[key])
    if key in EXTRA_KEYS:
        return EXTRA_KEYS[key]
    if key == "pass_inc":
        return ("attempts", "completions")
    if key in POSITION_REC_BONUS:
        return ("receptions",)
    for bkey, col, _ in bonus:
        if bkey == key:
            return (col,)
    raise KeyError(key)


@functools.lru_cache(maxsize=16)
def _stat_frame(season: int, columns: Tuple[str, ...]) -> pd.DataFrame:
    """nflverse regular-season stat lines for `season`, summed per (gsis, week),
    the struck 2022 game restored, only `columns`."""
    from lotg_support import scoring_events as SE
    from lotg_support.struck_games import add_struck_stat_rows
    df = add_struck_stat_rows(SE.weekly_stats(season), season)
    cols = [c for c in columns if c in df.columns]
    out = df[["player_id", "week"] + cols].copy()
    out["player_id"] = out["player_id"].astype(str)
    out["week"] = pd.to_numeric(out["week"], errors="coerce")
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    for c in columns:
        if c not in out.columns:
            out[c] = 0.0
    out = out.dropna(subset=["week"])
    out["week"] = out["week"].astype(int)
    return out.groupby(["player_id", "week"], as_index=False)[list(columns)].sum()


@functools.lru_cache(maxsize=None)
def _bridge() -> Dict[str, str]:
    from lotg_support import wins_added as W
    return {str(k): str(v) for k, v in W.load_gsis_bridge().items()
            if v is not None and str(v).lower() != "nan"}


def score_deltas(season: int, spec: RuleSpec) -> Dict[Tuple[str, int], float]:
    """{(sleeper id, week): new points - real points} for every player with an
    nflverse stat line that season (0.0 included, so a missing key means no
    stat line). Linear in the changed keys, so exact."""
    old = scoring_table(season)
    new = scenario_table(season, spec)
    changed = {k: new.get(k, 0.0) - float(old.get(k, 0.0)) for k in spec.scoring}
    changed = {k: d for k, d in changed.items() if abs(d) > 1e-12}
    if not changed:
        return {}
    _, bonus = _build_scoring()
    thresholds = {bkey: (col, thr) for bkey, col, thr in bonus}
    cols = tuple(sorted({c for k in changed for c in _columns_for(k)}))
    frame = _stat_frame(season, cols)
    gsis_to_sids: Dict[str, List[str]] = defaultdict(list)
    for sid, g in _bridge().items():
        gsis_to_sids[g].append(sid)
    positions = Q.players().positions()
    pos = frame["player_id"].map(lambda g: positions.get(gsis_to_sids.get(g, [""])[0], ""))
    delta = np.zeros(len(frame))
    for key, d in changed.items():
        if key in POSITION_REC_BONUS:
            delta += d * frame["receptions"].to_numpy() * (pos == POSITION_REC_BONUS[key]).to_numpy()
        elif key == "pass_inc":
            delta += d * (frame["attempts"] - frame["completions"]).to_numpy()
        elif key in thresholds:
            col, thr = thresholds[key]
            delta += d * (frame[col].to_numpy() >= thr)
        else:
            delta += d * frame[list(_columns_for(key))].sum(axis=1).to_numpy()
    out: Dict[Tuple[str, int], float] = {}
    for g, wk, dv in zip(frame["player_id"], frame["week"], delta):
        for sid in gsis_to_sids.get(g, ()):
            out[(sid, int(wk))] = float(dv)
    if any(k in POSITION_REC_BONUS for k in changed):
        # A shared gsis id is scored under the first sid's position above;
        # recompute per sid so each takes his own label.
        for key, d in changed.items():
            if key not in POSITION_REC_BONUS:
                continue
            want = POSITION_REC_BONUS[key]
            for g, wk, rec in zip(frame["player_id"], frame["week"], frame["receptions"]):
                sids = gsis_to_sids.get(g, ())
                if len(sids) < 2 or not rec:
                    continue
                first = positions.get(sids[0], "") == want
                for sid in sids:
                    own = positions.get(sid, "") == want
                    if own != first:
                        out[(sid, int(wk))] = out.get((sid, int(wk)), 0.0) + d * rec * (own - first)
    return out


# ---------------------------------------------------------------------------
# Lineups
# ---------------------------------------------------------------------------
def _fits(pos: frozenset, pool: Tuple[str, ...]) -> bool:
    if "_FLEX_" in pos:          # unknown position: flex-eligible, as Max PF treats it
        return len(pool) >= 3
    return bool(pos & set(pool))


class _Matcher:
    """Incremental bipartite matching of players to slots."""

    def __init__(self, slots: Sequence[Tuple[str, ...]], elig: Callable[[str], frozenset]):
        self.slots = list(slots)
        self.elig = elig
        self.match: Dict[int, str] = {}

    def _augment(self, pid: str, seen: Set[int]) -> bool:
        pos = self.elig(pid)
        for idx, pool in enumerate(self.slots):
            if idx in seen or not _fits(pos, pool):
                continue
            seen.add(idx)
            if idx not in self.match or self._augment(self.match[idx], seen):
                self.match[idx] = pid
                return True
        return False

    def add(self, pid: str) -> bool:
        before = dict(self.match)
        if self._augment(pid, set()):
            return True
        self.match = before
        return False

    @property
    def full(self) -> bool:
        return len(self.match) == len(self.slots)

    def players(self) -> List[str]:
        return list(self.match.values())


def best_lineup(points: Dict[str, float], elig: Callable[[str], frozenset],
                slots: Sequence[Tuple[str, ...]]) -> Tuple[float, List[str]]:
    """The roster's best lineup: matroid greedy (best player first, kept if the
    set still fits the slots) is exact for a transversal matroid, any template."""
    m = _Matcher(slots, elig)
    for pid in sorted(points, key=lambda p: (-points[p], p)):
        if m.full:
            break
        m.add(pid)
    chosen = m.players()
    return round(sum(points[p] for p in chosen), 2), chosen


def _max_pf_elig(season: int) -> Callable[[str], frozenset]:
    positions = Q.players().positions()

    def elig(pid: str) -> frozenset:
        pinned = max_pf_positions(pid, season)
        if pinned:
            return frozenset(pinned)
        pos = (positions.get(str(pid)) or "").upper()
        return frozenset({pos}) if pos in ("QB", "RB", "WR", "TE") else frozenset({"_FLEX_"})
    return elig


def _lineup_elig(league, season: int) -> Callable[[str], frozenset]:
    learned = league.eligibility.get(season, {})
    fallback = _max_pf_elig(season)

    def elig(pid: str) -> frozenset:
        e = learned.get(pid)
        return frozenset(e) if e else fallback(pid)
    return elig


def adapt_lineup(real_starters: Sequence[str], real_empty: int, roster: Iterable[str],
                 points: Dict[str, float], elig: Callable[[str], frozenset],
                 slots: Sequence[Tuple[str, ...]], recent: Callable[[str], Optional[float]],
                 out: Set[str]) -> Tuple[float, List[str], List[str], List[str]]:
    """The manager's real lineup carried into a new template.

    Returns (points, lineup, benched starters, bench fillers). A removed slot
    first absorbs a real empty slot, then benches a starter: among starters
    whose removal still leaves a legal lineup, those within 5 of the weakest
    last-3 form, the one who scored least (hindsight among the plausible). An
    added slot is filled from the bench by the `Wins added` fill rule."""
    keep = [p for p in real_starters]
    empty = real_empty
    benched: List[str] = []

    def fits(players: Sequence[str]) -> bool:
        m = _Matcher(slots, elig)
        return all(m.add(p) for p in players)

    while len(keep) + empty > len(slots) and empty:
        empty -= 1
    while len(keep) > len(slots) - empty or not fits(keep):
        cands = [p for p in keep if fits([q for q in keep if q != p])] or list(keep)
        form = {p: recent(p) for p in cands}
        floor = min((v for v in form.values() if v is not None), default=None)
        plausible = [p for p in cands if floor is None or form[p] is None
                     or form[p] <= floor + PLAUSIBLE_MARGIN] or cands
        drop = min(plausible, key=lambda p: (points.get(p, 0.0), p))
        keep.remove(drop)
        benched.append(drop)

    free = len(slots) - empty - len(keep)
    fillers: List[str] = []
    total = sum(points.get(p, 0.0) for p in keep)
    if free > 0:
        m = _Matcher(slots, elig)
        for p in keep:
            m.add(p)
        taken = set(keep)
        bench = [p for p in roster if p not in taken and p not in real_starters and p not in out]

        def can_fill(p: str) -> bool:
            trial = _Matcher(slots, elig)
            trial.match = dict(m.match)
            return trial.add(p)

        options = [p for p in bench if recent(p) is not None and can_fill(p)]
        ranked = sorted(options, key=lambda p: -recent(p))
        bar = (recent(ranked[min(free, len(ranked)) - 1]) - PLAUSIBLE_MARGIN) if ranked else 0.0

        def counted(p: str) -> float:
            cap = CAP_MULTIPLIER * recent(p)
            return min(points.get(p, 0.0), max(cap, 0.0))

        plausible = [p for p in options if recent(p) >= bar]
        rest = [p for p in options if p not in plausible]
        for pool in (plausible, rest):
            for p in sorted(pool, key=lambda q: (-counted(q), q)):
                if len(fillers) >= free:
                    break
                if m.add(p):
                    fillers.append(p)
        total += sum(counted(p) for p in fillers)
    return round(total, 2), keep + fillers, benched, fillers


# ---------------------------------------------------------------------------
# Standings and bracket (any ids: team names here, roster ids in the forecast)
# ---------------------------------------------------------------------------
def standings(scores: Dict[int, Dict[Any, float]], pairs: Dict[int, List[Tuple[Any, Any]]],
              names: Dict[Any, str], fmt: Format) -> List[R.Standing]:
    """The regular-season table under `fmt`: head-to-head (plus a game against
    the week's median when on), seeded by W + 0.5·T then PF — `replay`'s rule —
    or by PF first when seeding is `points`."""
    tally = {k: [0, 0, 0, 0.0] for k in names}
    for wk in range(1, fmt.regular_season_weeks + 1):
        if wk not in scores:
            continue
        week = scores[wk]
        for a, b in pairs.get(wk, ()):
            pa, pb = week.get(a, 0.0), week.get(b, 0.0)
            tally[a][3] += pa
            tally[b][3] += pb
            if pa > pb:
                tally[a][0] += 1
                tally[b][1] += 1
            elif pb > pa:
                tally[b][0] += 1
                tally[a][1] += 1
            else:
                tally[a][2] += 1
                tally[b][2] += 1
        if fmt.median_game and week:
            med = float(np.median([week.get(k, 0.0) for k in names]))
            for k in names:
                v = week.get(k, 0.0)
                tally[k][0 if v > med else 1 if v < med else 2] += 1
    table = [R.Standing(k, names.get(k, str(k)), w, l, t, round(pf, 2))
             for k, (w, l, t, pf) in tally.items()]
    if fmt.seeding == "points":
        table.sort(key=lambda s: (-s.points_for, -s.sort_key[0], s.team))
    else:
        table.sort(key=lambda s: (-s.sort_key[0], -s.sort_key[1], s.team))
    return table


def _bracket_order(size: int) -> List[int]:
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [x for s in order for x in (s, n + 1 - s)]
    return order


@dataclass
class Game:
    round: int
    weeks: Tuple[int, ...]
    high: str
    high_pts: float
    low: str
    low_pts: float
    winner: str


@dataclass
class BracketResult:
    seeds: List[str] = field(default_factory=list)
    games: List[Game] = field(default_factory=list)
    champion: str = ""
    runner_up: str = ""
    finalists: Tuple[str, ...] = ()
    complete: bool = False

    @property
    def field(self) -> List[str]:
        return list(self.seeds)


def bracket(scores: Dict[int, Dict[Any, float]], table: Sequence[R.Standing],
            names: Dict[Any, str], fmt: Format) -> BracketResult:
    """Single elimination, fixed bracket (no reseeding), byes to the top seeds,
    ties to the higher seed, the home bonus to the higher seed in the rounds
    `fmt.home_bonus_round` names. Incomplete while any round's weeks are unplayed."""
    ids = [s.roster_id for s in table[:fmt.playoff_teams]]
    out = BracketResult(seeds=[names.get(i, str(i)) for i in ids])
    if len(ids) < fmt.playoff_teams:
        return out
    seed_of = {i: n + 1 for n, i in enumerate(ids)}
    slots: List[Optional[Any]] = [ids[s - 1] if s <= len(ids) else None
                                  for s in _bracket_order(fmt.bracket_size)]
    rounds = len(fmt.playoff_weeks)
    for r, weeks in enumerate(fmt.playoff_weeks):
        if any(w not in scores for w in weeks):
            return out
        final = r == rounds - 1
        bonus_here = fmt.home_bonus_round == "all" or (
            fmt.home_bonus_round == "semifinal" and r == rounds - 2)
        nxt: List[Optional[Any]] = []
        for a, b in zip(slots[0::2], slots[1::2]):
            if a is None or b is None:
                nxt.append(a if b is None else b)
                continue
            high, low = (a, b) if seed_of[a] < seed_of[b] else (b, a)
            ph = sum(scores[w].get(high, 0.0) for w in weeks)
            pl = sum(scores[w].get(low, 0.0) for w in weeks)
            if bonus_here:
                ph += fmt.home_bonus
            ph, pl = round(ph, 2), round(pl, 2)
            win = high if ph >= pl else low
            out.games.append(Game(r + 1, tuple(weeks), names.get(high, str(high)), ph,
                                  names.get(low, str(low)), pl, names.get(win, str(win))))
            if final:
                out.champion = names.get(win, str(win))
                out.runner_up = names.get(low if win == high else high, "")
                out.finalists = (names.get(high, ""), names.get(low, ""))
            nxt.append(win)
        slots = nxt
    out.complete = bool(out.champion)
    return out


# ---------------------------------------------------------------------------
# A season, replayed
# ---------------------------------------------------------------------------
@dataclass
class Outcome:
    scores: Dict[int, Dict[str, float]]
    table: List[R.Standing]
    bracket: BracketResult
    fmt: Format

    def record(self, team: str) -> R.Standing:
        return next(s for s in self.table if s.team == team)


@dataclass
class SeasonRun:
    season: int
    teams: List[str]
    pairs: Dict[int, List[Tuple[str, str]]]
    real_slots: Tuple[str, ...]
    slots: Tuple[str, ...]
    #: variant -> (baseline, scenario). actual: reality vs scenario with the
    #: managers' lineups; optimal: best lineups under the real rules vs under
    #: the scenario's.
    outcomes: Dict[str, Tuple[Outcome, Outcome]]
    #: (week, team) -> (real starters, scenario lineup) for the actual variant
    lineups: Dict[Tuple[int, str], Tuple[List[str], List[str]]]
    #: position -> [starter points real, scenario, starts real, scenario, optimal starts real, scenario]
    positions: Dict[str, List[float]]
    #: (pid) -> [real points, scenario points] over rostered weeks
    player_totals: Dict[str, List[float]]
    benched: int = 0
    filled: int = 0
    no_stat_line: int = 0
    complete: bool = True
    warnings: List[str] = field(default_factory=list)


CACHE_VERSION = 1


def cache_dir() -> Path:
    return Path(os.environ.get("LOTG_RULES_CACHE") or (Q.repo_root() / ".rules_cache"))


def _fingerprint() -> str:
    """Everything the League is built from: content of team_week and the
    bridge, size + mtime of every nflverse stat file and snapshot file."""
    root = Q.repo_root()
    h = hashlib.sha256(f"v{CACHE_VERSION}".encode())
    for rel in ("exports/team_week.csv", "exports/raw/wins_added_gsis_bridge.csv"):
        path = root / rel
        h.update(rel.encode())
        if path.exists():
            h.update(path.read_bytes())
    files = sorted((root / ".cache").glob("nflverse_stats_player_week_*.csv"))
    files += sorted((root / "exports" / "snapshot").rglob("*.json"))
    files += sorted((root / "data").glob("*.csv"))
    for path in files:
        st = path.stat()
        h.update(f"{path.relative_to(root)}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:20]


_MEMO: Dict[str, Any] = {}


def load_league():
    """`replay`'s League, through the on-disk cache (see the module docstring);
    once per process and repo root."""
    root = str(Q.repo_root())
    if root not in _MEMO:
        _MEMO[root] = _load_league_uncached()
    return _MEMO[root]


def _load_league_uncached():
    try:
        key = _fingerprint()
    except OSError:
        return R._league()
    path = cache_dir() / f"league_{key}.pkl"
    if path.exists():
        try:
            with path.open("rb") as fh:
                return pickle.load(fh)
        except Exception:
            pass
    built = R._league()
    if built is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            for old in path.parent.glob("league_*.pkl"):
                old.unlink()
            tmp = path.with_suffix(".tmp")
            with tmp.open("wb") as fh:
                pickle.dump(built, fh, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(path)
        except OSError:
            pass
    return built


def _season_keys(league, season: int) -> List[WeekKey]:
    return [k for k in league.order if k[0] == season]


def run_season(season: int, spec: RuleSpec, league=None) -> SeasonRun:
    league = league or load_league()
    if league is None:
        raise FileNotFoundError("exports/team_week.csv and the snapshot are needed")
    keys = _season_keys(league, season)
    if not keys:
        raise LookupError(f"no {season} weeks in the exports")
    warnings: List[str] = []
    real_fmt = real_format(season)
    fmt = scenario_format(season, spec, warnings)
    real_names = real_slot_names(season)
    names = scenario_slot_names(season, spec)
    real_pools, new_pools = pools(real_names), pools(names)
    if tuple(league.slots.get(season, ())) != real_pools:
        warnings.append(f"{season}: the League's template {league.slots.get(season)} differs "
                        f"from the league settings {real_pools}")
    template_changed = tuple(sorted(real_names)) != tuple(sorted(names))
    deltas = score_deltas(season, spec)
    positions = Q.players().positions()
    elig_actual = _lineup_elig(league, season)
    elig_opt = _max_pf_elig(season)
    out_flags: Set[Tuple[str, int]] = set()
    if template_changed:          # only an added slot needs them (~5 s a season)
        try:
            out_flags = Q.unavailable(season)
        except Exception:
            warnings.append(f"{season}: no bye/injury flags — bench fills may pick an absent player")

    teams = sorted({t for k in keys for t in league.weeks[k]})
    pairs: Dict[int, List[Tuple[str, str]]] = {}
    sc: Dict[str, Dict[int, Dict[str, float]]] = {
        "real": {}, "actual": {}, "opt_real": {}, "optimal": {}}
    lineups: Dict[Tuple[int, str], Tuple[List[str], List[str]]] = {}
    pos_acc: Dict[str, List[float]] = defaultdict(lambda: [0.0] * 6)
    player_totals: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0])
    benched = filled = no_line = 0

    for key in keys:
        wk = key[1]
        teams_wk = league.weeks[key]
        pts_real = league.points_by_week.get(key, {})
        pts_new = {p: round(v + deltas.get((p, wk), 0.0), 2) for p, v in pts_real.items()}
        for name in sc:
            sc[name][wk] = {}
        seen = set()
        for team, tw in teams_wk.items():
            if tw.opponent:
                pair = tuple(sorted((team, tw.opponent)))
                if pair not in seen:
                    seen.add(pair)
                    pairs.setdefault(wk, []).append(pair)
            roster = sorted(tw.players)
            starters = list(tw.starters)
            raw = round(tw.pf - tw.offset, 2)
            sc["real"][wk][team] = raw
            for p in roster:
                player_totals[p][0] += pts_real.get(p, 0.0)
                player_totals[p][1] += pts_new.get(p, 0.0)
                if spec.changes_scoring and pts_real.get(p, 0.0) and (p, wk) not in deltas \
                        and p in starters:
                    no_line += 1
            if template_changed:
                empty = len(real_pools) - len(starters)
                total, lineup, bn, fl = adapt_lineup(
                    starters, empty, roster, pts_new, elig_actual, new_pools,
                    lambda p, k=key: league.recent_avg(p, k), {p for p in roster if (p, wk) in out_flags})
                benched += len(bn)
                filled += len(fl)
            else:
                lineup = starters
                total = round(sum(pts_new.get(p, 0.0) for p in lineup), 2)
            sc["actual"][wk][team] = total
            lineups[(wk, team)] = (starters, lineup)
            pool_real = {p: pts_real.get(p, 0.0) for p in roster}
            pool_new = {p: pts_new.get(p, 0.0) for p in roster}
            opt_r, chosen_r = best_lineup(pool_real, elig_opt, real_pools)
            opt_n, chosen_n = (best_lineup(pool_new, elig_opt, new_pools)
                               if (template_changed or deltas) else (opt_r, chosen_r))
            sc["opt_real"][wk][team] = opt_r
            sc["optimal"][wk][team] = opt_n
            if wk <= real_fmt.regular_season_weeks:
                for p in starters:
                    acc = pos_acc[positions.get(p, "?")]
                    acc[0] += pts_real.get(p, 0.0)
                    acc[2] += 1
                for p in lineup:
                    acc = pos_acc[positions.get(p, "?")]
                    acc[1] += pts_new.get(p, 0.0)
                    acc[3] += 1
                for p in chosen_r:
                    pos_acc[positions.get(p, "?")][4] += 1
                for p in chosen_n:
                    pos_acc[positions.get(p, "?")][5] += 1

    def outcome(scores, f):
        tbl = standings(scores, pairs, {t: t for t in teams}, f)
        return Outcome(scores, tbl, bracket(scores, tbl, {t: t for t in teams}, f), f)

    outcomes = {
        "actual": (outcome(sc["real"], real_fmt), outcome(sc["actual"], fmt)),
        "optimal": (outcome(sc["opt_real"], real_fmt), outcome(sc["optimal"], fmt)),
    }
    complete = outcomes["actual"][0].bracket.complete
    if not complete:
        warnings.append(f"{season} is in progress (through week {keys[-1][1]}): standings so far, "
                        "no bracket — use the forecast for the rest")
    if no_line:
        warnings.append(f"{season}: {no_line} scoring starter-week(s) have no nflverse stat line, "
                        "so the scoring change could not move them (kept at their real points)")
    return SeasonRun(season=season, teams=teams, pairs=pairs, real_slots=real_names, slots=names,
                     outcomes=outcomes, lineups=lineups, positions=dict(pos_acc),
                     player_totals=dict(player_totals), benched=benched, filled=filled,
                     no_stat_line=no_line, complete=complete, warnings=warnings)


def history_seasons() -> List[int]:
    """Completed seasons with exports: 2020 (ESPN) and every finished Sleeper one."""
    lg = load_league()
    have = sorted({k[0] for k in lg.order}) if lg is not None else []
    done = set(Q.completed_seasons()) | {2020}
    return [s for s in have if s in done]


@dataclass
class Simulation:
    spec: RuleSpec
    seasons: List[SeasonRun]
    warnings: List[str] = field(default_factory=list)

    def run(self, season: int) -> SeasonRun:
        return next(r for r in self.seasons if r.season == season)


def simulate(spec: RuleSpec, seasons: Optional[Sequence[int]] = None) -> Simulation:
    lg = load_league()
    if lg is None:
        raise FileNotFoundError("exports/team_week.csv and the snapshot are needed")
    chosen = list(seasons or spec.seasons or history_seasons())
    runs = [run_season(int(s), spec, lg) for s in chosen]
    warnings = sorted({w for r in runs for w in r.warnings})
    return Simulation(spec=spec, seasons=runs, warnings=warnings)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def _real_results(season: int) -> Tuple[Dict[str, str], str]:
    """team -> regular-season record, and the champion, from the exports."""
    ty = Q.load_sheet("team_year")
    ty = ty[pd.to_numeric(ty["Year"], errors="coerce") == season]
    records = {str(t): str(r) for t, r in zip(ty["Team"], ty["Regular season record"])}
    tw = Q.load_sheet("team_week")
    tw = tw[(pd.to_numeric(tw["Year"], errors="coerce") == season) & (tw["Week Name"] == "Final")]
    champ = [str(t) for t, w in zip(tw["Team"], tw["Win?"]) if str(w).strip().lower() in ("true", "1")]
    return records, (champ[0] if champ else "")


def check_identity(season: int) -> List[str]:
    """An empty spec must reproduce the season's records, PF and champion."""
    run = run_season(season, RuleSpec())
    base, scen = run.outcomes["actual"]
    problems = []
    for a, b in zip(base.table, scen.table):
        if (a.team, a.record, a.points_for) != (b.team, b.record, b.points_for):
            problems.append(f"{season}: empty spec moved {a.team} {a.record} {a.points_for} -> "
                            f"{b.team} {b.record} {b.points_for}")
    if base.bracket.champion != scen.bracket.champion:
        problems.append(f"{season}: empty spec changed the champion")
    records, champ = _real_results(season)
    if run.complete and (len(records) != len(base.table) or not champ):
        problems.append(f"{season}: team_year / team_week gave {len(records)} records and "
                        f"champion {champ!r} — nothing to check against")
    for s in base.table:
        want = records.get(s.team)
        if want is not None and want.split(" ")[0] != s.record:
            problems.append(f"{season}: {s.team} replays {s.record}, team_year says {want}")
    if run.complete and champ and base.bracket.champion != champ:
        problems.append(f"{season}: champion replays {base.bracket.champion}, exports say {champ}")
    if run.complete:
        tw = Q.load_sheet("team_week")
        tw = tw[pd.to_numeric(tw["Year"], errors="coerce") == season]
        pf = {(str(t), int(w)): float(v) for t, w, v in
              zip(tw["Team"], pd.to_numeric(tw["Week"]), pd.to_numeric(tw["PF"], errors="coerce"))}
        for g in base.bracket.games:
            if g.round != len(base.fmt.playoff_weeks) - 1 or len(g.weeks) != 1:
                continue
            got = pf.get((g.high, g.weeks[0]))
            if got is not None and abs(got - g.high_pts) > 0.011:
                problems.append(f"{season} wk {g.weeks[0]}: {g.high} semifinal {g.high_pts} with the "
                                f"bonus, team_week PF {got}")
    return problems


def check_max_pf(season: int) -> List[str]:
    """The optimal routine, real template and real points, must equal Max PF."""
    run = run_season(season, RuleSpec())
    tw = Q.load_sheet("team_week")
    tw = tw[pd.to_numeric(tw["Year"], errors="coerce") == season]
    problems = []
    compared = 0
    opt = run.outcomes["optimal"][0].scores
    for t, w, v in zip(tw["Team"], pd.to_numeric(tw["Week"]), pd.to_numeric(tw["Max PF"], errors="coerce")):
        got = opt.get(int(w), {}).get(str(t))
        if got is None or pd.isna(v):
            continue
        compared += 1
        if abs(got - float(v)) > 0.011:
            problems.append(f"{season} wk {int(w)} {t}: optimal {got:.2f} vs Max PF {float(v):.2f}")
    if not compared:
        problems.append(f"{season}: no team-week compared against Max PF")
    return problems


def validate(seasons: Optional[Sequence[int]] = None) -> List[str]:
    out: List[str] = []
    for s in seasons or history_seasons():
        out.extend(check_identity(int(s)))
        out.extend(check_max_pf(int(s)))
    return out


# ---------------------------------------------------------------------------
# Forecast mode
# ---------------------------------------------------------------------------
class ForecastRules:
    """The hook `forecast.forecast(rules=...)` takes: the scenario's scores for
    the weeks already played, a per-team weekly shift carried into the
    simulated weeks (the mean scenario-minus-real change so far — the forward
    projection is NOT re-scored, so a scoring change that grows or fades later
    is not seen), and the scenario's table and bracket."""

    def __init__(self, year: int, spec: RuleSpec, variant: str = "actual"):
        teams = Q.teams(year)
        self.by_name = {v: k for k, v in teams.items()}
        self.names = dict(teams)
        self.fmt = scenario_format(year, spec)
        self.playoff_teams = self.fmt.playoff_teams
        self.observed: Optional[Dict[int, Dict[int, float]]] = None
        self.shift: Dict[int, float] = {}
        if spec.changes_scoring or spec.changes_lineup:
            lg = load_league()
            if lg is not None and _season_keys(lg, year):
                run = run_season(year, spec, lg)
                base, scen = run.outcomes[variant]
                self.observed = {wk: {self.by_name[t]: v for t, v in s.items() if t in self.by_name}
                                 for wk, s in scen.scores.items()}
                diffs: Dict[int, List[float]] = defaultdict(list)
                for wk, s in scen.scores.items():
                    for t, v in s.items():
                        if t in self.by_name and wk <= run.outcomes["actual"][0].fmt.regular_season_weeks:
                            diffs[self.by_name[t]].append(v - base.scores[wk][t])
                self.shift = {rid: float(np.mean(v)) for rid, v in diffs.items()}

    def standings(self, scores, pairs, teams, meta):
        return standings(scores, pairs, dict(teams), self.fmt)

    def bracket(self, scores, table, teams, meta):
        return bracket(scores, table, dict(teams), self.fmt)


@dataclass
class ForecastCompare:
    year: int
    spec: RuleSpec
    real: Any
    scenario: Any
    shift: Dict[str, float]
    fmt_real: Format
    fmt: Format


def forecast(spec: RuleSpec, year: Optional[int] = None, sims: int = 5000,
             seed: int = 20260807, variant: str = "actual") -> ForecastCompare:
    """The current season's odds under the real rules and under `spec`, same
    seed (common random numbers), so the difference is the rule change's."""
    from lotg_support import forecast as F
    year = year or max(Q.snapshot_seasons())
    real = F.forecast(year, sims=sims, seed=seed)
    hook = ForecastRules(year, spec, variant)
    scen = F.forecast(year, sims=sims, seed=seed, rules=hook)
    return ForecastCompare(year=year, spec=spec, real=real, scenario=scen,
                           shift={hook.names[r]: v for r, v in hook.shift.items()},
                           fmt_real=real_format(year), fmt=hook.fmt)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@dataclass
class Ledger:
    seasons: int = 0
    wins: float = 0.0
    wins_new: float = 0.0
    games: int = 0
    games_new: int = 0
    pf: float = 0.0
    pf_new: float = 0.0
    weeks: int = 0
    titles: int = 0
    titles_new: int = 0
    finals: int = 0
    finals_new: int = 0
    playoffs: int = 0
    playoffs_new: int = 0


def ledger(sim: Simulation, variant: str = "actual") -> Dict[str, Ledger]:
    out: Dict[str, Ledger] = defaultdict(Ledger)
    for run in sim.seasons:
        base, scen = run.outcomes[variant]
        for b in base.table:
            n = scen.record(b.team)
            led = out[b.team]
            led.seasons += 1
            led.wins += b.wins + 0.5 * b.ties
            led.wins_new += n.wins + 0.5 * n.ties
            led.games += b.wins + b.losses + b.ties
            led.games_new += n.wins + n.losses + n.ties
            led.pf += b.points_for
            led.pf_new += n.points_for
            led.weeks += base.fmt.regular_season_weeks
            led.playoffs += b.team in base.bracket.seeds
            led.playoffs_new += b.team in scen.bracket.seeds
            led.titles += b.team == base.bracket.champion
            led.titles_new += b.team == scen.bracket.champion
            led.finals += b.team in base.bracket.finalists
            led.finals_new += b.team in scen.bracket.finalists
    return dict(out)


def records(sim: Simulation, variant: str = "actual", n: int = 3) -> Dict[str, Tuple[list, list]]:
    """League records under the real rules and the scenario: best and worst
    team-week, best regular-season PF and record."""
    def collect(which: int):
        weeks, seasons = [], []
        for run in sim.seasons:
            o = run.outcomes[variant][which]
            for wk, s in o.scores.items():
                for t, v in s.items():
                    weeks.append((v, t, run.season, wk))
            for st in o.table:
                seasons.append((st, run.season, o.fmt.regular_season_weeks))
        return weeks, seasons
    out = {}
    for which, label in ((0, "real"), (1, "scenario")):
        weeks, seasons = collect(which)
        out[label] = {
            "high week": sorted(weeks, key=lambda x: -x[0])[:n],
            "low week": sorted(weeks, key=lambda x: x[0])[:n],
            "season PF / wk": sorted(seasons, key=lambda x: -x[0].points_for / max(x[2], 1))[:n],
            "best record": sorted(seasons, key=lambda x: (-(x[0].wins + 0.5 * x[0].ties) / max(
                x[0].wins + x[0].losses + x[0].ties, 1), -x[0].points_for))[:n],
        }
    return {k: (out["real"][k], out["scenario"][k]) for k in out["real"]}


def position_shift(sim: Simulation) -> Dict[str, List[float]]:
    acc: Dict[str, List[float]] = defaultdict(lambda: [0.0] * 6)
    for run in sim.seasons:
        for pos, vals in run.positions.items():
            for i, v in enumerate(vals):
                acc[pos][i] += v
    return dict(acc)


def player_movers(sim: Simulation, n: int = 8) -> List[Tuple[float, str, int, float, float]]:
    rows = []
    for run in sim.seasons:
        for pid, (a, b) in run.player_totals.items():
            if abs(b - a) > 0.005:
                rows.append((round(b - a, 2), pid, run.season, a, b))
    rows.sort(key=lambda r: -abs(r[0]))
    return rows[:n]


def _fmt_week(entry) -> str:
    v, t, s, w = entry
    return f"{v:.2f} {t} {s} wk {w}"


def _fmt_season(entry) -> str:
    st, s, weeks = entry
    return f"{st.team} {s} {st.record} {st.points_for / max(weeks, 1):.2f}/wk"


def render_season(run: SeasonRun, variant: str = "actual") -> List[str]:
    base, scen = run.outcomes[variant]
    lines = [f"--- {run.season} ({variant}) ---"]
    if base.fmt != scen.fmt:
        lines.append(f"  format  real: {base.fmt.describe()}")
        lines.append(f"          new:  {scen.fmt.describe()}")
    if run.slots != run.real_slots:
        lines.append(f"  lineup  {' '.join(run.real_slots)} -> {' '.join(run.slots)}"
                     + (f"  ({run.filled} bench fills, {run.benched} starters benched)"
                        if variant == "actual" else ""))
    seed_real = {t: i + 1 for i, t in enumerate(s.team for s in base.table)}
    lines.append(f"  {'team':<16} {'record':>14} {'PF':>18} {'seed':>7}")
    for st in scen.table:
        b = base.record(st.team)
        seed_new = scen.table.index(st) + 1
        mark = ""
        if (st.team in scen.bracket.seeds) != (st.team in base.bracket.seeds):
            mark = "  IN" if st.team in scen.bracket.seeds else "  OUT"
        lines.append(f"  {st.team:<16} {b.record:>6} -> {st.record:<6} "
                     f"{b.points_for:>8.2f} -> {st.points_for:<8.2f} "
                     f"{seed_real[st.team]:>2} -> {seed_new:<2}{mark}")
    if run.complete:
        same = base.bracket.champion == scen.bracket.champion
        lines.append(f"  champion {base.bracket.champion} -> {scen.bracket.champion}"
                     + ("  (same)" if same else "  CHANGED")
                     + f"; runner-up {base.bracket.runner_up} -> {scen.bracket.runner_up}")
        for g in scen.bracket.games:
            lines.append(f"    round {g.round} wk {'+'.join(map(str, g.weeks))}: "
                         f"{g.high} {g.high_pts:.2f} v {g.low} {g.low_pts:.2f} -> {g.winner}")
    flips = 0
    for wk, ps in run.pairs.items():
        if wk > min(base.fmt.regular_season_weeks, scen.fmt.regular_season_weeks):
            continue
        for a, b in ps:
            ra, rb = base.scores[wk][a], base.scores[wk][b]
            ca, cb = scen.scores[wk][a], scen.scores[wk][b]
            if (ra > rb) != (ca > cb) or (ra == rb) != (ca == cb):
                flips += 1
    lines.append(f"  {flips} regular-season game(s) flip")
    return lines


def render(sim: Simulation, variants: Sequence[str] = VARIANTS, seasons_detail: bool = True) -> str:
    spec = sim.spec
    lines = ["=" * 78, f"RULE CHANGE: {spec.name or 'unnamed'}", "=" * 78]
    for d in spec.describe():
        lines.append(f"  {d}")
    if spec.note:
        lines.append(f"  note: {spec.note}")
    lines.append(f"  seasons: {', '.join(str(r.season) for r in sim.seasons)}")
    lines.append("")
    lines.append("CHAMPIONS")
    head = f"  {'season':<7}" + "".join(f"{v + ' real':<18}{v + ' new':<18}" for v in variants)
    lines.append(head)
    for run in sim.seasons:
        row = f"  {run.season:<7}"
        for v in variants:
            b, s = run.outcomes[v]
            bc = b.bracket.champion or "(in progress)"
            sc = s.bracket.champion or "(in progress)"
            row += f"{bc:<18}{sc + ('' if sc == bc else ' *'):<18}"
        lines.append(row)
    lines.append("  (* = changed. 'optimal real' is every lineup at its best under the real rules,"
                 "\n   so optimal real -> optimal new is the rule's effect with lineup skill removed.)")
    for v in variants:
        lines.append("")
        lines.append(f"WHO GAINS / LOSES ({v} lineups; totals over the seasons above)")
        lines.append(f"  {'team':<16} {'wins / games':>22} {'win %':>13} {'PF/wk':>14} "
                     f"{'playoffs':>9} {'finals':>8} {'titles':>8}")
        led = ledger(sim, v)
        order = sorted(led, key=lambda t: -((led[t].titles_new - led[t].titles) * 100
                                           + (led[t].wins_new - led[t].wins)))
        for t in order:
            L = led[t]
            pct, pct_new = 100 * L.wins / max(L.games, 1), 100 * L.wins_new / max(L.games_new, 1)
            lines.append(
                f"  {t:<16} {L.wins:>5g}/{L.games:<3} -> {L.wins_new:>5g}/{L.games_new:<3}({L.wins_new - L.wins:+g}) "
                f"{pct:5.1f}->{pct_new:<5.1f} "
                f"{L.pf / max(L.weeks, 1):>6.2f} {(L.pf_new - L.pf) / max(L.weeks, 1):+6.2f} "
                f"{L.playoffs:>3}->{L.playoffs_new:<3} {L.finals:>3}->{L.finals_new:<3} "
                f"{L.titles:>3}->{L.titles_new:<3}")
    lines.append("")
    lines.append("PLAYOFF FIELDS THAT CHANGE (actual lineups)")
    any_field = False
    for run in sim.seasons:
        b, s = run.outcomes["actual"]
        if b.bracket.seeds != s.bracket.seeds:
            any_field = True
            ins = [t for t in s.bracket.seeds if t not in b.bracket.seeds]
            outs = [t for t in b.bracket.seeds if t not in s.bracket.seeds]
            lines.append(f"  {run.season}: seeds {', '.join(b.bracket.seeds)} -> {', '.join(s.bracket.seeds)}"
                         + (f"  (in: {', '.join(ins)}; out: {', '.join(outs)})" if ins or outs else ""))
    if not any_field:
        lines.append("  none — the same teams make it, in the same seed order")
    lines.append("")
    lines.append("RECORDS (actual lineups; regular season + playoffs, raw points, no +5)")
    for label, (real, new) in records(sim).items():
        fmt = _fmt_week if "week" in label and "PF" not in label else _fmt_season
        lines.append(f"  {label:<14} real: {'; '.join(fmt(e) for e in real)}")
        lines.append(f"  {'':<14} new:  {'; '.join(fmt(e) for e in new)}")
    lines.append("")
    lines.append("POSITIONAL VALUE (regular season; share of starter points, points per start,")
    lines.append("                  and how many starts each position gets in OPTIMAL lineups)")
    acc = position_shift(sim)
    tot_r = sum(v[0] for v in acc.values()) or 1.0
    tot_n = sum(v[1] for v in acc.values()) or 1.0
    lines.append(f"  {'pos':<4} {'share real':>10} {'new':>7} {'pts/start':>10} {'new':>7} "
                 f"{'opt starts':>11} {'new':>6}")
    for pos in sorted(acc, key=lambda p: -acc[p][0]):
        v = acc[pos]
        lines.append(f"  {pos:<4} {100 * v[0] / tot_r:>9.1f}% {100 * v[1] / tot_n:>6.1f}% "
                     f"{v[0] / max(v[2], 1):>10.2f} {v[1] / max(v[3], 1):>7.2f} "
                     f"{int(v[4]):>11} {int(v[5]):>6}")
    movers = player_movers(sim)
    if movers:
        lines.append("")
        lines.append("PLAYERS WHOSE ROSTERED POINTS MOVE MOST (season totals, every rostered week)")
        pl = Q.players()
        for d, pid, season, a, b in movers:
            lines.append(f"  {pl.name(pid):<24} {season}  {a:8.2f} -> {b:8.2f}  ({d:+.2f})")
    if seasons_detail:
        for run in sim.seasons:
            lines.append("")
            lines.extend(render_season(run, "actual"))
    lines.append("")
    lines.append("CAVEATS")
    caveats = [
        "Managers' real starters are kept; nobody re-set a lineup for the new scoring. The "
        "'optimal' variant brackets that assumption from above.",
        "Bench = every non-starter (taxi and IR included: there is no weekly taxi flag), so an "
        "added slot or an optimal lineup can use a taxi player the real rules would not allow.",
        "Rosters, trades and waiver claims are the real ones: under a different rule the "
        "managers would have built different rosters. This measures the rule on the rosters "
        "that existed, which is the fair first-order answer, not the whole one.",
        "Lineups were 9 starters 2020-23 and 10 from 2024; slot edits apply to each season's own "
        "template. 2020 is the ESPN backfill (14-week regular season, final week 16).",
        "Regular-season PF in the tables carries no +5; the bracket adds the home bonus itself.",
    ]
    if spec.changes_scoring:
        caveats.append("Scoring moves each player-week by the changed keys on his nflverse line; "
                       "lines nflverse lacks (see warnings) keep their real points.")
    for c in caveats:
        lines.append(f"  - {c}")
    for w in sim.warnings:
        lines.append(f"  - {w}")
    return "\n".join(lines)


def render_forecast(fc: ForecastCompare) -> str:
    lines = ["=" * 78, f"FORECAST {fc.year}: real rules vs {fc.spec.name or 'the scenario'}",
             "=" * 78,
             f"  real format: {fc.fmt_real.describe()}",
             f"  new format:  {fc.fmt.describe()}",
             f"  {fc.real.sims} simulations each, same seed; played weeks "
             f"{', '.join(map(str, fc.real.played_weeks)) or 'none'}", ""]
    lines.append(f"  {'team':<16} {'playoffs %':>15} {'finals %':>15} {'title %':>15} {'wins':>13} {'shift/wk':>9}")
    real = {o.team: o for o in fc.real.odds}
    for o in sorted(fc.scenario.odds, key=lambda o: -o.champion):
        r = real[o.team]
        lines.append(f"  {o.team:<16} {r.playoffs:6.1f} -> {o.playoffs:5.1f} "
                     f"{r.finals:6.1f} -> {o.finals:5.1f} {r.champion:6.1f} -> {o.champion:5.1f} "
                     f"{r.expected_wins:5.2f} -> {o.expected_wins:5.2f} "
                     f"{fc.shift.get(o.team, 0.0):+8.2f}")
    lines.append("")
    lines.append("  - shift/wk: the team's mean weekly change under the scenario over the weeks "
                 "played, carried into the simulated weeks; the forward projection itself is not "
                 "re-scored, and the weekly spread is the real rules' (a scoring change that "
                 "widens scores is under-stated).")
    for w in sorted(set(fc.scenario.warnings) - set(fc.real.warnings)):
        lines.append(f"  - {w}")
    return "\n".join(lines)
