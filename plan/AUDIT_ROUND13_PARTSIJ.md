# Phase 13 Round 13 — Parts I+J (ESPN-2020 integration re-verification + build/test cleanliness + determinism)

Fresh full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_ROUND12_PARTSIJ.md`, run fresh from scratch on branch
`claude/agent-part-audits-1yy87u`. Agent 5 of 5 in Round 13 — the FIFTH and FINAL
part-pair. Round 13 siblings (all CLEAN entering this pair, 4-for-4):
- Parts A/B — `AUDIT_ROUND13_PARTSAB.md` — CLEAN (0 defects) at `4e1f259`.
- Parts C/D — `AUDIT_ROUND13_PARTSCD.md` — CLEAN (0 defects) at `8b94b0c`.
- Parts E/F — `AUDIT_ROUND13_PARTSEF.md` — CLEAN (0 defects) at `09669d6`.
- Parts G/H — `AUDIT_ROUND13_PARTSGH.md` — CLEAN (0 defects) at `060b133`.

**Build under audit:** TWO independent fresh offline builds
(`PYTHONPATH=src:lib python3 scripts/offline_build.py`), each **exit 0**, each with
exactly the **2 expected** network-unavailable warnings
(`https://api.sleeper.app/v1/league/0` and
`https://api.sleeper.app/v1/draft/espn_2020_draft`) and **0** error/exception/
traceback lines. Full population: picks **514** (152 startup, 10 drafted classes +
future pool 2026-2030), trades **504**, transactions **1,510**, player_week
**21,376** (2,632 in 2020 across weeks 1-16), team_week **808**, team_year **48**,
13 exported CSVs. Working tree restored to clean after the determinism runs
(`git checkout -- exports`); only this findings file is new.

All worked examples are NOVEL — deliberately different from every prior round.
Round-12 anchored on Kelce/Diggs/Jones and Nick Chubb (startup 2.01); this round
uses **AJ Dillon** and **Kirk Cousins** for the 2020→2021 seam traces, the
**Hockenson-Drake trade (2020-12-16)** for the commissioner-overlay pick injection,
and **Justin Fields (2021 2.01, orig. stevenb123)** for the pick round-trip.

**Result: CLEAN.** Zero confirmed defects. Both Part I (ESPN-2020 integration) and
Part J (build/test cleanliness + determinism) pass with **no source change**.

---

## Part I — ESPN-2020 integration re-verification (full population)

### 2020 season shape — CLEAN
2020 `player_week` carries weeks **1-16 only** (max 16, no week 17): 2,632 rows.
`team_week` 2020 = 128 rows (8 teams × 16 weeks). The 2020 `Week Name` set is
exactly `{Week 1..Week 14, Semifinal, 3rd Place, Final, Toilet Semis, Toilet Final,
Toilet Trash}` — weeks 1-14 regular + a 4-team winners' bracket and a 4-team toilet
bracket in weeks 15-16, ending at Week 16. Matches the ESPN 16-week season.

### 2020 cross-sheet reconciliation (Part-1-style invariants) — CLEAN
Recomputed per-week on the 2020 rows:
- `league_week.PF` = Σ `team_week.PF` per week — **max abs diff 0.0**.
- `Number of transactions` league vs Σ team — **max diff 0**.
- `Number of Injuries` / `Number of suspensions` / `Number of players on bye` —
  **max diff 0** each.
- `Number of trades`: Σ team = exactly **2×** league for every 2020 trade-week
  (ratio set = `{2.0}`) — the by-design bilateral double-count (each 2-team trade
  counted by both participants; league counts it once). 2020 is the cleanest
  season here: EVERY 2020 trade is bilateral, matching the all-bilateral
  email-sourced trade ledger. (2021+ show 3.0 etc. for multi-team deals — correct,
  out of Part-I scope.)
- `team_year.Record` win count = Σ `team_week.Win?` for all 8 2020 teams (and,
  as a 2021+-non-regression check, **0 mismatches across all 48 team-years**).

### 2020-specific N/A columns — CLEAN (both directions)
- **FAAB N/A pre-2022:** `team_week.Amount of FAAB spent` = **0 non-null / 128**
  for 2020; `transactions.Faab` / `Total FAAB bid` = **0 non-null / 206** for 2020.
