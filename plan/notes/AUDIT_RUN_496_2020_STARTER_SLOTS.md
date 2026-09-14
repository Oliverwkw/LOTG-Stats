# Run 496: the 3-part audit of the 2020 starter-slot fix

PR #424 (squash-merged as `ccbfb73`) changed one thing the build ships: the 2020
ESPN backfill now emits each week's `starters` in `roster_positions` order, so
`player_week["Position started in (if starter)"]` labels the player who actually
filled that slot. Run **496** (`workflow_dispatch`, 2026-09-14 05:52→06:06 UTC)
is the post-merge build; run **495** (2026-09-10) is the baseline. Both committed
their exports, so the sweep below reads committed CSVs rather than artifacts.

**Verdict: the change landed exactly as specified. 957 cells moved, all in that
one column, all in 2020. Everything else that moved is four days of league and
upstream data, mechanism confirmed for each. Nothing unexplained.**

## Part 1 — code-based

| | run 495 | run 496 |
|---|---|---|
| conclusion | success | success |
| pytest | 1 failed, 353 passed | 1 failed, **383** passed |
| new ERROR lines in `build_debug.log` | 0 | **0** |
| schema | — | no column added, removed or renamed |

The 30 extra tests are the two files the PR added (8 + 22), all collected.

**`exports/raw/build_debug.log` is append-only across builds** — it spans
2026-06-29 to now, and a naive `grep -c Traceback` returns **75** on either run's
copy because it is counting three months of history. Both counts being equal is
the actual signal: run 496 appended 48 lines, every one of them `INFO` (plus one
`WARN` whose message begins "info:"). The most recent real `ERROR` in the file is
dated **2026-09-09**, before either run.

    # the only honest way to read it: the CURRENT run's segment
    git show <commit>:exports/raw/build_debug.log | awk '/===== Build start/{b=""} {b=b $0 ORS} END{printf "%s", b}'

### The two non-404 tracebacks, investigated

They are **one** event, not two, and it is **already fixed**.
`pandas.errors.LossySetitemError` is the internal exception pandas raises before
re-raising it as `TypeError: Invalid value 'WR' for dtype 'float64'`; both lines
belong to a single traceback dated **2026-08-20**:

    ERROR at load_nflverse_weekly_rosters_2026: TypeError: Invalid value 'WR' for dtype 'float64'
      external.py: apply_position_pins -> df.loc[hit, col] = pos

The 2026 weekly-roster file published before the season started carried an
all-empty `position` column, which `read_csv` types `float64`. Writing the Travis
Hunter pin (`'WR'`) into it raised, `_safe_df` swallowed it, and that season's
weekly rosters were unavailable for the rest of the build — so player NFL team
fell back to the season-level and `"NFL"` sentinel paths. Current
`external.apply_position_pins` casts every position column it is about to
overwrite to `object` first, with a comment naming this exact failure, so the
bug cannot recur. No action.

The 404s are the same shape of history: the loader tries the release asset then
the `raw.githubusercontent` mirror, and the mirror had no 2026 file in August.
nflverse has since published it; run 496 logged no 404 at all.

## Part 2 — results-based (7 cases from the change spec)

| # | case | result |
|---|---|---|
| 1 | `tests/test_2020_starter_slots.py` against the built sheet | 8/8 pass, incl. the export-based guard that was red pre-merge |
| 2 | every full lineup's slot multiset == `QB RB1 RB2 WR1 WR2 WR3 TE FLX1 SFLX` | 0 of 127 deviate |
| 3 | the season's one short lineup (shmuel256 wk 16) | exactly `QB RB1 RB2 WR1 WR2 WR3 TE` — short at the TAIL, which is why no padding is needed |
| 4 | spot checks | Dalvin Cook wk 8 `QB`→`RB1`; Derek Carr wk 8 `TE`→`QB`; Tyreek Hill wk 4 `QB`→`FLX1`; Hunter Henry wk 8 `WR1`→`TE` |
| 5 | slot legality: can the player's position fill the slot he is filed in? | 0 of 1,150 illegal (wholesale violations before) |
| 6 | 2021-2025 untouched | 6,381 starter rows, 0 changed |
| 7 | volume | 957 of 1,150 2020 labels changed; 193 were already right by luck |

