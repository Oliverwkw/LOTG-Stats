# Phase 13 Round 11 — Parts I+J (ESPN-2020 integration re-verification + build/test cleanliness + determinism re-confirm)

Self-designed full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 5 of 5 in Round 11 (the FINAL part-pair).
Round 11 siblings:
- Parts A/B — `AUDIT_PHASE13_ROUND11_PARTSAB.md` — CLEAN at `898f3df`.
- Parts C/D — `AUDIT_PHASE13_ROUND11_PARTSCD.md` — 2 tooltip-TEXT fixes
  (Hardship would-be-starter mis-claim + Drafting-skill stale column ref) at
  `afa5686`.
- Parts E/F — `AUDIT_PHASE13_ROUND11_PARTSEF.md` — 1 real COMPUTATIONAL fix
  (`Weeks between pickup and start` date-string compare: 6 N/A→0, 24 undercounts)
  at `9b6719f`.
- Parts G/H — `AUDIT_PHASE13_ROUND11_PARTSGH.md` — 1 real BUILD-DETERMINISM fix
  (unstable tied-timestamp sort silently renumbered `#N` link refs) at `9fdbb7e`.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (a non-audit ancestor on the upstream tip), and
`git merge-base --is-ancestor 9fdbb7e HEAD` did NOT print `OK_AT_OR_AHEAD`.
Hard-reset to `origin/claude/phase-13-audit-tsapoy`, after which
`git log -1 --oneline` = `9fdbb7e` ("Phase 13 round-11 audit Parts G/H…") and the
merge-base check printed `OK_AT_OR_AHEAD` (9fdbb7e is at HEAD, carrying every
Round-5..Round-11/GH fix).

**Build under audit:** two independent fresh offline builds
(`PYTHONPATH=src:lib python3 scripts/offline_build.py`, both exit 0; each with
exactly the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450
(152 startup), player_week 21,376 (2,632 in 2020, weeks 1-16, 236 distinct
players), team_week 808, team_year 48, 13 exported CSVs.

All examples below are NOVEL — different players/picks/teams than ALL prior
rounds. Deliberately avoided the Round-9/10/11 anchors (Saquon Barkley, Derrick
Henry, George Kittle as the prior 2020 identity cast; the prior standings narrative
re-used the same eight managers, which are unavoidable for an 8-team league but the
worked reconciliation here uses a fresh recompute). This round's 2020-specific
novel cast: **Alvin Kamara, Davante Adams, Justin Jefferson** for the ESPN→Sleeper
identity bridge + rookie-flag integration; the 2020 startup **Round-1 board**
(Ezekiel Elliott 1.03 / Lamar Jackson 1.05 / Michael Thomas 1.07 / Clyde
Edwards-Helaire 1.08) for the startup-draft integration; and an independent
recompute of the 2020 **5th-8th toilet-bracket standings**.

**Result: CLEAN — zero defects across Parts I and J.** The 2020 ESPN season
integrates correctly throughout the export, no NEW instance of the Round-10
"narrative/tooltip assumes 17 weeks for the 16-week 2020 season" defect family
exists (the three surviving "17-week" mentions in source all correctly contrast
the 16-week 2020 season; the Round-10 `Result`-tooltip fix is in place), the build
is clean (exit 0, 2 expected warnings, `0 ERROR/0 WARN` data-quality sanity),
pytest is 15/15, and **the build is fully deterministic — two independent fresh
builds produced byte-identical CSVs for all 13 exports (0 differing)**, re-confirming
the Round-11 G/H fix (`9fdbb7e`) holds. No source change required.

---

## Part I — ESPN-2020 integration re-verification (full population)

### Season shape: 2020 is genuinely 16 weeks (ESPN), data-driven — CLEAN
`player_week` and `team_week` for 2020 carry weeks **1-16 only** (max week = 16,
no week 17), vs weeks 1-17 for 2021+. 2020 player_week = **2,632 rows / 236
distinct players**, all within weeks 1-16. `espn_2020.emit_sleeper_2020`
(src/espn_2020.py ~574) emits `playoff_week_start: 15, playoff_teams: 4,
num_teams: 8, last_scored_leg: 16` for the synthetic "espn_2020" league, and the
final 2020 rosters are taken from "the last week that actually has lineups
(weeks 17-18 are empty: the 2020 fantasy season ends at week 16)" (espn_2020.py
~583). The build derives every season's regular-season window dynamically as
`Week < playoff_start` (lotg.py 13149/13226) — never a hardcoded 17 — and
`last_completed_week` excludes week 17 for `season <= 2020` but week 18 for
`season >= 2021` (lotg.py 2974). So a 16-week 2020 is handled structurally, not by
special-case patching.

