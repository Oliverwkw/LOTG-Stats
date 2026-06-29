# Phase 13 — 10-Part Audit, Round 1, Parts 7–9

Branch: `claude/phase-13-audit-tsapoy`
Starting commit: 238062c (Parts 4-6 CLEAN)
Date: 2026-06-29

## Result: CLEAN — no source changes

All three parts were audited thoroughly with hand-computed values against the
underlying CSVs and the rendered `exports/LOTG_Stats.xlsx` workbook. No new
defects were found. Build and tests are green both before and after (no source
change was needed).

- Build: `PYTHONPATH=src:lib python3 scripts/offline_build.py` → succeeds with
  exactly the 2 expected unresolved fetches (`api.sleeper.app/v1/league/0` live
  league + `espn_2020_draft`; KTC 403 is the other normal one). NOT defects.
- Tests: `PYTHONPATH=src:lib python3 -m pytest tests/ -q` → **15 passed, 0 failed**.

Novel examples used (none reused from prior docs): George Pickens / 2022 2.01
pick, Caleb Williams / 2024 1.02 pick, Jeff Wilson (LWebs53), Rico Dowdle,
Tyler Conklin FAAB, team AvgPoints record cells, benchwarmer-suppressed weeks.

---

## Part 7 — Odd-result hunt

Methodology: scanned every export sheet for statistically impossible /
surprising values, then verified each as correct-but-surprising or a real bug.

### 7.1 Percentage range scan (all sheets)
Scanned every `% / win % / boom % / bust % / efficiency` column for values
outside expected bounds.
- `boom %` / `bust %` (player sheets) span 0–100 — they are stored on a 0-100
  scale (the `*100` at lotg.py ~12885/12952), NOT fractions. Confirmed the
  number-format special-case (lotg.py 864-866, `'0.00"%"'`) handles them so
  Excel does not multiply again. Correct.
- `% of starts …`, `% of points …` are 0–1 fractions (e.g. picks `% of starts`
  = 0.5588) and get the `0.00%` Excel-percent format (x100). Consistent.
- `All-play win % minus Win %` and `… minus regular-season win %` legitimately
  go negative (they are differences). Not a defect.

### 7.2 Internal arithmetic invariants
- **team_year `Differential` == `Points` − `Points against`**: 0 violations / 48 rows.
- **team_year `Avg differential` == `Differential` / games**: 0 violations.
- **team_year `Record` ↔ `Win %`** (Win% = (W+0.5T)/G): 0 mismatches / 48 rows.
- **player floor ≤ ceiling** (Starter + Rostered scoring): 0 violations.
- **trades `Net points` == `Points added` − `Points lost`**: 0 violations / 504 rows.
- **transactions `Net points` == `Points Added` − `Points Lost`**: 0 violations / 1514 rows.
- No negative values in any `Number of …` / `Times …` / `Most number of …` count column (all sheets).

### 7.3 team_all_time record decomposition (novel: AceMatthew, all 8 teams)
`All time record` must equal the sum of `Regular season + Playoff + Toilet bowl
+ Third place game + Toilet losers game` records. Verified for all 8 teams:
e.g. AceMatthew 41-48 + 1-1 + 4-4 + (3rd) + (toilet losers) = **48-53** =
reported all-time 48-53. All 8 reconcile exactly to 0 W/L slack.

### 7.4 Award uniqueness (player_week)
- **Player of the week**: exactly 1 winner per (Year, Week) across all 101
  league-weeks. QB/RB/WR/TE of the week: exactly 1 each per week (101 weeks).
- **Benchwarmer of the week** missing in 20 weeks — verified each is a week
  with ≥2 starters tied at 0 points (e.g. 2023 W1 had 5 starters at 0; 2025 W6,
  2022 W9, 2020 W2 each had 2). This is the documented tie-suppression rule
  (lotg.py 10349, "if 2+ starters tie at 0 points, no winner"), matching the
  formulas.py tooltip ("lowest-scoring starter"). Correct-by-design.

### 7.5 FAAB premium (novel: Tyler Conklin 2024)
`FAAB premium %` formula `(winner − second)/winner * 100` (lotg.py 5526),
bounded 0–100, undefined when winning bid = 0. Verified:
- 20 rows have a `FAAB difference over second place` but a blank
  `FAAB premium %` — all 20 have `Faab` (winning bid) = 0.0, so premium is
  correctly undefined (no div-by-zero). Matches the tooltip exactly.
