# Phase 13 Round 10 — Parts I+J (ESPN-2020 integration re-verification + build/test cleanliness)

Self-designed full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 5 of 5 in Round 10 (final part-pair).
Siblings:
- Parts A/B — `AUDIT_PHASE13_ROUND10_PARTSAB.md` — CLEAN at `f95d3ea`.
- Parts C/D — `AUDIT_PHASE13_ROUND10_PARTSCD.md` — 2 NEW-family tooltip fixes
  (`Taxi-eligible` first-year gate + `Result` finish vocabulary) at `814cdb6`.
- Parts E/F — `AUDIT_PHASE13_ROUND10_PARTSEF.md` — 2 computational fixes at
  `a683193`, the **second** of which (the `Result` 5th-8th ranking-window change
  to a pure regular-season cutoff) was **reverted** in `70ebfc0` because
  toilet-bowl bracket results were intentionally part of final standings for
  2020-2024 by original league/code design. The other E/F fix (Taxi-eligible
  pad-rows for 4 transaction-only first-year-2025 never-started players: Joe
  Milton, Jordan Watkins, Zavier Scott, Tanner McKee) is correct and unchanged.
- Parts G/H — `AUDIT_PHASE13_ROUND10_PARTSGH.md` — CLEAN at `6bd5a8f`.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at a state where `git merge-base --is-ancestor 6bd5a8f HEAD` printed
NEEDS_RESET (`6bd5a8f` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy`, then confirmed `OK_AT_OR_AHEAD` with
`git log -1 --oneline` = `6bd5a8f` ("Phase 13 round-10 audit Parts G/H…").

**Build under audit:** fresh offline build (`PYTHONPATH=src:lib python3
scripts/offline_build.py`, exit 0; only the 2 expected network-unavailable
warnings — `api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`). Not a
stale cache. Full population: picks 450 (152 startup), player_week 21,376
(2,632 in 2020), team_year 48, team_week 808.

All examples below are NOVEL — different players/teams than every prior round
(deliberately avoided the prior anchors; this round's 2020-specific cast:
**Saquon Barkley, Derrick Henry, George Kittle** for ESPN→Sleeper identity
continuity, and the 2020 non-playoff quartet **BROsenzweig / AceMatthew /
JacobRosenzweig / stevenb123** for the toilet-bracket standings; shmuel256's
2020 championship).

**Result: 1 real doc/code-drift defect found and FIXED** — a **2020-specific
tooltip imprecision** in the `Result` column's text (and its developer-comment
twin), the exact failure mode Part I is mandated to catch: a tooltip spanning the
16-week 2020 ESPN season that wrongly implied a Week-17 cutoff. Text-only; the
exported `Result` DATA is unchanged and was independently re-verified correct.
Build exit 0 (2 expected warnings only), pytest 15/15, freshness sweep clean.

---

## Part I — ESPN-2020 integration re-verification (full population)

### Season shape: 2020 is genuinely 16 weeks (ESPN), 2021+ is 17 (Sleeper) — CLEAN
`team_week` and `player_week` for 2020 carry weeks **1-16 only** (max week 16,
no week 17), vs weeks 1-17 for 2021+. `espn_2020.py` emits
`playoff_week_start: 15, playoff_teams: 4, num_teams: 8` for the synthetic
"espn_2020" league; the build derives the brackets from standings. 2020 player_week
= 2,632 rows, 236 distinct players, all across weeks 1-16.

### Player-ID integration / ESPN→Sleeper identity bridge — CLEAN
Novel spot-checks **Saquon Barkley**, **Derrick Henry**, **George Kittle** each
resolve to a SINGLE continuous identity spanning seasons `{2020,2021,2022,2023,
2024,2025}`, each with a complete 16-week 2020 ESPN stint. This confirms the
`espn_2020.ESPN_TO_SLEEPER_RID` roster bridge + DynastyProcess playerId join
correctly stitches the 2020 ESPN player objects onto the same player identities
the Sleeper 2021+ path uses (no orphaned/duplicate 2020 identities).

### 2020 startup draft — 152 rows relabeled Year='startup' — CLEAN
`picks.csv` carries exactly **152** startup rows = **19 rounds × 8 teams** (every
round has exactly 8 picks). The `Year` column's distinct values are
`{startup, 2021, 2021 (vet), 2022, 2023, 2024, 2025, 2026, 2027, 2028}` — there
is **no bare `2020`** anywhere in the pick `Year` column (the 2020 startup picks
were computed as a normal 2020 draft then relabeled `startup`), and `2021 (vet)`
remains a DISTINCT label. The recurring 2020-vs-2021 startup/vet seam family stays
exhausted (consistent with Rounds 9 & 10 C/D's grep findings).

### 2020 standings / playoff structure — CLEAN
2020 has a 4-team winners' bracket AND a 4-team toilet (consolation) bracket in
weeks 15-16 (verified from `team_week` Week-Name labels):
- Week 15: `Semifinal` (LWebs53, Oliverwkw, plehv79, shmuel256) + `Toilet Semis`
  (AceMatthew, BROsenzweig, JacobRosenzweig, stevenb123).
- Week 16: `Final` (shmuel256 143.90 beats Oliverwkw 118.10) → Champion / 2nd;
  `3rd Place` (LWebs53 219.46 beats plehv79 125.08) → 3rd / 4th; `Toilet Final`
  + `Toilet Trash` for the consolation quartet.

The exported 2020 `Result` column (team_year) reconciles exactly:
shmuel256 Champion, Oliverwkw 2nd, LWebs53 3rd, plehv79 4th, then the 4
non-playoff teams ranked by their full-window (Week≤17 → all 16 weeks) record:
BROsenzweig 8-8 (.500) → **5th**, AceMatthew 6-10 (.375, PF 2061.7) → **6th**,
JacobRosenzweig 6-10 (.375, PF 1994.6, lost the PF tiebreak) → **7th**,
stevenb123 3-13 (.188) → **8th**. Manual recomputation matches the export
cell-for-cell. (For 2020 the reg-season-only window happens to give the same
order, so 2020 has no Result-vs-last-place disagreement — that disagreement is a
2021-2023 phenomenon.)

### 2020-specific narrative / tooltip text — **1 DEFECT FOUND + FIXED**
The codebase is generally careful to distinguish the 16-week 2020 ESPN season
from the 17-week 2021+ Sleeper seasons — e.g. `formulas.py`:
- PF tooltip (line 861): "the Semifinal week (Week 15 in the **16-week 2020
  season**; Week 16 in the 17-week 2021+ seasons)…" — CORRECT.
- Win % / Record tooltips (lines 966, 969): "**16** games in the completed 2020
  season, **17** in each completed 2021+ season" — CORRECT.

**Defect:** the **`Result`** column tooltip (`formulas.py` ~line 1038) broke that
established 16-vs-17 precision. It read:
> "…ranked by record (PF as tiebreaker) **through Week 17 for 2020-2024** (which
> folds in the toilet bowl bracket…)…"

For the 16-week 2020 season there is no Week 17 — the season ends at Week 16. The
code's `cutoff = 17 if season < 2025 else 15` is the literal *parameter* (and for
2020 a `Week<=17` filter simply captures all 16 weeks, which is the correct
intent), but the user-facing tooltip's "through Week 17 for 2020-2024" wording
incorrectly implies the 2020 season ran to Week 17 — exactly the
"narrative/tooltip assumes 17 weeks for the 16-week 2020 season" failure mode
Part I is tasked to catch. (Prior Round-10 E/F and G/H reviews quoted this string
but were focused on the toilet-bowl-design reversion, not the 16-vs-17 precision
for the 2020 row; this Part-I-scoped re-read is the first to flag it.)

**Fix (text only):**
- `src/formulas.py` — Result tooltip rewritten to parallel lines 861/966/969:
  "…ranked by record (PF as tiebreaker) **through the season's final game for
  2020-2024 (Week 16 in the 16-week 2020 season; Week 17 in the 17-week
  2021-2024 seasons)** — which folds in the toilet bowl bracket… — or through
  Week 15 for 2025+ (the true regular season only)."
- `src/lotg.py` (~line 13319) — the developer-comment twin updated to the same
  "Week 16 in the 16-week 2020 ESPN season, Week 17 in the 17-week 2021-2024
  seasons" phrasing for consistency.

No DATA change: the `cutoff` value and the `Week<=cutoff` filter are byte-for-byte
unchanged, so the 2020-2024 Result rankings (incl. the toilet-bowl inclusion that
70ebfc0 correctly restored) are identical before/after. Verified: 2020 Result
column unchanged after rebuild; `team_year.csv` has zero data diff. The corrected
tooltip renders in `exports/formulas.csv` AND `exports/LOTG_Stats.xlsx`
(xl/worksheets/sheet1.xml).

---

## Part J — Build / test cleanliness + freshness sweep

### Offline build — CLEAN
`PYTHONPATH=src:lib python3 scripts/offline_build.py` → **exit 0**. Exactly the
**2 expected** unresolved fetches (`api.sleeper.app/v1/league/0` and
`…/draft/espn_2020_draft`); no other warnings/errors/exceptions in stdout.

### build_debug.log — CLEAN
`exports/raw/build_debug.log`: `data-quality sanity: 0 ERROR, 0 WARN across 0
findings`. The only WARN lines are (a) `ktc fetch … 403 Forbidden` (the expected
offline KTC block) and (b) `commish pick-trade UNMATCHED: 2026 R209
Oliverwkw->LWebs53` / `1/33 pick-hops unmatched` — **PRE-EXISTING** (documented in
Round 8 I/J and Round 9 I/J; concerns one 2026 *future* toilet pick, no data-cell
error). No unexpected errors/tracebacks.

### pytest — 15/15
`PYTHONPATH=src:lib python3 -m pytest tests/ -q` → **15 passed** (both before and
after the fix; 0 regressions).

### Repo freshness sweep — CLEAN (no stray/orphaned state)
- No stray uncommitted source/plan files beyond this audit's deliberate edits.
- The only untracked item is `.pytest_cache/` (gitignored test-runner cache).
- The committed `exports/` regenerate with only KTC dynasty-rank column
  fluctuations (e.g. `#1304`↔`#1303` for Hayden Hurst / Cole Kmet's tx rows) —
  these are EXTERNAL dynamic values (KTC is 403 offline; fallback ranks drift
  build-to-build), NOT source-computed data drift. `team_year.csv` (where the
  source-computed Result lives) has **zero** diff. This is normal rebuild noise,
  consistent with every prior round; not a defect. The regenerated exports
  carrying the corrected Result tooltip are committed alongside the source fix.

---

## Round-10 closing status

Per-part-pair outcomes:
- A/B: CLEAN (`f95d3ea`).
- C/D: 2 tooltip-TEXT fixes (`814cdb6`).
- E/F: 1 surviving correct fix (Taxi pad-rows) + 1 fix that was reverted
  (`a683193` then `70ebfc0`).
- G/H: CLEAN (`6bd5a8f`).
- **I/J: 1 tooltip-TEXT fix (this commit).**

Because multiple part-pairs in Round 10 found and fixed real defects (C/D's two
tooltips, the surviving E/F Taxi fix, and now I/J's Result tooltip), **Round 10
was NOT fully clean** — there were genuine defects fixed across the round. By the
repeating-cycle rule (a round is "fully clean" only when ALL five part-pairs find
zero defects), **a Round 11 (a fresh full repeat) must be run** to confirm the
codebase reaches a fully-clean state with zero defects across all five part-pairs.
There are no KNOWN OPEN defects after this commit (the I/J fix is verified and
all sibling fixes are in place), but the round itself did not achieve the
zero-defect bar.
