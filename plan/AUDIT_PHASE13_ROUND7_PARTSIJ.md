# Phase 13 Round 7 — Parts I+J (ESPN-2020 backfill re-verification + build/test cleanliness)

Self-designed full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 5 of 5 (the LAST of Round 7).
Siblings this round: Parts A/B — `AUDIT_PHASE13_ROUND7_PARTSAB.md` — CLEAN at
`4bf5575`; Parts C/D — `AUDIT_PHASE13_ROUND7_PARTSCD.md` — 4 tooltip-text drift
fixes (`src/formulas.py`, 2020-vs-2021 draft terminology) at `be65140`; Parts E/F —
`AUDIT_PHASE13_ROUND7_PARTSEF.md` — CLEAN at `00447a0`; Parts G/H —
`AUDIT_PHASE13_ROUND7_PARTSGH.md` — CLEAN, link-data byte-identical to Round 6, at
`3ebc177`.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (the `main`-side diff base), which is NOT a descendant of
the branch tip; `git merge-base --is-ancestor 3ebc177 HEAD` printed NEEDS_RESET.
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`3ebc177`, the Round-7 Parts
G/H tip carrying all Round-4/5/6 fixes + the Round-7 C/D 4 tooltip-text fixes), then
confirmed `git merge-base --is-ancestor 3ebc177 HEAD` → `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: transactions
1,514, picks 450, team_year 48, player_year 1,859, player_week 21,376, team_week
808, trades 504, player_all_time 649.

All examples below are NOVEL — different players/teams/picks/seasons than every
prior round (Rounds 4-7 exclusion list honoured; deliberately avoiding Mitchell
Trubisky / Hayden Hurst / Wayne Gallman / Giovani Bernard / MVS / KJ Hamler / Drew
Brees / AJ Dillon / Matt Ryan / Tony Pollard / Mattison / Drake / Meyers / Taysom
Hill / Aaron Jones / A.J. Green / Jack Doyle / Golden Tate / John Brown / Adrian
Peterson / Antonio Brown / Anthony McFarland / Allen Lazard / CEH / Hockenson /
Kerryon Johnson / Robbie Chosen / Ameer Abdullah / Deuce Vaughn / Ryan Tannehill as
NEW findings). The novel 2020-seam surfaces used here: **Kyle Rudolph**, **Malcolm
Brown**, **Lynn Bowden**, **Travis Fulgham** (fresh clean boundary-holder seam
drops); **Drew Lock** and **Rex Burkhead** (fresh same-team-reappear-after-gap cases
whose 2020 holding was closed within 2020, so they correctly get NO synthetic seam
drop — the inverse of the Trubisky/Hurst exception); the **transactions
'Length of tenure on team'** header tooltip + **Travis Fulgham** history hover (fresh
comment-clip spot-checks); **team_week / team_year / picks 'Original Team'** columns
(fresh team-name word-wrap spot-checks).

**Result: CLEAN — 0 defects found in Parts I or J.** The ESPN-2020 backfill is
correct at full population (team/roster/draft-type tagging, transaction-type +
FAAB/bids N/A'ing, the 3 startup-exclusion DATA columns 0 for all 8 teams, and the
2020→2021 platform-seam-teleport fix all hold for fresh, previously-unexamined
players). Build is exit 0 with only the 2 expected network warnings; pytest 15/15;
no debug prints / dead code / TODO markers introduced in the PR diff; the workbook
opens cleanly and both original formatting bugs (comment clipping, team-name
word-wrap) remain fixed on fresh cells. No source change required.

---

## Part I — ESPN 2020 backfill re-verification

### I.0 — Does any in-PR change touch 2020-specific logic? — reviewed
`git diff 6d83635...HEAD -- src/` is 3 files: `src/formulas.py` (tooltip TEXT only,
the C/D-family 2020-vs-2021 fixes — never computation), `src/lotg.py` (the cumulative
Round-4/5/6 fixes, incl. the platform-seam transfer-drop synth re-verified in I.4),
and `src/espn_2020.py`. The only `espn_2020.py` change is a 2020 trade→weekly-bucket
alignment in `emit_sleeper_2020` (a new `_calendar_trade_wk` using lotg.py's
calendar-anchored `_trade_wk` rule instead of the old email-parser `trade_week`
heuristic, so team_week's per-week trade bucket agrees with league_week's
independently-recomputed `Number of trades`). It changes only which WEEK a 2020 trade
buckets into — never the trade's existence, type, or count — and is fully documented
in-code. The 2020 emitter still produces only `waiver` / `free_agent` / `trade`
types and ZERO `commissioner` types (confirmed in I.1).

### I.1 — 2020 transactions: type tagging + FAAB/bids N/A'ing — CLEAN
**221 2020 transactions** (derived by `Date.year == 2020`): **192 free_agent + 29
waiver, 0 commissioner, 0 trade-as-tx** — exactly the ESPN-2020 emitter's type
vocabulary (no FAAB-era commissioner churn leaking into 2020).

**FAAB fields properly N/A'd (Fix 3 — 2020 has no FAAB bidding).** Reading the export
with NaN-coercion disabled (so a literal `N/A` string is distinguishable from a blank
cell), **all 221** 2020 transactions render the literal string **`N/A`** in every one
of `Faab`, `Total FAAB bid`, and `Number of bids` — 0 blanks, 0 `0`, 0 fabricated
placeholder. The bidirectional control holds: the **29 2020 waiver** rows also show
`Number of bids = N/A` (2020 ESPN has no competing-claim data), while **2022 waiver**
rows carry real Faab values (1.0…48.0) — so the gate is 2020-specific, not globally
blanked.

### I.1b — 2020 completeness grids — CLEAN
- **team_week 2020:** 8 teams × 16 weeks = **128 rows**, complete; every team has
  exactly weeks 1..16 (`{AceMatthew:16, …, stevenb123:16}`), **0 gaps, 0 phantom**.
- **league_week 2020** = weeks 1..16; **team_year 2020** = 8/8 teams;
  **player_year 2020** = 247 rows; **player_week 2020** = 2,632 rows / 236 distinct
  players. No 2020 season silently short on any sheet.

### I.2 — 2020 draft-type tagging (startup vs in-season) — CLEAN
picks `Year`-label distribution keeps the inaugural draft cleanly separated from the
2021 vet draft and from rookie classes:
`startup 152 | 2021 (vet) 32 | 2021 32 | 2022 32 | 2023 32 | 2024 33 | 2025 40 |
2026 33 | 2027 32 | 2028 32`. The **152 startup picks = 19 rounds × 8 teams**, all 8
teams present as Original Team, rounds **1..19** all present. The `startup` label is a
distinct token from `2021 (vet)` — no conflation in the DATA (matching the C/D
tooltip-text fix that corrected the same distinction in the *tooltip*).

### I.3 — 2020 startup picks excluded from the 3 draft-count/value columns — CLEAN (re-verified, not trusted)
Re-derived fresh from the export's `team_year` (not relying on the Round-7 E/F
claim): for **2020, all 8 teams**:

| Column | 2020 value (all 8 teams) |
|---|---|
| `Draft Value` | **0.0** |
| `Number of first round picks made` | **0** |
| `Total number of picks made` | **0** |

Per-team confirmation (all 8): `{Draft Value 0.0, first-round 0, total 0}`. The
19-round 2020 ESPN startup IS excluded from these rookie-draft-only columns exactly
as the C/D-corrected tooltips now document. Control: non-2020 years carry real
nonzero counts (e.g. 2022 `Total number of picks made` ∈ {2,3,4,5,6}; 2024 ∈
{2,3,4,12}) — so the 0 is a 2020-specific exclusion, not a globally-zero column.

### I.4 — 2020→2021 platform-seam-teleport fix re-verify (narrowest-correct condition) — HOLDS

The seam synthesizes one drop per holdover player at the 2021 transfer day
(`2021-08-23`). Full-population scan of `Date dropped/traded == 2021-08-23`:
**12 seam-drop tx rows, 11 distinct players, exactly 1 player with >1** (Mitchell
Trubisky — his two 2020 waiver adds both closing at the seam, the documented Round-7
C/D Sleeper duplicate-add pattern, one stint). The other 10 are clean one-drop
holdovers.

**Fresh boundary-holder seam drops verified end-to-end** (each was on the team's 2020
roster, held at the boundary, absent the ENTIRE 2021 season → gets exactly ONE
`2021-08-23: dropped by <boundary team>`):
- **Kyle Rudolph** — `2020-12-04 added by JacobRosenzweig` → `2021-08-23 dropped by
  JacobRosenzweig`. One clean seam drop, no later reappearance, no teleport.
- **Travis Fulgham** — `2020-10-15 added by stevenb123` → `2020-10-17 dropped by
  stevenb123` (recorded intra-2020) → `2020-10-21 added by BROsenzweig` →
  `2021-08-23 dropped by BROsenzweig`. The seam drop is attributed to the player's
  *boundary holder* (BROsenzweig), not the earlier stevenb123 stint — correct
  `_holder_2020_end` attribution.
- **Malcolm Brown** — `2020-09-12 added by shmuel256` → `2020-09-15 traded to
  Oliverwkw` → `2020-12-23 dropped by Oliverwkw` → `2020-12-23 added by shmuel256` →
  `2021-08-23 dropped by shmuel256`. Through a 2020 trade AND a same-day re-add, the
  seam drop still fires for the correct final boundary holder (shmuel256).
- **Lynn Bowden** — `2020-12-17 added by shmuel256` → `2020-12-26 dropped by
  shmuel256` → `2020-12-26 added by stevenb123` → `2021-08-23 dropped by stevenb123`.
  Correct boundary-holder attribution after an intra-2020 hand-off.

**The narrow-exception path re-verified with FRESH same-team-after-gap cases.** Full
scan for players present in 2020, absent the ENTIRE 2021 season, reappearing 2022+:
**12 gap-crossers — 5 reappear on the SAME 2020 team, 7 on a DIFFERENT team.** The
fix fires a synthetic seam drop ONLY for a genuine boundary-holder whose 2020 holding
was never closed by a recorded drop and who is re-acquired later by the SAME team —
i.e. Trubisky/Hurst. The two NOVEL same-team gap-crossers prove the condition is
narrow (not over-broad):
- **Drew Lock** (shmuel256 2020 → shmuel256 2023): his 2020 holding was already
  closed by a **recorded** `2020-11-17 dropped by shmuel256`, so he is NOT a boundary
  holder. His narrative is `2020-11-11 added by shmuel256 → 2020-11-17 dropped by
  shmuel256 → 2023-12-20 added by shmuel256 → 2023-12-27 dropped`. **No synthetic
  seam drop** (correct — there is already a real drop separating the stints; a seam
  drop would be a spurious double-departure). 0 teleport.
- **Rex Burkhead** (LWebs53 2020 → LWebs53 2022): `2020-09-26 added by LWebs53 →
  2020-10-05 dropped by LWebs53 → 2022-09-14 added by LWebs53 (waiver $11) →
  2022-09-30 dropped`. Again a **recorded** 2020 drop closes the holding → **no
  synthetic seam drop**, no teleport. (Note Burkhead reappears in 2022, not 2021, and
  via a real recorded add — never crossing an OPEN holding.)

The 7 different-team gap-crossers (NOVEL: **Joshua Kelley**, **Marlon Mack**, **Matt
Breida**, **Randall Cobb**, **Jerick McKinnon**, plus the excluded Brees/Hamler) are
correctly handled by the general arrival-anchored reconciliation (a different team's
re-acquisition closes the old holding) and get no extra seam drop — consistent with
the fix's documented guard.

**Narrative-layer full-population teleport scan (all 649 player + all 450 pick
history comments).** **0 chronological inversions** (player 0, picks 0). **0
cross-team add→add teleports.** The only 5 same-team add→add suspects are the
documented Sleeper duplicate-add pattern, all already identified in prior rounds
(Ameer Abdullah, Deuce Vaughn, Mitchell Trubisky, Ryan Tannehill, Taysom Hill) — each
a FA record + commissioner/re-logged correction for ONE roster stint, all same-team,
0 cross-team. The platform-seam-teleport fix (Round 5 I/J) holds in BOTH the
transaction/link layer (12 clean seam drops) and the narrative layer (0 teleports)
for fresh, previously-unexamined boundary crossers.

---

## Part J — Build & test cleanliness — CLEAN

- **`pytest tests/ -q`: 15 passed** in ~72s, **0 failed / 0 skipped**, exit 0. The
  prompt's `test_no_player_history_continuity_breaks` is the only test gated by a
  skipif (`@pytest.mark.skipif(not _xlsx_path().exists() or not _is_fixera_build())`,
  keyed on the `"orphaned roster lineage"` marker in `exports/raw/build_debug.log`).
  On a fresh build the marker is present (count = 2 in the log), so the test **RAN and
  PASSED** (verified independently: `pytest tests/test_player_history_continuity.py
  -v` → `PASSED`). The skipif gate is intact (it would skip only on a CSV-only / stale
  pre-fix workbook); the test is NOT silently failing or masked — it is the
  full-build roster-lineage continuity guard and it passes, confirming the 2020 seam
  drops introduce no continuity break. No regression.
- **Offline build: exit 0.** `exports/raw/build_debug.log` reviewed in full (17
  lines): only INFO records (gsis corrections, ESPN-2020 injection "8 teams, 152
  draft picks, 222 transactions", commissioner pick-trade overlay, scoring-settings
  changes, commissioner-wash exclusions, draft-day synthetic-pick) — **0 ERROR, 0
  WARN, 0 traceback**. The stdout/stderr stream carries **exactly the 2 expected
  network-unavailable warnings** (`api.sleeper.app/v1/league/0`,
  `…/draft/espn_2020_draft`) and nothing else.
- **No leftover debug prints / dead code / TODO markers in the PR diff.**
  `git diff 6d83635...HEAD -- src/` (the diff vs main): **0 raw `print(` statements**
  added; **0 `TODO`/`FIXME`/`XXX`/`HACK` markers** added (the only "DEBUG"-ish matches
  are 3 legitimate `_log_exc(debug, …)` structured-exception calls, not stray prints);
  every added `#` line is explanatory prose documenting the logic/rationale, **not
  commented-out dead code**. No incomplete-work residue.
- **Workbook opens cleanly** — all 13 sheets load via openpyxl with no error.
  - **Comment-clipping fix HOLDS (fresh cells).** Read the persisted VML box geometry
    for all comment boxes: **1,892 boxes**, widths {460 (header), 560 (history)},
    heights **80–620px across 41 distinct values** (per-text-length sizing), **0 over
    the 900px header cap, 0 over the 1,100px history cap, 0 pinned at a cap** — no box
    clipped by a flat pin. Two FRESH spot-checks, both present and substantial and
    rendered in a text-sized box: the **transactions `Length of tenure on team`**
    header tooltip (415 chars, 3 lines) and the **Travis Fulgham** history hover (229
    chars, 4 lines).
  - **Team-name word-wrap fix HOLDS (fresh cells).** With `wrap_text=True` on all
    data cells (Phase 12 #7), the fix is the full-column-scan width
    (`min(40, max(10, maxlen+2))`) so a team-name token never wraps mid-token. Three
    FRESH columns: **team_week `Team`**, **team_year `Team`**, **picks `Original
    Team`** are each **width 17.0 = longest name "JacobRosenzweig" (15) + 2** → every
    team name fits on one line, 0 mid-token wrap.
- **`git status` clean** after reverting build artifacts (`git checkout -- exports/`,
  `git clean -fdq exports/ .cache/`) — only this new findings doc remains.

---

## ROUND 7 OVERALL SUMMARY — NOT fully clean (4 defects fixed this round)

| Agent / Parts | Result |
|---|---|
| **A/B** — completeness + cross-sheet reconciliation | **CLEAN** (`4bf5575`). |
| **C/D** — header-comment + asset-history narrative accuracy | **4 FIXES** (`be65140`), all `src/formulas.py` tooltip TEXT — the 2020-startup-label family (`Startup draft players remaining` wrong year; `Draft Value` / `Number of first round picks made` / `Total number of picks made` incomplete exclusion). No cell data changed. Part D narrative CLEAN. |
| **E/F** — domain-bounds + N/A-vs-0-vs-blank | **CLEAN** (`00447a0`); re-verified the 2020 DATA of the 4 C/D-fixed columns matches the corrected tooltips. |
| **G/H** — link integrity + workbook structure | **CLEAN** (`3ebc177`); link-data byte-identical to Round 6. |
| **I/J** — ESPN-2020 re-verification + build/test cleanliness | **CLEAN.** 2020 type/FAAB/bids/draft-type tagging correct; the 3 startup-exclusion columns 0 for all 8 teams (re-verified, not trusted); platform-seam-teleport fix holds for fresh boundary holders (Kyle Rudolph / Travis Fulgham / Malcolm Brown / Lynn Bowden) AND the narrow same-team-after-gap exception is correctly NOT over-firing (Drew Lock / Rex Burkhead get no spurious seam drop). Build exit 0, pytest 15/15, no debug/dead-code/TODO in the diff, both formatting fixes hold on fresh cells. |

**Round-7 total: 4 defects fixed, all in C/D, all tooltip-TEXT in `src/formulas.py`
(the 2020-vs-2021 draft terminology family); A/B, E/F, G/H, I/J all came back clean.**
No cell/numeric output changed anywhere in Round 7.

Per the user's repeating-cycle instruction: because this 5-agent audit pass was **NOT
fully clean** (4 tooltip-text fixes were needed in C/D), the 5-agent audit type would
re-run again as a future round with fresh examples before the cycle advances. But the
DATA layer is now clean across all five agent-pairs at full population for the second
consecutive round (Round 6 and Round 7 both found only TEXT defects, never a cell
value) — the audit is converging: the surviving defects are documentation drift, not
computational error.

This continues the Rounds 2-6 pattern: broader/deeper full-population checks keep
surfacing real, narrow defects sample-based checks miss — but for I/J specifically,
the highest-risk surface (the structurally-distinct ESPN-2020 pipeline and its
2020→2021 platform seam) is fully CLEAN at full population this round, with the
platform-seam-teleport fix re-confirmed on genuinely fresh boundary crossers in BOTH
directions (fires for true boundary holders, does not over-fire for within-2020-closed
same-team reappearances).
