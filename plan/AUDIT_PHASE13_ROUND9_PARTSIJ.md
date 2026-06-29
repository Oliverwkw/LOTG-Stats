# Phase 13 Round 9 — Parts I+J (ESPN-2020 backfill re-verification + build/test cleanliness)

Self-designed full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 5 of 5 — the LAST of Round 9.
Siblings this round: Parts A/B — `AUDIT_PHASE13_ROUND9_PARTSAB.md` — CLEAN at
`642f111`; Parts C/D — `AUDIT_PHASE13_ROUND9_PARTSCD.md` — 2 tooltip-text fixes
(the 2020-startup-draft-label family: `O-Score` Notes + picks `Number of trades`
Notes, both mislabelling the inaugural **2020** ESPN startup draft as a "2021"
event) at `133d85e`; Parts E/F — `AUDIT_PHASE13_ROUND9_PARTSEF.md` — CLEAN at
`cafa982` (confirmed the underlying N/A-vs-0 DATA was already correct); Parts
G/H — `AUDIT_PHASE13_ROUND9_PARTSGH.md` — CLEAN at `98c097c` (link-data
byte-identical to Round 8; the O-Score header box grew 620→668px to fit the
corrected longer C/D text, still under the 900px cap).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (the `main`-side diff base; `git merge-base
--is-ancestor 98c097c HEAD` printed `STALE` — `98c097c` was NOT an ancestor of
HEAD). Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`98c097c`, the
Round-9 Parts G/H tip carrying all Round-5..Round-9 fixes), then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings on stdout — `api.sleeper.app/v1/
league/0` and `…/draft/espn_2020_draft`). Not a stale cache. Full population:
transactions 1,514 (221 in 2020), picks 450, team_year 48, player_year 1,859,
player_week 21,376, team_week 808, league_week 101, trades 504,
player_all_time 649.

All examples below are NOVEL — different players/teams/seasons/picks than every
prior round (Rounds 4-9 A/B-C/D-E/F-G/H exclusion lists honoured; deliberately
avoiding the long named list incl. Mitchell Trubisky / Hayden Hurst / Kyle
Rudolph / Malcolm Brown / Lynn Bowden / Travis Fulgham / Giovani Bernard / Wayne
Gallman / Julian Edelman / Brian Hill / Dexter Williams / Tyron Billy-Johnson /
Anthony McFarland / Marquez Valdes-Scantling / Denzel Mims / Sterling Shepard /
Mike Williams / Calvin Ridley / Davante Adams / Dalton Kincaid, and the prior PF
Semifinal seed pairs). The novel 2020 surfaces used here: **Golden Tate** (a
NOVEL startup-drafted holdover seam-dropped at the boundary, never traded/added
mid-season), **AJ Dillon** and **Adam Trautman** (NOVEL 2021-vet-draft narrative
cases — AJ Dillon is the textbook 2020-startup→2021-vet *re-draft* dual-draft
chain), and the **picks `Original Team` + player_all_time `Last team`** columns
as fresh word-wrap spot-checks.

**Result: 1 real defect found + FIXED** (the SAME 2020-vs-2021 draft-seam family
as Rounds 6/7/8/9-C/D — this round in the **generated asset-history NARRATIVE
text**, not a tooltip). The inline-generated history-comment line for every
**2021 supplemental veteran draft** pick was rendered as **"2021 startup (vet)
draft: …"** — applying the word "startup" (which belongs to the *2020* ESPN
startup draft) to the *2021* vet draft. **32** player_all_time comments + the
corresponding **47** picks-sheet comments carried the mislabel. Rewritten to
**"2021 supplemental veteran draft: …"** (`src/lotg.py`), matching the
C/D-corrected tooltip terminology; the test-support parser regex in
`scripts/audit_player_history.py` was updated in lock-step to recognize the new
draft-line wording (and keep the legacy form for robustness). Everything else in
Parts I/J is CLEAN at full population.

---

