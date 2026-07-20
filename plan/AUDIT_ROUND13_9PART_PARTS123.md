# Round 13 — 9-part RUN3 full-population audit — Parts 1, 2, 3

**Build under audit:** the committed fresh Round-13 baseline exports
(`exports/*.csv`, `exports/LOTG_Stats.xlsx`) — the deterministic offline
Round-13 rebuild (league `1192931349575991296`, seasons 2019→2025, cut at 2025),
already verified byte-identical across two builds and CLEAN by the prior 10-part
battery. **Audited in place — no rebuild, no edits to `src/` or `exports/`.**
Agent 1 of 3. Verification via direct pandas (`PYTHONPATH=src:lib`).

Population: league_week 101 rows, league_year 6, league_all_time 1,
team_week 808, team_year 48 (8 teams × 6 seasons), team_all_time 8,
player_week 21,376, player_year 1,859, player_all_time 649, transactions 1,510,
trades 504, picks 514.

---

## PART 1 — Cross-sheet reconciliation: **CLEAN** (0 defects)

All stated RUN3 invariants hold at full population, N/A-aware:

| Invariant | Result |
|---|---|
| league_week == Σ team_week: PF, #tx, Injuries, suspensions, players-on-bye, FAAB, donuts, starting-donuts, players over 20/30/40/50, rookies started/rostered | 0 mismatch each |
| league_year == Σ league_week (PF, #tx, donuts, FAAB, over-N, injuries, suspensions) | 0 mismatch |
| league_all_time == Σ league_year (PF, #tx, donuts, FAAB, Total/Off/In trades, injuries) | match |
| team_year Record **wins** == Σ team_week `Win?` | 0/48 mismatch |
| team_year Record **losses** == Σ team_week ¬`Win?` | 0/48 |
| team_year == Σ team_week (Points, PA, #tx, injuries, suspensions, donuts, FAAB, byes, hardship-flags) | 0 mismatch each |
| Total trades == Offseason + Inseason (team_year **and** league_year) | 0 mismatch |
| team_all_time == Σ team_year — the 12 `Times …?` award rollups + Points/PA/#tx/trades/donuts/injuries/picks/FAAB | 0 mismatch each (24 columns) |
| player_all_time == Σ player_year — drops, trades, #tx, starts, weeks, points, all 9 `Times as …?` awards | 0 mismatch each (19 columns) |
| player_year == Σ player_week: `Weeks as starter` | 0 mismatch |

**2020 seam:** 2020 reconciles identically to every other season
(league_week==Σteam_week for the 6 core cols confirmed on 2020 rows;
records, awards, points all tie). No 2020↔2021 breakage.
FAAB N/A era aligns on both sides: league_week FAAB is NaN for exactly the
2020+2021 weeks and the team-week sum is NaN for exactly those same weeks.

## PART 2 — Stat-family hand-checks: **CLEAN** (0 defects; ~22 families hand-derived)

Hand-derived from inputs, full population, incl. 2020-only reruns:

- team_week `Efficiency` = PF/Max PF — 0 mismatch (2020 reran: 0)
- team_week `Margin` = PF − PA — 0 (2020: 0)
- team_year `Efficiency` = Points/Max PF — 0
- team_year `Differential` = Points − PA — 0
- team_year `Avg points`/`Avg PA`/`Avg differential`/`Avg max PF` = total/games — 0 each
- team_year `Win %` = wins/games; `Regular season win %` = regW/regG — 0 each
- team_all_time `All time win %`, `Regular season win %` = W/G — 0 each
- team_year `All-play win % minus Win %` = allplay − win% — 0
- **All-play win %** hand-derived = Σ(teams w/ strictly lower PF each week)/Σ(others) — 0/48 mismatch (e.g. Oliverwkw 2023 = 0.6303 vs Win% 0.7059)
- **Win Variance** = −(place − (PF_rank+MaxPF_rank)/2): Σ per season == exactly 0.0 for all six seasons (rank-conservation invariant); all values ½-integer
- `Change in win % from previous season` = Win% − prevWin%: 0 mismatch, 2020 correctly N/A, 2021+ correct
- league_week `Number of games within 10`/`within 5` = Σ |margin|≤N games /2 — 0 mismatch
- league_week `Avg margin` = mean winning margin — 0
- league_week `Margin range` = max−min winning margin — 0
- team_week `Increase in points from previous week` = PF − prior-week PF — 0 (carries across season boundary; only the very first 2020-wk1 slice is N/A, 8 rows)

**No season-specific formula divergence — 2020 uses identical formulas to 2021-2025.**

Two initial hand-derivations that "mismatched" were **my wrong hypotheses**, not
data defects — see Anomaly C-1: league Efficiency and Margin-range use
mean-of-team / range-of-winning-margins definitions, which then matched 0/exactly.

## PART 3 — N/A vs 0 sweep: **CLEAN** (0 defects; every gated family verified BOTH directions)

- **Pre-2022 FAAB era:** `Amount of FAAB spent` NaN for 100% of 2020+2021 rows in
  team_week/team_year/league_week/league_year, and non-NaN for 100% of 2022+ rows
  (real 0s preserved — 371 team-week, 4 league-week). transactions `Faab` /
  `Total FAAB bid`: all-NaN 2020+2021, populated 2022+.
- **Waiver vs FA gating (2022+):** waiver rows 389/389 have `Faab` and
  `Number of bids`; free-agent (672) + commissioner (7) rows 100% N/A. No over-broad, no over-narrow.
- **2020 Number of bids:** N/A for all 206 rows (ESPN competing-claim data
  unrecoverable). 2021 waivers correctly carry `Number of bids` (30/30) while
  `Faab` stays N/A (no FAAB system pre-2022) — the two gates are independent and both right.
- **Offseason turnover/trades** (`Offseason starter/roster turnover`,
  `Offseason trades`) N/A for all 2020 rows (team_year + league_year), real for
  100% of 2021+ (incl. 2 real-zero `Offseason trades`).
- **Win % vs / Record vs <self>:** N/A for 0 non-NaN self-pairs in team_year and team_all_time.
- **3-year roster retention rate:** real for 2020/2021/2022, N/A for 2023/2024/2025
  (the +3-yr roster isn't played yet) — correct forward gate.
- **Playoff / Toilet win %:** N/A for the bracket a team never entered, real 0.0
  where a team played and lost. Both directions correct.
- **Player consistency/PAR** (volatility, PAR, percentiles, PPG starter): N/A for
  all 798 never-started player-years; `Starter scoring volatility` N/A for all 212
  one-start players (needs ≥2 starts); boom/bust % keep real 0 for started players (675 real-zeros).
- **transactions per-row gates:** `Number of times dropped by this team` /
  `Dropped total points` N/A on 348/348 pure-pickup rows, real on 1162/1162
  drop rows (89 real-zero dropped totals). `Length of tenure on team` N/A on
  439/439 no-added rows, real on 1071/1071 added rows.
- **KTC / O-Score offline (by-design):** all KTC columns empty on
  transactions/picks/trades; `O-Score` empty on picks/trades. (See Anomaly C-2:
  transactions `O-Score` IS populated offline.)

---

## Anomalies flagged (over-inclusive)

### (a) CONFIRMED DEFECTS
**None.** All stated invariants reconcile to 0; all gating is correct in both directions.

### (b) LIKELY BY-DESIGN / DOCUMENTED
- **B-1 — Inseason trades (team_year) ≠ Σ team_week `Number of trades`** (7 team-years
  off by 1–2, e.g. shmuel256 2022: yearly Inseason=10 vs weekly-sum=11; stevenb123
  2025 = 2 vs 4). *Reason:* the two are computed by deliberately different methods —
  team_week weekly count is per-received-player keyed by pid with a 7-day-pre-kickoff
  fold into Week 1 (`src/lotg.py:6837-6853`), while team_year Inseason is a
  distinct-date count with a hard Sept-7 boundary (`src/lotg.py:12520-12544`). Source
  comment 6840-6842 explicitly states "Year/all-time totals are counted separately."
  Weekly trade-sum is **not** a stated RUN3 invariant; `Total==Off+In` and the
  all-time trade rollups all reconcile.
- **B-2 — player_year tx/drops/trades ≠ Σ player_week** (720/681/366 player-years;
  player_year ≥ Σweek in **all 1859** cases, never <). *Reason:* player_week rows
  exist only for rostered-and-scored weeks, so offseason drops / adds-and-drops with
  no scored week (e.g. Tom Brady 2023 drop-to-FA: player_year tx=1, 0 player_week
  rows) can't appear weekly. The stated invariant player_all_time==Σplayer_year holds exactly.
- **B-3 — league_year Total trades ≠ Σ team_year Total trades** (odd Σteam parity for
  2021-2024, e.g. 2021 league 15 vs Σteam 31). *Reason:* 30 three-team trades
  contribute 3 team-participations but one league event; league dedups distinct dates
  league-wide, team dedups per-team. `Total==Off+In` holds at both grains.
- **B-4 — 10 player-years N/A on `Starter boom %` / `Starter scoring volatility` /
  `Consistency percentile` despite `Weeks as starter`=1** (Hunter Henry 2023, Trey
  Sermon 2021, Khalil Shakir 2022, Deuce Vaughn 2023, +6). Each was started exactly
  once in a week that scored 0 (inactive start; `Total points as starter`=0). Matches
  the documented tier-share gate "N/A for a player with no active started/played
  weeks" (`src/lotg.py:1432-1442`). Minor cosmetic split: `PPG starter` shows real
  0.0 for the same rows while the tier %s show N/A — defensible (PPG counts the
  started week; tier classification requires an *active* week).

### (c) NEEDS-HUMAN-JUDGMENT
- **C-1 — league_week / league_year `Efficiency` is the mean of the teams' finer-grain
  efficiencies, NOT `PF / Max PF` of the displayed pooled columns** (98/101 league-weeks
  differ from PF/MaxPF; league_week Eff == mean(team_week Eff) 0/101, league_year Eff
  == mean(league_week Eff) 0/6). The choice is internally consistent, but league_week
  and league_year both *display* `PF` and `Max PF` whose ratio a reader would expect to
  equal the shown `Efficiency`, and it doesn't. Cosmetic/definitional — flag for a human
  to confirm the averaging convention is intended for the league grain.
- **C-2 — transactions `O-Score` is populated offline (439/1510 rows, real values
  6.5–43.8, no fake 0s), whereas picks/trades `O-Score` and all KTC columns are empty
  offline.** transactions O-Score is derived from point-based percentile components
  (available offline) rather than KTC, so it computes. This is *more* data, not a
  defect — but it means the blanket "all KTC/O-Score columns are empty offline"
  characterization is imprecise; a human should note that transactions O-Score is a
  real offline output and confirm parity with production.

---

## Verification

- Method: direct pandas over the committed `exports/*.csv`, `PYTHONPATH=src:lib`,
  N/A-aware comparisons (NaN==NaN treated equal; a number-vs-NaN flagged).
- Part 1: ~55 reconciliation columns across 5 sheet-pairs, all Δ=0; 2020 slice reran clean.
- Part 2: ~22 derived families hand-derived from inputs; Win-Variance rank-conservation
  (Σ=0/season) and All-play (Σ strictly-lower-PF) reproduced independently; 2020 reran identical.
- Part 3: every `_preserve_na` gated family (`src/lotg.py:1336-1561`) checked in both
  directions at full population — FAAB (4 sheets + 5 tx columns), Number-of-bids,
  offseason turnover/trades, win%-vs-self, retention, playoff/toilet win%, player
  consistency/PAR, tx drop/tenure columns, KTC/O-Score offline.
- Source cross-refs read: `_preserve_na` (1336-1561), Win Variance (14572-14574),
  All-play (17780-17833), weekly-trade vs yearly-trade counting (6837-6853, 12520-12544).
- No files under `src/` or `exports/` modified.

**Result: Parts 1, 2, 3 — CLEAN. 0 confirmed defects. 4 by-design items, 2 needs-human-judgment items flagged over-inclusively.**
