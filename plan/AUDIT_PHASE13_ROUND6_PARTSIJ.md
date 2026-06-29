# Phase 13 Round 6 — Parts I+J (ESPN-2020 re-verification + build/test cleanliness)

Self-designed full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 5 of 5 (the LAST of Round 6).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `fc3f726` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`fc3f726`, the Round-6
Parts G/H tip carrying the 2 Round-6 C/D tooltip-text fixes) before any work, then
confirmed `git merge-base --is-ancestor fc3f726 HEAD` → `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Reflects all prior fixes:
transactions.csv 1,514, trades.csv 504, picks.csv 450, player_all_time 649,
player_year 1,859, team_year 48.

All examples below are NOVEL — different players/teams/picks than every prior
round (deliberately avoiding Josh Doctson, Kenny Pickett, Hunter Henry,
K.J. Osborn, Carter, Stevenson, Pacheco, Jefferson, DJ Moore, Tyler Johnson,
Larry Fitzgerald, Cam Newton, Mike Gesicki *as a new finding*, BROsenzweig pick
examples, the 2026 2.09 toilet pick, Trubisky/Hurst *as new findings*, AJ Dillon,
Matt Ryan, Tony Pollard, Mattison, Drake, Meyers, Taysom Hill, Kerryon Johnson,
Aaron Jones, T.J. Hockenson, Robbie Chosen, CEH, KJ Hamler, Jalen Guyton, Brady,
Brees). The novel 2020 surfaces used here: A.J. Green, Jack Doyle, Golden Tate,
John Brown, Mike Williams, Adrian Peterson, Antonio Brown, Anthony McFarland,
Allen Lazard — plus the four 2020 bracket teams (shmuel256/Oliverwkw/LWebs53/
plehv79) and the 2020→2023 retention rates for Oliverwkw/plehv79/AceMatthew/
shmuel256/stevenb123.

**Result: 1 minor comment-drift defect found and FIXED** (`src/lotg.py` line 12972
— an internal CODE comment, NOT a cell/tooltip, that the Round-6 C/D agent left
stale when it fixed the parallel user-facing tooltip; comment-text-only, provably
zero computational impact). Everything else in Parts I and J is CLEAN at full
population — 2020 completeness, comment accuracy, link integrity, and the two
Round-6 C/D tooltip fixes are all confirmed accurate FOR 2020 SPECIFICALLY.

---

## Do the Round-6 fixes touch 2020-specific logic? — verified NO (ran to ground, not assumed)

The whole Round-6 source diff (`git diff 81ef7e6..HEAD -- src/`) is **only
`src/formulas.py`** — the 2 Round-6 C/D tooltip-text edits (`Week of playoff
elimination`, `3-year roster retention rate`). `src/lotg.py` and `src/espn_2020.py`
were byte-identical to the Round-5 tip across all of Round 6 (until my own one-line
comment fix below). `formulas.py` carries ONLY tooltip text, never computation —
so by construction the C/D fixes cannot have altered any 2020 (or any) cell value.

The prompt asks specifically whether each fixed tooltip's UNDERLYING COLUMN is
computed differently for 2020 vs other seasons, and if so whether the corrected
tooltip text is ALSO accurate for 2020. Verified directly for BOTH columns:

### `Week of playoff elimination` — computed identically for 2020; corrected tooltip accurate for 2020
- The metric comes from `_playoff_elimination_weeks` (`src/lotg.py` ~13110). It
  iterates `teams_by_year` for EVERY season (2020 included) with NO `if season ==
  2020` branch anywhere in the function (grep of lines 13110-13182 for any year
  literal → **none**). The only season-specific input is `playoff_start_by_season
  .get(season)` (2020's playoff start vs 2021+'s), which the corrected tooltip's
  phrase "computed over the regular-season weeks only (weeks before the playoff
  start)" describes correctly for 2020 too.
- **Actual 2020 `team_year` data matches the corrected tooltip exactly**
  (NOVEL season, not aggregated):
  | 2020 Result | Team | ElimWeek |
  |---|---|---|
  | Champion | shmuel256 | **0** |
  | 2nd | Oliverwkw | **0** |
  | 3rd | LWebs53 | **0** |
  | 4th | plehv79 | **0** |
  | 5th | BROsenzweig | 13 |
  | 6th | AceMatthew | 12 |
  | 7th | JacobRosenzweig | 12 |
  | 8th | stevenb123 | 11 |
  The 4 bracket (top-4) teams carry `0`; the 4 non-bracket teams carry their real
  regular-season elimination week (11-13). This is precisely the corrected
  sentinel semantics (`0` = made the bracket; non-bracket = real week) — and it
  holds for 2020, the structurally-distinct ESPN season, with **0 violations in
  either direction**.

### `3-year roster retention rate` — computed identically for 2020; corrected tooltip's "2020→2023" claim is accurate
- The rate comes from the `retention_3yr_by_ty` block (`src/lotg.py` ~12969). It
  builds `_wk1_roster` keyed by `(team, Y)` from week-1 `player_week` rows for ALL
  years and emits a rate whenever `(team, Y+3)` exists — NO 2020 special-casing
  (the only year literals in the region are in a code COMMENT, fixed below). 2020's
  week-1 roster is just another `(team, 2020)` entry; because the 2023 week-1
  roster exists, 2020→2023 is measurable exactly like 2021→2024.
- **Actual 2020 `team_year` data confirms the corrected tooltip's new "2020→2023"
  claim:** all **8/8** 2020 rows carry a numeric retention rate (0 N/A), range
  0.0476-0.3158. This is the data the Round-6 C/D tooltip fix newly asserts is
  measurable, and it is.
- **Independent recompute (NOVEL teams)** from raw week-1 rosters matches the
  export to 4 dp on every team checked:
  | Team | \|roster_2020\| | kept by 2023 wk1 | recompute | export |
  |---|---|---|---|---|
  | Oliverwkw | 19 | 6 | 0.3158 | 0.3158 ✓ |
  | plehv79 | 19 | 4 | 0.2105 | 0.2105 ✓ |
  | AceMatthew | 19 | 2 | 0.1053 | 0.1053 ✓ |
  | shmuel256 | 21 | 2 | 0.0952 | 0.0952 ✓ |
  | stevenb123 | 21 | 1 | 0.0476 | 0.0476 ✓ |

So both corrected tooltips are accurate for 2020 specifically, precisely BECAUSE
the code computes 2020 the same as every other season.

---

## Part I — ESPN-2020 specific re-verification (full population)

### 2020 completeness — CLEAN
- **team_week grid:** 8 teams × 16 weeks = **128 rows**, complete; every team has
  exactly weeks 1..16, **0 gaps, 0 phantom weeks**. league_week 2020 = weeks 1..16.
- **team_year** 8/8 teams; **player_year** 247 rows; **player_week** 2,632 rows. No
  2020 season silently short on any sheet.
- **2020 startup picks:** all **152** (19 rounds × 8 teams) present; every one
  carries its origin-header comment (**0 missing**). NOVEL made-pick draft-line
  spot checks (deep startup, never named before): `17.01 Jack Doyle` (orig
  Oliverwkw), `17.03 Golden Tate` (orig JacobRosenzweig), `17.04 John Brown` (orig
  AceMatthew) — each `2020 Draft: TEAM drafted PLAYER (round.pick)` line present
  and matching the Number + Original Team.

### 2020 trades raw-vs-export reconciliation — CLEAN (DST-aware, NOVEL detail)
Reconciled the raw ESPN ledger (`data/espn_2020_raw/email_trades.json`, 13
entries) against trades.csv 2020 rows:
- **12 email entries carry player legs → exactly 24 export trade rows** (12 distinct
  events × 2 mirror sides) across 11 distinct local dates.
- **1 empty-leg entry** (`2020-09-09T21:45:18Z`, `involves_picks=true`, no player
  legs) is the documented single exclusion.
- Date sets match once UTC→America/New_York is applied: the only apparent mismatch
  (email `2020-09-30…Z` vs export `2020-09-29`) is the EDT local shift, not a
  missing trade. Export dates: 09-12/09-15/09-29/10-01/10-07/10-29/11-20/11-29/
  12-01/12-13/12-16.

### 2020 comment accuracy — CLEAN (0 fabrications, full population)
Cross-checked every 2020-dated event line in every player_all_time history comment
against the real export rows (date-only key, `(date, team, player)`):
- **175 `added by` lines** → all reconcile to a real transactions.csv 2020 add
  event. **0 fabricated.** (NOVEL: A.J. Green 2020-10-22 added by LWebs53; Adrian
  Peterson 2020-09-19 by stevenb123; Antonio Brown 2020-10-21 by AceMatthew.)
- **171 `dropped by` lines** → all reconcile to a real 2020 drop event. **0
  fabricated.** (NOVEL: A.J. Green 2020-10-15 dropped by BROsenzweig; Allen Lazard
  2020-12-16 by shmuel256.)
- **39 `traded …` lines** → all reconcile to a 2020 trades.csv event whose
  `Assets received`/`Assets sent` blob contains the player on that date. **0
  unreconciled.**
- **0 chronological inversions** in any comment touching a 2020 event (across all
  649 player + 450 pick comments).

### 2020 link integrity (Part G analog) — CLEAN
- **563 link references** in the 4 transactions link columns, restricted to
  2020-dated rows: **0 out-of-range** (`PH#` ≤ 450 picks, `T#` ≤ 504 trades, `#`
  ≤ 1,514 transactions).
