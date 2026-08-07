# Inquiry playbook

How to answer a question about this league quickly, and over-inclusively, without
re-deriving the same primitives every time.

An **inquiry** here means a question answered *from* the committed data — "who
has the most X", "when did Y last happen", "would Z still have won without that
trade" — as opposed to a change to the build. Inquiries are read-only. They must
not alter `exports/`, `data/`, the workflows, or anything `python -m lotg`
produces. A written-up inquiry lands as a note in `plan/notes/` (plus, if it
needed one, a script in `scripts/`), never as a change to a build output.

## Answer first. Ask before you build anything.

**A question is a request for the answer, not for a pull request.** Most
inquiries are someone wanting a number in the next couple of minutes. Give them
that, then ask whether they want it made permanent. Everything else in this
document — the note in `plan/notes/`, the new primitive, the guard, the tests,
the PR — is **phase two, and it starts only when they say yes.**

### Phase one: the answer (target: under 3 minutes)

1. **Find the number and report it.** One command if a sheet has it, a scratch
   script if not. A throwaway script is *fine here* — the rule against them
   (below) governs what gets committed, not how you get the first answer.
2. **Clear the accuracy floor** (next section). Non-negotiable, and it is fast.
3. **Report the answer with its caveats inline**, in chat. Which snapshot/date it
   is as of, what was excluded, anything borderline (the over-inclusive rule at
   the bottom applies to a two-line answer exactly as it does to a note).
4. **Then ask**, in one line: *want this written up as a note / shipped as a
   helper + PR, or was the answer all you needed?*

What phase one does **not** include, no matter how obviously useful it looks:
writing to `plan/notes/`, adding anything to `lib/`, adding tests, running the
full suite (~2.5 minutes on its own), committing, or opening a PR.

### The accuracy floor — what speed never buys

**The 3 minutes is a target. Accuracy is the constraint.** They almost never
conflict: the checks below cost seconds, because the expensive parts of an
inquiry (the primitive, the test suite, the note, the PR) are the parts that
*prove* an answer to the next reader, not the parts that make it right. When
they do conflict, the budget yields — take the extra minute and say why. Nothing
here is ever traded away for speed:

- **Read the trap list before you trust a number.** It is at the bottom of this
  file, it is short, and every entry on it is there because it silently produced
  a wrong answer at least once. `PF` is not Sleeper's raw points; positions
  drift; 2020 has no snapshot; `"0"` is a legal empty slot; offseason trades sit
  in `week_01`; `Points added` is cumulative. Skimming it is ~30 seconds and it
  is the single highest-value thing in phase one.
- **Reconcile against a build number whenever one exists.** If the build
  computes the thing, or something adjacent, reproduce a handful of its rows
  before quoting yours. Three weeks is enough for a spot-check; the full sweep
  is phase two. This is what separates "I computed something" from "I computed
  *the same thing the league's tables report*".
- **When nothing can verify it, say so in the answer.** An unverifiable number
  is reportable — quietly presenting one as though it were checked is not. Name
  which parts are backed by a build figure and which are not.
- **Never round off a caveat to make the answer land cleanly.** The
  over-inclusive rule is not a phase-two luxury: as-of date, what was excluded,
  and any borderline item that could move the ranking go in the first reply.
- **If the fast path and a slower reading disagree, report the disagreement**
  rather than picking the one you got first.

A fast wrong answer is worse than no answer, because it gets acted on. If the
question cannot be answered accurately in three minutes, the honest phase-one
reply is the partial answer, what is still unverified, and how long the rest
will take.

### Phase two: only after they say yes

Then the rest of this document applies as written — the primitive instead of the
script, the `check_*` guard, the tests, `python -m pytest tests/ -q`, the note,
the draft PR. Ask which parts they want; "just the note" is a common answer and
is much cheaper than the full treatment.

### What phase one actually looks like

"Give all 8 teams by avg age (current rosters)" — a question with no sheet to
read it off (the exports stop at the last completed season) and no primitive
when it was first asked. Phase one was still four steps:

```bash
pip install pandas                                     # the one setup step
python scripts/inquire.py columns 'age'                # -> team_week "Player average age"
grep -n "Player average age" src/lotg.py               # -> how the build computes it
python scratch.py                                      # roster json x birth dates; 2s
```

The scratch script did both jobs at once: averaged today's rosters, *and*
recomputed the build's own column for three past weeks to prove the arithmetic
matched (24/24 exact). That is the accuracy floor cleared inside the budget —
the reconciliation was two extra lines in a script that had already loaded the
data. The primitive, the 680-week guard, the tests and the note all came later,
and only because the asker was asked first.

