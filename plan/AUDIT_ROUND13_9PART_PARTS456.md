# Round 13 — 9-part RUN3 full-population audit — Parts 4, 5, 6

**Build under audit:** the committed fresh Round-13 baseline exports
(`exports/*.csv`, `exports/LOTG_Stats.xlsx`) — the deterministic offline
Round-13 rebuild (league `1192931349575991296`, seasons 2019→2025, cut at 2025),
already verified byte-identical across two builds and CLEAN by the prior 10-part
battery. **Audited in place — no rebuild, no edits to `src/` or `exports/`.**
Agent 2 of 3 (Parts 4, 5, 6). Verification via direct pandas (`PYTHONPATH=src:lib`).

Population reused from Agent 1: league_week 101, league_year 6, league_all_time 1,
team_week 808, team_year 48, team_all_time 8, player_week 21,376,
player_year 1,859, player_all_time 649, transactions 1,510, trades 504, picks 514.

Known offline/by-design conditions (not re-argued at length): KTC / O-Score /
pick-value columns empty offline (dynasty-daddy/KTC 403; on-disk backfill not
merged offline); transactions `O-Score` IS populated offline (439/1510);
`season_2026` snapshot exists but the build correctly cuts at 2025.

---

## PART 4 — Edge cases: **1 NEEDS-JUDGMENT (real inconsistency), rest CLEAN**

Cases exercised (50+): synthetic future-pick slots, startup / vet / startup-
cornerstone picks, multi-team seasons, suspensions/byes/injuries, retention &
future-pick N/A gating, players added+dropped between weekly snapshots,
teleport/rename (name-collision) handling, mid-season roster churn, initial-
roster vets, no-2020-regression.

**CLEAN sub-checks:**
- **Synthetic future picks** (2026–2030, 162 rows): `Player Picked`="Unknown",
  `Number`="1.??", and every outcome column (`Number of starts before next
  transaction`, `Avg PPG on team`, `% of starts…`, `Length of tenure`, O-Score,
  KTC) is 100% N/A. Correct skeleton/by-design.
- **Multi-team seasons** present in every year incl. 2020 (2020:91, 2021:97,
  2022:104, 2023:131, 2024:102, 2025:60). `Number of teams` max = 6 (≤8), no
  impossible values.
- **Injuries/byes** flagged in all six seasons (incl. 2020: 394 injury, 153
  bye weeks). **Suspensions** only in 2022/2023/2025 — matches real data, not a
  gating error (0 rows for other years is correct, not a missing-value bug).
