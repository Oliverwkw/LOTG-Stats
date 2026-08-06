# Inquiry playbook

How to answer a question about this league quickly, and over-inclusively, without
re-deriving the same primitives every time.

An **inquiry** here means a question answered *from* the committed data — "who
has the most X", "when did Y last happen", "would Z still have won without that
trade" — as opposed to a change to the build. Inquiries are read-only. They must
not alter `exports/`, `data/`, the workflows, or anything `python -m lotg`
produces. A written-up inquiry lands as a note in `plan/notes/` (plus, if it
needed one, a script in `scripts/`), never as a change to a build output.

## The tools

| Tool | For |
|---|---|
| `scripts/inquire.py` (`lotg_support.inquiry`) | finding, filtering and ranking anything in the twelve export sheets, and reading the raw Sleeper snapshot |
| `scripts/whatif.py` (`lotg_support.replay`) | counterfactual seasons: rewind a trade — or a whole sequence of them — or move a player, replay every week, re-seed, re-run the bracket |
| `lotg_support.analysis` (via `inquire.py group/stacks/compare/compare-all/correlate/stretch/timeline/scarcity/spend`) | the joins and comparisons a judgement question needs: position attached to any sheet, roster-group depth, lineup composition, cohort tests with FDR control, arbitrary time windows, entity timelines, positional scarcity, spend vs return |

All three are additive and read-only. None is imported by the build or run by
any workflow.

## Start here, not with a script

```bash
# 1. Which sheet and column holds the concept? (~1,000 columns across 12 sheets;
#    column names AND their documented notes are searched)
python scripts/inquire.py columns 'efficien|max pf'
python scripts/inquire.py describe team_week Efficiency

# 2. Rank it, filter it
python scripts/inquire.py top player_year Points -n 10 --where Year=2025
python scripts/inquire.py rows team_week --where Year=2025 --where 'Margin<2' \
    --select Team,Week,Opponent,Margin,Win?

# 3. One entity, everything at once
python scripts/inquire.py player 'Lamar Jackson'      # all-time, by year, best week, trades
python scripts/inquire.py team shmuel256
python scripts/inquire.py season 2025                  # shape, standings, bracket

# 4. The raw snapshot — where counterfactuals start
python scripts/inquire.py trades --season 2025         # both sides, named, picks + FAAB
python scripts/inquire.py roster 2025 6 --team shmuel256 --bench
```

Filters are `Column<op>value`, repeatable, ANDed: `=`, `!=`, `>`, `>=`, `<`,
`<=`, and `~` for a case-insensitive regex. Add `--csv` for parseable output.

## Sweeps — the over-inclusive shape

When the question is "what is notable about X" rather than "what is X's Y",
don't pick the stats to check. Sweep every column and let the data decide, the
same way the weekly digest does:

```bash
# every column where shmuel256's 2025 lands in the top/bottom 2 of that season
python scripts/inquire.py sweep team_year --where Team=shmuel256 --where Year=2025 \
    --within Year=2025 --window 2

# a player against his own season's field
python scripts/inquire.py sweep player_year --where 'Player~^Josh Allen$' \
    --where Year=2025 --within Year=2025

# both ends of every rankable column at once — "what stood out at all?"
python scripts/inquire.py extremes league_year
python scripts/inquire.py extremes team_year --within Year=2025 --top 2
```

`--where` picks the row being asked about; `--within` narrows the board it is
ranked against (leave it off to rank against all seasons). Columns come from the
digest's own discovery, so an inquiry and the weekly email always consider the
same set of stats, and there is no curated list to fall out of date.

**Build-volatile columns are kept and flagged, not dropped.** Anything in the
`Luck` / `skill` / rolling-window family legitimately moves between builds
(`lotg_support.volatile_columns`); the sweep marks it `[build-volatile]` so it
gets classified in the write-up rather than quietly filtered. `--no-volatile`
drops them when you specifically want build-stable facts only.

In Python, the same thing:

```python
import sys; sys.path.insert(0, "lib")
from lotg_support import inquiry as Q

Q.rows("player_week", "Year=2025", "Points>40")
Q.top("team_all_time", "Championships")
Q.sweep("team_year", "Team=shmuel256", "Year=2025", within=["Year=2025"])
Q.extremes("league_year")
Q.week(2025, 6)[8].starters          # snapshot lineup, slot order
Q.trades(player="Justin Herbert")
```

## Judgement questions

