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
| `scripts/whatif.py` (`lotg_support.replay`) | counterfactual seasons: rewind a trade or move a player, replay every week, re-seed, re-run the bracket |
| `lotg_support.analysis` (via `inquire.py group/stacks/compare/scarcity/spend`) | the joins and comparisons a judgement question needs: position attached to any sheet, roster-group depth, lineup composition, cohort tests, positional scarcity, spend vs return |

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
```

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
   currently exact for 2021-2025.

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

## Writing it up

- The note goes in `plan/notes/` — the question, the answer, the method, the
  guards that back it, and the caveats. `WHATIF_HERBERT_TRADE_2025.md` is the
  worked example.
- Anything reusable belongs in `lib/lotg_support/` with a test, not in a
  one-off script. A script in `scripts/` should be a thin CLI over it.
- Confirm the inquiry changed nothing that ships: `git status` should show only
  new files under `plan/notes/`, `scripts/`, `lib/`, `tests/`.