### Player-ID integration / ESPN→Sleeper identity bridge — CLEAN
Novel spot-checks **Alvin Kamara**, **Davante Adams**, **Justin Jefferson** each
resolve to a SINGLE continuous identity (exactly **1** `player_all_time` row each)
spanning seasons `{2020,2021,2022,2023,2024,2025}`, each with a complete 16-week
2020 ESPN stint (weeks 1-16 present). This confirms the
`espn_2020.SLEEPER_ROSTER_ID_BY_MANAGER` roster bridge + the DynastyProcess
`espn_id`→sleeper_id join correctly stitch the 2020 ESPN player objects onto the
same identities the Sleeper 2021+ path uses — no orphaned/duplicate 2020
identities.

**Rookie-flag integration (novel sub-check):** **Justin Jefferson** (a 2020 NFL
rookie) is correctly flagged `Rookie? = True` in every 2020 player_week row, while
**Alvin Kamara** (2017 rookie) is `Rookie? = False` in 2020. So the 2020 ESPN path
carries the per-season rookie status correctly, not just the identity.

### 2020 startup draft — 152 rows relabeled Year='startup' — CLEAN
`picks.csv` carries exactly **152** startup rows = **19 rounds × 8 teams** (every
round 1-19 has exactly 8 picks). The pick `Year` column's distinct values are
`{startup, 2021, 2021 (vet), 2022, 2023, 2024, 2025, 2026, 2027, 2028}` — there is
**no bare `2020`** anywhere (the 2020 startup picks were computed as a normal 2020
draft then relabeled `startup` at lotg.py ~16424), and `2021 (vet)` stays a
DISTINCT label (the recurring 2020-vs-2021 startup/vet seam family remains
exhausted). Novel integration spot-check — the 2020 startup Round 1 board:
1.01 Christian McCaffrey (Oliverwkw), 1.02 Saquon Barkley (LWebs53),
**1.03 Ezekiel Elliott (JacobRosenzweig)**, 1.04 Dalvin Cook (AceMatthew),
**1.05 Lamar Jackson (stevenb123)**, 1.06 Patrick Mahomes (plehv79),
**1.07 Michael Thomas (BROsenzweig)**, **1.08 Clyde Edwards-Helaire (shmuel256)** —
all populated, and 150/152 startup rows carry an `Avg PPG on team` value (the 2
blanks are unmade/never-rostered picks, expected).

### 2020 standings / playoff structure — CLEAN (independently recomputed)
2020 has a 4-team winners' bracket AND a 4-team toilet bracket in weeks 15-16
(verified from `team_week` Week-Name labels):
- Week 15: `Semifinal` (LWebs53, Oliverwkw, plehv79, shmuel256) + `Toilet Semis`
  (AceMatthew, BROsenzweig, JacobRosenzweig, stevenb123).
