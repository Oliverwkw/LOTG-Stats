# Phase 13 Round 5 — Parts E+F (domain-bounds/plausibility + N/A-vs-0-vs-blank correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Worktree self-verified — the recurring
stale-worktree environment bug recurred (HEAD landed at `6d83635`, behind the
branch tip; origin tip was `76b6257`, the just-landed Parts C/D writeup). Hard-
reset to `origin/claude/phase-13-audit-tsapoy` (`76b6257`) before any work, then
confirmed `git merge-base --is-ancestor 76b6257 HEAD` → OK.

Build under audit: offline build (`scripts/offline_build.py`, exit 0; only the
expected `api.sleeper.app` / `espn_2020_draft` network-unavailable warnings).
Fresh export: trades.csv 504 rows (post Parts A/B wash fix), picks.csv 450,
transactions.csv 1,512, player_year 1,857, player_all_time 649.

All examples below are NOVEL — different players/teams/seasons than every prior
round (avoiding Josh Doctson, Kenny Pickett, Hunter Henry, K.J. Osborn, Carter,
Stevenson, Pacheco, Jefferson, DJ Moore, Tyler Johnson, Larry Fitzgerald, Cam
Newton, Mike Gesicki, BROsenzweig-pick examples) except where the 4
wash-fix-surfaced trades are checked specifically as their own Part F surface.

**Result: 1 real defect found and fixed** (`src/lotg.py`): an undrafted future
2.09 toilet-reward pick rendered its `Player Picked` as `N/A` while all 96
ordinary undrafted future picks render `Unknown` for the identical condition.
Everything else CLEAN at full population. Two apparent anomalies were run to
ground and shown to be documented intentional behavior (the playoff-elimination
`0` sentinel; the trades FAAB-only `Asset difference in average age = 0`).

---

## Part E — Domain-bounds & plausibility sweep (every numeric/categorical column, every sheet)

Scanned all 12 data sheets. Established per-column plausible domains and scanned
the FULL column population for out-of-domain values.

### Bounded-domain columns — CLEAN
- **Ages** (`player_year.Age`, `player_week.Age`, `team_year`/`league_year`
  `Player average age` + `Team age including picks`, `picks.Age when drafted`):
  every value in [18, 60] — 0 out of range.
- **Week numbers** (`player_week.Week`, `league_week.Week`, `team_week.Week`):
  all in [1, 18] (2020 → 1..16; 2021-2025 → 1..17). 0 phantom week-0 or week>18.
