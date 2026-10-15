# CLAUDE.md

Orientation for a session working in this repo.

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
python scripts/fast.py rank player_week Points 44.2 --where Starter/Bench=Starter
python scripts/fast.py live --team Oliverwkw                    # live scoreboard: starters, slots, kickoff status
python scripts/fast.py q "pw[(pw.Team=='Oliverwkw')&(pw.Points>=40)].tail(3)"   # any pandas expression
```

All `count` flags: `THRESHOLD`, `--bench | --any` (default starters),
`--pos QB,WR`, `--no-qb`, `--ge` (default strict `>`), `--loss | --win`,
`--entering late|early|morning|SNF|Monday|Thursday|<any game slot>`,
`--team T` (filters the table), `--year 2025,2026` (filters history), `--live`
(Sleeper's current week placed against history — use it for any "now" / "this
week" question, even before kickoff; `--season/--week` only pick which week
`--live` reads, `--snapshot` reads the committed copy), `-n N` (rows; ties at the cut kept).
`rank SHEET COLUMN VALUE [--where COL=V ...] [--low] [-n N]`; `--where` takes
`=`, `!=`, `<`, `>`, `<=`, `>=`, `~regex`. `live [--team T] [--bench]`.

`q` preloads `pw` (player_week typed — Year/Week int, Points float, Win? bool —
with Opponent/Margin/PF joined), `lpw` (pw + the live week), `live`, `tw`/`ty`/
`py`/`pa`/any sheet name (text; `num(df, col)` for numbers). pandas is already
installed in the cloud container; Sleeper's API is reachable from it.

The traps that matter for these (the full list is in the playbook): **team
`PF` includes the semifinal +5** (players' `Points` and live Sleeper points do
not); **lineups were 9 starters 2020-23, 10 from 2024**; **2026 rows are in
the exports** through the last finalized week; `Year` is TEXT in
`inquire`/`Q.load_sheet` frames (`pw` in `fast.py` is typed); live `Win?` means
"leading now" and game status is a kickoff-clock guess; **bench = every
non-starter, taxi and IR included** (no weekly taxi flag exists). Name the
as-of week.
Reach for the playbook when `fast.py` does not cover the question.


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