## Part 3 — diff sweep, every change classified

Untouched entirely: **`team_week`, `league_week`, `league_year`, `formulas`**. No
PF, Max PF, efficiency or weekly team/league metric moved anywhere.

**Intended:** `player_week` — 957 cells, 1 column, Year 2020 only. The same 957
the pre-merge differential predicted.

**Four days of data**, each with its mechanism confirmed rather than assumed:

| what moved | mechanism | how it was confirmed |
|---|---|---|
| `add_drops` +3 rows; Add/Drop, waiver and transaction counts +3 at league/team level | 3 new waiver adds | dated 2026-09-10 and 09-11; the latest date before was 09-09 |
| `Length of tenure on team`, 85 cells | days elapsed | every delta is exactly **+4.0** (Sept 10 → Sept 14) |
| `Avg career PPG`, `Avg PPG on team`, `Player addition value`, `O-Score`, `Difference of averages`, Drafting/Trading/Add-Drop skill | career averages now include 2026 week 1 | spans every season, magnitudes ~0.1 |
| `Link to next/previous transaction`, 259 cells | ledger renumbering | shifts by exactly 1-3, matching the 3 inserted rows (`#981`→`#982`) |
| `KTC value difference 1 year later`, 6 cells NaN→value | the 1-year horizon arrived | the 3 trades are dated 2025-09-11, -12 and -14 |
| `Tanking` 2026, 37 cells | future capital / roster age as of now | 2026 rows only |
| `player_all_time` +2, `player_year` +3, `player_additions` +3 rows | the 2 new players and 3 new moves | — |

**UNEXPECTED: none.** That is a claim about the code, not just an observation:
before the merge the same build ran twice in two worktrees (PR base vs head) on
frozen inputs, with a base-vs-base control that produced **0 differing cells**,
and base-vs-head produced only that one column across all 15 sheets. Run 496's
extra diffs appear only once four days of real data are added.

## Mid-week artifacts

* **No 2026 `team_week` rows.** Week 1 is not over by the clock, so the build
  emits none. 2026 therefore exists in `team_year` (placeholder rows are seeded)
  and not in `team_week`. Correct, and worth knowing before reading either sheet
  mid-week.
* **`test_a_league_of_identical_teams_comes_out_uniform` was the only failure on
  both runs**, and it is not flaky — it is structurally red in-season. Fixed in
  the PR that carries this note; the reasoning is below.

## The uniform-forecast test was measuring the calendar

`forecast(strength_model="uniform")` sets every prior to 0 and `sd_true` to 0, so
`_update_strength` returns early and played weeks cannot move a team's strength.
The test read that as "identical teams, so identical odds" — but the results of
played weeks are already **banked**: a team that won week 1 is likelier to be
seeded and to survive the bracket however even the talent is.

Measured on 2026 week 2, same call, 6,000 sims:

| | worst championship deviation | worst playoff deviation |
|---|---|---|
| live clock (week 1 played) | **3.90pp** (tolerance 2.0) | **14.42pp** (tolerance 4.0) |
| `as_of_week=0` | 0.53pp | 0.98pp |

It failed 10.30% on run 495 and 16.40% on run 496 — drifting further every week,
which is what a calendar-dependent assertion looks like. The fix pins the clock
(`as_of_week=0`, the parameter `backtest` already uses for exactly this) rather
than widening the tolerance, so the property is checked year-round instead of
only in the preseason. It is also 4x faster.

## Reproducing any of this

```bash
# the sweep: committed CSVs, before vs after, sorted by canonical keys
git show ccbfb73:exports/player_week.csv > /tmp/before.csv
git show 965c034:exports/player_week.csv > /tmp/after.csv

# the results cases
PYTHONPATH=src:lib python tests/test_2020_starter_slots.py

# the forecast finding
PYTHONPATH=src:lib python -c "
import sys; sys.path.insert(0,'lib')
from lotg_support import forecast as F
for kw in ({}, {'as_of_week': 0}):
    fc = F.forecast(2026, sims=6000, strength_model='uniform', **kw)
    n = len(fc.odds)
    print(kw, sorted(fc.played_weeks),
          max(abs(o.champion - 100.0/n) for o in fc.odds))"
```