"Who had the best WR corps", "does stacking cost me ceiling", "are QBs
overvalued" all need joins and comparisons that no single sheet holds.
`lotg_support.analysis` supplies them.

**Position, attached to anything.** `picks` and `transactions` carry no position
column, which stalls any spend-by-position question on line one.
`with_position(df, "Player Picked", "Year")` joins it from the build's own
`player_week` (per season, so no dictionary drift), falling back to Sleeper's
dictionary for players who were drafted or added but never fielded. Rows naming
no player — an unexercised future pick is written `Unknown`, a drop-only
transaction has a blank `Player Added` — are excluded and *counted*, never
silently dropped; `placement_report()` gives the tally.

**Depth, not a total.** A single sum flatters the team that had one great
receiver.

```bash
python scripts/inquire.py group WR --season 2025
```

Alongside `points` you get `effective_players` (1/Σ(share²) — 1.0 means one
player did everything, 4.0 means four equal contributors), `top1/top3_share`,
`contributors`, `ppg` and `share_of_team`. Drop `--season` to rank every
team-season at once, which is what an all-time question wants.

**Lineup composition and stacking.**

```bash
python scripts/inquire.py stacks --compare 'Max PF' --condition 'stack_WR>=2'
```

`lineup_stacks()` gives one row per fielded lineup with `max_same_nfl_team`, a
`stack_<POS>` count per position, and the team-week's PF / Max PF / Efficiency
already joined, so a ceiling question is a group-by.

**Every column at once.** The over-inclusive form of a cohort question: don't
pick the metric you expect to move, test the condition against everything.

```bash
python scripts/inquire.py compare-all stacks --condition 'stack_WR>=2'
python scripts/inquire.py correlate team_year --target 'Win %'
```

`compare_all()` runs the cohort test on every numeric column ranked by effect
size; `correlate_all()` correlates every column against one target. Both report
a **Benjamini-Hochberg q-value across the whole family**, because a hundred
tests at p<0.05 produce about five hits from noise alone — never quote a sweep's
p-value on its own. Columns that are definitionally part of the condition or
target will top the list (`starter_points` "predicts" `PF` at r=1.00); recognise
those rather than reporting them.

**A different window.** "All time" is rarely one window — three dominant seasons
and one monster year are different claims.

```bash
# best 3-season WR corps, by total points
python scripts/inquire.py stretch group --metric points --length 3 --order Year
# best 5-week scoring run by any team, ever
python scripts/inquire.py stretch team_week --metric PF --length 5
```

`best_stretch()` takes any long frame and finds each entity's best contiguous
run. Contiguity is by row order *within the entity*, so a missing week makes its
neighbours adjacent — the `span` column shows the real endpoints, so a run that
jumped a gap is visible rather than hidden.

**The story of one entity.** `timeline()` merges draft picks, adds/drops and
trades — three sheets, three date columns — into one chronological log:

```bash
python scripts/inquire.py timeline --player 'Justin Herbert'
python scripts/inquire.py timeline --team shmuel256 --season 2025
```

**Cohort comparison.** `compare(frame, condition, metric)` reports *both*
cohorts — n, mean, median, sd — plus the difference, Cohen's d, a deterministic
permutation p-value, and a **per-season breakdown**. Read the breakdown before
the pooled number: a gap that exists in one season and reverses in another is a
different claim from one that holds every year, and the pooled mean cannot tell
you which you have.

**Scarcity and spend.**

```bash
python scripts/inquire.py scarcity --season 2025      # best vs replacement, per position
python scripts/inquire.py spend --team Oliverwkw      # draft capital + FAAB vs points back
```

Replacement rank comes from `observed_demand()` — how many of that position the
league *actually starts* per week — not from a rule of thumb, because the flex
and superflex slots mean you cannot read demand off the lineup template.
`--demand-multiple` tests a stricter replacement level.

`spend_by_position()` prices two channels, draft (pick slot + KTC on draft day)
and FAAB, against the starter points that came back. **Trades are not priced**
— `trades` stores its assets as free text — and any write-up using that table
has to say so.

## Counterfactuals

```bash
# would shmuel256 still have won 2025 without the Herbert-for-Jackson trade?
python scripts/whatif.py --season 2025 --undo-trade-player 'Justin Herbert' --model all

# arbitrary: this player on that roster instead, from week 9
python scripts/whatif.py --season 2024 --move '4881:5->8@9'

# a teardown is not one trade — rewind the whole sequence at once
python scripts/whatif.py --season 2024 --model all \
    --undo-trade-id 1092268177528127488 --undo-trade-id 1095772841745821696
```

