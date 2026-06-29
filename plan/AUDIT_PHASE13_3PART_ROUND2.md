# Phase 13 follow-up — 3-part audit ROUND 2 on PR #319

Second pass of the mandatory 3-part audit, run fresh against the CURRENT
branch tip `claude/phase-13-audit-tsapoy` @ `858c301` ("fix column auto-size
full scan + header comment box clipping"), diffed against `main` @ `6d83635`
(the merge-base, the pre-PR baseline). Unlike the original
`plan/AUDIT_PHASE13_3PART.md` (which covered only the first 4 fixes), this
round covers the FULL accumulated PR: Rounds 1-4 plus the two just-landed
formatting fixes. All spot-check examples below are deliberately NOVEL —
different players/teams/seasons/picks than those already written up in
`AUDIT_PHASE13_3PART.md` and
`AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP_RESULTS.md`.

Methodology: local offline build (`scripts/offline_build.py`, exit 0, only
the expected `api.sleeper.app` / `espn_2020_draft` unresolved-fetch warnings
from the sandboxed no-network environment), full `pytest tests/ -q`, and
full-population (not sampled) internal-consistency invariants computed
directly on the freshly-built export CSVs / workbook.

> Environment note: the committed `exports/*.csv` in the repo are STALE —
> last regenerated in `296c8dc` (#293), BEFORE any Round 1-4 fix. Running
> `pytest` against those committed CSVs spuriously fails
> `test_pick_chain_link_integrity` (5 "sibling self-links") because they
> predate the Parts G/H pick-chain fix. After a fresh `offline_build.py` the
> CSVs reflect the fixed code and the suite is 15/15. This is a build-artifact
> staleness artifact, NOT a regression — the committed CSVs are an input
> fixture, not part of the code under audit.

## Part 1 — Code-based audit: PASS

`git diff main..858c301 -- src/lotg.py src/formulas.py src/espn_2020.py`
read in full (lotg.py +324/-47, formulas.py 4 lines, espn_2020.py +26).
Every distinct logical change maps 1:1 to a documented, scoped fix from the
audit-history docs — no stray/accidental edits:

- **`_preserve_na()` additions** (KTC checkpoint cols; `Amount of FAAB
  spent`; `Number of bids`): Round 1 / Round 4 N/A-vs-0 preservation.
- **`Amount of FAAB spent` → None for season < 2022** (team_week, team_year,
  league_week, league_year, both the per-row builds and the post-merge
  `fillna` overwrites): Round 1.
- **`Total FAAB bid` $0-preservation** (2022+ waivers; `... or None` no longer
  collapses a real $0): Round 4 Parts E/F (`a1dd0dd`).
- **`Age difference` requires BOTH ages present** (no phantom age-0 on
  single-side rows): Round 4 Parts E/F.
- **Player tx/drop counter rebuild from final `transactions_rows`** + the
  synth-row pickup/drop re-tally: Round 4 Parts A/B + E/F (`7acbd11`,
  `a1dd0dd`).
- **`_ktc_idx = None` defensive init** + always-N/A-fill the picks KTC cols
  regardless of index availability: Round 1.
- **player_year pad name-collision guard** (`existing_names`) and
  **player_all_time pad requires a player_year row** (`_py_pids`): Round 4
  Parts A/B (`7acbd11`).
- **Pick-chain re-key to FULL numbered identity** `(year, round, number,
  orig)`, the `2.09`→`_R209` sentinel alignment, `_pick_neighbors` skipping
  every other `PH#` entry, and on-or-after-draft-date player-chain anchoring:
  Round 4 Parts G/H (`698ccea`) + run-2 Part 8.
- **`formulas.py` Hardship tooltip** rewritten from the stale "opponent
  average max PF / schedule strength" text to the real injury/suspension
  points-lost definition: Round 4 Parts C/D (`c549e42`).
- **`espn_2020.py` `_calendar_trade_wk`** replacing the email-parser's
  roster-vote week so 2020 team_week trade buckets agree with league_week's
  calendar rule: run-2 Part 1.
- **Just-landed (`858c301`):** column auto-size now scans EVERY data row
  (was first 200 only); header-comment box height sized by wrapped-line count
  with the cap raised 520→900px.

`pytest tests/ -q` (fresh build present): **15 passed, 0 failed, 0 skipped**.
Offline build: exit 0, no new warnings beyond the known network-unavailable
fetches.

## Part 2 — Results-based audit: PASS (NOVEL examples per fix)

**Pick-chain sibling-collision (Parts G/H) — NOVEL: 2024 round-2
JacobRosenzweig 2.02 + 2.09; 2026 future picks.**
- Full sweep: **0 sibling self-links across all 450 picks** (no picks-sheet
  link points at a different picks row).
- `PH#138` (2024 2.02, orig JacobRosenzweig) → prev `T#223`; `PH#441`
  (2024 2.09, same orig) → prev `T#28`. The two same-round siblings resolve
  to their OWN distinct trades, not each other. Round-trip confirmed: `T#28`
  received "2024 2.09" and its per-asset "next" is `PH#441`; `T#223`
  received "2024 2.02(X. Worthy)" and points to `PH#138`. The `2.09`→`_R209`
  sentinel keys the toilet pick's draft terminal with its trade chain
  correctly.
- `PH#207` (2026 2.??, un-drafted future) and `PH#450` (2026 2.09) both
  prev/next N/A — number-0 future picks have no draft row and cannot
  collide, as designed.

**Synthesized-row counter fixes (Parts A/B, E/F) — NOVEL: BROsenzweig /
Josh Doctson drop chain; full pa==Σpy sweep.**
- All **433 drop-only rows** carry a populated "Number of times dropped by
  this team" — **0 blank/N/A**. Novel: BROsenzweig / Josh Doctson's three
  drop-only rows number 1 → 3 → 4 (gaps from interleaved pickups),
  monotonic and consistent — no "one numbered, one blank" desync.
- Full-population `player_all_time == Σ player_year` by Player name across 9
  additive counters (Number of transactions / drops / trades, Points, Times
  as Player of the week / Captain, injury & suspension weeks, weeks as
  starter): **0 mismatches**. 0 player_all_time names absent from
  player_year and vice-versa (the phantom-name pad fix holds).

**Total FAAB bid $0-preservation — NOVEL: AceMatthew / Mike Gesicki 2024.**
- 2022+ waivers: **126 genuine $0 totals preserved** (not N/A), each paired
  with a real bid count and a $0 `Faab` claim (uncontested $0 claims);
  **263 positive totals; 0 spurious N/A**. Novel: row 99 AceMatthew /
  Mike Gesicki 2024-09-17 → Total FAAB bid = 0 (not N/A).

**Age difference fix — NOVEL: Larry Fitzgerald (add) / Cam Newton (drop).**
- All **781 single-side rows render N/A** (0 fabricated age gaps); **714 of
  723 both-sided rows carry a real computed difference**. Novel: pure-add
  Larry Fitzgerald (row 3) and pure-drop Cam Newton (row 27) both N/A.

**Column-width full-scan (just-landed) — NOVEL: player_week.Player
(row 6962), team_week.Team (row 203).**
- In the rebuilt workbook, `player_week.Player` width = 26.0 (= 24-char name
  at data-row 6962 + 2) and `team_week.Team` width = 17.0 (= 15-char name at
  row 203 + 2) — both long values fall PAST the old 200-row scan window, so
  the columns would have been under-sized before. `trades."Assets received"`
  = 40.0 (capped; longest value at row 219).

**Header-tooltip height (just-landed) — VML box-height sweep.**
- transactions / trades / picks each now emit a **620px** comment box for the
  2244-char `O-Score` tooltip (the longest in the workbook). The old formula
  capped at 520px (`min(520, …)`); under the new `min(900, …)` the longest
  tooltips are no longer clipped. **0 boxes pinned at the old 520 cap.**

## Part 3 — Diff/consistency audit (full population): PASS

Computed at FULL scale (every row, not sampled) on the freshly-built exports:

- **`player_all_time == Σ player_year`** (9 additive counters): **0
  mismatches**.
- **`team_year` Record wins == Σ `team_week` (Win?==True)** across all 48
  team-seasons: **0 mismatches** (Win? is boolean True/False; no ties).
- **`team_all_time` award rollups == Σ `team_year`** (all 12 `Times …`
  award columns): **0 mismatches**.
- **`league_year` == Σ `team_year`** (Number of transactions): **0
  mismatches**.
- **Distinct-count columns** ("Number of QB/WR/RB/TE started/rostered",
  "Number of NFL teams among players"): correctly NON-additive
  (team_all_time ≤ Σ team_year, 0 cases where it exceeds) — a player/team
  started across multiple seasons is one distinct entry all-time but one per
  season per year, so the deliberate non-sum is correct, not a defect. Same
  explanation for the apparent league_year QB/WR-started "gaps".
- **`Number of bids` N/A correctness** (full population): all 1042
  `free_agent` + 14 `commissioner` rows N/A (no competing-bid concept); all
  29 `waiver` 2020 rows N/A (ESPN data unrecoverable); all 419 `waiver`
  2021+ rows numeric. Exactly the intended scope.

### Benign artifact (investigated, root-caused, OUT OF SCOPE — not a defect)

`league_week`'s "Number of trades" disagrees with a standalone
`distinct-trade-date` re-derivation on 9 of ~100 week rows — but ONLY at
week boundaries (e.g. 2021 wk10/11, 2022 wk12/13), and each adjacent
week-pair's totals reconcile exactly (2021 wk10+11 = 3 = 3). Root cause: the
sheet counts DISTINCT TRADE DATES per (year, NFL-scoring-week) via
`_trade_dates_by_yw` (line ~14767), deliberately deduping the 2-team /
3-team mirror rows; the crude calendar `//7` proxy used for a standalone
re-derivation places a handful of boundary trades in the adjacent NFL week.
This counting code is **byte-identical between `main` and the branch** (the
PR's only edits in these blocks are the `Amount of FAAB spent` season gate),
so it is pre-existing behavior, not introduced or affected by this PR —
directly analogous to the stable-sort tie-break artifact accepted in the
original 3-part audit. No code change made.

### Conclusion: 3-part audit ROUND 2 is **CLEAN**

All Rounds 1-4 fixes plus the two just-landed formatting fixes are confirmed
correct, scoped, and fully isolated on the current branch tip, verified with
fresh NOVEL examples and full-population invariants (every player/team/award
rollup invariant = 0 mismatches). The one cross-sheet trade-count
week-boundary discrepancy is a pre-existing calendar-bucketing artifact in
code unchanged by this PR. `pytest tests/ -q` = 15/15.

**CLEAN — 0 defects found, nothing to fix.**