## Part I — ESPN 2020 backfill re-verification

### I.0 — Does any in-PR change touch 2020-specific logic? — reviewed
`git diff 6d83635...HEAD -- src/` is 3 files: `src/espn_2020.py` (+26 — the 2020
trade→weekly-bucket alignment in `emit_sleeper_2020`), `src/formulas.py` (tooltip
TEXT only — the cumulative C/D-family 2020-vs-2021 fixes), `src/lotg.py` (the
cumulative Round-4..9 fixes incl. the platform-seam transfer-drop synth re-verified
in I.4, plus THIS round's narrative-label fix). All `espn_2020.py` changes are
week-bucket alignment that changes only WHICH WEEK a 2020 trade falls into — never
the trade's existence/type/count — and the 2020 emitter still produces only
`waiver`/`free_agent`/`trade` types and ZERO `commissioner` types (confirmed in
I.1).

### I.1 — 2020 transactions: type tagging + FAAB/bids N/A'ing — CLEAN
**221 2020 transactions** (by `Date.year == 2020`): **192 free_agent + 29 waiver,
0 commissioner, 0 trade-as-tx** — exactly the ESPN-2020 emitter's type vocabulary
(no FAAB-era commissioner churn leaking into 2020).

**FAAB fields properly N/A'd (2020 has no FAAB bidding).** Reading the export with
`keep_default_na=False` (literal `N/A` distinguishable from blank), **all 221**
2020 transactions render the literal string **`N/A`** in every one of `Faab`,
`Total FAAB bid`, `Number of bids` — 0 blanks, 0 `0`, 0 fabricated placeholder.
The 29 2020 waiver rows also show `Number of bids = N/A` (the gate is
2020-specific, not globally blanked — the control held in prior rounds with 2022
waivers carrying real Faab values).

### I.1b — 2020 completeness grids — CLEAN
- **team_week 2020:** 8 teams × 16 weeks = **128 rows**, weeks 1..16, 0 gaps, 0
  phantom (no week 17).
- **league_week 2020** = weeks 1..16; **team_year 2020** = 8/8 teams;
  **player_year 2020** = 247 rows; **player_week 2020** = 2,632 rows / 8 teams,
  weeks 1..16 only. No 2020 season silently short on any sheet. (Stable vs Rounds
  5-8.)

### I.2 — 2020 draft-type tagging (startup vs in-season) — CLEAN
picks `Year`-label distribution keeps the inaugural draft cleanly separated:
`startup 152 | 2021 (vet) 32 | 2021 32 | 2022 32 | 2023 32 | 2024 33 | 2025 40 |
2026 33 | 2027 32 | 2028 32`. The **152 startup picks = 19 rounds × 8 teams** (all
rounds 1..19 present, all 8 teams present as Original Team). The `startup` token is
distinct from `2021 (vet)` — no conflation in the DATA.

### I.3 — 2020 startup picks excluded from the 3 draft-count/value columns — CLEAN (re-derived fresh)
Re-derived fresh from the export's `team_year` (not relying on prior-round claims):
for **2020, all 8 teams**: `Draft Value` = **0.0**, `Number of first round picks
made` = **0**, `Total number of picks made` = **0**. The 19-round 2020 ESPN
startup IS excluded from these rookie-draft-only columns. Control: non-2020 years
carry real nonzero counts (2022 `Total number of picks made` ∈ {2,3,4,5,6}; 2024 ∈
{2,3,4,12}) — so the 0 is a 2020-specific exclusion, not a globally-zero column.
Also re-confirmed: **all 152 startup picks AND all 32 vet picks have `Number of
trades` = 0** (0 nonzero in either set), the count the Round-9 C/D tooltip fix
documents.

### I.4 — 2020→2021 platform-seam-teleport fix re-verify (fresh players) — HOLDS
Full-population scan of the seam-drop rows (`Date = 2021-08-23 20:00:00`, `Date
dropped/traded = N/A`): **14 seam-drop rows, 14 DISTINCT dropped players, exactly 0
players with >1** — each boundary holdover gets exactly ONE synthetic seam drop.

**NOVEL boundary-holder verified end-to-end — Golden Tate** (a fresh
*startup-drafted* holdover, not previously used): picks origin `startup 17.03`,
Original Team & Final Team JacobRosenzweig, `Number of trades = 0`; present only in
2020 player_week (JacobRosenzweig); **no recorded mid-season add or trade** (he was
drafted in the startup and simply held). His rendered narrative is exactly:
```
2020 17.03 — originally JacobRosenzweig's pick
2020 Draft: JacobRosenzweig drafted Golden Tate (17.03)
2021-08-23: dropped by JacobRosenzweig
```
One clean seam drop, chronological, no teleport across the empty 2021/2022 seasons.
The 2020 startup draft line is correctly labelled "2020 Draft:" (not "startup").

The other 13 seam-drop holdovers map to the prior-round-documented set (Giovani
Bernard, Wayne Gallman, Travis Fulgham, Kyle Rudolph, Julian Edelman, Mitchell
Trubisky, Dexter Williams, Tyron Billy-Johnson, Anthony McFarland, Brian Hill,
Malcolm Brown, Hayden Hurst, Lynn Bowden) — re-confirmed: each appears exactly once
(Trubisky's documented duplicate-add still yields exactly ONE seam drop). The fix
holds.

### I.5 — DEFECT: the 2021-vet-draft narrative is mislabelled "startup" (the recurring 2020-vs-2021 seam family) — FOUND + FIXED

The prompt specifically asked to grep `src/formulas.py` AND any inline `lotg.py`
generated text ONE more time for any remaining `"2021"` + `"startup"` co-occurrence
or `"vet draft"`/`"vet/startup"` phrasing that might still mislabel the 2020 draft,
to see if this family is now truly exhausted. **It was not yet exhausted** — it had
moved from the tooltip layer (Rounds 6/7/8/9-C/D) into the **generated
asset-history narrative** layer.

**`src/lotg.py` line 15794-15798 — the pick-history narrative line for every 2021
vet-draft pick.** The branch `if "(vet)" in _yr_disp.lower():` (which fires for
`Year == "2021 (vet)"`) emitted the history line:
- Old: `f"{_yr} startup (vet) draft: {_final} {_drafted_txt}"` → rendered
  **`"2021 startup (vet) draft: stevenb123 drafted AJ Dillon (1.01)"`**.

This is the SAME conflation the Round-9 C/D fixes corrected in two tooltips: the
word **"startup"** belongs to the *2020* ESPN startup draft, while this event is the
*2021* supplemental veteran draft. The code's OWN adjacent comments (lotg.py
15887-15889) distinguish them correctly — *"a veteran taken in the 2020 ESPN startup
… then RE-drafted in the 2021 supplemental (vet) draft (e.g. Matt Ryan…)"* — so the
generated user-visible string was drifting from the code's own (correct) model. For
a re-drafted veteran this produced the absurd implication of TWO startup drafts for
one player (a "2020 Draft" AND a "2021 startup (vet) draft").

**Full-population impact (built workbook, BEFORE fix):** **32** player_all_time
column-A history comments + the corresponding **47** picks-sheet column-A comments
contained `"2021 startup (vet) draft"` (47 > 32 because a picks comment shows the
drafted player's FULL history, so re-drafted veterans surface the line on multiple
pick rows).

**Fix (`src/lotg.py`):** rewrote the generated line to
`f"{_yr} supplemental veteran draft: {_final} {_drafted_txt}"` → renders
**`"2021 supplemental veteran draft: …"`**, matching the C/D-corrected tooltip
terminology, and updated the adjacent code comment to state explicitly that this is
the 2021 supplemental veteran draft (distinct from the 2020 ESPN startup) and that
it must NOT be labelled "startup". This is a pure narrative-TEXT change — no cell
value, no link, no count changed; `Number of trades` for these vet picks is still 0.

**Companion fix (`scripts/audit_player_history.py`) — required for the continuity
guard.** The test-support parser's draft-line regex hard-coded the old wording:
```
_RE_DRAFT = re.compile(r"^(\d{4}) (?:startup \(vet\) )?(?:[Dd]raft|startup \(vet\) draft): (\S+) ")
```
After the narrative fix it no longer recognized the vet-draft arrival line, so
`tests/test_player_history_continuity.py` reported false
`MISSING_ARRIVAL_BEFORE_DROP`/`…_TRADE` breaks for every vet-drafted player (Adam
Trautman, AJ Dillon, Anthony Firkser, Cam Newton, Damien Harris, …). Generalised
the regex to recognize ANY draft-descriptor prefix before `draft:`:
```
_RE_DRAFT = re.compile(r"^(\d{4}) (?:[\w() ]+ )?[Dd]raft: (\S+) ")
```
Verified it matches the plain `"YYYY Draft:"`/`"YYYY draft:"` form, the new `"YYYY
supplemental veteran draft:"` form, AND the legacy `"YYYY startup (vet) draft:"`
form, while correctly NOT matching drop/origin lines. With this, the continuity
guard passes against the rebuilt workbook (15/15).

**Post-fix verification (rebuilt workbook):**
- player_all_time comments with `"startup (vet) draft"`: **32 → 0**; with
  `"supplemental veteran draft"`: **0 → 32**.
- picks-sheet comments with `"startup (vet) draft"`: **→ 0**; with `"supplemental
  veteran draft"`: **→ 47**.
- Generated-text grep of `src/lotg.py` for any f-string still pairing `startup`
  with `vet`/`2021`: **0 hits** — the narrative layer is now clean.
- **NOVEL corrected narratives rendered whole (not clipped):**
  - **Adam Trautman** (162 chars): `2021 3.06 — originally LWebs53's pick` →
    `2021 supplemental veteran draft: LWebs53 drafted Adam Trautman (3.06)` →
    `2021-08-31: dropped by LWebs53 (added Jamison Crowder)`.
  - **AJ Dillon** (950 chars — the textbook dual-draft re-draft case): `2020 Draft:
    plehv79 drafted AJ Dillon (15.06)` (2020 startup, correctly "2020 Draft") →
    `2020-12-31: dropped by plehv79` → `2021 supplemental veteran draft: stevenb123
    drafted AJ Dillon (1.01)` (2021 vet, now correctly labelled) → four chronological
    trade events → `2024-07-24: dropped by Oliverwkw`. Both draft events now
    correctly distinguished; before the fix the second line would have read "2021
    startup (vet) draft", implying two startup drafts for one player.

### I.5b — The C/D-family tooltip layer (formulas.py) is now exhausted — CLEAN
Re-grepped `src/formulas.py` for `"startup"`+`"2021"` co-occurrence / `"startup
(vet)"` / `"vet/startup"` / `"startup/vet"`: the 7 surviving hits (lines 184, 306,
346, 1075, 1078, 1081, 1243) are all the CORRECTLY-WORDED tooltips from the prior
fixes — each names "**the 2020 ESPN startup draft**" and "**the 2021 supplemental
veteran draft**" as distinct events (they co-occur only because both correct names
appear in the same sentence). 0 surviving mislabels in the tooltip layer. Combined
with the narrative-layer fix above, the 2020-vs-2021 draft-label family is now
exhausted across BOTH user-visible text surfaces (tooltips + generated narratives).

