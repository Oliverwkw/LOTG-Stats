# Round 13 — 9-part RUN3 full-population audit — Parts 7, 8, 9

**Build under audit:** the committed fresh Round-13 baseline exports
(`exports/*.csv`, `exports/LOTG_Stats.xlsx`) — the deterministic offline
Round-13 rebuild (league `1192931349575991296`, seasons 2019→2025, cut at 2025),
verified byte-identical across two builds and CLEAN by the prior 10-part battery.
**Audited in place — no rebuild, no edits to `src/` or `exports/`.** Agent 3 of 3
(the FINAL part-group, Parts 7, 8, 9). Verification via direct pandas
(`PYTHONPATH=src:lib`).

Population (matches siblings): league_week 101, league_year 6, league_all_time 1,
team_week 808, team_year 48, team_all_time 8, player_week 21,376, player_year
1,859, player_all_time 649, transactions 1,510, trades 504, picks 514.

Known offline/by-design (not re-argued): KTC / picks-&-trades O-Score / KTC-diff
columns empty offline (dynasty-daddy 403; on-disk backfill not merged); transactions
`O-Score` IS populated offline (439/1510); `season_2026` snapshot exists but the
build correctly cuts at 2025 (no 2026 leak — confirmed Year∈2020–2025 in all
weekly/yearly sheets).

---

## PART 7 — Metric accuracy / odd-result hunt: **CLEAN (0 defects; 1 corroborated NEEDS-JUDGMENT)**

Every suspicious leaderboard-topping / extreme value was run to ground from inputs.

- **3-year roster retention = 0.0000 (LWebs53 2021 and 2022)** — the lowest values
  in the sheet. Ran to ground: LWebs53's 2021 week-1 roster (25 players incl. Aaron
  Rodgers, Davante Adams, Tom Brady, Travis Kelce, Dalvin Cook) has **0 overlap**
  with its 2024 week-1 roster; 2022→2025 likewise 0. A genuine full dynasty
  teardown/rebuild, not a bug. `retention_3yr_by_ty` (`src/lotg.py:14147-14170`) =
  |wk1 roster ∩ wk1 roster Y+3| / |wk1 roster|. **BY-DESIGN / real outcome.**