- Tyler Conklin 2024: winning bid $0 but `Total FAAB bid` $16 (higher bids
  invalidated and excluded per the `b <= winner_bid_val` filter, lotg.py 5513),
  so difference=0, premium=N/A. Consistent with tooltip ("Bids strictly greater
  than the winning bid are excluded — they were invalidated").

### 7.6 Season-length sanity (2020 vs 2021+)
league_week and team_week: 2020 spans weeks 1–16 (16 unique), 2021–2025 span
1–17 (17 unique). Consistent with the ESPN-2020 16-week vs Sleeper 17-week
distinction. No week-17 leakage into 2020.

---

## Part 8 — Asset-story tracking

Methodology: traced specific picks and waiver assets end-to-end through
trades.csv / picks.csv / transactions.csv, verifying mirrored entries, trade
counts, originating franchise, and the doubly-linked `T#`/`#` reference chains.

### 8.1 The 2022 2.01 pick → George Pickens (novel)
Full lifecycle traced through trades.csv:
1. **2022-07-02**: JacobRosenzweig **sends** `2022 2.01(G. Pickens)` →
   stevenb123 **receives** it (both rows mirror each other exactly).
2. **2022-08-11**: stevenb123 **sends** it → plehv79 **receives** it (mirrored).
3. picks.csv: `2022 2.01 George Pickens`, **Team = plehv79**, **Original Team =
   JacobRosenzweig**, **Number of trades = 2** (matches the 2 traded events),
   `Link to previous transaction = T#263`.
4. T#263 resolves to trades row 263 = plehv79's 2022-08-11 acquisition. Correct.

### 8.2 The 2024 1.02 pick → Caleb Williams (companion leg, novel)
Same 2022-07-02 deal sent `2024 1.02(C. Williams)` from JacobRosenzweig →
stevenb123, who kept it. picks.csv: Team = stevenb123, Original Team =
JacobRosenzweig, **Number of trades = 1** (the single deal). Consistent.

### 8.3 Link-reference integrity (whole repo)
Collected every `T#N` and `#N` reference across trades, transactions, and picks
link columns: **5089 references, 0 broken** (every `T#N` resolves to a valid
trades row 1..504; every `#N` to a transactions row 1..1514).

### 8.4 Repeated-pickup chain — Jeff Wilson on LWebs53 (novel)
LWebs53 picked up Jeff Wilson **6 times** (2021–2022). Verified:
- `Number of times picked up by this team` increments 1→2→3→4→5→6 in strict
  date order.
- Every stint's `Date dropped/traded` is after its pickup date (no negative
  tenures).
- Full **18-event** Jeff Wilson cross-team chain: every `Link to next/previous
  transaction (added player)` points to a valid Jeff-Wilson event, next-links
  always go forward in time, prev-links always go backward — **0 integrity
  issues**. (Note: the links thread the player's *global* movement history
  across all teams, not just LWebs53's pickups, so consecutive LWebs53 pickups
  are correctly separated by the intervening stevenb123 add/drop events
  #1310/#1334 — verified, not a chain break.)

---

## Part 9 — Cell-by-cell + aesthetics audit (rendered xlsx)

Methodology: loaded the rendered `exports/LOTG_Stats.xlsx` with openpyxl and
inspected number formats, conditional/color formatting, record-highlight cell
fills, header text, and column types against the styling code in lotg.py
(_col_number_format @846, color scale @2562, record highlight @2572).

### 9.1 Number-format correctness (rendered cells)
- player_year `Starter boom %` / `Starter bust %`: format `0.00"%"` (literal %,
  no x100) — renders 50 → "50.00%". Correct.
- `% of points (highest team)` = 0.0824 with format `0.00%` → "8.24%". Correct.
- `Avg points`, `Starter PAR`, `Age`, `Length of tenure on team`: `0.00`.
- Count columns (`Times as Captain?`, `Number of teams`): `0` (whole numbers).
- team_year `Win %`/`Regular season win %`/`All-play win % minus Win %`: `0.00%`.
- picks `Number` ("1.01") and `Year` ("2021 (vet)"): left as text/General — not
  coerced to numeric. Correct (pick labels / vet-vs-rookie draft tags).

### 9.2 Conditional formatting & record highlights
- Each headline sheet carries exactly **1** ColorScaleRule range (red→yellow→
  green percentile scale) on its headline column (team_year Win %, picks/trades/
  transactions O-Score, etc.). league_year/league_all_time correctly have 0
  (not in `_scale_cols`).
- Record highlights use direct `PatternFill` (not conditional formatting), so
  they don't show as CF ranges. Verified on team_year `Avg points`: the single
  max (167.49) is gold `FFD966`, the single min (109.54) is blue `BDD7EE`,
  exactly one cell each — matching the highest/lowest-record intent.

### 9.3 trades exploded-slot columns
28 blank-header per-asset link slots are narrowed to width 16; none are fully
empty so 0 are hidden (all carry per-asset link data). Auto-filter applied.

### 9.4 Tooltip/header coverage
`formulas.undocumented_columns()` run against the actual exported column sets of
all 12 data sheets returns **0 undocumented columns** — every output column has
a matching Formulas tooltip entry, with headers byte-matching the docs.

---

## Conclusion

Parts 7, 8, and 9 are **CLEAN**. No statistically implausible values, no
asset-chain breaks/duplications/contradictions, and no formatting/aesthetic
defects were found. No source changes were made; build succeeds and tests
remain 15/15.