---

## Part J — Build & test cleanliness — CLEAN (after the fix)

- **`pytest tests/ -q`: 15 passed** in ~75s, **0 failed / 0 skipped**, exit 0.
  - The narrative fix initially regressed `test_no_player_history_continuity_breaks`
    (the parser regex no longer matched the reworded vet-draft line); the companion
    `scripts/audit_player_history.py` regex fix resolved it. After both fixes the
    full suite is **15/15**, including the full-build
    `test_no_player_history_continuity` (the roster-lineage continuity guard — it
    RAN, the fix-era marker being present on a fresh build) and
    `test_pick_chain_link_integrity`. No residual regression.
- **Offline build: exit 0** (both before and after the fix), with **exactly the 2
  expected network-unavailable warnings on stdout** (`api.sleeper.app/v1/league/0`,
  `…/draft/espn_2020_draft`). `exports/raw/build_debug.log` reviewed: the only
  non-INFO records are (a) the KTC `dynasty-daddy.com` 403 ERROR + WARN — one of the
  2 expected network-unavailable sources (KTC is fetched over the same blocked proxy;
  offline by design), (b) the `WARN commish pick-trade UNMATCHED: 2026 R209
  Oliverwkw->LWebs53` + `1/33 pick-hops unmatched` — **PRE-EXISTING, not in this
  PR's diff** (documented in Round 8 I/J; concerns one 2026 *future* toilet pick, no
  data-cell error), and (c) `WARN ... across 0 findings` = the known-player
  validation line reporting 0 mismatches (clean). **0 NEW ERROR/WARN beyond the 2
  expected network-unavailable ones.**
