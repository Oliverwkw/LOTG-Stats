# Grading the advice tools (2026-10-29)

How far to trust `advise.py startsit`, `advise.py waivers` and `trade.py`'s odds
deltas, from a walk-forward replay over every completed week since 2021.
Code: `lib/lotg_support/grade.py`; CLI: `scripts/grade_tools.py`; tests:
`tests/test_grade.py`. Read-only: nothing touches `exports/`. Not in the weekly
build (a full uncached run is ~15 min, mostly the 170 trade forecasts; cached
reruns take ~5 min).

```bash
python scripts/grade_tools.py all --by Team --save   # writes the track-record lines advise/trade print
```

## Method (point in time)

Each week is replayed with only what was known before its games: earlier
weeks' Sleeper stats (scored with that season's league scoring — equal to the
matchup points, `tests/test_advise.py`), that week's Sleeper projection, the
roster as it stood (snapshot matchups, late listings undone) and byes. Never the
week's own results, the `Injury?` flags, or the build's projection columns
(those zero players who did not play — hindsight). Lineups use `advise`'s own
`best_lineup` and `value_column` rules. The replay's set-lineup points equal
team_week `PF` on every team-week except the semifinal +5 (tested).

Approximations (printed with every report): 2020 is out (no snapshot);
positions are Sleeper's current dictionary; taxi is not recorded weekly (a
player on the season's final taxi squad the team had not yet started is
treated as unstartable); "out" on the PPG bases = no Sleeper projection row or
one under 0.5 (of players who went on to score 10+, 0.5-3% had no row), or a
bye. 8 teams: per-manager rows are ~92 weeks each — read the ±se.

## Start/sit — 736 team-weeks, 2021 to 2026 week 7

| basis | vs set lineup, pts/wk | ±se | weeks ≥ set | reg-season wins +/− (net) |
|---|---|---|---|---|
| **proj** (Sleeper projection) | **+1.33** | 0.45 | 67% | 24 / 27 (−3) |
| season PPG | −2.92 | 0.53 | 46% | 20 / 50 (−30) |
| last-3 PPG | −5.35 | 0.59 | 41% | 27 / 55 (−28) |
| blend (proj + season) / 2 | +0.07 | 0.47 | 61% | −4 |
| blend3 (all three) / 3 | −1.33 | 0.50 | 54% | −15 |
| hindsight best | +31.4 | | | |

- **The projection lineup is the only basis worth following**: it beat the
  managers' own lineups by 1.3 pts/wk (t ≈ 3), but that has not turned into
  wins (net −3 of 51 flips: coin-flip noise at this size). It beat the season
  basis in 6/6 seasons (+4.2/wk, t 8.4) and last-3 in 6/6 (+6.7/wk, t 11).
- **season and L3 lineups are worse than what the managers set** — following
  `best:season` would have cost 30 regular-season wins over 5.5 seasons,
  `best:recent` 28. They are context, not a recommendation. Last-3 form is
  the worst signal of all.
- **No candidate rule beat the projection** (blend −1.25/wk, blend3 −2.7/wk,
  0/6 seasons ahead each), so `startsit`'s rule is unchanged. A smarter rule
  would need a better projection (the build's Enhanced projection is better on
  MAE but zeroes did-not-play players, so it cannot be replayed honestly here).
- Per manager (proj vs set, ±~1.2): plehv79 +4.3 (sets the projection lineup
  exactly 39% of weeks, and the projection is at least as good as his lineup
  in 83%); stevenb123 +1.5; shmuel256 +1.7; LWebs53 +1.3 (but −7 net wins);
  Oliverwkw +1.2; BROsenzweig +0.5; AceMatthew +0.3; JacobRosenzweig −0.1. Only
  plehv79's gap is clearly beyond noise.
- Weeks 1-3 the projection is no better than the managers (−0.2 ± 0.8); from
  week 4 on it is +1.7 ± 0.5. Playoffs +3.0 ± 2.0 (80 team-weeks).
- Reference: the build's `Start/sit miss (Sleeper Projection)` is > 0 for some
  starter in 62% of these team-weeks; the replay's projection lineup differs
  from the set one in 75% (mean 1.2 players) — the replay also counts
  re-shuffles the build's per-player reference misses, and holes Sleeper left
  that the build's column fills.