- **2020→later teleport re-scan (narrative layer):** scanned every player history
  comment for a 2020 `added` immediately followed by another `added` ≥2 seasons
  later with no intervening close — **0 suspects**. The Round-5 I/J platform-seam
  fix (Trubisky/Hurst) holds; no NEW 2020-origin teleport exists.

### One real finding — stale INTERNAL CODE COMMENT (fixed)
`src/lotg.py` line 12972 — the inline code comment documenting the retention block
— still read *"so currently only 2021->2024 and 2022->2025 are measurable"*. This
is the EXACT stale claim the Round-6 C/D agent corrected in the user-facing tooltip
(`src/formulas.py`), but the parallel code comment was left untouched. The data
proves it wrong: 2020→2023 IS measurable (all 8 teams numeric, verified above).
This is a comment-accuracy defect squarely in Part I's "comment accuracy with the
same rigor as 2021+" mandate (the stale claim specifically OMITS 2020).

**Fix:** rewrote the code comment to state the RULE (measurable only for source
years Y whose Y+3 season has been played; currently 2020→2023, 2021→2024,
2022→2025; Y of 2023+ pending), matching the corrected tooltip. **Comment-text
only — a Python `#` comment, not a string literal — so it provably cannot change
any computed value or the build output** (confirmed: post-edit rebuild exit 0, no
new warnings; full pytest 15/15).

