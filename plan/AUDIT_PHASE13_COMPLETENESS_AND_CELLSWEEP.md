# Phase 13 follow-up — self-designed completeness + full cell/comment sweep (Round 4)

Custom audit battery (not a repeat of `plan/AUDIT_PHASE13_10PART*.md`'s
structure) requested directly: *"design your own comprehensive and complete
audit... full history of the league should be shown by the data... full
cell-by-cell sweep of the final excel... every cell and every comment is
each of: accurate, reasonable, explainable, and captures what is
intended."*

Two things distinguish this round from Rounds 1-3:
1. **Full-population checks, not spot-checks**, wherever the data size makes
   it feasible (every season × team × week row, every picks/player_all_time
   chain, every header comment) — "over-specific and over-inclusive."
2. **Comments are now first-class audit subjects**, not just cell values:
   both the static header tooltips (column definitions pulled from
   `src/formulas.py`) and the per-row asset-history hover-comments (picks
   column 1, player_all_time column 1) get checked for textual accuracy
   against the underlying data, not just presence.

Build under audit: offline build (`scripts/offline_build.py`) on top of
HEAD (`4b4bfd7`, includes all Round 1-3 fixes).

## Part A — League-history completeness (full population, no sampling)

For every sheet, enumerate the *expected* full population and diff against
what's actually present:
- Every season the league has played (earliest to latest, per
  `data/`/cached league config) appears in every season-keyed sheet
  (team_year, team_week, league_year, league_week, player_year — for
  players active that year, picks, trades, transactions). No season
  silently missing from one sheet but present in another.
- Every team that ever rostered a player in league history appears in
  team_all_time exactly once, and in team_year/team_week for every season
  it was active (no gaps mid-history unless the team is genuinely
  inactive that year — verify against raw roster data, not assumption).
- Every week 1..N (N = that season's actual number of weeks, including
  playoffs) appears for every active team in team_week — no missing week
  rows, no extra phantom weeks.
- Every player who appears ANYWHERE (any roster snapshot, any
  transaction, any trade, any pick) has at least one player_year row for
  every season they were on a roster, and exactly one player_all_time
  row. Cross-check player_week -> player_year -> player_all_time row
  counts reconcile (no player silently dropped at a rollup stage).
- Every startup-pool and future-pool draft slot that should exist (8
  teams x however many startup rounds; one slot per team per round per
  future year currently tracked) appears exactly once in picks.csv —
  enumerate the *expected* full grid and diff, not just "spot check a
  few."
- Every trade and transaction event recorded in the raw source (Sleeper
  transactions API + ESPN 2020 email ledger) has a corresponding row in
  trades.csv/transactions.csv — count raw events vs exported rows,
  reconcile exactly (with documented exclusions, if any, named and
  justified).

## Part B — Cross-sheet numeric reconciliation at full scale

Repeat the standard RUN3 invariants (league_week = Σteam_week for
PF/tx/injuries/suspensions/bye/FAAB/donuts; team_year Record = Σteam_week
Win?; award rollups; player_all_time = Σplayer_year) but compute the
diff across **every** season/team/week row in the export, not a sampled
subset — report exact count of mismatches (expect 0) rather than "N
spot-checked rows passed."

## Part C — Header-comment (column-tooltip) accuracy sweep