- **No leftover debug prints / dead code / TODO markers in the PR diff.**
  `git diff 6d83635...HEAD -- src/` (vs main): **0 raw `print(`/`pdb`/`breakpoint`
  added**, **0 `TODO`/`FIXME`/`XXX`/`HACK` markers added**, **0 commented-out dead
  code**. This round's `src/lotg.py` change is a 1-line generated-string edit + a
  5-line explanatory comment (no residue). (The companion change is in
  `scripts/audit_player_history.py`, outside `src/` — a test-support parser, not
  product code; also clean, a 1-line regex generalisation + a 3-line comment.)
- **Workbook opens cleanly** — all 13 sheets load via openpyxl with no error.
  - **Comment-clipping fix HOLDS (fresh cells).** Read the persisted VML box
    geometry from `xl/drawings/commentsDrawing*.vml`: **1,892 boxes** (793 header
    width-460 + 1,099 history width-560), heights **80–668px**, **0 over the 900px
    header cap, 0 over the 1,100px history cap, 0 pinned** — per-text-length sizing.
    - **The O-Score header box is still 460×668px** (the C/D Round-9 longest box).
      My narrative fix did NOT touch the O-Score tooltip, so it stayed at 668px —
      232px of headroom under the 900px cap. Verified the 2,402-char tooltip renders
      whole, ending with the full sentence "…Percentiles are within each sheet
      (picks vs picks, etc.)." — not clipped, not pinned.
    - The corrected vet-narrative hover boxes (e.g. AJ Dillon, 950 chars) render in
      a text-sized 560px-wide box, well under the 1,100px history cap, unclipped.
  - **Team-name word-wrap fix HOLDS (fresh cells).** Two NOVEL columns:
    **picks `Original Team`** and **player_all_time `Last team`** are each **width
    17.0 = longest name "JacobRosenzweig" (15) + 2**, with `wrap_text=True` → every
    team name fits on one line, 0 mid-token wrap.