---

## Part J — Build/test cleanliness — CLEAN

- **`pytest tests/ -q`: 15 passed** in ~62s, 0 failed / 0 skipped — INCLUDING the
  full-build `test_player_history_continuity` (roster-lineage continuity end to
  end) and `test_pick_chain_link_integrity`. No net-new warnings vs the Round-5
  baseline.
- **Offline build: exit 0** (rebuilt after the comment fix), only the 2 expected
  network-unavailable warnings (`api.sleeper.app/v1/league/0`, `…/draft/
  espn_2020_draft`). **No new warnings, no tracebacks** (9-line log, identical
  shape to the Round-5/6 baseline).
- **Full Round-6 diff vs the Round-5 baseline introduces no net-new pytest
  warnings/regressions.** The cumulative Round-6 source diff (`81ef7e6..HEAD` +
  my fix) is `src/formulas.py` (the 2 C/D tooltip-text fixes) + `src/lotg.py`
  (one code-comment line) — ALL comment/text-only, ZERO computational changes.
  15/15 held throughout the round.
- **`git status` clean** after reverting build artifacts (`git checkout -- exports/`,
  `git clean -fd exports/ .cache/`) — only `src/lotg.py` (the comment fix) +
  this new file remain.

---

## ROUND 6 OVERALL SUMMARY — NOT fully clean (3 defects fixed this round)