For every column across every sheet that carries a hover-comment (sourced
from `src/formulas.py`'s `column_definitions()`/`documented_columns()`):
- Pull the comment text and the actual computation logic for that column
  in `src/lotg.py`. Confirm the comment's stated formula/meaning matches
  what the code actually computes today (catch doc/code drift — a
  comment can be stale if the formula was edited but the doc wasn't).
- Confirm every NON-identity column (i.e. not in `IDENTITY_ALLOWLIST`)
  that should be documented actually has a comment attached in the built
  workbook (no column silently missing its definition).
  Cross-check `formulas.undocumented_columns(catalog)` against the real
  built sheet's header set per sheet.
- Confirm no comment is attached to the WRONG column (e.g. via a stale
  key match, or attached under a same-named-but-different-meaning column
  in a different sheet — the code explicitly prefers
  `(sheet_name, col)` over the global `(None, col)` default; verify this
  resolves correctly everywhere it matters, not just for the one
  documented "picks 'Number of trades'" example in the code comment).

## Part D — Asset-history hover-comment narrative accuracy (full population)

The picks-sheet column-1 and player_all_time-sheet column-1 cells carry a
synthesized natural-language history (`pick_history_text` /
`player_history_text`) describing the full transaction chain for that
pick/player. For the FULL population (not a sample):
- Parse each comment's claimed sequence of events/dates/teams and
  cross-check against the actual underlying chain data structure that
  generated it (the `chains` dict / linked transaction records) —
  confirm every claimed event in the text actually occurred, in the
  stated order, attributed to the stated team, with no fabricated or
  omitted link.
- Confirm the FIRST event named in the comment matches the row's actual
  origin (startup draft / waiver add / trade-in) and the LAST event
  matches the row's current status (on a roster / dropped / traded away
  / future pick unmade).
  Confirm a comment never references a transaction reference (e.g.
  `T#NNN`, `#NNN`, `PH#NNN`) that doesn't actually exist or doesn't
  belong to this same chain.
- Confirm comments are internally self-consistent in chronological order
  (no comment narrating events out of date order — this is the bug
  shape Round 2 found at the LINK level; this part re-derives the same
  invariant directly from comment TEXT as an independent cross-check).
- Spot the inverse failure mode: a row whose comment text says
  "no history" / is empty when the underlying data actually has
  transaction history that should have produced a comment (silently
  missing comments, not just wrong ones).

## Part E — Domain-bounds & plausibility sweep, every column, every sheet

For every numeric/categorical column in every sheet (not just the
headline ones already hand-checked in prior rounds), establish a
plausible domain (e.g. percentages in [0,100], ages in a sane human
range, week numbers in [0,18], counts >= 0 unless explicitly
signed-allowed like Margin/Luck) and scan the FULL column for any value
outside that domain. Flag anything implausible even if it doesn't
violate a hard invariant (e.g. a count of 9999, a percentage of 250%, a
date outside the league's 2019-2026 span).

## Part F — N/A-vs-0-vs-blank correctness, every conditionally-defined column

Enumerate every column documented as "N/A under condition X" (FAAB
pre-2022, bids 2020, KTC-unreachable, win-variance <2 played weeks,
retention-rate windows, etc.) and verify, for the FULL set of rows that
satisfy condition X, that 100% of them render as true N/A (not 0, not
blank-string, not a fabricated placeholder) — and conversely that rows
NOT satisfying condition X never get incorrectly N/A'd (no
over-broadened gate masking real data).

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

Every "Link to previous/next transaction" reference across
picks/transactions/trades/player_all_time, for the FULL row population:
in-range, chronologically ordered, and round-trip consistent (if A's
"next" points to B, B's "previous" points back to A). Report exact
counts of violations (expect 0), not sampled spot-checks.

## Part H — Workbook-structural integrity sweep

- Every sheet opens without corruption; every hyperlink cell's target
  anchor actually exists in the target sheet at the stated row (no
  hyperlink to a row that's out of range or off-by-one after a sort/
  filter operation).
- Every comment box (header tooltip + asset-history hover) renders
  without being clipped/truncated for its actual text length, and
  without garbled encoding (special characters, em-dashes, accented
  player names).
- Freeze panes, tab colors, conditional-formatting ranges match the
  sheet's actual current row/column extent (not stale from a smaller
  prior build).

## Part I — ESPN-2020 specific re-verification

Targeted re-check that 2020's completeness (Part A), comment accuracy
(Parts C/D), and link integrity (Part G) hold with the same rigor as
2021+, since 2020 is sourced from a structurally different pipeline
(ESPN email backfill vs. Sleeper API).

## Part J — Build/test cleanliness

`pytest tests/ -q` full pass; offline build completes with no new
warnings; `git status` clean after revert of build artifacts.

---

## Execution plan

Dispatch parallel sub-agents over disjoint parts, each with read access to
a fresh offline build, `openpyxl`/`pandas` for direct cell+comment
inspection, and the actual `src/lotg.py`/`src/formulas.py`/`src/espn_2020.py`
source for cross-referencing comment text against real computation logic.
Findings get root-caused and fixed directly on `claude/phase-13-audit-tsapoy`
(PR #319); a synthesis writeup follows, listing fixes applied and full
verification (pytest + targeted post-fix re-checks at the same full-population
scale that found each issue).
