# Phase 13 Round 12 — Parts I+J (ESPN-2020 integration re-verification + build/test cleanliness + determinism)

Self-designed full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run **fresh from scratch**
against `claude/phase-13-audit-tsapoy`. Agent 5 of 5 in Round 12 — the FIFTH and
FINAL part-pair. Round 12 siblings (all CLEAN entering this pair, 4-for-4):
- Parts A/B — `AUDIT_PHASE13_ROUND12_PARTSAB.md` — CLEAN at `50a86fc`.
- Parts C/D — `AUDIT_PHASE13_ROUND12_PARTSCD.md` — CLEAN at `1027ab4`.
- Parts E/F — `AUDIT_PHASE13_ROUND12_PARTSEF.md` — CLEAN at `c7b912f`.
- Parts G/H — `AUDIT_PHASE13_ROUND12_PARTSGH.md` — CLEAN at `2aa5186`.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (a non-audit upstream ancestor) and
`git merge-base --is-ancestor 2aa5186 HEAD` printed `STALE_NEEDS_RESET`
(`2aa5186` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`2aa5186`, the Round-12 Parts G/H tip
carrying all Round-5..Round-12/GH fixes), after which `git log -1 --oneline` =
`2aa5186` and the merge-base check printed `OK_AT_OR_AHEAD`.

