# CLAUDE.md

Orientation for a session working in this repo.

## Speed never limits the answer

The fast paths below (`fast.py`, `trade.py`, `advise.py`) exist to get the DATA
in one call so the time goes to thinking. They print data and caveats, never a
verdict. The time targets cover the data pull, not the answer: when a question
needs more — a news search, a follow-up `q`, a forecast scenario, a check
against the build, the strategy guide — do it, and say what was checked. A
fast answer that skips a caveat the output printed is a wrong answer.

## Stat checks first: ONE tool call, then answer (target 15 seconds)

Most questions are a count, a rank or a lookup ("most starters over 18 in a
loss", "anyone ever bench 4+ over 20", "where does 44.2 rank", "is X close to
it before the late window", "when did I last have a 40"). For those, do NOT
read or grep the playbook and do NOT run `--help` — every flag is listed
below. Make ONE Bash call — chain every part of the question with `::`
(`fast.py count 20 --bench :: count 20 --bench --no-qb`), one process, one
Sleeper fetch — then answer in a few lines. Its output
prints its own caveats (strict `>` vs `>=` borderline rows, every week type
counted, lineup size by season, as-of week, live = raw Sleeper / leading-now):

```bash
python scripts/fast.py count 18 --loss                          # starters over 18, losses, ranked
python scripts/fast.py count 18 --loss --entering late --live --team Oliverwkw  # league top + the team's best + NOW, with who is left to play before 4pm
python scripts/fast.py count 20 --bench --no-qb                 # bench; --any / --pos WR,TE / --ge / --team / --year
python scripts/fast.py count all --slot MNF --live              # most starters playing Monday night (now vs record)
python scripts/fast.py cols "margin entering|choke"             # which sheet/column holds it (team_week has ~300)
python scripts/fast.py rank player_week Points 44.2 --where Starter/Bench=Starter
python scripts/fast.py live --team Oliverwkw                    # live scoreboard: starters, slots, kickoff status
python scripts/fast.py q "pw[(pw.Team=='Oliverwkw')&(pw.Points>=40)].tail(3)"   # any pandas expression
python scripts/fast.py q "l = twt[twt['Win?']==False]; l.nlargest(5, 'Margin entering Monday')[['Team','Year','Week','Margin entering Monday','Margin']]"   # biggest blown leads
```

All `count` flags: `THRESHOLD`, `--bench | --any` (default starters),
`--pos QB,WR`, `--no-qb`, `--ge` (default strict `>`), `--loss | --win`,
`--entering late|early|morning|SNF|Monday|Thursday|<any game slot>` (games
kicked off BEFORE that stage), `--slot MNF,SNF` (only players IN those games;
`THRESHOLD` may be `all` to count every player),
`--team T` (filters the table), `--year 2025,2026` (filters history), `--live`
(Sleeper's current week placed against history — use it for any "now" / "this
week" question, even before kickoff; `--season/--week` only pick which week
`--live` reads, `--snapshot` reads the committed copy), `-n N` (rows; ties at the cut kept).
`rank SHEET COLUMN VALUE [--where COL=V ...] [--low] [-n N]`; `--where` takes
`=`, `!=`, `<`, `>`, `<=`, `>=`, `~regex`. `live [--team T] [--bench]`.

**`--entering X` = games kicked off BEFORE X; `--slot X` = players IN X's games.**

`q` preloads `pw` — one row per player-week, typed, columns exactly: `Player,
Team, Year, Week, Week Name, Starter/Bench, Position, Position started in (if
starter), NFL team` (that week's, not current) `, Game slot` (Thursday / Sunday
morning|early|late / SNF / MNF / Saturday / Bye …) `, Points, Opponent, Win?,
Margin, PF, Points against, Live, Snap %, Targets, Carries, Target share, Air
yards, Red-zone opportunities, xFP, Points minus xFP, Acquired via, Acquired,
Acquired season, Season source, In-season pickup` — so do not spend a call on `list(pw.columns)`; `lpw` (pw + the live week), `live`, `tw`/`ty`/
`py`/`pa`/any sheet name (text; `num(df, col)` for numbers), and TYPED sheets
`twt`/`tyt`/`pyt`/`lwt`/`lyt` or `T("sheet")` (numbers float, Win? bool — use
these, not the text ones). `q` takes statements too (newline or `;`); the last
expression is printed. Team-week questions are usually already a `team_week`
column — e.g. `Margin entering SNF/Monday/last game`, `Comeback/Choke size …`,
`Players over 20/30/40 pts (starters|roster)`, `Points from QBs`, `Max PF`,
`Luck` — so `cols REGEX :: q "<twt expression>"` in one call. pandas is already
installed in the cloud container; Sleeper's API is reachable from it.

**Usage / xFP** (`lotg_support.usage`, 2020+): `Snap %` and `Target share` are
0-1 fractions, `xFP` = expected points of his targets / carries in league
scoring (ffopportunity's expected components × each season's scoring table; no
fumble term), `Points minus xFP` = `Points − xFP` (+ = scoring beyond the
opportunity, rarely sticky; rising xFP / snaps = a role change). NaN = nflverse
shows no game that week; live-week rows are NaN. player_year / player_all_time
sum them over ROSTERED weeks (`Weeks with usage data`, `Avg xFP` …); team_week /
team_year carry `Starters' xFP` and `Starters' points minus xFP`.
`advise.py startsit|waivers` and `trade.py` print each player's season vs last-3
usage and flag opportunity shifts / scoring beyond xFP.

**Acquisition and correlation questions** ("share of starter points from
waivers/trades/the draft", "is X linked to win %") are ONE `q` too. `Acquired
via` = how the player's CURRENT stint on that team began (Waiver / Free agency /
Trade / Draft / Commissioner, latest player_additions row on or before the
week; every 2020-25 row matches); `Season source` = "Week-1 roster" if he was
on it in week 1, else `Acquired via`; `In-season pickup` = Season source is
Waiver or Free agency (the strategy guide's "pickups gave 1.6-4%"). In `q`:
`share(mask, years=...)` = per team-season share of STARTER points, regular
season only (mask = a pw bool column name or bool Series); `ts` = typed
team_year by (Team, Year) plus `Regular season all-play win %`;
`corr(x, y, control=ts.Tanking, where=ts.Tanking < 0.5)` = n, Pearson,
Spearman and their p-values (scipy's t-test values, no scipy needed), partial
when `control` is given. **Control for tanking** in any team-season
correlation (Tanking alone drove the waiver result):

```bash
python scripts/fast.py q "o = share(pw['Acquired via'].isin(['Waiver','Free agency']), years=range(2021,2026)); y = ts['Regular season win %']; pd.concat([corr(share('In-season pickup', years=range(2021,2026)), y), corr(o, y), corr(o, y, where=ts.Tanking < 0.5), corr(o, y, control=ts.Tanking)])"
```

The traps that matter for these (the full list is in the playbook): **team
`PF` includes the semifinal +5** (players' `Points` and live Sleeper points do
not); **lineups were 9 starters 2020-23, 10 from 2024**; **2026 rows are in
the exports** through the last finalized week; `Year` is TEXT in
`inquire`/`Q.load_sheet` frames (`pw` in `fast.py` is typed); live `Win?` means
"leading now" and game status is a kickoff-clock guess; **bench = every
non-starter, taxi and IR included** (no weekly taxi flag exists). Name the
as-of week.
**Let pandas do every count** ("more than once", "how many times", "who has
the most"): end the `q` with `.value_counts()` / `groupby(...).size()` and quote
that, never a tally of printed rows. Print only what the answer needs
(`.head(10)`, the columns you quote) so the output never has to be re-read. Benchmarks miscounted rows twice (14 read
as 9; a team listed with two blown leads called "once").
Reach for the playbook when `fast.py` does not cover the question.


## Trade questions: ONE `scripts/trade.py` call, then a web search for news

"Should X take this trade?" starts from one command (about 10 s; the first run
in a fresh container adds ~8 s to calibrate the forecast, then it is cached):

```bash
python scripts/trade.py shmuel256 --give "Christian McCaffrey" --get "A.J. Brown,Chuba Hubbard" --give-pick "2029 3rd"
# scenarios in the same call: --rate "Name=PPG" (forecast rate) / --healthy "Name" (drop IR/Out caps); chain with ::
python scripts/trade.py shmuel256 --give "Christian McCaffrey" --get "A.J. Brown,Chuba Hubbard" :: \
  shmuel256 --give "Christian McCaffrey" --get "A.J. Brown,Chuba Hubbard" --rate "Chuba Hubbard=16" --healthy "A.J. Brown"
```

It prints the moving players (this season vs the two before, and the
forecast's rate, availability and IR/designation for each), KTC now vs a month
ago (one small input — Oliver's rule), standings, both teams' position depth
before/after, and title/finals/playoff odds and weekly points before -> after
for every team, then the caveats. Read the caveats: they name each player whose
forecast rate disagrees with this season by 4+ PPG and each IR-capped player,
with the override to try. The forecast reads no news, so do ONE web search on
the players the caveats flag — their injury timeline AND their role (who left
or got hurt in that backfield / WR room; a 2026 PPG far above the forecast is
often a new role, not a hot streak) — and read the league strategy guide in
project memory (see "Advice questions" below) plus the partner files
`manager-profiles` (trade/draft record), `negotiation-styles` (how each manager
negotiates, from Oliver's DMs — use it to shape any offer or counter),
`league-2026-windows` (contenders, holes, who owns whose 1sts) and
`ktc-caveats` (all printed at the end of the output) — then answer. `--no-forecast` / `--no-ktc`
skip those parts. It wraps the forecast without editing it (tests/test_trade.py).

## Advice questions: start/sit, add/drop, strategy — ONE `scripts/advise.py` call

```bash
python scripts/advise.py startsit Oliverwkw     # set lineup vs best on projection / season / last-3, injuries, byes, kickoffs, matchup ranks
python scripts/advise.py waivers Oliverwkw --pos RB,WR -n 15   # free agents by points they add to THIS lineup, drop candidates, FAAB left
python scripts/advise.py strategy Oliverwkw     # standings + forecast odds, positional strength ranks, ages, future picks
python scripts/advise.py roster Oliverwkw       # every player, every column
python scripts/advise.py startsit Oliverwkw :: waivers Oliverwkw --pos RB   # chain with ::
```

About 10 s for all of them together. Points are this league's scoring of
Sleeper's NFL stats, so free agents are scored too (player_week has rostered
players only); `tests/test_advise.py` reconciles them with Sleeper's matchup
points. Then, before answering:
- **News**: one web search on every player the output flags (injury, no
  projection, depth-chart change, small sample). Sleeper's feed is not the
  injury report.
- **The league strategy guide is printed at the end of the output** (and of
  `trade.py`'s): the memory files for that question, read live from project
  memory by `lotg_support.guide` — so it costs no extra call. Read it there;
  do not Read the files one by one. A file the output lists under "other
  guide files" is worth opening only if the question reaches it. The guide is
  the files MEMORY.md's
  "Strategy guide" line lists (`dynasty-strategy`, `trade-strategy`,
  `rookie-picks`, `season-arc`, `weekly-lineup-strategy`, `start-sit-edges`,
  `waivers-streaming`, `league-settings`, `league-structure-evidence`,
  `ktc-caveats`, plus `league-size-caveat`; for anything involving another
  team also `manager-profiles`, `negotiation-styles`, `league-2026-windows`;
  follow that line so new files are picked up). Full evidence behind them is in
  `/mnt/project-files/strategy/` (README.md says which report answers what). Read the files themselves, never a copy: apply
  them, and cite the rule you used. If memory is not readable, say no guide
  rule was applied.
  When an answer turns up a new lesson, or shows a rule in the guide failing in
  this league, add or correct that line in the guide (fact + why, one line), so
  lessons are not lost.
- **FAAB is a 100 budget with house rules**, not Sleeper's 10000 setting;
  `waivers` prints what is left on the 100 scale. Never size a bid against 10000.
- Trades go to `trade.py` (above); a what-if season to `scripts/whatif.py`.

## Player values in league FAAB — `scripts/faab_value.py`

`board` / `explain NAME...` / `calls` / `votes` print the stats-only valuation (general rules fitted to the
league's trades, cuts and calls; no names, no pins) and how each rule moved a player. Rating-page votes
(`docs/rate/`) are a capped signal for the fit, never a per-player edit. See
`plan/notes/FAAB_VALUE_SYSTEM.md`.

## What this is

A cloud-only pipeline that pulls the league's history from Sleeper (plus an ESPN
backfill for 2020) and exports it as the CSV/Excel tables described in
`plan/LOTG Plan - Sheet1.csv`. It runs on GitHub Actions; there is no local
setup. `python -m lotg` (`src/lotg.py`) is the build; `lib/lotg_support/` holds
its supporting modules; `exports/` holds the committed outputs and the raw
Sleeper snapshot they are built from.

## Two kinds of work — know which one you are doing

**Build changes** — anything that alters what `python -m lotg` produces. These
follow the phase workflow and the mandatory 3-part audit in
`plan/MASTER_TODO.md`. Read that before changing build code.

**Inquiries** — questions answered *from* the committed data ("who has the most
X", "would Y still have won without that trade"). These are read-only: they must
not change `exports/`, `data/`, the workflows, or any build output.

**An inquiry is answered in chat, fast — then you ask.** Target 15-30 seconds
for a stat check that `scripts/fast.py` covers (top section — go straight
there), under a minute when it needs a new column or a scratch script, under 3
minutes otherwise. The note in `plan/notes/`, the new
helper in `lib/`, the tests and the PR are a *second phase* that starts only
when the asker says they want it. Do not open a PR for a question. (`pip install
pandas` is the one setup step; skip `requirements.txt`, it pulls ortools.)

**The 3 minutes is a target; accuracy is the constraint.** They rarely conflict
— the playbook's accuracy floor (read the trap list, reconcile against a build
number where one exists, state what is unverified, keep the caveats) costs
seconds — and for a `fast.py` stat check it is already met: the traps that
apply are listed in the top section, the tool is reconciled against build
columns in `tests/test_fast.py`, and its output prints the caveats. What's
expensive is *proving* an answer to the next reader, not getting it right.
Where they do conflict, take the extra minute and say why.

**Start any other inquiry at `plan/INQUIRY_PLAYBOOK.md`.** It documents the tools that
exist for exactly this — `scripts/inquire.py` for finding/filtering/ranking
across the fourteen export sheets and the raw snapshot (including over-inclusive
sweeps that rank on every column rather than a curated few), `lotg_support.analysis`
for the joins a judgement question needs (position attached to any sheet, roster
depth, lineup composition, cohort tests, positional scarcity, spend vs return),
and `scripts/whatif.py` for counterfactual seasons — and it lists the data traps
that have cost time before (the +5 semifinal bonus baked into `PF`, 2020 having no snapshot, the
lineup template and playoff calendar changing between seasons, position drift in
Sleeper's current-only player dictionary). Do not hand-roll a loader over
`exports/` or `exports/snapshot/` before reading it.

## Conventions

- Answers and analyses are written up as notes in `plan/notes/` **once asked
  for**. Reusable logic goes in `lib/lotg_support/` with a test in `tests/`; a
  script in `scripts/` is a thin CLI over it.
- **If an inquiry needs a helper that does not exist yet, offer to add it** —
  answer the question first, then build it if they want it, as its own PR,
  additive only, changing no build output. `plan/INQUIRY_PLAYBOOK.md` has the
  rules and the pre-PR checklist ("When the helper you need does not exist").
  Once you are building it, put it in `lib/`, not in a throwaway script the next
  session cannot find.
- **Report over-inclusively**: flag every borderline item and classify it
  (by-design / needs-human-judgment / defect) rather than filtering quietly.
  This is the standing rule for the audits, the weekly digest and inquiries
  alike.
- Tests are plain functions runnable both under `pytest tests/` (what CI runs)
  and directly as `python tests/test_x.py`. Data-dependent tests skip cleanly
  when `exports/` is absent and assert only against **completed** seasons.
- Never commit regenerated `exports/` from a local run — CI owns those. The
  offline build (`scripts/offline_build.py`) is a smoke test, not a source of
  truth (see the warning at the top of `plan/MASTER_TODO.md`).