`--undo-trade-player` and `--undo-trade-id` are repeatable, and
`replay.undo_trades` / `replay.compose` merge the undos **per player**, not by
concatenation: someone traded A→B and later B→C becomes a single C→A move, and
endpoints that do not chain raise rather than get picked between. Undoing a fire
sale one trade at a time understates it — each undo alone leaves the rest of the
roster gutted. (`WHATIF_TEARDOWN_2024.md` is the worked example: the headline
trade alone is worth 2 wins, all five together are worth 5.)

The lineup model is the load-bearing assumption in any counterfactual, so there
are three, and `--model all` runs each:

- **anchored** (default) — the real lineup minus departures; an arriving player
  starts only if his real manager started him that week; holes and surpluses are
  resolved by prior-form PPG subject to slot legality, skipping anyone the build
  flags bye/injured/suspended. No hindsight.
- **strict** — the arrival plays only in the departing player's slot, matched by
  position. Nothing else moves.
- **ceiling** — the score moves by the change in the roster's optimal lineup,
  using the build's own Max PF routine.

**Report where the models disagree rather than picking one.** If they agree, say
so — that is the strongest form the answer can take.

## Trust, then verify

```bash
python scripts/inquire.py validate            # all completed seasons
python scripts/inquire.py validate --season 2025
```

Three guards, also run by `whatif.py` before it answers, and by
`tests/test_replay.py` in CI:

1. every lineup actually fielded that season is legal under the season's slot
   template;
2. the ceiling routine reproduces `team_week.Max PF` exactly;
3. **a replay with no moves reproduces the built `PF`, bracket and champion** —
   currently exact for 2021-2025;
4. composing trade rewinds agrees with the single-trade path it generalises —
   one trade composed equals `undo_trade` of it, and an undo composed with its
   mirror cancels to no moves at all.

The analysis layer has its own two, in `tests/test_analysis.py`: the starter
points it rebuilds from `player_week` must equal `team_week.PF` (allowing the
+5), and its `max_same_nfl_team` must equal the build's own "Most number of
players started from same NFL team" column for every lineup.

A counterfactual whose baseline cannot reproduce reality is not evidence. If a
guard fails, fix that before quoting any number.

## Traps this tooling already absorbs

Each of these has cost real time at least once. They are handled in code — the
list is here so an answer written by hand does not walk into them.

- **`team_week.PF` is not Sleeper's raw `points`.** The league gives the higher
  seed in each semifinal +5 (home field) and the build bakes it into `PF`.
  Exactly eight rows across 2021-2025 differ, all in the playoff-start week.
  `inquiry.SEMIFINAL_HOME_BONUS`.
- **2020 has exports but no snapshot.** It came from the ESPN backfill, so
  anything snapshot-based must skip it: `season_meta(2020).has_snapshot` is
  False and `replay()` refuses it by name.
- **The starting lineup changed.** One flex through 2023, two from 2024. Read it
  from `season_meta(year).starting_slots`, never hardcode it.
- **The playoff calendar changed.** Weeks 16-17 through 2025; 2026 starts week
  15 and plays a two-week final. `semifinal_week` / `finals_weeks`.
- **The Sleeper player dictionary is current-only, so positions drift.**
  Cordarrelle Patterson is listed RB today but filled a strict WR slot in 2021 —
  which makes three real lineups look illegal. Use
  `season_eligibility(year)`, which adds every strict slot a player was actually
  fielded in. (`Max PF` in the exports is built from current positions, so
  `lineup.compute_optimal_lineup` is deliberately left alone.)
- **Sleeper writes `"0"` for an empty start slot** (`inquiry.EMPTY_SLOT`) — a
  legal lineup, not a bug.
- **Offseason trades live in `week_01`** of the season they precede. The
  Herbert deal is dated 2025-08-07 and sits in `season_2025/weeks/week_01`.
- **Team-name case differs** between Sleeper (`Shmuel256`) and the sheets
  (`shmuel256`). `canonical_team()` / `teams(year)` return the sheets' spelling.
- **Names are ambiguous.** "Lamar Jackson" is also a cornerback. `resolve()`
  prefers a startable position, then someone actually rostered here, and raises
  with the candidates rather than guessing.
- **Seeding is wins + 0.5·ties, then regular-season PF** — the build's rule, and
  playoff PF does not count toward it.