- **Number of bids N/A for 2020:** **0 non-null / 206** (competing-claim data
  unrecoverable from one manager's cookies — `espn_2020_backfill.md`). Contrast:
  2022 `Number of bids` = **57 non-null / 260** — the gate is not over-broad.

### No teleports across the 2020→2021 seam — CLEAN (novel traces)
Built each player's 2020 end-of-season owner (last populated 2020 week) and each
player's 2021 Week-1 owner:
- **34 players changed team** across the seam — **0 unexplained.** Every one has a
  concrete drop/add/trade/2021-vet-draft event. **43 players NEW in 2021 W1** —
  **0 unexplained** (all trace to a 2021 draft, a 2020/2021 add, or a startup
  pick).
- Novel airtight chains (no teleport):
  - **AJ Dillon** — startup **15.06** (plehv79) → on plehv79 through 2020 Week 16
    → **dropped by plehv79 2020-12-31 19:00:00** → **2021 (vet) 1.01 by
    stevenb123** → 2021 W1 stevenb123.
  - **Kirk Cousins** — 2020 EOS **stevenb123** (last owned Week 13) → dropped by
    stevenb123 → **2021 (vet) 3.05 by plehv79** → 2021 W1 plehv79.
- `scripts/audit_player_history.py exports/LOTG_Stats.xlsx`: **661 players audited,
  0 continuity breaks** — the strong all-seasons no-teleport guarantee.

### 2020 startup draft — CLEAN
`picks.Year` distinct = `{startup:152, 2021:32, 2021 (vet):32, 2022:32, 2023:32,
2024:33, 2025:40, 2026:33, 2027:32, 2028:32, 2029:32, 2030:32}`. The 152 startup
rows = **19 rounds × 8 teams**, every round exactly 8. No bare `2020` pick label;
`2021 (vet)` remains a distinct label (the startup/vet seam stays exhausted).

### Email-sourced trade ledger + commissioner-pick overlay — CLEAN
`data/commissioner_pick_trades.csv` holds **14 rows dated 2020** (incl. the
documented Cook 10-pick bundle). Novel end-to-end injection trace — the
**Hockenson-Drake trade, 2020-12-16 16:43:22** (LWebs53 ↔ stevenb123): the ledger
row (stevenb123's 2021 R2 → LWebs53) renders **natively** in `trades.csv` as
`2021 2.01(J. Fields)` alongside Kenyan Drake + Cole Kmet (LWebs53 sent T.J.
Hockenson), and `picks.csv` shows **2021 2.01 = Justin Fields, Original Team
stevenb123, drafted by LWebs53**. The overlay reconciles to the ledger and looks
native (matches Parts C+D).

### 2020 standings / playoff structure — CLEAN
`team_year` 2020 Result reconciles with the bracket + records:
- Winners bracket (Semifinal → Final / 3rd Place): shmuel256 **Champion** (12-4),
  Oliverwkw **2nd** (10-6), LWebs53 **3rd** (10-6), plehv79 **4th** (9-7).
- Toilet bracket (Toilet Semis → Toilet Final / Toilet Trash): BROsenzweig, AceMatthew,
  JacobRosenzweig, stevenb123. The **5th-8th ranks are assigned by full-window
  record with PF tiebreak, NOT by the toilet-bracket outcome**: BROsenzweig 8-8 →
  5th; AceMatthew 6-10 → 6th and JacobRosenzweig 6-10 → 7th (PF tiebreak); stevenb123
  3-13 → 8th. Consistent with the documented Round-12 disposition — the Toilet
  Final/Trash labels are game labels, not the ranking source. No defect.

### 2020 KTC columns N/A — CLEAN (correct offline AND online)
All 24 2020 trades have every KTC-difference column empty. This is correct in BOTH
environments: offline the KTC index is empty (cross-agent item 1), and even in a
real-network production build KTC has **no pre-Aug-2021 history**
(`espn_2020_backfill.md`), so 2020 KTC stays N/A regardless. 2020 is therefore
unaffected by the offline-KTC gap.

### Nothing in 2021+ regressed — CLEAN
Full-population counts match the Round-13 siblings (514 picks / 504 trades / 1,510
tx / 808 team_week / 48 team_year / 21,376 player_week / 661 players 0-break).
All-season invariants re-derived: league PF = Σ team PF (**0** seasons mismatch),
Record = Σ Win? (**0** of 48 team-years mismatch). No 2026 leak — every season-keyed
sheet (`player_week`, `team_year`, `player_year`, `league_year`, `transactions`,
`trades`) is exactly `{2020-2025}`.

---

## Part J — Build / test cleanliness + determinism

### pytest — 46/46 CLEAN
`PYTHONPATH=src:lib python3 -m pytest tests/ -q` = **46 passed / 0 failed / 0
skipped** in ~69s, including the full-build continuity / pick-chain / cross-sheet
guards.

### Offline build — CLEAN
Two fresh `PYTHONPATH=src:lib python3 scripts/offline_build.py` runs, both **exit
0**. Each produced exactly the **2 expected** unresolved fetches
(`api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`) and **0**
error/exception/traceback lines in the build log.

### Determinism — CLEAN (byte-identical)
Two independent fresh builds from identical current source produced
**byte-identical** exports. `diff -q` over all 8 checked CSVs
(`transactions`, `trades`, `picks`, `player_year`, `team_year`, `player_week`,
`team_week`, `league_week`) reported **IDENTICAL** for every file, and the combined
md5 over `transactions`+`trades`+`picks` matched across both runs
(`bc7b3dd6f2f8a1056b16ea6400dc7f09`). The committed CSVs were also byte-identical to
both rebuilds; only `LOTG_Stats.xlsx` / `LOTG_Exports.zip` / per-run logs
(`build_debug.log`, `audit_snapshot.json`) differed (embedded timestamps/metadata,
not data). No non-deterministic data byte found.

---

## Anomalies flagged (over-inclusive)

### (a) CONFIRMED DEFECTS
**None.**

### (b) LIKELY BY-DESIGN / DOCUMENTED
- **`Commissioner moved?` is uniformly `False` across all 514 picks** — despite
  source at `src/lotg.py:9155/9174/9199` that CAN set it `True` and a comment
  ("Surface this on pick_history so it's visible"). Investigated the full code
  path: `_detect_commissioner_moves` (`3130-3177`) flags a pick ONLY when its
  snapshot owner is **not reachable through any recorded trade event**
  (`if int(snap_owner) not in chain_owners`). The authoritative pass
  (`6139-6144`) rebuilds `commissioner_pick_moves` AFTER injecting every
  `commissioner_pick_trades.csv` leg into `pick_trade_events`, so each overlay pick
  now moves as a **native recorded trade** and is (correctly) not flagged. The
  column is a tripwire for pick moves the ledger never explains; with the overlay
  covering everything, it correctly fires **zero** times. No exported datum is
  wrong (Original Team, trade legs, chains all verified via Hockenson-Drake). BY-
  DESIGN, and consistent with Parts C+D ("the overlay is meant to look native").
- **2020 `Number of trades` team-sum = 2× league** — bilateral double-count
  (participation vs distinct-trade), verified as by-design across all seasons.
- **Toilet-bracket 5th-8th ranked by full-window record + PF tiebreak, not by
  bracket outcome** — documented Round-12 disposition; consistent.
- **2020 KTC columns 100% N/A** — correct in both offline and online (no
  pre-Aug-2021 KTC history); folds into cross-agent item 1 but has no 2020 impact.

### (c) NEEDS-HUMAN-JUDGMENT
- **Cross-agent item 1 — offline KTC 100% empty / on-disk backfill bypassed
  offline.** See verdict below.
- **Cross-agent item 2 — `season_2026` snapshot present, build cut off at 2025.**
  See verdict below.

---

## Cross-agent adjudication (final)

### Item 1 — Offline KTC 100% empty: PRIMARILY AN OFFLINE-ENVIRONMENT ARTIFACT, with a real (minor) latent robustness gap. NOT a defect in the committed exports.
The KTC index build (`lotg_support.ktc.build_index`) performs a live dynasty-daddy
fetch that 403s through the sandbox proxy; the outer `try/except` leaves
`_ktc_idx = None`, so all KTC-derived columns (32 across picks/trades/transactions)
are empty offline. In **production** (real network) the index builds and these
columns populate — so the **committed exports are not defective on account of
KTC** (they are the offline baseline; the audit convention is that KTC is
network-sourced). The determinism check is also unaffected: both offline builds
equally lack KTC and are byte-identical.

The legitimate gap: `data/ktc_backfill/` **exists on disk (563 JSON files, real
superflex values)** but is **never consulted as an offline fallback** when the live
`build_index()` fails. A defensive fallback to the committed backfill would make
offline builds mirror production far more closely and would remove the silent
loss of dozens of tooltip'd columns (and the 0-fill of the Trade-impact-score KTC
term). This is a **code robustness gap worth a human decision** (wire the backfill
in as an offline fallback vs. accept offline-KTC-empty), NOT a data defect.
**For Part I specifically it is moot** — 2020 KTC is N/A in every environment
(no pre-Aug-2021 KTC history), so the ESPN-2020 integration is correct regardless.

### Item 2 — `season_2026` snapshot present but build cuts off at 2025: CUTOFF IS CORRECT / BY-DESIGN. No 2026 leak. One non-blocking visibility recommendation.
The declared build scope is 2019-2025. As of the 2026-07-14 build date the 2026
NFL season has not been played — only 2026 dynasty offseason activity exists. I
confirmed **no 2026 leak into any season-keyed sheet**: `player_week`, `team_year`,
`player_year`, `league_year`, `transactions`, and `trades` all carry exactly
`{2020-2025}` (matching siblings A/B and E/F). Future draft-pick assets for
2026-2030 ARE correctly carried as placeholders in `picks.csv` (the intended
forward-roll). The 6 `commissioner_pick_trades.csv` rows dated 2026 (incl. the
ledger-documented first-ever 5-team trade, 2026-07-10) are **correctly unrealized**
— their target trades are 2026 (out of scope), so the overlay does not inject them.
The cutoff at 2025 is **intended and correct**, and nothing 2026 leaked.

The only borderline: the unmatched-commissioner-overlay warning
(`src/lotg.py:6121-6128`) routes through the debug-gated `_log`, so in a normal
(non-debug) build the 6 unrealized 2026 ledger rows warn **silently**. No current
data is wrong, but a human may wish to **surface the unmatched-overlay warning
non-silently** so those 2026 hops are not forgotten when 2026 is eventually
ingested. Classification: NEEDS-HUMAN-JUDGMENT on the warning visibility only — the
data cutoff itself is confirmed correct.

---

## Verification
- `PYTHONPATH=src:lib python3 -m pytest tests/ -q`: **46 passed** (~69s), 0 failed /
  0 skipped.
- Two fresh offline builds: **exit 0** each, 2 expected fetches each, 0
  error/traceback lines.
- Determinism: 8 key CSVs **byte-identical** across the two runs (md5 match).
- No source or committed-export change (`git status` clean after
  `git checkout -- exports`; only this findings file is new).

## Verdict
**Parts I+J: CLEAN — zero confirmed defects, no source change.** Part I re-verified
the full ESPN-2020 integration (16-week shape, 2020 cross-sheet reconciliation, the
FAAB/Number-of-bids N/A gates, zero teleports across the 2020→2021 seam via novel
AJ Dillon / Kirk Cousins chains and a 661-player 0-break continuity audit, the
152-row 19×8 startup draft, the native commissioner-overlay pick injection via
Hockenson-Drake, the winners/toilet playoff structure, 2020 KTC N/A, and no 2021+
regression). Part J confirmed 46/46 pytest, two clean exit-0 offline builds, and
fully deterministic byte-identical exports. Both cross-agent items adjudicated:
offline-KTC is an environment artifact (with a minor backfill-fallback robustness
gap for humans) and the 2026 cutoff is correct with no leak (only the silent
unmatched-overlay warning is a visibility suggestion). This makes **Round 13 FULLY
CLEAN** — all 5 part-pairs returned zero confirmed defects.
