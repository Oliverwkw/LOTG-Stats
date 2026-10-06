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
  CI runs the pinned pandas 3.0.6 (Python 3.11); a pandas 2 laptop reads the
  exports' text columns as `object` where CI reads `str`. For anything
  dtype-sensitive, reproduce CI with `pd.options.future.infer_string = True`.
- **You do not have to read this whole file to answer.** Skim the tool table and
  the trap list; come back for the section you actually need. Reading 400 lines
  before running one command is most of the way to blowing the 3-minute budget.
- **`scripts/build_digest.py` only reads `--snapshot` unless you pass
  `--write-snapshot`** (#468; before that it overwrote the file, and a second
  comparison run diffed against the first run's output). To replay a later
  week, run once with `--write-snapshot` on a copy, then again without it.

## The tools

| Tool | For |
|---|---|
| `scripts/inquire.py` (`lotg_support.inquiry`) | finding, filtering and ranking anything in the fourteen export sheets, and reading the raw Sleeper snapshot |
| `scripts/whatif.py` (`lotg_support.replay`) | counterfactual seasons: rewind a trade (3-team deals included) — or a whole sequence of them — or move a player, replay every week under four lineup models (incl. the `Wins added` rule), re-seed, re-run the bracket |
| `lotg_support.analysis` (via `inquire.py group/stacks/compare/compare-all/correlate/stretch/timeline/ownership/scarcity/spend/age`) | the joins and comparisons a judgement question needs: position attached to any sheet, roster-group depth, lineup composition, cohort tests with FDR control, arbitrary time windows, entity timelines, who owned whom and in what order, positional scarcity, spend vs return, roster age (including the in-progress season) |
| `scripts/draft_capital.py` (`lotg_support.draft_capital`) | what a draft slot returns across *all* rounds, who gets which slot under each era's ordering rule, and what moving up the order costs in roster ceiling |
| `scripts/contract_study.py` (`lotg_support.contracts`) | the *real world* side: what an NFL contract predicts about fantasy production — signings ranked inside their position's market, matched against comparable players who did not get paid |
| `scripts/forecast.py` (`lotg_support.forecast`) | the season that has not happened yet: project rosters (rates, ageing, market-priced rookies, availability and depth), calibrate against completed seasons, simulate championship / playoff / seeding odds |
| `scripts/touchdowns.py` (`lotg_support.scoring_events`) | what a player actually DID rather than what he was worth: nflverse's stat lines joined onto this league's starters — touchdowns scored (and thrown) per starter-week, the scan for lineups that reached the end zone with nobody, and career totals in any nflverse stat, both as of a start and lifetime |
| `inquire.py gametime` (`lotg_support.gametime`) | when in the week the points came: the margin entering ANY stage (`--entering SNF / Monday / 'last game'` or any game slot — `'Sunday late'`, `Thursday`, …), comebacks: margin overcome (behind at the time) and points overcome (vs the opponent's final, with %s and per player left; `--comebacks --by margin|points|size`), Comeback size (standard deviations behind the expected finish × how close the team got; `--whole-week` for every kickoff of the matchup), and starter points per team-week by game slot (`--slots`); Thanksgiving / Christmas / doubleheader weeks fall out of the schedule |
| `scripts/boldness.py` (`lotg_support.boldness`) | how bold a lineup call was, 2020 on: each start against the best STARTABLE bench player (taxi counts as bench), on PRE-KICKOFF expected points (recency-weighted history scored with the judged season's rules, LOTG rookie-slot prior for a rookie's first weeks, next-man-up cuff promotion), plus bust odds; every week counts, tank weeks included; and team-week ex-ante Max PF minus expected PF |

All of them are additive and read-only. None is imported by the build or run by
any workflow — except `lotg_support.wins_added`, which IS the build's `Wins
added` column; its `explain()` is the inquiry entry point (see "Counterfactuals"),
and `lotg_support.boldness`, which IS `player_week` "Boldness" and the team
sheets' "Lineup Boldness" (the build feeds it its own data through
`build_inputs`). A change to either is a build change. So is
`lotg_support.gametime`: it IS `player_week` "Game slot" and the team_week
"Margin entering …", "… overcome (entering …)", "% of own points scored …" and
"Comeback size" columns.

## Start here, not with a script

```bash
# 1. Which sheet and column holds the concept? (~1,000 columns across 14 sheets;
#    column names AND their documented notes are searched)
python scripts/inquire.py columns 'efficien|max pf'
python scripts/inquire.py describe team_week Efficiency
python scripts/inquire.py formula 'Wins added'          # in words AND as an equation in raw API
                                                       # variables (+ the glossary symbols it uses);
                                                       # --sheet to pick one, --no-glossary to trim

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

**What a player actually did, not what he was worth.** Every sheet here stops
at points: `player_week` knows a starter scored 14.6, not that he caught a
touchdown, and the snapshot's per-week `stats_nfl.json` is an empty list in
every season folder. `lotg_support.scoring_events` supplies the missing side by
joining nflverse's weekly stat lines onto the league's own starters.

```bash
# team-weeks where no non-QB starter reached the end zone
python scripts/touchdowns.py drought
python scripts/touchdowns.py drought --qb-rule slot      # the superflex QB counts too
# one lineup, player by player; a season's scorers
python scripts/touchdowns.py lineup --season 2025 --week 12 --team Oliverwkw
python scripts/touchdowns.py scorers --season 2025
# the thinnest careers anyone ever started, lifetime or as of the start
python scripts/touchdowns.py career --position RB
python scripts/touchdowns.py career --measure career_to_date --min-years 3
```

For a career question the two numbers are `career_total` (the whole career,
including everything after) and `career_to_date` (what he had entering that
game — the résumé the manager was looking at), over any nflverse column:
`--stat receiving_yards`, `--stat carries`, whatever the question needs. They
rank differently and the tenure filter that belongs with each differs too, which
is what `DEFAULT_YEARS_RULE` encodes.

A passing touchdown is thrown, not scored, so it rides in its own column and is
never counted in `touchdowns`; `qb_rule` decides whether "non-QB" means the
player's position (superflex quarterback excluded) or the lineup slot (only the
dedicated QB slot excluded) — the two give different answers, which is why it is
an argument rather than a constant. A starter with no stat line comes back
`resolved=False` and is counted in the scan's `unresolved` column instead of
passing as a confident zero. `check_touchdown_join()` is the guard: no sheet
carries a touchdown, so it re-scores each matched stat line into league settings
and holds it against the starter points the build already published.

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

**The story of every entity at once.** `timeline()` takes one player at a time,
so it cannot answer "across *all* players, who has property P about their
ownership history". `ownership_ledger()` is the vectorised form — one row per
acquisition (draft, waiver add, trade) for the whole league, with the sending
roster named — and `ownership_summary()` collapses it to one row per player:

```bash
# who kept bouncing between the same two rosters?
python scripts/inquire.py ownership --min-trades 3 --max-teams 2
# the full route, one player at a time
python scripts/inquire.py ownership --player 'Alvin Kamara'
# re-acquired by a roster that already had him
python scripts/inquire.py ownership --min-boomerangs 4
```

`spells` counts acquisitions, `teams` counts *distinct* rosters, and the gap
between them is the point — `boomerangs` and `path` say where he went back to.
`check_trade_counts_match_build` ties the ledger's trade rows to
`player_all_time."Number of trades"` for all 651 players, exactly, which is what
licenses quoting it — in both directions, so an asset the ledger mistook for a
player (cash, a pick) is caught rather than passing for want of a row to compare
against. `check_ledger_chains` is the stronger one: all 464 trade hand-offs must
take the player from exactly the roster the ledger last had him on, which tests
ordering, sender attribution and the snapshot/sheet merge at once.
(`OWNERSHIP_PING_PONG.md`.)

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

**Draft capital, and what a tank actually buys.** "Is it worth blowing it up for
the first pick" is three questions, and doing it by hand walks into the `picks`
traps every time.

```bash
python scripts/draft_capital.py haul               # what a slot's WHOLE draft returned
python scripts/draft_capital.py slots --statistic bust_rate
python scripts/draft_capital.py cohorts            # the two comparisons that matter
python scripts/draft_capital.py order --all        # who gets which slot, under each rule
python scripts/draft_capital.py cost --draft 2026 --team Oliverwkw
```

`haul_table()` prices a draft position across all four rounds, because owning
1.01 means owning 2.01/3.01/4.01 and the rounds behave nothing alike.
`slot_cohorts()` runs the two comparisons through `analysis.compare` — bottom
four vs playoff teams (**+416, p=0.002**), and the marginal one, slots 1-2 vs
3-4 (**−155, p=0.53**) — so the answer arrives with both cohorts and a per-draft
breakdown rather than a mean. Note the `aggregate` parameter: a **rate** column
must be compared per pick, never summed across a slot's four picks.

`bottom_four_order()` implements both ordering rules and `order_rule()` says
which era a draft belongs to. `ceiling_cost()` prices moving up in the currency
the current rule uses — which players must leave for a roster's Max PF to reach
a target — by calling the build's own `lineup.compute_optimal_lineup`.
`check_max_pf_matches_build` and `check_bottom_four_order_matches_picks` tie
both halves to the build. (`TANKING_AND_DRAFT_CAPITAL.md`.)

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

For "did this pickup / pick / trade beat its price", read player_additions'
`Price paid (FAAB)` (every channel, trades included) and `Points above
expectation (total / rate)` (`lotg_support.acquisition`): what he scored for the
team minus what same-channel, same-price, same-position buys actually scored
over the same weeks, never-cut. Two things to know: the model refits every build
(a row moves a little each week), and long holds of hits read high by design.
`plan/notes/POINTS_ABOVE_EXPECTATION.md` has the evidence and the rejected
variants.

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

**Boldness — a start/sit call judged on what was knowable.** The same
comparison as `player_week`'s "Difference in averages of best/worst startables
over previous 5 games" — each starter against the best startable bench player
— built out to measure boldness instead of hindsight: that column picks its
reference by what he ACTUALLY scored that week (and does not enforce that he
could legally have started); `lotg_support.boldness` picks the bench player
with the best PRE-KICKOFF expectation who could come into the lineup in the
starter's place, the others reshuffling slots as needed. 2020 included (from
the ESPN backfill, as Wins added reads it). Exported as `player_week."Boldness"`
(starters; N/A on the bench) and `"Lineup Boldness"` on team_week / team_year /
team_all_time (ex-ante Max PF minus expected PF; the year and all-time cells are
the AVERAGE per lineup, not a sum).