Note what the floor caught even on the fast path: rosters here run 29-36
players, so the average depends on whether taxi and IR count — worth a line in
the answer, not a silent choice.

### Two things that cost minutes if you rediscover them

- **`pandas` is not installed.** It is the *only* dependency the inquiry layer
  needs: `pip install pandas`, a few seconds. Do **not** `pip install -r
  requirements.txt` for an inquiry — it drags in ortools and takes minutes.
- **You do not have to read this whole file to answer.** Skim the tool table and
  the trap list; come back for the section you actually need. Reading 400 lines
  before running one command is most of the way to blowing the 3-minute budget.

## The tools

| Tool | For |
|---|---|
| `scripts/inquire.py` (`lotg_support.inquiry`) | finding, filtering and ranking anything in the twelve export sheets, and reading the raw Sleeper snapshot |
| `scripts/whatif.py` (`lotg_support.replay`) | counterfactual seasons: rewind a trade — or a whole sequence of them — or move a player, replay every week, re-seed, re-run the bracket |
| `lotg_support.analysis` (via `inquire.py group/stacks/compare/compare-all/correlate/stretch/timeline/scarcity/spend/age`) | the joins and comparisons a judgement question needs: position attached to any sheet, roster-group depth, lineup composition, cohort tests with FDR control, arbitrary time windows, entity timelines, positional scarcity, spend vs return, roster age (including the in-progress season) |
| `scripts/contract_study.py` (`lotg_support.contracts`) | the *real world* side: what an NFL contract predicts about fantasy production — signings ranked inside their position's market, matched against comparable players who did not get paid |
| `scripts/forecast.py` (`lotg_support.forecast`) | the season that has not happened yet: project rosters (rates, ageing, market-priced rookies, availability and depth), calibrate against completed seasons, simulate championship / playoff / seeding odds |

All of them are additive and read-only. None is imported by the build or run by
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

**Roster age, including right now.** The exports stop at the last completed
season, so `team_week."Player average age"` cannot answer "how old is each
roster *today*". `roster_ages()` recomputes that column from the snapshot, which
lets it run on the in-progress season:

```bash
python scripts/inquire.py age                          # current rosters, oldest first
python scripts/inquire.py age --pool starters          # or 'active' (no taxi/IR)
python scripts/inquire.py age --season 2025 --week 17  # the build's per-week reading
```

Rosters are not the same size in this league, so the pool is an assumption, not
a detail — a deep bench of young taxi stashes moves a mean. Default `all`
matches the build (taxi and IR included); re-run under `active` / `starters`
before quoting a gap between neighbouring teams. `--week` also takes `on=` in
Python, which is how you compare two different rosters at the *same* date and
strip natural ageing out of the delta. `check_roster_age_matches_build` ties the
whole thing to the built column for every team-week 2021-2025.
(`ROSTER_AGE_2026.md`.)

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

**What the NFL paid him.** Nothing in `exports/` knows about real-world money,
so a "does getting paid mean anything" question starts in
`lotg_support.contracts`, which joins Over The Cap's contract history (via
nflverse) to a player-season fantasy panel scored with this league's settings.

```bash
python scripts/contract_study.py study                 # big signings vs matched non-signers
python scripts/contract_study.py raw                   # signers vs themselves (the misleading one)
python scripts/contract_study.py decompose             # was it games or points per game?
python scripts/contract_study.py value                 # weekly points per 1% of cap, and what a cap slice buys
python scripts/contract_study.py signings --year 2025
python scripts/contract_study.py validate
```

The load-bearing idea is the control group: a big contract follows a career
year, so signers decline afterwards at every position and the raw before/after
measures regression to the mean, not the contract. `study()` matches each signer
to same-position, same-season players with the same prior-season output (and
age) who were not paid, and reports the paired gap with a BH q-value over the
whole family. Every choice — what counts as big, how close a control must be,
whether one-year deals count — is a parameter, and
`plan/notes/CONTRACT_VALUE_BY_POSITION.md` runs the sensitivity table.

## The season that has not happened yet

"Who wins this year" is not a lookup, so it has its own tool.

```bash
python scripts/forecast.py --season 2026            # % chance of each team winning
python scripts/forecast.py --season 2026 --detail   # injuries, depth, age, rookie class
python scripts/forecast.py --season 2026 --model all --seeds
python scripts/forecast.py --season 2026 --sensitivity
python scripts/forecast.py --calibration            # what the projection is worth
```