## Waivers — 715 adds (waiver + free agent, leg 2 on), next 4 weeks

"Lineup gain" = points the player added to the team's hindsight-best lineup over
its pre-add roster, summed over the 4 weeks.

| comparison | mean diff | ±se | tool ahead / tied |
|---|---|---|---|
| tool's top pick vs the add made (lineup gain) | +0.70 | 0.42 | 36% / 30% |
| same, raw points | +4.4 | 1.0 | 50% / 6% |
| tool's top pick **at the added player's position** vs the add | −0.66 | 0.38 | 27% / 42% |

- **The tool's waiver ranking is no better than the managers' picks.** Its top
  overall pick out-gains the actual add by 0.7 lineup points over 4 weeks (not
  significant, and an upper bound: the top free agent was not always gettable),
  and at the manager's chosen position the manager did slightly better. Most
  adds (and most top picks) add nothing to the best lineup — depth/bye cover.
- Managers rarely take the tool's #1 (4%; median rank 39 of ~330).
- Alternative rankings (top pick by +proj, +recent, +blend instead of the
  tool's +season-then-proj): +recent − +season = +0.44 ± 0.32 (t 1.4, 4/6
  seasons), +proj +0.26 ± 0.36, +blend −0.25. **None is proven**, so the
  ranking is unchanged; re-run after 2026 to see if +recent holds.

## Trades — 85 two-team in-season trades, 170 sides, 2021-2025

`trade.run`'s before/after forecast, rewound to the week before each trade with
`forecast.backtest`'s rules (leave-season-out calibration, backtest
availability, 2000 sims, common seed), against the realized change in the
side's hindsight-best lineup pts/wk over the rest of the regular season (each
week's real roster with the trade undone).

| prediction (sides where |Δ| ≥ threshold) | sides | right sign | 95% CI | Spearman |
|---|---|---|---|---|
| forecast pts/wk (≥ 0.5) | 64 | **84%** | 74-91 | 0.56 |
| forecast expected wins (≥ 0.05) | 46 | 83% | 69-91 | 0.48 |
| forecast playoffs % (≥ 1) | 31 | 81% | 64-91 | 0.26 |
| forecast title % (≥ 0.5) | 53 | 47% | 34-60 | 0.17 |
| naive season-PPG lineup Δ (≥ 0.5) | 62 | 69% | 57-79 | 0.35 |

- **The forecast's points / wins / playoff deltas are directionally right
  about 4 times in 5**, clearly better than the naive "best lineup on season
  PPG" arithmetic (69%). Trust the sign of the pts/wk line; the size is
  rank-correlated 0.56 with what happened.
- **A title-odds move is noise unless the pts/wk move is 0.5+.** Alone, the
  title % sign was right 47% of the time; where pts/wk also moved 0.5+, 71% (of
  24). Title odds move on Monte Carlo noise and bracket effects; read pts/wk
  and playoffs % first (trade.py runs 5000 sims, less noisy than this 2000).
- Not tested: dynasty value (picks, age, KTC) — the realized measure is this
  season's lineup only, so a rebuilding trade that "loses" here can be right.

## What changed in the tools

- `advise.py startsit` / `waivers` and `trade.py` print a one-line track
  record from the last `grade_tools.py --save` run (`.cache/grade/track_record.json`),
  else the headline above (`grade.FALLBACK`). Cheap: a file read.
- No ranking rule changed: no candidate beat the existing rules in the replay.

## Strategy-guide lines (for project memory; not reachable from this session)

- weekly-lineup-strategy / start-sit-edges: "Start the projection's lineup, not
  season-PPG or last-3 lineups: replayed 2021-26 the projection beat set lineups
  by +1.3 pts/wk while season/L3 lineups lost 2.9/5.4 pts/wk and ~30 wins
  (ADVICE_TOOLS_GRADE.md). Recent form is the weakest signal."
- waivers-streaming: "advise waivers' #1 is not better than managers' own adds
  (+0.7 ± 0.4 lineup pts over 4 wks, 715 adds): use it to find candidates, not
  to pick between them; most adds add 0 to the best lineup."
- trade-strategy: "trade.py's pts/wk and playoffs-% deltas had the right sign
  ~83% of the time (85 trades); a title-% change with |pts/wk| < 0.5 is noise."