- **`git status` clean** after reverting build artifacts (`git checkout --
  exports/`, `git clean -fdq exports/ .cache/`) — only the 2 source changes
  (`src/lotg.py`, `scripts/audit_player_history.py`) + this new findings doc remain.

---

## ROUND 9 OVERALL SUMMARY — NOT fully clean (3 defects fixed this round)

| Agent / Parts | Result |
|---|---|
| **A/B** — completeness + cross-sheet reconciliation | **CLEAN** (`642f111`). Seasons/teams/weeks/player-rollups/picks-grid complete; trades 504, transactions 1,514; all B1-B5 invariants 0-mismatch; the 3 excluded raw trades are the documented exclusions. |
| **C/D** — header-comment + asset-history narrative accuracy | **2 FIXES** (`133d85e`), both `src/formulas.py` tooltip TEXT — the 2020-startup-draft-label family: `O-Score` Notes ("the 2021 vet/startup draft is excluded from every percentile pool" → names both drafts correctly + own-pool behaviour) and picks `Number of trades` Notes ("The 2021 startup (vet) draft … count 0 here" → separates the 2020 startup and 2021 vet drafts). Part D narrative CLEAN (450 picks + 649 players, 2,982 event lines, 0 fabrications/inversions/dangling-refs/teleports). |
| **E/F** — domain-bounds + N/A-vs-0-vs-blank | **CLEAN** (`cafa982`). Every bounded column in-domain; every conditional column N/A-correct both directions; the COMPUTED-DATA deep dive confirmed the 2020 DATA behind the C/D tooltip fixes was already correct (PF Semifinal Week-15 bonus, /16 Win%, the O-Score-N/A vs Number-of-trades-real-0 outcome). |
| **G/H** — link integrity + workbook structure | **CLEAN** (`98c097c`). 5,651 chain refs + 63,292 hyperlinks all in-range; 0 sibling self-links; 0 chronology violations; 0 teleports; all workbook-structural extents track current row counts; the only src change since Round-8 G/H was the 2 C/D tooltip edits (provably link-data-inert; O-Score box 620→668px, under cap). |
| **I/J** — ESPN-2020 re-verification + build/test cleanliness | **1 FIX** (this doc). The generated asset-history NARRATIVE line for every 2021-vet-draft pick said "2021 startup (vet) draft" — the SAME 2020-vs-2021 conflation as C/D, now in narrative text (32 player_all_time + 47 picks comments); rewritten to "2021 supplemental veteran draft" in `src/lotg.py`, with the test-support parser regex generalised in lock-step (`scripts/audit_player_history.py`) so the continuity guard still passes. ESPN-2020 backfill otherwise CLEAN at full population (type/FAAB/bids/draft-type tagging, the 3 startup-exclusion columns 0 for all 8 teams re-derived fresh, the platform-seam-teleport fix holds with the NOVEL startup-drafted holdover Golden Tate). Build exit 0 (only the 2 expected network warnings; the pick-trade WARN is pre-existing), pytest 15/15, no debug/dead-code/TODO in the src/ diff, both formatting fixes hold on fresh cells (O-Score box 668px / 232px headroom, word-wrap width 17.0). |