- **Year/Season** (every season-keyed sheet's `Year`/`Season`): all in
  [2019, 2026] except `picks.Year`, whose `2026/2027/2028` future-pick classes
  and `"2021 (vet)"`/`startup` text labels are by-design (not a span violation).
- **Win % / rates** (`team_year` Win % / Regular season win % / All-play win %,
  Efficiency, 3-year retention rate): all in [0, 1]; **percentile** columns
  (`player_year` Consistency/Floor/Ceiling) in [1.4, 100]; **boom/bust %** in
  [0, 100]. No >100% or <0% percentages.
- **Counts** (`Number of …`, `Times as …`, `Total trades`, donuts, weeks missed,
  etc., across team_year / player_year / player_all_time / transactions / picks
  / league_week / team_week / league_year): scanned for any negative — **0
  negative counts**. `picks.Number`'s only non-numeric values are the documented
  `X.??` blanked-slot display for unresolved future picks.

### Large-magnitude scan (≥9000 |value|) — all legitimate aggregates
`league_year.PF/Max PF` (~18-24k, season-wide 8-team sum), `team_all_time.Points`
(~14k, career sum), `league_all_time.PF` (112k, all-time), `league_all_time
.Number of players under 10` (12,913 of 21,376 player-weeks), `trades.Trade
impact score` (smooth distribution, median −1,148, range −13.9k…+30.7k). No
`9999`-style placeholders, no infinities, no NaN-leaking-as-numeric.

### Investigated, not a defect
- **`player_year.% of points (highest team)` = −0.0001** (Jimmy Garoppolo 2020):
  he scored **−0.24** fantasy points that season (negative scoring is legal), so
  a fractionally-negative share is mathematically consistent. Not implausible.
- **`team_year.Week of playoff elimination` = 0** for 24 rows: these are exactly
  the top-4 finishers (Champion/2nd/3rd/4th — bracket teams never
  regular-season-eliminated). `0` is the column's **documented sentinel**
  (`src/formulas.py`: "0 if it won it all or didn't make the bracket"); the code
  sets `None` for playoff teams and the numeric default fill renders it `0`. The
  non-bracket 5th-8th teams correctly carry real elimination weeks (10-15). A
  documented sentinel, not an out-of-domain accident — left unchanged. (The
  tooltip's "…or didn't make the bracket" wording is imprecise since non-bracket
  teams actually get a non-zero week, but tooltip-text accuracy is Parts C/D
  scope, already audited CLEAN this round.)

## Part F — N/A-vs-0-vs-blank correctness (every conditionally-defined column, full population)

Enumerated every `_preserve_na`-governed and otherwise conditionally-defined
column and verified, for the FULL set of rows satisfying / not satisfying each
condition, that N/A renders correctly.

### Verified CLEAN (0 violations either direction)
| Column / condition | Rows in condition | Bad (non-NA where NA required) | Bad (NA where value required) |
|---|---|---|---|
| `Amount of FAAB spent` pre-2022 (team_year/league_year/team_week/league_week) | 16/2/264/33 | 0 | 0 (32/4 post-2022 all numeric) |
| `Number of bids` non-waiver | 1,064 | 0 | — |
| `Number of bids` 2020 waiver (ESPN unrecoverable) | 29 | 0 | — |
| `Number of bids` 2021+ waiver | 419 | — | 0 |
| `Faab` non-waiver | 1,064 | 0 | — |
| `FAAB difference over second place` / `FAAB premium %` non-waiver | 1,064 | 0 | — |
| `Number of times dropped by this team` pure-pickup / has-drop | 352 / 1,160 | 0 | 0 |
| `Age difference` single-side transaction rows | 789 | 0 | — |
| `Dropped avg points` / `Dropped total points` no-drop rows | 352 | 0 | — |
| `Length of tenure on team` pure-drop rows | 437 | 0 | — |
| `Starter scoring volatility` <2 starts / ≥2 starts | 1,008 / 849 | 0 | 0 |
| `PPG starter` 0-start rows | 796 | 0 | — |
| `3-year roster retention rate` Y+3 not yet played (2023/24/25) | 24 | — | correct (all N/A); 2020-2022 present |
| KTC columns (transactions + picks), KTC index unreachable offline | 1,512 / 450 | — | all N/A (documented KTC-unreachable) |

`Win Variance` / `All-play win %` / `All-play win % minus Win %`: 0 N/A across
all 48 team-seasons (every season complete; correct).

### Wash-fix trades (novel Part F surface) — render correctly
The 4 trades that newly survive after the Parts A/B commissioner-wash fix carry
correct N/A/0/value rendering in their FAAB/age/score columns:
- **Josh Doctson** (2022-11-30, LWebs53 ↔ BROsenzweig + $1 FAAB): both mirror
  rows present; `Trade impact score` = −1342.2 (symmetric).
- **Kenny Pickett** (4 trade-side rows), **K.J. Osborn** (10), **Hunter Henry**
  (10): all present with real numeric impact scores, no fabricated N/A.

### **DEFECT FOUND + FIXED — undrafted 2.09 future pick rendered `Player Picked = N/A`**

**Symptom (full-population count):** among the 97 undrafted future picks
(2026-2028), 96 render `Player Picked = "Unknown"` but exactly **1** rendered
`"N/A"` — the **2026 2.09** toilet-reward pick (Oliverwkw). All three `2.09`
picks: 2024 → `Ja'Lynn Polk` (made), 2025 → `Jayden Higgins` (made), 2026 →
`N/A` (undrafted) — the odd one out.

**Root cause** (`src/lotg.py` ~line 6227): the ordinary synthesized-future-pick
path sets the drafted-player name to the literal `"Unknown"` placeholder when no
draft has happened (`_player, _picker_rid, _player_id = "Unknown", None, None`).
The SEPARATE synthetic 2.09 toilet-reward emission block, in its not-yet-drafted
branch, instead set `_player0, _pid_str = "", ""` (empty string). An empty-string
`Player Picked` is a TEXT column, so `_default_fill_for_column` fills it with
`"N/A"` downstream — yielding `N/A` for a row whose condition (undrafted future
pick) is identical to the 96 rows that correctly show `Unknown`.

**Fix:** set `_player0 = "Unknown"` (keeping `_pid_str = ""`) in the
not-yet-drafted 2.09 branch, with a comment pointing to the ordinary future-pick
path so the two stay in sync. Safe by inspection: every downstream "is this pick
made?" gate already treats `"unknown"`/`"nan"`/blank identically as
"not drafted yet" (e.g. `src/lotg.py` ~line 8609 `player.lower() not in
("unknown", "nan")`), and the 2.09's data columns (`Avg PPG on team`, `Points
added`, `O-Score`, `KTC on draft day`, …) remain correctly N/A — only the text
placeholder changed.

**Post-fix verification:** rebuilt export — future-pick `Player Picked` now
`Unknown × 97`, `N/A × 0`; the 2026 2.09 (Oliverwkw) now reads `Unknown`; 2024/
2025 2.09 still show their real drafted players; picks.csv still 450 rows (no
structural change). All Part F core checks re-run post-build: still 0 violations.

### Investigated, not a defect (documented intentional behavior)
- **`trades."Asset difference in average age"` = 0 for FAAB-only sides** (e.g.
  the Doctson-for-$1-FAAB trade): `src/lotg.py` ~line 9571-9577 **deliberately**
  reports `0.0` rather than blank when one side has no aged asset ("Phase 7C:
  one side has no aged asset (FAAB-only / empty) … Report 0 rather than leaving
  it blank"). The column is also listed in `_preserve_na`, but that listing is
  only a no-op safety net (it preserves NaN, and 0.0 is set explicitly). This is
  a documented design choice, not an accidental fabricated-0 — left unchanged.
  (Noted as an inter-column convention inconsistency vs. transactions'
  `Age difference`, which a prior round chose to render N/A for single-side rows;
  flagged for awareness, not changed, since reversing a documented decision is
  out of scope for a plausibility sweep.)

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~76s (incl. the full-build
  `test_player_history_continuity` and `test_pick_chain_link_integrity`).
- Offline build: exit 0, no new warnings.
- Build artifacts reverted (`git checkout -- exports/`, `git clean -fd`); `git
  status` clean except `src/lotg.py` + this file.

## Conclusion
**Part E is CLEAN** (every bounded column in-domain; all large magnitudes are
legitimate aggregates; the two flagged sentinels are documented intentional
values). **Part F found 1 real defect** — the undrafted 2.09 future pick's
`Player Picked` rendered `N/A` instead of the `Unknown` placeholder every other
undrafted future pick uses — now fixed and verified at full population. All other
conditionally-defined columns render N/A/0/value correctly across the full row
population, including the 4 wash-fix-surfaced trades.