Five layers, each fitted from this league's own history and separately
inspectable: **player rate** (two seasons, recency-weighted, shrunk, then
age-adjusted on a fitted curve); **rookie price** (from draft-day KTC against
what past classes returned — this is what makes a weak class read as weak);
**who can play** (taxi and unsigned removed, availability simulated with the
lineup refilled from whoever is left, so depth costs points); **who plays whom**
(always the real pairings; `schedule(year)` says whether a season is a balanced
round-robin — 2026 is, 2021-2025 are not); and **calibration** against every
completed season, which is where the simulation's spread comes from.

Three strength models, `--model all` runs each: `roster`, `history` and
`uniform`. **Quote the distance from `uniform`** — that is what says whether the
projection is telling you anything.

**Two rules this tool exists to enforce.**

*Outside reporting goes in a dated, sourced file, never in code.*
`plan/notes/forecast_status_<year>.csv` is one row per player: availability, a
rate multiplier, a note saying why, a URL and an `as_of` date. It is the only
place a judgement about the real world enters, and `check_research_file` refuses
a row that names nobody on a roster or omits its source. Research rots — the
date is there so the next reader can see how badly.

*The backtest may not see the present.* Today's injury designations, today's
free agents and a research file written today are all future information to a
projection of 2022. Letting the free-agent check into the backtest lifts
out-of-sample r from 0.68 to 0.73 — that is leakage, not skill. The calibration
therefore runs with all three off, which makes it a floor for the live forecast
rather than a flattering estimate.

**Report the refinements' measured value, not their plausibility.** Ageing, KTC
rookie pricing, recency and the depth model are each real at player level and
each worth almost nothing at *team* level (out-of-sample r moves 0.759 → 0.766
across all of them, on 32 team-seasons — not significant). What they change is
which of two close teams is favourite. Say that plainly rather than dressing it
up as accuracy.

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

The analysis layer has its own three, in `tests/test_analysis.py`: the starter
points it rebuilds from `player_week` must equal `team_week.PF` (allowing the
+5), its `max_same_nfl_team` must equal the build's own "Most number of
players started from same NFL team" column for every lineup, and `roster_ages`
must reproduce `team_week."Player average age"` for every team-week.

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
- **The in-progress season is the mirror image: snapshot, no exports.** The
  build emits no `team_week` rows for a preseason week, so any "as of now"
  question (roster age, who is on which roster) has to come from
  `exports/snapshot/season_<current>/`, and any test asserting against it must
  use `completed_seasons()`. `Q.export_seasons()` and `Q.snapshot_seasons()`
  genuinely differ at both ends.
- **Only the current season's snapshot carries `traded_picks.json`.** Past
  seasons' folders have rosters, users and weeks but no pick file, so a
  pick-ownership question about a past date has to be reconstructed from trade
  events — the current-ownership shortcut works for "now" only.
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
- **nflverse's `historical_contracts` csv is a stale artifact.** The `.csv` /
  `.csv.gz` assets on that release stop at 2022 and carry no `gsis_id`; only the
  `.parquet` is maintained (and reading it needs `pyarrow`). `load_contracts()`
  refuses a file whose newest signing predates `MIN_EXPECTED_YEAR` rather than
  quietly answering a question about 2011-2022.
- **A contract row's `cols` is the player's whole career cap table, not that
  contract's.** Over The Cap hangs the same career table off every deal a player
  ever signed, so exploding the column without deduplicating to one row per
  player counts each season once per contract. `cost_panel()` does the dedupe
  and `check_cost_panel_is_one_row_per_player_season()` guards it.
- **Points-per-dollar is a ratio, and behaves like one.** FPTS/$1M is not
  comparable across seasons (the cap doubled 2011-2025; use points per 1% of
  cap), is dominated by rookie contracts, and persists year-over-year at
  0.34-0.44 when both its inputs persist at 0.64-0.83. Rank on it within a
  position and season or not at all — `contract_study.py value` prints all four
  diagnostics, and `rank_persistence()` is the general test to run before
  trusting any derived ratio. The weekly variant (`ppg_per_cap_pct`) needs a
  games floor on top: a one-game cameo on a minimum salary is the largest number
  in the dataset. What the ratio *is* good for is `cost_curve()` — what the next
  percent of cap buys, which falls steeply at every position.
- **`cap_percent` is rounded to three decimals.** Fine on a star's deal, worth up
  to 40% on a minimum one, which is exactly where a per-share metric is already
  weakest. `league_cap_by_season()` recovers the cap from the expensive
  contracts so the share can be taken from `cap_number` directly. It reads 1-6%
  above the *published* cap because Over The Cap normalises against each team's
  adjusted (carryover-inclusive) cap — a season-constant offset, so within-season
  rankings are unaffected.