This 5-agent (Parts A/B … I/J) self-designed full-population audit pass found and
fixed real defects, so it is **NOT a clean pass**:

| Agent / Parts | Result |
|---|---|
| **A/B** — completeness + cross-sheet reconciliation | **CLEAN.** Full population: seasons/teams/weeks/player-rollups/picks-grid all complete; trade count 504, transactions 1,514, all cross-sheet invariants 0-mismatch. The 3 excluded raw trades are the documented exclusions (1 phantom-merge + 2 net-zero FAAB swaps). |
| **C/D** — header-comment + asset-history narrative accuracy | **2 FIXES** (both tooltip-TEXT in `src/formulas.py`): (1) `3-year roster retention rate`'s "measurable years" note was stale — omitted the now-measurable 2020→2023 — rewritten to state the rule; (2) `Week of playoff elimination` described the `0` sentinel BACKWARDS (0 is the bracket teams, not the non-bracket) and mislabeled the metric — rewritten accurately. Part D narrative accuracy fully clean. |
| **E/F** — domain-bounds + N/A-vs-0-vs-blank | **CLEAN.** Every bounded column in-domain; every conditional column N/A-correct in both directions; the playoff-elimination `0` sentinel's actual data matches the C/D-corrected tooltip 24/24 + 24/24 across 6 seasons. |
| **G/H** — link integrity + workbook structure | **CLEAN.** 5,651 chain refs + 63,292 hyperlinks all in-range; 0 teleports; 0 off-by-one; all workbook-structural extents track the round-6 row counts. C/D fixes confirmed link-data-inert. |
| **I/J** — ESPN-2020 re-verification + build/test cleanliness | **1 FIX** (`src/lotg.py`, code-comment only): the internal retention-block comment carried the SAME stale "only 2021→2024 and 2022→2025 measurable" claim C/D fixed in the tooltip but missed in the parallel code comment — corrected to include 2020→2023. 2020 completeness/comment/link integrity otherwise fully clean; both C/D tooltip fixes confirmed accurate for 2020 specifically. |

**Round-6 total: 3 defects fixed across 2 of the 5 agent-pairs (C/D = 2 tooltip-text
drifts, I/J = 1 parallel code-comment drift); A/B, E/F, G/H came back clean.** All
3 fixes are comment/tooltip TEXT only — no numeric/cell output changed this round.

> NOTE: The C/D and I/J defects are the SAME stale "measurable years" fact appearing
> in two places — C/D fixed the user-facing tooltip (`formulas.py`), I/J fixed the
> internal code comment (`lotg.py`) that documents the same logic. Both were stale
> for the same reason: the 2020 ESPN backfill made 2020→2023 retention measurable,
> but neither doc-string was updated when the data grew.

Per the user's repeating-cycle instruction: because this 5-agent audit pass was
**NOT fully clean** (3 fixes were needed — Round 6 found defects), this whole
5-agent audit type must be **re-run again as "Round 7" with fresh examples** before
the cycle can advance to the 10-part audit stage, continuing until the 5-agent
audit type comes back fully clean on a pass.

This continues the Rounds 2-5 pattern: broader/deeper full-population checks keep
surfacing real, narrow doc/comment-drift defects that sample-based checks miss —
here, a single stale "measurable years" fact (2020 backfill making 2020→2023
retention measurable) that had drifted in BOTH the user-facing tooltip and the
internal code comment, plus a sentinel whose meaning had never been written up
accurately (the playoff-elimination `0`).