```bash
python scripts/boldness.py week --season 2026 --week 4 --team BROsenzweig
python scripts/boldness.py top -n 20            # every week counts, tank weeks included
python scripts/boldness.py top --position QB
python scripts/boldness.py managers
python scripts/boldness.py teams                # ex-ante Max PF - expected PF
python scripts/boldness.py validate
```

`Boldness = max(0, E[best startable bench] - E[starter])`, with `Bust odds` the
calibrated chance the reference outscores the starter. E is a shrunk weighted
average of the player's own NFL games scored with THE JUDGED SEASON's settings
(2020 was not PPR; 2021 week 1 re-scores its 2020 games as PPR): recent games
weigh most (a weight that halves every few games played), last season's games
are discounted again, a game for another NFL team more; a rookie drafted here is
priced from his LOTG rookie-draft slot, fitted on earlier picks' ROOKIE-YEAR
points only, for his first few weeks — the slot's weight fades to nothing by
week 4, then he is judged on his own games (Achane 2023: not bold to start after
his breakout); a next man up whose higher-E teammate sits out is lifted to
a x the teammate's E + b x his own, (a, b) fitted per position on NFL events
2019-2025 (one beta x the teammate's E overrated weak backups by ~3 points and
underrated strong ones by ~2.5); the next man up is a backup the team has USED
this season, so a healthy-scratch rookie on his draft-round prior is not in line
(2026 wk 4: the Jets' lift went to one over Braelon Allen), and among those the
one who got the ball more in the games where both played — touches for backs
and QBs, targets for receivers and tight ends — not the higher E (Sleeper's
depth chart is current-only, so it cannot say who was next in 2022). `check_calibration` holds the
slope of (starter - reference) actual points on Edge near -1.

A rostered player with no game in the three-season window (Philip Rivers'
2025 return, Travis Etienne's lost 2021) is priced at the positional prior, not
left N/A. The lineup's ex-ante max is `best_lineup_value` (exact, using each
player's per-season slot eligibility, the same as the starts), NOT
`lineup.compute_optimal_lineup`. Fed expectations, that one's single *current*
position per player put Cordarrelle Patterson (RB today, WR in 2021) out of the
WR slot and returned a "best" lineup below the one actually set. The
invariant: Lineup Boldness >= the boldest single start of that lineup.

**Inquiry = export, to the cent.** `scripts/boldness.py` reproduces the exported
column because:
- the lift (a, b) is a pure NFL fit (the no-history fallback is kept out of the
  calibration, so the league's rosters cannot move it);
- outside the build, weeks stop at the last one the committed build finalized
  (its team_week rows). "Any points" alone counts a week in progress from
  Thursday night on.

`Q.played_weeks` is FINAL weeks only: weeks with points, capped at
`Q.finalized_week` (the committed build's last team_week). Every inquiry tool
counting weeks with it (analysis, draft_capital, forecast, replay, boldness)
therefore ignores the week in progress, which has points from Thursday night
on. For "has the season begun?" pass `include_in_progress=True`, as the
forecast's designation switch does.

**Empty slots are not boldness** [per user, 2026-10-02]. Both halves judge a
lineup on the slots that were FILLED: the ex-ante max fills only those, and a
starter's reference must be able to take his place among them. An empty slot
(a tank, or a clinched game coasted: shmuel256 emptied 2 slots in the 2020
Final once it was won) is counted in team_week `Empty slots`, summed on
team_year / team_all_time, and `boldness()` keeps its row with no Boldness. A DEAD START (a starter
flagged bye / injured / suspended who scored 0) is judged exactly like an empty
slot — no Boldness, slot out of the comparison, `Dead start?` in `boldness()` —
and is counted in `Empty slots` too [per user, 2026-10-05].

## The season that has not happened yet

"Who wins this year" is not a lookup, so it has its own tool.

```bash
python scripts/forecast.py --season 2026            # % chance of each team winning
python scripts/forecast.py --season 2026 --detail   # injuries, depth, age, rookie class
python scripts/forecast.py --season 2026 --model all --seeds
python scripts/forecast.py --season 2026 --sensitivity
python scripts/forecast.py --calibration            # what the projection is worth
python scripts/forecast.py --backtest              # has it ever been right?
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

**Score the probabilities, not just the projection.** `--backtest` rewinds every
completed season to its preseason, forecasts it strictly out of sample
(calibration, rookie price and age curve refitted leaving that season out) and
scores it against what happened: champion log-loss 1.85 against 2.08 for
guessing, playoff Brier 0.152 against 0.250, seed rank correlation 0.62 against
−0.04, the favourite winning 3 of 5. `check_beats_uniform` makes that a guard.
Two further habits it enforces: `as_of_week` lets you ask what the model would
have said in week 8, and the **confidence ratio** — realised score over the score
the forecast expects of itself — tests whether it was over-confident without
needing any baseline (a uniform forecast scores exactly 1.00).

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
are four, and `--model all` runs each:

- **anchored** (default) — the real lineup minus departures; an arriving player
  starts only if his real manager started him that week; holes and surpluses are
  resolved by prior-form PPG subject to slot legality, skipping anyone the build
  flags bye/injured/suspended. No hindsight.
- **strict** — the arrival plays only in the departing player's slot, matched by
  position. Nothing else moves.
- **ceiling** — the score moves by the change in the roster's optimal lineup,
  using the build's own Max PF routine.
- **plausible** — the build's `Wins added` lineup rule, called rather than
  copied (`wins_added.cf_lineup_points`): every slot a departing starter clears
  is filled by a different player; an arrival takes one explicit role (fill a
  cleared slot, take a real empty slot, or displace one named starter), with
  players sliding between slots to make room; the bench only fills cleared
  slots, never displaces anyone; every substitution must be plausible (incoming
  last-3-game average ≥ outgoing − 5; with h slots cleared a fill is judged
  against the h-th best option), a player nobody started counts for at most
  1.5× that average, and a rookie in his first 3 games never moves in.
  Hindsight picks among the plausible options. On the 2025 Herbert trade all
  four models agree (13-2, weeks 6 and 8); on the 2024 teardown it has
  Oliverwkw 9-6 (anchored / ceiling 8-7) but stevenb123 still champion.

In every model, **a player on nobody's roster scores his nflverse line** under
that season's league scoring (it used to count 0.00), **a 3-team trade undoes
itself** — each player goes back to the roster Sleeper says sent him — and
anchored's prior form before a player's first game is his last-3-NFL-game
average (week 1 used to be a tie at 0, so its surplus cut was arbitrary).

**Report where the models disagree rather than picking one.** If they agree, say
so — that is the strongest form the answer can take.

### "Why is this move −7?" — `Wins added`, game by game

`trades` and `add_drops` carry `Wins added` (games the move swung, from the move
to today, each week against the real opponent, no re-seeding) and `Wins added
per season` (× 17 / games since the move). Unlike `whatif.py`, this is a BUILD
column (`lotg_support.wins_added`, imported by `src/lotg.py`), so the question
is usually "which games make up the number", not "what would the season have
been". `explain()` answers it in seconds:

```python
import sys; sys.path.insert(0, "lib")
from lotg_support import inquiry as Q, wins_added as W

league = W.load_league(Q.load_sheet("team_week"), W.nflverse_points_from_cache())
trades, adds = Q.load_sheet("trades"), Q.load_sheet("add_drops")
moves = W.moves_from_sheets(trades, adds, league,
                            [Q.load_sheet("rookie_picks"), Q.load_sheet("non_rookie_picks")])
later = W.later_moves(moves)
mv = next(m for m in moves if m.sheet == "trades" and m.index == 491)  # stevenb123 gets McBride
W.explain(mv, later[id(mv)], league)          # [(((2023, 15),), 'LWebs53', 1.0), ...]
W.lineage(mv, later[id(mv)], W.local_value_fn())   # what the return turned into, with shares
W._given_up(mv, league, later[id(mv)])        # given-up players and their (start, end) weeks
```

Things to know before quoting one:

- **The rules are the user's, and each one moves the number** — given-up
  players count until the league lets him go (4 straight weeks on no roster) or
  the team re-acquires him; received ones while held, following later trades
  at their KTC share; FAAB is ignored; a substitution counts only if plausible
  (incoming 3-game average ≥ outgoing − 5), with a 1.5× cap on anyone nobody
  started and no rookie in his first 3 games ever moved in. The whole rule is
  the module docstring and the Formulas rows; `plan/MASTER_TODO.md` → "Wins
  added" has the history (it summed −726 / −522 before the plausibility test).
- **A recompute matches the build only with the build's inputs.** Score
  nflverse through the build's persisted bridge
  (`exports/raw/wins_added_gsis_bridge.csv`, read by default) or the 3-game
  averages drift and games flip. Rows whose lineage passes through a later
  trade use KTC shares: to reproduce them, replay the build's player values
  from `exports/raw/ktc_provenance.csv` (the #458 audit did, 2,176/2,176).
  `local_value_fn()` builds its own index (~2 min) and differs in the decimals.
- **Old moves swing more games by design** — compare `Wins added per season`
  across eras, the total within one. A brand-new move reads ±17 / ±8.5 after
  one or two games; the weekly email holds it off the rate boards for 5 weeks.
- **It is not `Trade addition value`** (per-game quality, every game counts)
  **nor `Trade impact score`** (a z-scored grade whose win term only looks at
  weeks a received player started). Say which one you are quoting.

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

- **A comeback is measured against the opponent's FINAL score, not the margin
  at the time** [per user, 2026-10-05]. So a team AHEAD going into Monday whose
  opponent then pulled clear on Monday night has a "Points overcome (entering
  Monday)" too (plehv79, 2023 Semifinal: +3.68 going in, 55.12 overcome). "Margin
  overcome" is the at-the-time deficit (old definition), as are the "Margin
  entering …" columns. (Names before 2026-10-06: "Down entering X comeback (…)".)
  **Comeback size is a model, not a count** [per user, 2026-10-06]: standard
  deviations behind the expected finish (starters' expected points: this season
  so far, padded with last season and the position average — nothing from later
  weeks) × the win chance the team later reached. It counts a lead held while the
  opponent's late players flopped (own players left: 0) — quote the margin columns
  too when that matters. The % columns are fractions. Monday includes 2020's
  Tuesday / Wednesday makeups; the abandoned 2022 week 17 Bills-Bengals game,
  struck from the nflverse schedule (the Damar Hamlin no-contest), is put back
  as a NORMAL game with a short stat pool [per user, 2026-10-05: "same thing as
  if all the players got injured midgame"] — `lotg_support.struck_games`: the
  schedule row goes back wherever the schedule is read, the 29 real stat lines
  (Sleeper's stats API → `data/struck_game_stats.csv`, nflverse schema, written
  by `scripts/struck_game_stats.py`) go back into the weekly stats and season
  totals, and the 4 who dressed and recorded nothing (Chase, Knox, Gabe Davis,
  Perine) are `active` in data/game_day_status.csv (snaps were voided too; none
  was on either inactive list). Before this, those 4 were flagged `Bye?` (Chase
  a dead start: BROsenzweig's 2022 3rd-place game showed 1 Empty slot) and every
  nflverse-based number (pre-pickup PPG, Wins added, expected points, cuffs)
  treated the game as unplayed — Hayden Hurst's 4.5 in it was in no dataset.

- **`team_week.PF` is not Sleeper's raw `points`.** The league gives the higher
  seed in each semifinal +5 (home field) and the build bakes it into `PF`.
  Twelve rows carry it, all in the playoff-start week: two per season 2020-2025
  (2020's are week 15 and come from the ESPN backfill, so snapshot-based checks
  see only the ten from 2021-2025). Anything derived from `PF` — Efficiency
  included — inherits the +5. `inquiry.SEMIFINAL_HOME_BONUS`.
- **2022 week 16 Toilet Semis (plehv79 v shmuel256) was thrown on purpose.**
  A tankathon matchup: while placement counted the toilet bowl (see that entry below),
  winning it cost draft position. plehv79 scored 45.36 (32.8% efficiency, the
  league's lowest ever) and shmuel256 67.16 (47.3%). Treat both rows as
  intentional, not performance — they top any "worst week" or efficiency-drop
  board and plehv79's week 17 then tops the rebound board. Confirmed by
  Oliver, 2026-09-27; see `plan/notes/EFFICIENCY_WEEK_OVER_WEEK.md`.
- **Streak columns mix numbers with the text `"In Progress"`.** 46 player_week
  and 15 team_week streak columns hold integers, with `"In Progress"` on rows
  whose run had not yet ended (terminal encoding), so pandas
  reads them as text and a naive `.sum()` / `.mean()` / `sort_values` is wrong or
  raises. Read them with `pd.to_numeric(..., errors="coerce")` — the build's own
  readers (`digest._MISSING`, `sanity.py`) already drop the sentinel, and nothing
  in the build does arithmetic on the exported strings. Left as-is by user
  decision (2026-09-30): the sheet is read by people, and the sentinel says
  something a blank would not.
- **The snapshot records no stat lines at all.** Every
  `season_*/weeks/week_*/stats_nfl.json` is an empty list, in all six seasons —
  so nothing in this repo knows what a player DID, only what he was worth.
  Touchdowns, carries and targets have to come from nflverse;
  `scoring_events.starter_touchdowns()` is that join, already guarded.
- **nflverse back-corrects a stat line; Sleeper never re-pays for it.** A
  touchdown reassigned weeks later moves the stat and not the fantasy points.
  Three starter-weeks in this league are a whole touchdown apart between the two
  — 2022 week 14 Tyreek Hill, 2023 week 4 Terry McLaurin, 2024 week 2 Trey
  McBride — inside the ~1.3% of rows that re-score to anything but the build's
  own number. Fine for a rate; an answer that turns on one player should be read
  against both sources.
- **An nflverse SEASON file holds three rows per player**: `REG`, `POST` and
  `REG+POST`, the last being the sum of the first two. Summing a column across
  the file double-counts every career. `scoring_events.CAREER_BASES` picks the
  rows; nothing reads a `REG+POST` row.
- **"Years in the league" has three readings, and they change the answer.** A
  player's tenure AS OF a start is not his career length: Jahan Dotson was a
  2022 rookie started in 2023 — two years in at the time, four counting the
  career he went on to have. `scoring_events.YEARS_RULES` names all three
  (`at_start` / `roster` / `played`) rather than picking one silently.
- **nflverse renames players between vintages.** John Metchie is
  "John Metchie III" in the 2023 files and "John Metchie" in 2024, so a
  career assembled by NAME loses seasons without erroring. Join on `gsis_id`;
  `gsis_bridge()` and the 2020 name fallback exist for exactly that.
- **An inquiry that touches the in-progress season pulls its file into
  `.cache/` and stamps `_fetch_log.json`.** That is the build's own loader doing
  its job; the pair is consistent. Reverting the log to keep `git status` clean
  while leaving the file behind is not — `test_refresh_external` then reports an
  undated cache file. Drop both or keep both.
- **The newest seasons have no season-totals file**, so a career total is
  stitched from seasonal files plus the weekly file for the rest — and the two
  sources drift, because nflverse revises a season after publishing its totals
  (12 of 4,328 overlapping player-seasons when this was written; Kyler Murray's
  2019 rushing yards are 539 in one and 544 in the other). Both
  `check_career_sources_agree` and `check_career_to_date_arithmetic` measure the
  rate rather than asserting an identity.
- **A cancelled game leaves fantasy points with no stat line.** The 2022
  Bills-Bengals week 17 game was abandoned and struck from nflverse while
  Sleeper kept the partial points — five starter-weeks in this league, which is
  why `resolved=False` exists rather than a confident zero.
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
- **Some `transactions.csv` rows are synthesized, and they count.** The build
  fabricates lineage-closing moves — the 2020->2021 platform-transfer releases,
  terminal dead-end cuts, arrivals with no recorded add — so ownership history
  has no holes. They look like ordinary drop-only rows with no FAAB and no bid
  count, and they are a large share of some team-seasons (nearly all of
  `JacobRosenzweig 2021`). They are counted in the team totals like any other
  row; do not filter them out of a "how many moves" answer, and do not read
  their blank FAAB as a zero-dollar claim — there was no claim.
- **A move's season is not its calendar year, and its week is not its date.**
  Season is the first championship not yet played (`_move_season`), read on the
  league clock. Its week is its DATE on the Tuesday-Monday league week
  (`_season_week_of`) — for team_week's Add/Drops, trades and FAAB alike — and an
  offseason move has no week at all (team_year still counts it). Sleeper's own
  `leg` is NOT the week: it files every offseason move under week 1, so the raw
  `season_YYYY/weeks/week_01/transactions.json` holds the whole offseason.
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
- **`Injury?` means "missed the week, and it was not a bye or a suspension" —
  not "was hurt".** It is the residual bucket, per its own note in
  `formulas.csv`, so a healthy scratch that was declared Out lands in it: 13 of
  the 33 flags 2026 week 1 carries are `Out` with an `injury_body_part` of
  "Coach's Decision", mostly backup and rookie quarterbacks. That is the
  league's decision, not a defect — but an injury RATE taken off `Injury?`
  overstates by that share, and the reason is recoverable, because
  `data/injury_tracker.csv` captures `injury_body_part` alongside the flag.
- **Sleeper's `injury_status = "NA"` is the commissioner exempt list, and this
  league counts it as a suspension.** It used to decide nothing, on the grounds
  that NA is ambiguous (96 players carry it, 65 of them teamless and
  "Inactive"), and the cost was Josh Jacobs's 2026 week 1: 0.00 points, no
  participation, no nflverse stat line, recorded as a played 0.00. The teamless
  NA players are still safe because a bye outranks a suspension, not because
  anything filters them — see `injury_tracker._SUSPENSION_TOKENS`.
- **The tracker's gsis bridge is not Sleeper's `gsis_id` field.** Sleeper
  carries one for 40 of the 247 players on the 2026 rosters and pads them with
  whitespace (`' 00-0035700'`); the DynastyProcess table closes the gap to 245,
  and it stocks five `AAA######` PLACEHOLDERS (`WAS569019`) that look like ids
  and join to nothing — `looks_like_gsis()` rejects them. The two blanks are
  Jack Strand and Mike Washington, undrafted 2026 rookies whom nflverse has a
  real id for but carries no `sleeper_id` against.
  `injury_tracker.resolve_gsis()` / `sleeper_gsis_bridge()`, and
  `data/injury_tracker.csv` now carries the resolved id per row, so a
  participation cross-check against nflverse needs no id chasing. Its
  `position` column is pinned at capture time too — Sleeper flipped Travis
  Hunter to `DB` on 2026-09-08 and the raw label disagrees with every sheet.
- **Offseason trades live in `week_01`** of the season they precede. The
  Herbert deal is dated 2025-08-07 and sits in `season_2025/weeks/week_01`.
- **An asset cell holds three kinds of thing, and only one is a player.**
  `trades.Assets received` is free text. A pick in it is written
  `2021 1.06(T. Etienne)`, so splitting the cell on `;` reads `T. Etienne` as a
  player who changed hands — inventing a 2020 trade for someone who did not
  enter the league until 2021. FAAB is written `$15 FAAB` (166 tokens, 2022
  onward), and being neither a pick nor a placeholder it survives any test that
  only looks for those, turning cash into a traded player. The build never hits
  either (it counts by Sleeper pid, off `_recv_player_ids`); both are purely
  hazards for code reading the *exported* sheet, where the pids are gone.
  `analysis.split_assets()` returns the three separately.
- **Sleeper can record one exchange twice.** When picks change hands around the
  draft that converts them, there can be both a pick trade and a player swap
  executing it — the league's one instance is 2021-08-29, LWebs53 and shmuel256
  trading 2021 2.08 for 3.06 (+ two fourths) and separately swapping the two
  players those picks became, Michael Carter for Rhamondre Stevenson. Counting
  both moves each player twice for one deal. `analysis.DUPLICATE_TRADE_TRANSACTIONS`
  holds the id and the reasoning; `check_trade_counts_match_build` is the
  detector if another one ever appears.
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
- **The picks sheet is TWO sheets, and their O-Scores are not comparable.**
  `non_rookie_picks` (the 2020 startup + the 2021 vet draft) and `rookie_picks`
  (every rookie draft) are ranked in separate percentile universes, and only the
  non-rookie one is de-trended for draft slot (each score moved three quarters of
  the way off a fitted `a + b·ln(overall pick)` expectation). Their `Player
  addition value` also carries a starts-length term — as does
  `player_additions`', which is the cross-channel comparable. `add_drops` and
  `trades` do NOT: their addition value is a difference against a dropped/sent
  side, not a one-sided level, so length would say something different there. So a 61 on one sheet does not
  mean what a 61 on the other does — never pool the two and rank O-Score across
  them. `Q.load_sheet("picks")` still works and returns the two CONCATENATED,
  which is right for anything except O-Score comparisons; ask for the sheet by
  name when the distinction matters. Drafting skill weighs a non-rookie pick
  0.5 against a rookie pick's 1.0.
- **`picks` cannot price a pick that was traded, and `Points added` is
  cumulative.** Every return column on `picks` stops at the pick's *next
  transaction*, so a pick flipped before its player suited up scores 0 no matter
  what came back — 2025 1.08 (Judkins) reads as the worst pick of a rebuild that
  actually turned it into Zay Flowers. Follow the asset with `timeline` /
  `player_year` before calling a converted pick a loss. And rank picks against
  each other on the **rate** columns (`Avg points added adjusted by position` and
  its pick-adjusted difference), never on `Points added`, which rewards whoever
  has been rostered longest. (`WHATIF_TEARDOWN_2024.md`.)
- **The draft-order rule changed at the 2026 draft.** Through 2025 the bottom
  four picked in reverse final placement; from 2026 they pick in **ascending
  Max PF** — roster ceiling, not record. Peter finished 5th with the league's
  worst ceiling and picked 1.01; Oliver finished 8th and picked 1.03. Applied
  retroactively the rule moves the 1.01 in four of six drafts, so any
  historical tanking claim has to say which rule it assumes.
  `draft_capital.order_rule()` / `MAX_PF_RULE_FROM_DRAFT`, guarded against
  `picks."Original Team"` for every draft on record.
- **The playoff block's draft order is not a rule this data can pin down.** It
  is reverse placement through the 2022 draft and swaps 3rd/4th from 2023 on,
  with no stated reason. `draft_capital.playoff_block()` returns what was
  observed; nothing models it.
- **Placement counted the toilet bowl through the 2024 draft.** Non-playoff
  finishes used record through week ≤17 for 2020-2024 and the regular season
  only from 2025 (`src/lotg.py:14907`), so winning consolation games used to
  cost draft position: Jacob went 3-12 in 2023, won both toilet games, and lost
  the 1.01 to a 5-10 team on a **1.92-point** PF tiebreak.
- **Slots above the league size exist.** The toilet-bowl reward pick is written
  `2.09`, and it belongs to a *non-playoff* team — so a bottom-four-vs-rest
  comparison that leaves it in files it under the playoff teams and inflates the
  gap (+416 becomes +440). `draft_capital.hauls()` drops and counts it.
- **A season's in-season window moves every year, at both ends.** Offseason /
  Inseason is split on (that season's week-1 OPENER .. its championship
  Monday), not a fixed date: the opener is normally the Thursday after Labor Day
  and ranges Sept 4 (2025) to Sept 10 (2020), and the season stops at the title
  game, not at New Year. `_season_opener()` (schedule-derived, the Thursday as
  fallback) + `_finals_weeks()`. **2026 is the season that broke the Thursday
  assumption**: week 1 opened WEDNESDAY Sept 9 (NE at SEA), a day ahead of its
  computed Thursday, so anything still anchored on `_nfl_kickoff_thursday`
  reads Sept 9 2026 as offseason while week 1 was being played. Anything
  hand-rolling "before Sept 7" will file a preseason deal as in-season — that is
  what hid the 2020 startup slot swap in the in-season bucket. Note the weekly
  bucket is a *different* rule: an offseason trade within 7 days of kickoff still
  rolls into week 1 by design, so "offseason" and "week 1" legitimately co-occur.
- **A fantasy week runs Tuesday-Monday.** 2026 week 2 begins Tuesday Sept 15,
  the day after week 1's Monday night game. Tuesday and Wednesday moves (most
  waivers) belong to the COMING week. `_season_week_of()` / `_week_tuesday()`
  are the rule. Until 2026-09-15 the build counted weeks from the Thursday
  kickoff, which filed 596 of 1,588 add/drops and 99 of 566 trade rows a week
  early. team_week's trade count also took Sleeper's `leg`, which rolls over
  partway through a Wednesday. So any weekly transaction count, or Quiet streak,
  quoted from an older build is off at the week boundaries.
- **Past seasons' snapshots have no `drafts.json`.** Like `traded_picks.json`,
  only the current season carries it, so the record of who owned a slot in an
  earlier draft is `picks."Original Team"`, not the snapshot.
- **The startup is the one SNAKE draft, so its slots and its pick numbers are
  different things.** `picks."Number"` is the position picked FROM, at every
  draft — Oliverwkw held the 1.01 and therefore the **2.08**, not a `2.01`. Do
  not read a startup pick number as the owner's slot, and do not assume a team's
  number is constant down the rounds; it mirrors every even round. (It really
  did read `2.01` until the fix in `plan/notes/STARTUP_DRAFT_ORDER.md`, which
  also skewed every startup pick-adjusted column, so a startup pick figure
  quoted from an older build is wrong.)
- **Six startup picks were traded, so `Original Team` is not the drafter there.**
  LWebs53 and AceMatthew swapped their round 4, 5 and 8 picks (Mike Evans,
  Golladay, A. Robinson, DJ Moore, Keenan Allen, Hunter Henry). `Final Team`
  drafted; `Original Team` owned the slot. It is a real `trades.csv` row now —
  two, one per side, dated 2020-09-09 with three picks each way — but it is
  **pick-only**, so any 2020 trade analysis that keys on players will see an
  empty deal. It is also the league's only **offseason** trade before 2021.
- **Removing a star lowers Max PF by much less than he scored.** The optimal
  lineup only loses his margin over the next-best legal option, so the observed
  exchange rate is about **1.9 points of production per 1 point of ceiling** and
  you have to strip depth as well as stars. Any "just sell the stars and tank"
  reasoning under the ceiling rule is wrong by roughly a factor of two.
- **The `strict` lineup model is degenerate for a player-for-picks trade.** It
  only lets an arrival occupy the slot the departing player vacated, so when a
  team sold stars for draft picks there is no vacated slot and the returning
  stars simply sit — the counterfactual PF can even fall. Report it, but read the
  spread from `anchored` and `ceiling`. (`WHATIF_TEARDOWN_2024.md`.)

- **Season-outcome columns used to read a live season as finished.** Fixed
  with the boldness PR: `team_year."Week of playoff elimination"` took the games
  played so far as the whole schedule (2026 after week 3: four teams
  "eliminated in week 3" at 1-2); `league_year."(smallest) Playoff tiebreaker"`
  reported a provisional seeding gap; `player_year`'s "Rostered by / Started by
  champion?" and "Started in championship game?" read False — "not on the
  champion's roster" — for a season with no champion. All N/A while live now
  (`tests/test_live_season_outcomes.py`). Any of these quoted from an older build
  for the in-progress season is wrong.
- **Roster size changed, and 2025 added a "supertaxi" long shot.** Roster spots
  (taxi and IR not counted): 21 in 2020 (ESPN), 23 in 2021-23, 26 from 2024.
  Taxi slots: 0 (2021-22), 2 (2023-24), 3 from 2025 — the third is a
  shot-in-the-dark slot for players under 50% rostered, so treat it as roughly
  one zero-value player per team. Any "how deep is the league" or replacement-
  level question has to say which seasons and whether taxi counts:
  `player_additions."Price paid (FAAB)"` sets replacement at roster spots × 8,
  less 8 from 2025 (168 / 184 / 208 / 200).
- **Taxi status is not tracked, and cannot be — and boldness treats taxi as
  bench, by design.** `rosters.json` holds a `taxi` list only as of the moment
  the snapshot was taken (2023 on, when taxi slots began); there is no weekly
  history of it and the transaction log records no taxi moves, so a season-end
  list read as every week's is wrong in both directions. For boldness it does
  not matter: keeping a player on taxi is a lineup decision like benching him
  (leaving a productive rookie there is bold), so taxi players are ordinary
  bench options. `forecast.startable_pool` reads the CURRENT list, which is
  accurate for "now" only.
- **nflverse's position is a player's, not his role's.** Taysom Hill is a TE in
  nflverse but started at QB for New Orleans in 2021 weeks 13-14, so any
  same-position logic (the boldness cuff promotion, a positional prior) misses
  that role. Read a top-of-board Taysom row by hand.
- **An offseason depth-chart change is not an injury.** Jordan Love entering
  2023 or Jalen Hurts entering 2021 had backup histories; nothing in the cache
  records that the job became theirs, so week-1 starts of new starters read as
  bold. The boldness promotion only covers an absent teammate.

### Forecasting traps

- **A good projection is not a good forecast.** `calibrate` measures how well
  the projection predicts a team's mean weekly points; it says nothing about
  whether a 30% favourite wins three times in ten. Those are different claims
  and need different evidence — `backtest` supplies the second.
- **Don't re-tune a knob on five seasons.** Scaling the team-strength sd from
  0.6x to 2x moves backtest log-loss by about 6%, monotonically, with no
  interior optimum. A monotone "improvement" with no minimum is over-fitting to
  four champions, not a discovered parameter. Report the insensitivity instead.

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
- **nflverse's game-status report is thin in the week it covers, so it is not a
  cross-check.** 2026 week 1's `nflverse_injuries.csv` has 139 rows for the
  whole league, 131 of them with a BLANK `report_status` (they are
  practice-participation rows) and 5 "Out". The player it most needed to name,
  Josh Jacobs, is not in it at all.
- **`stats_player_week` is an EVENT list, not an appearance list, so absence
  from it is NOT evidence that a player did not play.** This one cost real
  time and shipped a wrong conclusion before being caught. It carries 31-40
  rows per team against the ~47 that dress, 1,040 of its 1,041 rows have at
  least one non-zero stat, and 248 of 379 active-roster WRs have no row in
  2026 week 1 at all. A receiver who plays eight snaps and is not targeted
  records nothing and simply is not in the file — De'Zhaun Stribling and every
  other backup on the 2026 week-1 rosters. **For "did he take the field", use
  nflverse's `snap_counts` release**, which is a true appearance list
  (`offense_snaps` / `defense_snaps` / `st_snaps`), or Sleeper's own
  participation capture in `data/injury_tracker.csv`, which is a SUPERSET of
  the event list (no player with a stat line is ever missing from it).
- **`Injury?` before the snap-count fix over-flagged, and any figure quoted
  from an older build still carries it.** The build's injury gap-fill writes an
  injury for every week a player did not appear in, and "appear" used to mean
  "has a `stats_player_week` row" — so a man who dressed, played and recorded
  nothing read as injured. That was **275 of the 3,826 `Injury?` flags (7.2%)
  in 2020-2025** (the measured export diff, run 34873813049 vs run 496),
  2.4-3.6% in 2020-2022 rising to ~10.5% from 2023, the worst played near-full
  games (Gabe Davis 2023 wk11 at 67 snaps; Cole Kmet 2024 wk9 66; Cade Otton
  2025 wk3 66; Courtland Sutton 2024 wk7 57). A name-matched recount gets 262 —
  it misses A.J./AJ-style spellings and lends Michael Carter II's snaps to
  Michael Carter the RB — which is the name-join trap below in miniature. It inflated `Hardship`, and through it
  `Luck` and `Loss from hardship?`, and dropped those weeks out of played-week
  denominators like `Adjusted Avg`. `played_players_by_week` is now the event
  list UNIONED with `snap_counts`, and
  `test_no_injury_flag_coincides_with_snaps_played` holds it — but an
  `Injury?`, `Hardship` or `Luck` number taken from a build before that fix is
  wrong by roughly that much, so say which build a historical injury figure
  came from.
- **A player can dress and never take a snap, and 2020-2025 knows it by hand.**
  After the snap union, 215 `Injury?` weeks were left on players with no snap
  and no reserve-list status — mostly backup quarterbacks (Riley Leonard 2025,
  Russell Wilson 2025 wks 5-9, Jake Browning 2024 wks 1-7, Desmond Ridder
  2022). Each was looked up in the team's own inactive list;
  `data/game_day_status.csv` records the answer and its source. 208 dressed and
  sat and are **not** injured; 7 stay injured (inactive, reserve list, or Rome
  Odunze 2025 wk15, active but ruled out in pregame warmups). An emergency third
  quarterback is on the inactive list, so he counts as Out. The same change
  bridges snap counts through DynastyProcess's `pfr_id` where the weekly rosters
  leave it blank, clearing 31 more weeks of players who did play (Trey McBride
  2022 wks 2-9). Weekly-roster `ACT` cannot make this call on its own — it covers
  game-day inactives too — and Sleeper's `gms_active` is wrong for reserve-list
  players (Jeff Wilson 2021 on PUP reads as active). From 2026 the tracker's
  live participation capture decides instead, and the file may not hold those
  seasons.
- **Join nflverse on `gsis_id`, never on name.** A suffix
  (`Marvin Harrison Jr.`, `Deebo Samuel Sr.`) reads as 21 false disagreements
  against the tracker. `snap_counts` is the exception — it has no gsis at all,
  only `pfr_player_id`, so bridge through `nflverse_weekly_rosters.pfr_id`.
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
   fine *only* if the build does not import it — `analysis` is inquiry-only;
   `digest`, `lineup`, `ktc`, `sleeper`, `snapshot`, `utils`, `wins_added` and
   the rest are build code, so read from them, never change them. **`inquiry`
   and `replay` are now half and half** (since #458): the build imports
   `wins_added`, which uses `inquiry`'s `week` / `teams` / `season_meta` /
   `players` / `repo_root` / `_week_last_game_days` / `_normalize` /
   `_FLEX_POOL` / `EMPTY_SLOT` / `WeekRow` and `replay.is_legal`. Those are
   build code; the rest of both modules is still inquiry-only — check with
   `grep -o "Q\.[A-Za-z_]*\|is_legal" lib/lotg_support/wins_added.py | sort -u`.
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