**Build under audit:** TWO independent fresh offline builds
(`PYTHONPATH=src:lib python3 scripts/offline_build.py`), each exit 0, each with
exactly the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`. Not a stale cache. Full population: picks 450
(152 startup), player_week 21,376 (2,632 in 2020 across weeks 1-16, 236 distinct
players), team_week 808 (88 cols), team_year 48, 13 exported CSVs.
`build_debug.log`: 0 error/exception/traceback lines.

`pytest tests/ -q` (run as `PYTHONPATH=src:lib python3 -m pytest`) = **15 passed /
0 failures** in ~76s, incl. the full-build continuity and chain-link tests.

All worked examples are NOVEL — different players/picks/teams than ALL prior
rounds. Deliberately avoided the Round-9/10/11 identity anchors (Saquon Barkley /
Derrick Henry / George Kittle, then Alvin Kamara / Davante Adams / Justin
Jefferson) and the Round-11 startup board (Ezekiel Elliott / Lamar Jackson /
Michael Thomas / Clyde Edwards-Helaire). This round's 2020-specific novel cast:
**Travis Kelce, Stefon Diggs, Aaron Jones** for the ESPN→Sleeper identity bridge;
the 2020 startup **Round-2 board** (Nick Chubb 2.01 / Davante Adams 2.02 / Julio
Jones 2.03 / Josh Jacobs 2.04 / Austin Ekeler 2.05 / Tyreek Hill 2.06 / Derrick
Henry 2.07 / Alvin Kamara 2.08) for the startup-draft integration, with **Nick
Chubb (2.01 → Oliverwkw)** as the pick→2020-stint round-trip example.

**Result: CLEAN.** Zero defects found. Both Part I (ESPN-2020 integration) and
Part J (build/test cleanliness + determinism) pass with no source change.

---

## Part I — ESPN-2020 integration re-verification (full population)

### Season shape: 2020 is genuinely 16 weeks (ESPN), 2021+ is 17 (Sleeper) — CLEAN
2020 `player_week` carries weeks **1-16 only** (max week 16, no week 17): 2,632
rows, 236 distinct players. The 2020 `Week Name` set is exactly
`{Week 1..Week 14, Semifinal, 3rd Place, Final, Toilet Semis, Toilet Final,
Toilet Trash}` — i.e. weeks 1-14 regular + a 4-team winners' bracket and a 4-team
toilet bracket in weeks 15-16, ending at Week 16. `espn_2020.py` line 584 confirms
"the 2020 fantasy season ends at week 16" and the final-roster snapshot is taken at
the last populated week (16).

### Player-ID integration / ESPN→Sleeper identity bridge — CLEAN
Novel spot-checks **Travis Kelce**, **Stefon Diggs**, **Aaron Jones** each resolve
to a SINGLE continuous identity spanning seasons `{2020,2021,2022,2023,2024,2025}`,
each with a complete 16-week 2020 ESPN stint. Confirmed single-identity at the
aggregate level too: each appears as exactly ONE row in `player_all_time.csv` and
exactly ONE `player_year` row per season (no duplicate/orphan 2020 identity). This
confirms the `espn_2020.ESPN_TO_SLEEPER_RID` roster bridge + DynastyProcess
playerId join correctly stitches the 2020 ESPN player objects onto the same player
identities the Sleeper 2021+ path uses.

### 2020 startup draft — 152 rows relabeled Year='startup' — CLEAN
`picks.csv` `Year` distinct values: `{startup:152, 2021:32, 2021 (vet):32,
2022:32, 2023:32, 2024:33, 2025:40, 2026:33, 2027:32, 2028:32}`. The 152 startup
rows = **19 rounds × 8 teams**, and every one of the 19 rounds has exactly 8 picks.
There is **no bare `2020`** anywhere in the pick `Year` column (the 2020 startup
picks are relabeled `startup`), and `2021 (vet)` remains a DISTINCT label — the
recurring 2020-vs-2021 startup/vet seam family stays exhausted. All 152 startup
`Player Picked` values resolve to real player identities in `player_all_time.csv`
(zero missing/orphaned). Round-trip example: **Nick Chubb** (startup **2.01** →
Oliverwkw) is on Oliverwkw from Week 1 of 2020 in `player_week`, so the startup
pick correctly stitches to the 2020 ESPN ownership chain.

### 2020 standings / playoff structure — CLEAN
`team_year` 2020 Result column (8 teams) reconciles exactly with the bracket:
shmuel256 Champion (12-4), Oliverwkw 2nd (10-6), LWebs53 3rd (10-6), plehv79 4th
(9-7) from the winners' bracket; then the non-playoff quartet ranked by
full-window record (PF tiebreak): BROsenzweig 8-8 → **5th**, AceMatthew 6-10 →
**6th**, JacobRosenzweig 6-10 → **7th** (lost the PF tiebreak), stevenb123 3-13 →
**8th**. Regular-season records (`5-9`, `7-7`, `4-10`, `9-5`, `9-5`, `9-5`,
`10-4`, `3-11`) sum to the 16-game full-window records once the weeks-15/16 bracket
games are folded in — consistent with recent correction #1 (the `cutoff=17 games`
window for 2020-2024 intentionally includes the toilet-bowl bracket by design).

### 2020-specific narrative / tooltip text — CLEAN (no lingering 17-week defect)
Full sweep of every `2020` / week-count surface in `src/` for the "claims 17 weeks
for 2020" defect family hit in Round 10:
- `formulas.py` PF tooltip (861): "Week 15 in the **16-week 2020 season**; Week 16
  in the 17-week 2021+ seasons" — CORRECT.
- `formulas.py` Win%/Record tooltips (966, 969): "**16** games in the completed
  2020 season, **17** in each completed 2021+ season" — CORRECT.
- `formulas.py` Result tooltip (1038): the Round-10 fix is intact — "through the
  season's final game for 2020-2024 (**Week 16 in the 16-week 2020 season**; Week
  17 in the 17-week 2021-2024 seasons)" — CORRECT.
- `lotg.py` Result developer-comment twin (13327-13338): the Round-10 fix is
  intact — "**Week 16 in the 16-week 2020 ESPN season**, Week 17 in the 17-week
  2021-2024 seasons" — CORRECT.
- `lotg.py` `last_completed_week` (2972) and `week_allowed` (3808): both correctly
  EXCLUDE week 17 for seasons ≤ 2020 (the empty placeholder week beyond the
  16-week 2020 season) — correct logic, not a narrative defect.
- `lotg.py` lines 228, 7805-7807, 8009-8017: NFL-week / rolling-window / KTC-Sleeper
  comments, none tied to the 2020 season length.

No new lingering instance of the "17 weeks for the 16-week 2020 season" failure
family. The defect family remains exhausted.

### Investigated, NOT a defect: `_championship_monday` 2020 one-week overshoot
`lotg.py` `_championship_monday(season_year)` (8013-8017) computes the KTC
"end of season" snapshot anchor as `week1_sunday + 16 weeks + 1 day` for ALL
seasons. For the 16-week 2020 ESPN season the actual championship was fantasy
week 16 (one NFL week earlier than the 2021+ Sleeper week-17 final), so for 2020
this helper overshoots the true championship Monday by one week. **Confirmed zero
observable impact:** all 24 2020-season trades have `KTC value difference at end of
season = "N/A"` in `trades.csv` because the KTC index has no data near the
2020/2021 boundary (the helper's own examples reference only 2021+). The anchor is
never reached for any 2020 row, so no exported cell is affected. Logged as a latent
harmless inaccuracy, not flagged as a defect (no user-facing data change; matches
the "investigated/no-impact" disposition of prior rounds).

---

## Part J — Build / test cleanliness + determinism

### Offline build — CLEAN
Two fresh `PYTHONPATH=src:lib python3 scripts/offline_build.py` runs, both **exit
0**. Each produced exactly the **2 expected** unresolved fetches
(`https://api.sleeper.app/v1/league/0` and
`https://api.sleeper.app/v1/draft/espn_2020_draft`) — no other warnings, errors,
exceptions, or tracebacks in stdout. `build_debug.log`: 0 error/exception/traceback
lines.

### pytest — 15/15 CLEAN
`PYTHONPATH=src:lib python3 -m pytest tests/ -q` = **15 passed / 0 failures**
(~76s), including the full-build `test_player_history_continuity` and the
pick/player chain-link tests.

### Determinism — CLEAN (byte-identical)
Two independent fresh builds produced **byte-identical** CSVs: `cmp` over all 13
exported CSVs reported zero differences, and the combined md5 over all CSVs was
identical across both builds (`928c650247dbdbe90f024cfd0b9ee798`). The full build
is fully deterministic — re-confirming recent correction #5 (stable full-identity
tiebreaker sorts).

---

## Verdict

**Parts I+J: CLEAN — zero defects, no source change.**

This makes **Round 12 FULLY CLEAN** — all 5 part-pairs (A/B `50a86fc`, C/D
`1027ab4`, E/F `c7b912f`, G/H `2aa5186`, and I/J this commit) returned zero
defects. Round 12 is the first FULLY CLEAN round in this audit chain since Round 7,
satisfying the standing termination condition for the 5-agent audit battery.