- **The `strict` lineup model is degenerate for a player-for-picks trade.** It
  only lets an arrival occupy the slot the departing player vacated, so when a
  team sold stars for draft picks there is no vacated slot and the returning
  stars simply sit — the counterfactual PF can even fall. Report it, but read the
  spread from `anchored` and `ceiling`. (`WHATIF_TEARDOWN_2024.md`.)

## Over-inclusive reporting

The house rule, the same one the audits and the weekly digest follow: **flag
every borderline item, then classify it** — by-design / needs-human-judgment /
defect — rather than filtering quietly and presenting a clean answer. In
practice, for an inquiry:

- state the answer first, then the caveats that could move it;
- report the sensitivity runs even when they agree;
- surface anything the tooling warned about (`Result.warnings` carries e.g. a
  player who was on nobody's roster in some week, hence scored 0);
- name what was held constant (FAAB, draft picks, second-order behaviour) and
  say why it cannot change the answer — or that it could.

## When the helper you need does not exist — add it

This toolkit is meant to grow. If a question needs a primitive that is not here,
**write the primitive, not a throwaway script**: the next inquiry of that shape
should start where this one finished. Ship it as its own PR, separate from the
answer.

The rule that makes this safe is that an inquiry **changes no outcome**. Adding
a helper must not alter a single byte of what the build produces or what any
workflow does. Concretely:

1. **Additive only.** New files under `lib/lotg_support/`, `scripts/`, `tests/`,
   `plan/notes/`. Do not edit `src/`, `config/`, `.github/workflows/`,
   `exports/`, or `data/`. Editing an existing `lib/lotg_support/` module is
   fine *only* if the build does not import it — `inquiry`, `analysis` and
   `replay` are inquiry-only; `digest`, `lineup`, `ktc`, `sleeper`, `snapshot`,
   `utils` and the rest are build code, so read from them, never change them.
2. **Nothing the build runs may import your module.** Check before you finish:
   `grep -rn "your_module" src/ .github/workflows/` must come back empty.
3. **Reuse the build's own logic rather than reimplementing it.** The ceiling
   model calls `lineup.compute_optimal_lineup`; the sweeps call the digest's
   `discover_numeric_columns`. A second implementation of a build rule is a
   second answer to the same question, and they will drift.
4. **Tie the new primitive to a number the build already computed**, wherever
   one exists, as a `check_*` function plus a test. Precedents:
   `check_identity` (a no-move replay must reproduce the built `PF`, bracket and
   champion), `check_max_pf`, `check_starter_points_reconcile`,
   `check_stack_counts_match_build`. If no independent number exists, say so in
   the docstring and pin the behaviour with a synthetic fixture instead.
5. **Tests follow the house style**: plain `test_*` functions that run under
   `pytest tests/` and directly as `python tests/test_x.py`; data-dependent ones
   skip cleanly when `exports/` is absent and assert only against
   `Q.completed_seasons()` — never an in-progress season, whose snapshot weeks
   the build has not exported yet.
6. **Name the assumptions.** Anything debatable (replacement level, what counts
   as a contributor, a lineup model) is a documented parameter with a default,
   not a constant inside a loop — so the next question can vary it and report
   the sensitivity.
7. **Stay over-inclusive.** A new helper should flag and classify borderline
   items, not filter them: keep build-volatile columns and mark them, count the
   rows you could not place, return `warnings` for anything the caller should
   know. If it runs many tests at once, report the family size and an FDR
   q-value — never a bare p-value from a sweep.
8. **Document it**: add a row to the tool table above, a worked command in the
   relevant section, and — if you hit a new one — an entry in the trap list.

Before opening the PR:

```bash
git status --porcelain          # only new files; no tracked build file modified
git diff --stat main            # expect no changes to src/, workflows/, exports/, data/
python -m pytest tests/ -q      # the whole suite, not just yours
python scripts/inquire.py validate
```

Open it as a **draft PR** whose description states plainly what the helper does,
which guard backs it, and that nothing shipped changes. Keep the answer note and
the tooling separable: a reviewer should be able to take the primitive without
taking the conclusion.

## Writing it up

- The note goes in `plan/notes/` — the question, the answer, the method, the
  guards that back it, and the caveats. `WHATIF_HERBERT_TRADE_2025.md` is the
  worked example.
- Anything reusable belongs in `lib/lotg_support/` with a test, not in a
  one-off script. A script in `scripts/` should be a thin CLI over it.
- Confirm the inquiry changed nothing that ships: `git status` should show only
  new files under `plan/notes/`, `scripts/`, `lib/`, `tests/`.