- Week 16 (the final week — there is no Week 17): `Final` + `3rd Place`
  (winners' side) and `Toilet Final` + `Toilet Trash` (consolation side).

The exported 2020 `Result` column (team_year) is fully populated with all 8
ordinal finishes: shmuel256 Champion, Oliverwkw 2nd, LWebs53 3rd, plehv79 4th,
then the 4 non-playoff teams. **Independent recompute** of the 5th-8th ranking
directly from the 16 weeks of `team_week` (True/False `Win?`, PF tiebreaker)
reproduces the export cell-for-cell: BROsenzweig 8-8 (.500) → **5th**,
AceMatthew 6-10 (.375, PF 2061.70) → **6th**, JacobRosenzweig 6-10 (.375,
PF 1994.56 — loses the PF tiebreak) → **7th**, stevenb123 3-13 (.188) → **8th**.
Each of those 4 teams has exactly **16** games, re-confirming the 16-week season,
and confirming the `cutoff = 17 if season < 2025 else 15` parameter correctly
captures all 16 weeks for 2020 (a `Week<=17` filter ⇒ all of 1-16).

### 2020-specific narrative / tooltip text — CLEAN (the Round-10 family stays fixed; NO new instance)
Per the Part-I mandate I swept the whole source tree for the Round-10 defect
family ("a tooltip/narrative assumes the 2020 season ran 17 weeks"). There are
exactly **three** surviving "17-week" mentions in `src/`, and **all three
correctly contrast the 16-week 2020 season**:
- `formulas.py:861` — PF / homefield tooltip: "Week 15 in the **16-week 2020
  season**; Week 16 in the 17-week 2021+ seasons". CORRECT.
- `formulas.py:1038` — the `Result` tooltip: "through the season's final game for
  2020-2024 (**Week 16 in the 16-week 2020 season; Week 17 in the 17-week
  2021-2024 seasons**) … or through Week 15 for 2025+". This is exactly the
  Round-10 I/J fix, present and intact.
- `lotg.py:13330` — the developer-comment twin of the Result tooltip: "**Week 16
  in the 16-week 2020 ESPN season, Week 17 in the 17-week 2021-2024 seasons**".
  The Round-10 fix's comment twin, intact.

The Win%/Record tooltips (`formulas.py:966,969`) likewise say "**16** games in the
completed 2020 season, **17** in each completed 2021+ season". No other surface
hardcodes a 17-week assumption: the `next 17 PLAYED games` window for dropped
players (lotg.py 7803-7817) is an *NFL-games-played* window, unrelated to the
fantasy season length; the `Inseason …turnover` tooltips say "between Week 1 and
**the championship week**" (resolves per-season, not a fixed week); the 3-year
retention comment's "2020->2023" mapping (lotg.py 12995) is week-1-to-week-1, not
week-count-dependent. **No new defect.**

---

## Part J — Build / test cleanliness + full-determinism re-confirm

### Offline build — CLEAN (×2)
Two independent `PYTHONPATH=src:lib python3 scripts/offline_build.py` runs, each
**exit 0**, each with exactly the **2 expected** unresolved fetches
(`api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`); no other
warnings/errors/exceptions on stdout.

### build_debug.log — CLEAN
The latest build's `data-quality sanity` line = **`0 ERROR, 0 WARN across 0
findings`**. The only WARN/ERROR lines anywhere in that build's section are the
documented PRE-EXISTING ones: (a) `ktc fetch … 403 Forbidden` (the expected
offline KTC/dynasty-daddy block) and (b) `commish pick-trade UNMATCHED: 2026 R209
Oliverwkw->LWebs53` / `1/33 pick-hops unmatched` — a single 2026 *future* toilet
pick, documented clean in Rounds 8/9/10 I/J; no data-cell error. No unexpected
tracebacks.

### pytest — 15/15
`PYTHONPATH=src:lib python3 -m pytest tests/ -q` → **15 passed** (0 failures).

### FULL BUILD DETERMINISM — CONFIRMED (byte-identical across 2 fresh builds)
Snapshotted all 13 CSVs from build #1, ran build #2 from scratch, then
`cmp`-compared every CSV: **0 of 13 differ — every export is byte-identical**
between the two independent builds. This re-confirms the Round-11 G/H determinism
fix (`9fdbb7e`, the stable tied-timestamp sort + full identity tiebreaker) holds:
the `#N`/`PH#`-style link references in `transactions.csv` (inherited by
`picks.csv`/`trades.csv`) no longer renumber run-to-run. Note this is even
stronger than prior rounds, where the KTC dynasty-rank fallback columns were said
to drift; here all 13 CSVs match exactly, so the offline build is now fully
reproducible end-to-end.

### Committed-vs-fresh export delta — NOT a defect (explained by already-committed fixes)
The working tree shows `picks.csv`, `trades.csv`, `transactions.csv` differing
from the *committed* HEAD versions. This is the committed exports lagging the
source fixes, NOT data drift:
- Decomposing `transactions.csv`: after dropping the 4 position-dependent
  `Link to …` columns and re-sorting both files by transaction identity, the ONLY
  remaining cell difference is **exactly 30** cells in `Weeks between pickup and
  start` — precisely the Round-11 E/F fix (`9b6719f`: 6 N/A→0 + 24 undercounts).
  All other apparent per-column diffs are row-reordering artifacts of the G/H
  stable-sort change plus the consequent `#N` link renumbering.
- `picks.csv` / `trades.csv`: 0 non-link cell diffs; the only changes are the
  `Link to …` `#N` reference columns (the G/H reordering), which are themselves now
  deterministic build-to-build (proved above).
The freshly regenerated exports carrying these already-committed fixes are
committed alongside this findings doc.

---

## Round-11 closing status

Per-part-pair outcomes:
- A/B: CLEAN (`898f3df`).
- C/D: 2 tooltip-TEXT fixes (`afa5686`).
- E/F: 1 real COMPUTATIONAL fix (`9b6719f`).
- G/H: 1 real BUILD-DETERMINISM fix (`9fdbb7e`).
- **I/J: CLEAN (this commit) — no defects in either part.**

Although Parts I/J are clean, **Round 11 as a whole is NOT fully clean**: C/D, E/F,
and G/H each found and fixed genuine defects. By the repeating-cycle rule (a round
is "fully clean" only when ALL five part-pairs find zero defects), **a Round 12 (a
fresh full repeat) must be run** to confirm the codebase reaches a fully-clean
state with zero defects across all five part-pairs. There are no KNOWN OPEN
defects after this commit — every Round-11 fix is verified in place, the 2020
integration is correct, the build is clean and fully deterministic, and pytest is
15/15 — but the round itself did not achieve the zero-defect bar.