- **`Number of teams` outliers** (Davante Adams 2024 = **4** teams despite 17 weeks
  on shmuel256, 0 trades, 0 transactions in-year; A.J. Brown 2024 = 3; Christian
  Kirk 2023 = 4; Aaron Jones 2022 = 3). **CORROBORATES sibling FINDING 4-J1.**
  Reproduced the exact scope: **108 player_year rows** (2020:9, 2021:18, 2022:23,
  2023:31, 2024:27; 2025:0) have `Number of teams > distinct weekly teams` **with 0
  in-year trades AND 0 in-year transactions**. Root cause confirmed at
  `src/lotg.py:12713 _fy_window` → `[Sep 1 yr N, Sep 1 yr N+1)`, so the entire
  year-N+1 dynasty offseason (Feb–Aug N+1) is filed under FY N; Adams's 4 teams come
  entirely from his **2025-dated** trades (Apr/Jul/Aug 2025 — plehv79→shmuel256→…),
  which `trades.csv` correctly files under `Season=2025`. Files the hops and the
  resulting team-count in **different year rows** (internally inconsistent) and is
  season-boundary-unstable (2025 clean only because its offseason isn't loaded).
  See "Number of teams verdict" below. **NEEDS-HUMAN-JUDGMENT.**
- **Luck extremes** (most-unlucky shmuel256 2024 = −3.8147; luckiest stevenb123
  2024 = +3.9514). team_year Luck ties out to the sum of team_week weekly Luck
  (shmuel256 2024: weekly Σ −3.8146 vs yearly −3.8147, rounding). Additive and
  coherent — real outcome.
- **Lowest team-week Efficiency** (plehv79 2022 wk16 = 0.3278; PF 45.36 vs Max PF
  138.36). It is the **Toilet Semis** (loser's-bracket) week and carries
  `Tanking = 0.609` (>0, flagged) — an intentional bad lineup, explained by the
  tanking metric. **BY-DESIGN.** Efficiency never exceeds 1.0 (max 1.0 = started
  every optimal player) anywhere; `% of starts made while rostered` never >1 (0 rows).
- **Transaction Net-points extreme** (stevenb123 Jalen Hurts 2020 = +1661.90; Jared
  Goff to JacobRosenzweig 2022 = +991.44) — franchise-defining waiver adds that were
  never dropped; `Points Added` = cumulative rostered scoring. Real.
- **Trade impact / Net points extremes** (shmuel256 2020 Net +1026.98, TIS 12.3;
  LWebs53 2024 Net −194.90, TIS −5.5). Range −5.5…12.3, all 504 populated. Realistic.
- **FAAB extremes** (max spend 120 on Croskey-Merritt plehv79 2025; `FAAB premium %`
  range 0–100; max `Number of bids` 7). All in-bounds.
- **Transaction skill** (team_all_time 28.3–34.4, 8 teams) reasonable; `Drafting
  skill` / `Trading skill` NaN offline (O-Score/KTC-derived) — by-design offline.
- **Retired-but-rostered "legend" ages** (Tom Brady 48.37 in 2025, 47.39 in 2024;
  Drew Brees 45.94) surfaced as age outliers — see Part 9 (all bench, 0 pts,
  NFL team="NFL"; by-design roster-clog rows).

## PART 8 — Asset-story tracking (no-teleport test): **CLEAN (0 teleports, 0 dangling links)**

- **0 out-of-range link references** across **5,645** parsed refs in all 8 link
  columns (transactions ×4, trades ×2, picks ×2). Ref grammar `^(PH|T)?#(\d+)$`
  (`src/lotg.py:2563`): `#N`→transactions row N, `T#N`→trades row N, `PH#N`→picks
  row N (1-indexed). Every N ∈ [1, sheet length]; **0 bad-format, 0 OOB.**
- **0 teleports (transactions link graph).** For all 3,669 transaction link refs
  — 3,250 same-sheet (`#N`) + 419 cross-sheet (`T#`/`PH#`) — the referenced
  transaction/trade/pick row **actually involves the same asset** (added/dropped
  player, or a trade whose asset list contains the player, or the pick's `Player
  Picked`). 0 mismatches. This is the strong no-teleport invariant: no link points
  to an unrelated asset.
- **0 teleports (trades per-asset links).** 747 per-asset "next" refs that point at
  a transaction (`#N`) resolve to a row whose added/dropped player is that asset. 0
  mismatch.
- **Novel multi-hop chain traced end-to-end across the 2020→2021 seam and beyond —
  Diontae Johnson:** startup/initial → **LWebs53** → **plehv79** (2022-07-15 trade,
  Gage+Diontae+Renfrow+2023 3.06 for Cousins+Hill) → **AceMatthew** (2023-06-11
  trade, Diontae+picks for Gibbs slot) → **dropped to FA by AceMatthew** (2025-08-29
  transaction). Every hop is a real preceding trade/transaction — no teleport, no
  gap. Also spot-traced Davante Adams's 2022 (shmuel↔LWebs blockbuster) → 2025
  offseason chain; every leg reconciles to a dated `trades.csv` row.
- Documented by-design origin gap unchanged: startup pool (152) + 2021(vet) pool
  (32) carry the known zero-realized-event origins (Phase-13 cornerstones /
  initial-roster vets); not teleports.

## PART 9 — Comprehensive cell-by-cell sweep: **CLEAN (0 defects; 4 by-design, 1 needs-judgment)**

Wide pass over all 12 sheets. No `inf` in any numeric column of any sheet. No
negative counts (all `Number of…`/`Weeks…`/`Times…` ≥ 0 in team_year & player_year).
`% of league points` (player_all_time) sums to 0.999 ≈ 1.0. Result labels are exactly
{Champion, 2nd…8th} with **exactly 1 Champion per season**. No `team_week` PF < 0.

Cell-level items examined and resolved:

- **Week / season labels are internally consistent, not off-by-one.** 2020 spans
  weeks 1–16 (128 team-weeks = 8×16); 2021–2025 span 1–17 (136 = 8×17) — the real
  shorter 2020 fantasy calendar, **by-design**, not a mislabel. `Week Name` maps the
  playoff tail to {Semifinal, Final, 3rd Place, Toilet Semis/Trash/Final} above the
  numbered "Week 1…15" — coherent. picks `Year` ∈ {startup, 2021(vet), 2021…2030}.
- **`"In Progress"` sentinel in 26 streak columns** (the source of the pandas
  mixed-dtype warning). Verified semantically correct: it marks an **active
  ongoing streak** as of that week; a played sub-threshold week ends it. Traced
  Josh Allen 2023 `10+ point streak`: wk1 (8.04) = 0, wk2–12 (all ≥10) = In
  Progress, wk13 (0.0 bye) = NaN, wk14–17 = In Progress. **BY-DESIGN.**
- **Retired-but-rostered "legend" rows** (14 total): Tom Brady 2024/2025, Drew
  Brees 2024, Odell Beckham 2022, Josh Doctson 2022/2023, Demaryius Thomas 2021.
  `NFL team = "NFL"` (the no-team placeholder), **all Bench, 0.0 points**, age
  incrementing off birthdate (Brady → 48.37). Dynasty roster-clog holds; 0 of
  these are starters, so they don't touch PF/efficiency. **BY-DESIGN.**
- **2026 pick "2.09" carries a concrete slot number** while its 32 sibling future
  picks are `"1.??"/"2.??"` skeletons (`Player Picked="Unknown"`). Consistent: the
  9th 2nd-round slot is a **fixed supplemental pick** (a known traded extra — also
  present as a real 2.09 in 2024 & 2025), so its position is determined even though
  the player isn't, whereas standard-round slots depend on unfinished standings
  (`"??"`). **BY-DESIGN.** (Minor: total future skeleton picks 2026–2030 = **161**,
  not the 162 the Parts 4-6 write-up stated — a harmless count typo; all 161 are
  `Unknown`.)
- **Unit-convention split (cosmetic):** ratio columns `Win %`, `Regular season win
  %`, `All-play win %`, `Efficiency` are stored on a **0–1** scale, while
  `% of players drafted`, `% of 3rd year+ players drafted`, `% of starters
  boom/bust/quartile`, `FAAB premium %` are stored on a **0–100** scale — both under
  "%"-style names. Internally each family is consistent; the mixed 0–1 vs 0–100
  presentation under similar-looking headers is a definitional/display choice.
  **NEEDS-HUMAN-JUDGMENT** (very low concern; long-standing, not new).

---

## Anomalies flagged (over-inclusive)

### (a) CONFIRMED DEFECT
- *(none)* — no teleport, dangling link, stray/corrupt cell, sign error, or
  mis-computed value found in Parts 7–9.

### (b) LIKELY BY-DESIGN / DOCUMENTED
- **P7:** LWebs53 3-yr retention 0.0000 (2021, 2022) — real full teardown (0 wk-1
  roster overlap into Y+3), not a bug.
- **P7:** lowest-efficiency week (plehv79 2022 Toilet Semis, 0.328) — flagged
  `Tanking = 0.609`; intentional bad lineup.
- **P7:** huge positive Net-points / Trade-impact extremes (Hurts +1661, shmuel256
  2020 trade Net +1026, TIS 12.3) — real never-dropped franchise assets.
- **P8:** startup (152) + 2021(vet) (32) zero-realized-event origins — documented
  Phase-13 cornerstone/initial-roster gap.
- **P9:** 2020 = 16 weeks vs 2021+ = 17 weeks — real shorter 2020 calendar.
- **P9:** `"In Progress"` streak sentinel (26 columns) — active-streak marker.
- **P9:** retired-rostered legends (Brady age 48 etc; NFL team="NFL", bench, 0 pts).
- **P9:** 2026 pick "2.09" concrete-number among "??" future picks — fixed
  supplemental slot.

### (c) NEEDS-HUMAN-JUDGMENT
- **P7 — `Number of teams` offseason bleed (CORROBORATES sibling FINDING 4-J1).**
  108 player_year rows (2020–2024) report more teams than the player was ever on
  in-season, with 0 in-year moves, because the Sep→Sep `_fy_window` folds the next
  offseason's churn into the prior season. Internally inconsistent with `Number of
  trades` (files the same hops under season N+1, per `trades.csv`) and
  season-boundary-unstable. Novel: Davante Adams 2024 = 4 teams over 17 weeks on
  one team with 0 moves. Definitional window choice → human decision. I lean the
  same way the sibling did (factually misleading value → defect-flavored, but the
  correct FY window is a design call).
- **P9 — 0–1 vs 0–100 unit split** across similarly-named "%"/"win %" columns.
  Cosmetic/definitional; confirm intended presentation.

---

## Verdict on the sibling "Number of teams" finding

**CORROBORATED.** Independently reproduced the mechanism (`_fy_window` Sep→Sep,
`src/lotg.py:12713`) and the **exact** scope — 108 rows, distribution
2020:9 / 2021:18 / 2022:23 / 2023:31 / 2024:27 / 2025:0 — and the flagship example
(Davante Adams 2024 `Number of teams=4`, `Number of trades=0`,
`Number of transactions=0`, single weekly team shmuel256; the 3 extra teams are his
2025-dated trades). Real internal inconsistency; classification **NEEDS-HUMAN-
JUDGMENT** (window definition), leaning defect. Not a 2020-specific regression;
affects all seasons uniformly and is pre-existing.

---

## Verification

- All checks in place against committed `exports/*.csv`, `PYTHONPATH=src:lib`; no
  rebuild, no edits to `src/` or `exports/`.
- Source cross-refs read: `_fy_window` / `_fy_inseason_window` (12713-12723),
  `Number of teams` tenure augmentation (13065, 13517), `retention_3yr_by_ty`
  (14147-14170), link ref grammar `_ref_re`/`_set_ref_link` (2560-2571).
- **`pytest tests/ -q`: 46 passed** (0 failed) in ~90s.
- **Checks run:** ~28 distinct verifications across Parts 7/8/9 (retention ground-
  truth, Number-of-teams scope + mechanism, luck/efficiency/net-points/trade-impact/
  FAAB extremes, 5,645-ref out-of-range scan, 3,669+747 asset-consistency teleport
  scans, 2 novel multi-hop chain traces, inf/negative/percentage-bounds sweep, week/
  season/pick-label sweep, streak-sentinel + retired-legend + supplemental-pick
  cell checks).
- **Totals: 0 confirmed defects · 8 by-design/documented items · 2 needs-human-
  judgment (Number-of-teams offseason bleed [corroborated]; 0–1 vs 0–100 unit
  split).**

**Result: Parts 7, 8, 9 — CLEAN. 0 confirmed defects. Sibling Number-of-teams
finding independently corroborated.**