- **nflverse gives return specialists an offensive position.** Matthew Slater has
  six seasons in the panel as a WR with a real cap hit and 0.00 fantasy points.
  They sit at the bottom of any value leaderboard without being fantasy players
  at all; nothing filters them today.
- **A player's own before/after around a big contract is regression to the
  mean.** Points fall at every position after a top-five deal, because the deal
  followed a career year. Any "did X change after Y" question about a player
  selected *on* his prior performance needs the matched-control shape in
  `contracts.study()`, not a paired before/after.
- **`picks` cannot price a pick that was traded, and `Points added` is
  cumulative.** Every return column on `picks` stops at the pick's *next
  transaction*, so a pick flipped before its player suited up scores 0 no matter
  what came back — 2025 1.08 (Judkins) reads as the worst pick of a rebuild that
  actually turned it into Zay Flowers. Follow the asset with `timeline` /
  `player_year` before calling a converted pick a loss. And rank picks against
  each other on the **rate** columns (`Avg points added adjusted by position` and
  its pick-adjusted difference), never on `Points added`, which rewards whoever
  has been rostered longest. (`WHATIF_TEARDOWN_2024.md`.)
- **The `strict` lineup model is degenerate for a player-for-picks trade.** It
  only lets an arrival occupy the slot the departing player vacated, so when a
  team sold stars for draft picks there is no vacated slot and the returning
  stars simply sit — the counterfactual PF can even fall. Report it, but read the
  spread from `anchored` and `ceiling`. (`WHATIF_TEARDOWN_2024.md`.)

### Forecasting traps

- **A roster's player list is not its startable players.** A week's `players`
  includes the **taxi squad** and anyone on **reserve/IR**, neither of which can
  be started. Feed that list to an optimal-lineup routine and it will cheerfully
  start a taxi quarterback — in 2026 that meant Patrick Mahomes (reserve)
  reading as plehv79's best player and Fernando Mendoza (taxi) making
  Oliverwkw's lineup. `forecast.startable_pool` removes taxi. A rostered player
  with **no NFL team** is the same problem with a different cause.
- **In the preseason, Sleeper's injury flags are stale.** A manager parks a
  player in the IR slot in December and never moves him, so an August snapshot
  records how *last* season ended: 11 of the 15 players flagged on 2026 rosters
  were injured in the closing weeks of 2025, and the flags were wrong in both
  directions (three fully healthy, one an unsigned free agent). The season's
  `nflverse_injuries.csv` is empty until games are played. Believe the flags
  only in season; before that, use dated outside reporting.
- **The regular season is not always a round-robin.** 2026's fourteen weeks are
  a clean double round-robin (every pair twice, so no strength-of-schedule edge
  can exist); 2021-2025 ran fifteen, where some pairs met three times and some
  twice. And SoS must be measured against the *other* teams, not the
  whole-league mean — a team never draws itself, so comparing to a mean that
  includes it reads every strong team as having an easy schedule.
- **The rookie draft is not all rookies.** Veterans get picked in it (2026 had
  Darnell Mooney at 4.07 and Chig Okonkwo at 3.02), so a draft-slot prior must
  only be applied to players with no history of their own. And the reverse trap:
  projecting a real rookie at zero penalises whoever holds the most picks —
  `forecast.rookie_price` prices him from draft-day KTC instead.
- **`team_year.Points` includes the playoffs**, so it is not "how good was this
  team": four teams play two extra weeks and four do not. Any strength measure
  has to come from `team_week` filtered to `regular_season_weeks`.

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

## When the helper you need does not exist — offer it, then add it

**Phase two only.** Answer the question first with whatever gets you there
fastest, including a scratch script, and ask. A missing primitive is a reason to
*offer* to build one; it is not permission to spend twenty minutes building it
before anyone has seen the number.

Once they say yes: this toolkit is meant to grow. If a question needs a
primitive that is not here, **commit the primitive, not the throwaway script**
— the next inquiry of that shape should start where this one finished. Ship it
as its own PR, separate from the answer.

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

**Phase two only** — a note is what an answer becomes when someone asks for it
to be kept, not the default shape of a reply. The answer itself belongs in chat,
first.

- The note goes in `plan/notes/` — the question, the answer, the method, the
  guards that back it, and the caveats. `WHATIF_HERBERT_TRADE_2025.md` is the
  worked example.
- Anything reusable belongs in `lib/lotg_support/` with a test, not in a
  one-off script. A script in `scripts/` should be a thin CLI over it.
- Confirm the inquiry changed nothing that ships: `git status` should show only
  new files under `plan/notes/`, `scripts/`, `lib/`, `tests/`.