**Round-9 total: 3 defects fixed (2 in C/D + 1 in I/J), ALL of the SAME root-cause
family — the 2020-vs-2021 draft-seam label conflation (the inaugural startup was the
2020 ESPN draft, distinct from the 2021 supplemental veteran draft), ALL pure TEXT
(no cell/numeric output changed anywhere in Round 9).** A/B, E/F, G/H came back
clean. So **Round 9 was NOT fully clean.**

This continues the Round 2-8 pattern: broader/deeper full-population checks keep
surfacing real, narrow defects that sample-based checks miss — and this round closes
the loop on the 2020-vs-2021 draft-label family by following it from the tooltip
layer (where Rounds 6/7/8/9-C/D found it) into the **generated-narrative** layer (the
last place it survived). After this fix, a fresh grep of BOTH user-visible text
surfaces — `src/formulas.py` tooltips AND `src/lotg.py` generated narrative
f-strings — finds **0** remaining instances that mislabel the 2020 startup or apply
"startup" to the 2021 vet draft. The DATA layer remains clean across all five
agent-pairs at full population for the **fourth consecutive round** (Rounds 6, 7, 8,
9 each found only TEXT/comment defects, never a cell value) — the audit is
converging: the surviving defects were documentation/label drift around the same
2020-vs-2021 structural seam, and that family now appears exhausted across both text
surfaces. Per the repeating-cycle rule, because Round 9 was NOT fully clean, the
5-agent audit type would re-run as a future round with fresh examples.