- **Retention / not-yet-played gating (#318):** future-pick outcome columns all
  N/A; two startup picks (Devine Ozigbo, Justin Jackson) correctly show N/A
  `% of starts` because they made 0 starts while rostered (0/0 undefined, not 0).
- **Name-collision / teleport test:** of 36 skill-position name collisions in
  the Sleeper DB, 8 names actually appear in-league (Ronald Jones, Kenneth
  Walker, David Johnson, Chris Thompson, Tony Jones, Mike Williams, Kyle
  Williams, Frank Gore). Each resolves to a **single coherent player** in
  player_week — one NFL team lineage, monotonically increasing Age, one Position.
  No two distinct players merged; ID-based disambiguation works. (Frank Gore =
  the 2020 Jets RB, age-diff −14.79 vs Benny Snell confirms Gore Sr., correct.)
- **Startup cornerstones / initial-roster vets:** startup (152) and 2021(vet)
  (32) pools present and attributed; the known zero-realized-transaction origin
  gap is by-design (Phase-13). `% of starts` populated for 150/152 startup picks.
- **Top/Last team** for the bleed-affected rows (below) is CORRECT — those use a
  tighter in-season window (Sep→Feb), so e.g. Adams 2024 Top/Last = shmuel256.

### FINDING 4-J1 (NEEDS-HUMAN-JUDGMENT — real internal inconsistency)
**`player_year` "Number of teams" over-counts by pulling the *following*
offseason's roster churn into the prior season's row.**
- Mechanism: `Number of teams` = max(distinct weekly teams, distinct *full-FY*
  tenure teams). The FY window (`src/lotg.py:12713 _fy_window`) is
  **Sep 1 (year N) → Sep 1 (year N+1)**, so all of the year-N+1 dynasty
  offseason (Feb–Aug N+1) is filed under FY N.
- Concrete: **Davante Adams 2024** → `Number of teams = 4`, but he was on
  shmuel256 for **all 17 weeks**, with **0 trades and 0 transactions in 2024**.
  The 3 extra teams come from his 2025-offseason trades (Apr–Aug 2025). Those
  same moves are counted as **`Number of trades = 3` under his 2025 row**, while
  the 2025 row's `Number of teams = 1`. → the trades and the resulting team
  changes land in **different year-rows**, inconsistent with each other and with
  `trades.csv` (which files those hops under `Season = 2025`).
- Scope: **108 player_year rows** across 2020–2024 have `Number of teams >
  weekly teams` with **0 in-year trades AND 0 in-year transactions** (pure
  next-offseason bleed): 2020:9, 2021:18, 2022:23, 2023:31, 2024:27. Other
  novel examples: A.J. Brown 2024 (3 vs 1), Christian Kirk 2023 (4 vs 1),
  Davante Adams 2024 (4 vs 1), Aaron Jones 2022 (3 vs 1).
- **2025 rows are NOT inflated** (bleed count = 0) only because 2025's following
  offseason isn't loaded — so identical players will report different team
  counts once the next season is added (a season-boundary asymmetry / instability).
- Classification: I lean **defect** (a `Number of teams = 4` for a player who
  was on one team the whole season with zero moves is factually misleading and
  internally inconsistent), but the *correct* window (Sep→Sep vs a draft-to-draft
  "dynasty year" vs strict in-season) is a design decision → **NEEDS-HUMAN-
  JUDGMENT.** Not a 2020-specific regression; affects all seasons uniformly and
  is pre-existing (Phase-3A.2 tenure-augmentation feature). The documented intent
  (catch Renfrow's added+dropped-between-snapshots 5th team *during the season*)
  is legitimate; only the offseason-spanning window is questionable.

---

## PART 5 — Duplicate / redundant column sweep: **CLEAN (0 new; 1 by-design degenerate pair)**

Scanned all 12 sheets for identical-value column pairs (`Series.equals`), then
filtered out pairs where either column is 100% empty (those "matches" are just
two all-NaN offline columns, not real duplication).

- **`Most number of QBs started from same NFL team` ≡ `Most number of TE started
  from same NFL team`** — identical in league_week/league_year/league_all_time/
  team_year/team_all_time. **Structural by-design:** the lineup starts exactly 1
  QB and exactly 1 TE, so both columns are constant `1` and therefore always
  equal. Genuinely redundant/degenerate, but a legitimately-defined stat, not a
  mis-computed column. Pre-existing "same-NFL-team family" (RUN3), **not new.**
- All large "identical" blocks in **picks** (O-Score ≡ every KTC column), **trades**
  (Pick value received ≡ O-Score ≡ all KTC-diff ≡ Change in pick value), and
  **transactions** (all `KTC value…` / `Net KTC value…` columns mutually
  identical) are **all-empty-offline artifacts** (403 to KTC source) — NOT real
  duplicates. Confirmed: picks/trades O-Score & all KTC cols = 0 non-null; tx
  O-Score = 439/1510 (populated, and correctly *not* in the duplicate set).
- **`Drafting skill` ≡ `Trading skill`** (team_year, team_all_time): both 100%
  empty offline (O-Score-derived). By-design offline, not a duplicate.
- Coincidental small-sample equalities in league_all_time (1 row) and
  team_all_time (8 rows) between assorted `Most number of … from same NFL team`
  columns are artifacts of tiny n, not structural duplication.
- **No NEW duplicate column introduced** by the Round-13 baseline.

---

## PART 6 — Data-quality gaps: **CLEAN (0 defects)**

- **player_year has 0 duplicate `(Player, Year)` pairs** — the Phase-13 padding-
  pass `(name, year)` guard (`src/lotg.py:13504`) holds. Spot: Justin Jefferson,
  DJ Moore, Tyler Johnson each have exactly one row per year.
- **188 tx-only pad rows** (`Weeks rostered == 0`) are all legitimate: every one
  has ≥1 real transaction/drop/trade (0 rows with all-zero counters). No
  phantom/empty padded rows.
- **0 orphans:** player-name sets are identical across player_week ⊆ player_year
  ⊆ player_all_time and back (0 in every direction). Every `Player Added` /
  `Player Dropped` in transactions and every non-"Unknown" `Player Picked` in
  picks resolves to a player_all_time row.
- **tx-only padding is complete:** all 1,510 transaction `(Player, Season)` pairs
  have a corresponding player_year row (0 missing).
- **Name-collision artifacts:** none surface as merged/mis-keyed rows (see Part 4
  — 8 in-league collisions each resolve to one coherent identity).
- **Key hygiene:** 0 leading/trailing whitespace, 0 double-spaces, 0 non-ASCII in
  Player/Team key columns across player_year/week/all_time/picks/transactions/
  trades. All team keys ∈ the 8 valid teams; picks `Team`/`Original Team` valid.
  Year range 2020–2025 in player_week/player_year — **no 2026 leak** (0 rows).
- **0 fully-duplicate rows** in transactions/trades/picks/player_week; **0
  structural key duplicates** — picks unique per `(Year, Number)` (future picks
  excluded), player_week unique per `(Player, Year, Week)` (no mid-week double-
  roster), transactions unique per `(Team, Added, Dropped, Date)`.
- **`Commissioner moved?` = False for all 514 picks** — verified **by-design**,
  not a dead flag. The `commissioner_pick_trades.csv` overlay (45 pick-hops)
  *injects synthetic trade legs* so those off-platform pick moves flow as normal
  recorded trades (e.g. 2021 R1.05 Javonte Williams: Original Team = plehv79,
  Team = shmuel256, `Number of trades = 1` — the plehv79→shmuel256 CEH-deal hop,
  correctly represented). `_detect_commissioner_moves` (`src/lotg.py:3130`) then
  flags only picks whose ownership is *still* unexplained after the overlay — of
  which there are zero. Constant-False is the correct outcome here (I could not
  exercise the True branch because the overlay fully reconciles every move;
  flagged for over-inclusiveness, but low concern).

---

## Anomalies flagged (over-inclusive)

### (a) CONFIRMED DEFECT
- *(none)* — no silent corruption / phantom / mis-keyed row found in Parts 4–6.

### (b) LIKELY BY-DESIGN / DOCUMENTED
- **P5:** `Most number of QBs started` ≡ `Most number of TE started` from same
  NFL team (constant 1; 1 QB + 1 TE lineup slots). Degenerate but valid; RUN3
  same-NFL-team family, not new.
- **P5:** picks/trades/transactions KTC & O-Score "identical" blocks, and
  `Drafting skill` ≡ `Trading skill` — all-empty-offline (403), not duplicates.
- **P4:** future-pick skeleton rows (2026–2030, "Unknown"/"1.??", outcomes N/A).
- **P4:** startup-cornerstone / initial-roster-vet zero-realized-event origin gap.
- **P6:** 188 tx-only pad rows (each has ≥1 real event).
- **P6:** `Commissioner moved?` constant-False (overlay reconciles all off-
  platform moves as normal trades; flag reserved for truly-unexplained moves).
- **P6:** startup picks all show `Number of trades = 0` (direct startup selection,
  no pre-draft slot trade).

### (c) NEEDS-HUMAN-JUDGMENT
- **FINDING 4-J1:** `player_year` "Number of teams" pulls the following
  offseason's roster churn into the prior-season row (Sep→Sep FY window). 108
  rows (2020–2024) inflated with 0 in-year moves; internally inconsistent with
  `Number of trades` (files the same hops under season N+1) and unstable across
  the season boundary (2025 unaffected until next offseason loads). Novel:
  Davante Adams 2024 = 4 teams despite 17 weeks on one team, 0 moves. Human
  should decide the intended year-window; the fix is a definitional choice.

---

## Verification

- All checks run in place against committed `exports/*.csv` with
  `PYTHONPATH=src:lib`; no rebuild, no edits to `src/` or `exports/`.
- Cross-checks against `src/lotg.py` (`_fy_window` 12713, padding guard 13320–
  13517, `_detect_commissioner_moves` 3130, `Commissioner moved?` 9154) and
  `data/commissioner_pick_trades.csv` (45 hops) confirm root causes.
- **Checks run:** ~38 distinct verifications across Parts 4/5/6.
- **Totals:** 0 confirmed defects · 7 by-design/documented families · 1 needs-
  human-judgment (Number-of-teams offseason bleed).
