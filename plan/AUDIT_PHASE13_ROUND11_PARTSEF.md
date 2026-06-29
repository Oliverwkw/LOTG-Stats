# Phase 13 Round 11 — Parts E+F (domain-bounds/plausibility + N/A-vs-0 correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 3 of 5 in Round 11 (siblings this round:
Parts A/B — `AUDIT_PHASE13_ROUND11_PARTSAB.md` — landed CLEAN at `898f3df`;
Parts C/D — `AUDIT_PHASE13_ROUND11_PARTSCD.md` — found+fixed 2 tooltip-drift
defects at `afa5686`: the **Hardship** would-be-starter mis-claim and the
**Drafting skill** stale `picks.Final Team` column reference).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed behind the branch tip; `git merge-base --is-ancestor afa5686 HEAD`
printed nothing (afa5686 was NOT an ancestor). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`afa5686`, the Round-11 Parts C/D tip
carrying all Round-5..Round-11/CD fixes), then confirmed `OK_AT_OR_AHEAD` with
`git log -1 --oneline` showing `afa5686`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
player_all_time 649, player_year 1,859, player_week 21,376, team_year 48,
team_all_time 8, team_week 808, trades 504, transactions 1,514, league_year 6,
league_week 101, league_all_time 1, formulas 432.

All examples below are NOVEL — different players/teams/seasons/picks than every
prior round (Rounds 4-11 exclusion lists honoured). This round deliberately
stepped past the now-exhausted families re-scrutinised by recent E/F rounds (the
2020-vs-2021 draft seam, the Round-10 `Result` 5th-8th toilet-bowl ranking, the
Round-10 `Taxi-eligible` pad-row gate, the Week-1 pregame-diff rows, the 90
genuine-0 dropped points) and targeted the **transactions post-pickup timing
family** — surfacing a genuine COMPUTATIONAL N/A-vs-0 / undercount defect in
`Weeks between pickup and start`.

**Result: 1 real COMPUTATIONAL defect found and FIXED** (in `src/lotg.py`) —
a date-comparison bug in `Weeks between pickup and start` that (a) wrongly
rendered **N/A** for 6 transaction rows whose added player started in their very
pickup week (real value should be **0** — the N/A-vs-0 defect, Part F) and
(b) **undercounted by exactly 1 bench week** for 24 further rows (Part E
domain-correctness). Both directions stem from the same root cause and both are
fixed by one targeted change. `pytest tests/ -q` = **15 passed / 0 regressions**.

---

## THE DEFECT — `Weeks between pickup and start` date-string comparison bug

### Root cause (`src/lotg.py` ~7458, transactions_polish pass 1)

The column counts player_week bench rows for `(Team, Player Added)` between the
pickup date and the player's first start on that team. Each player_week row is
bucketed with an **approximate DATE-only** week string via `_approx_week_date`
(`"YYYY-MM-DD"`), but the pickup/drop thresholds (`r["Date"]`,
`r["Date dropped/traded"]`) are **full DATETIME** strings
(`"YYYY-MM-DD HH:MM:SS"`). The loop did a raw lexicographic string compare:

```python
if wk_date and wk_date < add_date:   # "2022-09-21" < "2022-09-21 03:04:19"
    continue
```

A date-only string is a **prefix** of a same-calendar-day datetime, so
`"2022-09-21" < "2022-09-21 03:04:19"` evaluates **True** — the player_week row
that falls in the very pickup week is wrongly SKIPPED. Consequences:

- If that skipped week was the player's **first start on the team**, the loop
  never sees a start (`found_start` stays False) → the column is left at its
  `None` default and renders **N/A** instead of the correct **`0`** (player
  started immediately, zero bench weeks before the start). **N/A-vs-0 defect.**
- If a bench week was skipped before a later start, the count is **1 short**.

### Smoking-gun evidence (full population, two fresh builds compared to isolate
the change from a pre-existing build non-determinism — see note below)

My fix changes **exactly 30** `Weeks between pickup and start` cells, in two
buckets, with **0 value→N/A regressions**:

**Bucket 1 — 6 N/A→0 flips (the N/A-vs-0 defect; each player's first week on the
adding team was a Starter, so 0 bench weeks precede the start):**

| Player Added | Team | pickup date | first team week (Starter) | old | new |
|---|---|---|---:|---:|---:|
| Irv Smith | AceMatthew | 2022-09-21 | W3 Starter | N/A | 0 |
| Marcus Mariota | LWebs53 | 2022-09-28 | W4 Starter | N/A | 0 |
| Teddy Bridgewater | LWebs53 | 2022-10-05 | — | N/A | 0 |
| Isaiah Likely | plehv79 | 2022-11-02 | W9 Starter | N/A | 0 |
| Ronnie Rivers | plehv79 | 2022-11-02 | — | N/A | 0 |
| Cooper Rush | plehv79 | 2024-12-07 | W14 Starter | N/A | 0 |

  Verified each against `player_week`: e.g. Irv Smith's first AceMatthew row is
  W3 Starter (5.2 pts); Isaiah Likely's first plehv79 row is W9 Starter (9.4);
  Cooper Rush's first plehv79 row is W14 Starter (13.82). Zero bench weeks
  precede the start → the correct value is `0`, not N/A.

**Bucket 2 — 24 undercount-by-1 corrections (Part E domain correctness):** e.g.
Taysom Hill/AceMatthew 0→1, Cole Kmet/stevenb123 0→1, Samaje Perine/LWebs53 0→1,
Baker Mayfield/BROsenzweig 1→2, David Njoku/JacobRosenzweig 14→15, Geno Smith/
LWebs53 1→2, Brock Purdy/Oliverwkw 1→2, Khalil Shakir/plehv79 3→4, Nico Collins/
plehv79 2→3, Mike White/stevenb123 3→4, Parker Washington/stevenb123 1→2,
Devin Duvernay/stevenb123 6→7, Tyler Boyd/LWebs53 7→8, etc. — each had its
pickup-week bench row restored to the count.

### The fix (`src/lotg.py` ~7455)

Compare against the **date portion only** (`add_date[:10]`, `drop_after[:10]`),
matching the date-only granularity of `wk_date`, so the pickup-week player_week
row is no longer wrongly excluded:

```python
add_day = add_date[:10]
drop_day = drop_after[:10]
...
    if wk_date and wk_date < add_day:        # date-vs-date
        continue
    if drop_day and wk_date and wk_date >= drop_day:
        break
```

### Post-fix verification (full population, final build)
- `Weeks between pickup and start`: every no-add row is N/A; every zero (67 now,
  was 65) carries a real add; all 6 previously-N/A rows now render `0`; **0
  value→N/A regressions** vs the HEAD-clean build.
- Re-derived the gate bidirectionally: N/A iff `(no add) OR (added but never
  started for the team)` — the documented behavior ("blank if the player was let
  go before ever starting"); a real `0` = started in the pickup week.
- `pytest tests/ -q` = **15 passed**, 0 failed/skipped (incl.
  `test_player_history_continuity`, `test_pick_chain_link_integrity`).
- Offline build exit 0, only the 2 expected network warnings.

### Note on a pre-existing (unrelated) build non-determinism
While isolating my change I observed that **rebuilding from the *unmodified*
HEAD source already perturbs 4 transactions rows** (`Player Dropped`, `O-Score`,
`Tanking`, `Dropped avg/total points`, the link columns) and a couple of pick
link-IDs in `picks.csv` — i.e. the committed export is non-deterministic across
runs independent of my edit (same-day add/drop pairing/ordering jitter). This is
a SEPARATE, pre-existing phenomenon, NOT caused by — and NOT in scope of — this
fix; I flag it here for the record but do not change it. To keep the commit
clean I reverted the regenerated `exports/` artifacts and commit the **source
fix only** (it regenerates deterministically from `src/lotg.py`).

---

## Part E — Domain-bounds & plausibility sweep (every numeric/derived column)

Scanned all 12 data sheets. Established per-column plausible domains + internal
logical constraints and scanned the FULL population.

### Bounded-domain columns — CLEAN
- **Win % / rate / efficiency** (every `%`/`rate`/`efficiency`, excluding
  by-design signed `minus`/`change`/`difference`/`variance` columns and the
  0-100 FAAB-premium): all absolute values in **[0, 1]**, 0 OOB. The only
  flagged ranges — `player_week.% of points (if starter)` [−0.0417, 0.5238] and
  `player_year.% of points (highest/lowest team)` [−0.0001, 0.2023] — are the
  documented **negative-share** case; verified ALL 12 negative-share player_week
  rows have **Points < 0** (NOVEL: Bhayshul Tuten −2.50, Cam Newton −0.18, Chase
  Claypool −1.20, J.J. McCarthy −0.52, Jameis Winston −1.36). Bounded, explained.
- **Percentile / boom % / bust %**: all in **[0, 100]**, 0 OOB.
- **FAAB premium %** (`transactions`): [0, 100], n=87. In range.
- **Ages** (true age cols only): all in **[18, 60]**, 0 OOB.
- **Week numbers** (`league_week`/`team_week`/`player_week`): all **[1, 17]**, 0
  phantom week-0 / week>17.
- **Year/Season**: numeric played-season values in **[2020, 2025]** on every
  season-keyed sheet; `picks.Year` correctly spans **[2021, 2028]** (future-pool
  picks) plus the `startup`/`2021 (vet)` text labels — by design.
- **Dates**: `trades.Date` [2020-09-12, 2025-12-04] (504), `transactions.Date`
  [2020-09-09, 2025-12-30] (1,514) — 0 outside 2020-2026, 0 unparsed.

### Count columns — CLEAN
Strict true-count scan (`number of` / `times as` / `total` / `bids` / `weeks as`,
excluding avg/ppg/diff/skill/score/streak/margin/luck/net/change/rate/%): **0
negative true-counts** at full population.

### Negatives run to ground — all by-design signed, NOT defects
A broad negative sweep flagged ~110 columns; every one is legitimately signed,
verified against its tooltip:
- **Points-rooted** (`Points`, `Avg points`, `PPG starter/bench`, `Starter/
  Rostered scoring floor/ceiling`, `Lowest starter score`, `Points Added/Lost`,
  `Dropped total/avg points`): a real NFL fantasy game can score negative (114
  player_week rows have Points<0). NOVEL: `player_all_time.Rostered scoring
  ceiling` < 0 for **Clayton Tune −0.88, Jake Fromm −0.80, Max Brosmer −3.06,
  Richie James −0.10, Roman Wilson −0.60** — each a single-rostered-week player
  whose only week was negative (ceiling==floor). `Dropped total/avg points`
  tooltips explicitly: "NEGATED… more negative = worse drop." `Lowest starter
  score` tooltip: "Can be negative."
- **Explicit signed deltas/composites**: `*minus*`, `Change in *`, `Difference
  of *`, `Net points`, `Margin`, `Win Variance`, `Luck`, `Differential`,
  `*PAR*`, `Asset difference in average age`, the pick-adjusted differences.
- **Trade/tanking composites** (`Trade impact score`, `Tanking`, `Trade addition
  value`, `Player addition value`): tooltips document them as signed indices
  (`Tanking`: "negative = dealt picks/youth for win-now talent"; addition values
  blend a `Difference of averages adjusted by position` that can be negative).
  NOVEL: `transactions.Points Added` has 1 negative (−0.1, 2020-09-23) — a single
  negative-scoring started week; legitimate.

### Internal logical-constraint checks — CLEAN (NOVEL traces)
- **Win? reconciles with PF vs Points against**: across all **808** team-weeks,
  0 rows with `Win?=True & PF<PA`, 0 with `Win?=False & PF>PA`, 0 PF==PA ties.
- **Record reconciles with Win %** (`team_year`): all 48 team-seasons —
  `wins/(wins+losses)` == `Win %` to 3dp, 0 mismatches. All `Win %`-family
  columns in **[0, 1]** (the lone OOB flag was `All-play win % minus Win %`, a
  literal "minus" signed diff — excluded).
- **Result structural distinctness**: every season 2020-2025 carries exactly one
  of `{Champion, 2nd, 3rd, 4th, 5th, 6th, 7th, 8th}` — 0 duplicate/missing
  places, exactly **1 Champion per year** (no impossible double-champion).
- **Championship-appearances consistency**: `team_all_time.Number of
  championship appearances` == per-team count of `Result ∈ {Champion, 2nd}`
  (finalists) for all 8 managers (AceMatthew 1, LWebs53 3, shmuel256 3,
  stevenb123 3, Oliverwkw 1, plehv79 1, BROsenzweig 0, JacobRosenzweig 0) — 0
  mismatches. (Confirmed it counts FINALISTS, not titles — name is "appearances".)
- **Week of playoff elimination** internal consistency: every season the 4
  bracket teams (Champion/2nd/3rd/4th) carry the `0` "made-the-bracket" sentinel
  and the 4 non-bracket teams (5th-8th) carry a real regular-season elimination
  week — exactly 4 zeros + 4 real weeks per season, no impossible combinations
  (e.g. a Champion with a real elimination week, or a 5th-place team with 0).
- **team_all_time.Playoff win %** in [0, 1]; N/A only for JacobRosenzweig (never
  reached the winners' bracket — consistent with his never being
  Champion/2nd/3rd/4th).

### Sentinel / nan / inf scan — CLEAN
Full-population literal scan for `nan`/`inf`/`-inf` → **0** across all 12 data
sheets (re-confirmed on the final post-fix build). No `9999`/`99999` sentinel
masquerades as data.

**Part E conclusion:** every bounded column is in-domain; every negative is a
by-design signed column traced to its tooltip (incl. the NOVEL negative-ceiling
single-week players and the negative-share negative-points players); all internal
logical constraints (Win?↔PF/PA, Record↔Win%, one-Champion-per-year,
championship-appearances↔finalists, elimination-week↔bracket membership) hold at
full population; no sentinel/nan/inf. The one undercount defect in Part E scope —
the 24 `Weeks between pickup and start` rows short by 1 — shares the root cause
of the Part F defect and was fixed together (above).

---

## Part F — N/A-vs-0 correctness (every conditionally-defined column)

Read every sheet as raw strings (`dtype=str, keep_default_na=False`) to preserve
the exact `N/A`-vs-`0` distinction. Enumerated **111 columns** where literal
`N/A` and a real `0` coexist (the distinction is live) and re-derived each gate
independently, checking BOTH failure modes (real-0 silently N/A; missing-data
silently 0).

### Defect found + fixed (see top): `Weeks between pickup and start` — 6 real `0`s
silently shown as N/A (added players who started in their pickup week). 0
over-broad. Re-derived gate after fix: N/A iff `(no add) OR (added-but-never-
started)`; real `0` iff started in the pickup week — now 0/0 in both directions.

### Bidirectional condition correctness elsewhere — CLEAN (0 over-narrow, 0 over-broad)

| Column / re-derived gate | over-narrow | over-broad |
|---|---:|---:|
| `transactions.Faab` / `Total FAAB bid` — value iff waiver & season≥2022 (389) | **0** | **0** |
| `transactions.Number of bids` — value iff waiver & season≥2021 (419) | **0** | **0** |
| 18× `player_week.*streak` — value iff played (skip Injury\|Bye\|Suspension) | **0** | **0** |
| 6× `player_week.(if starter)/(if bench)` vs `Starter/Bench` (21,376) | **0** | **0** |
| `player_year/all_time.PPG starter, Starter floor/ceiling/boom/bust/PAR/g` — ≥1 start | **0** | **0** |
| `player_year/all_time.Starter scoring volatility, Consistency percentile` — ≥2 starts | **0** | **0** |
| `player_year/all_time.Adjusted PPG starter` — ≥1 **played** start | **0** | **0** |
| `player_year/all_time.PPG bench` — ≥1 bench | **0** | **0** |
| `player_year/all_time.Adjusted PPG bench` — ≥1 **played** bench | **0** | **0** |
| `player_year/all_time.Points / Avg points` — ≥1 roster week | **0** | **0** |
| `player_year/all_time.Adjusted Avg points` — ≥1 **played** week | **0** | **0** |
| `player_year/all_time.Rostered floor/ceiling/boom/bust (≥1), volatility (≥2)` | **0** | **0** |
| `picks.Length of tenure / starts-before-next-tx / Points added / Avg points added` — made pick | **0** | **0** |
| `picks.Avg PPG on team / % of starts` — pick whose player was on roster ≥1 NFL wk | **0** | **0** |
| `picks.Weeks before first start` — pick whose player started ≥1 wk | **0** | **0** |
| `team_year.Win % vs <each of 8 opponents>` — N/A iff self or 0 games | **0** | **0** |
| `team_year/week/league_week/league_year.Amount of FAAB spent` — value iff year≥2022 | **0** | **0** |
| `team_year.3-year roster retention rate` — value iff Year+3≤2025 | **0** | **0** |
| `team_week.Roster/Starter turnover from previous week` — N/A iff league wk1 | **0** | **0** |
| `transactions.Length of tenure on team` — value iff a player was added | **0** | **0** |
| `transactions.Dropped total/avg points` — value iff a player was dropped | **0** | **0** |

Notable exactness / subtle gates correctly applied (NOVEL cuts):
- **Streak family**: the N/A mask is **exactly** `Injury \| Bye \| Suspension`
  across all 18 streak columns × 21,376 player-weeks (5,115 N/A each, identical
  mask) — tooltip "Bye/injury/suspension weeks are skipped… those cells read
  N/A." The `0` values are real "streak broken" zeros. 0/0.
- **Adjusted-vs-unadjusted gates differ correctly**: `Adjusted PPG starter` /
  `Adjusted PPG bench` / `Adjusted Avg points` use a **played-week** denominator,
  so a player whose only start/bench/roster weeks were ALL bye/injury/suspension
  (0 played weeks) correctly gets **N/A** while the unadjusted variant is a
  defined `0.0`. A naïve `weeks-as-starter≥1` gate spuriously "flagged" 10
  (player_year) + 7 (player_all_time) `Adjusted PPG starter` rows — confirmed NOT
  defects: re-derived from `player_week`, each (NOVEL: **Chris Rodriguez 2025,
  Deuce Vaughn 2023, Donovan Peoples-Jones 2021, Dontayvion Wicks 2025, Hunter
  Henry 2023, Khalil Shakir 2022, Ronnie Rivers 2022, Terrace Marshall 2021,
  Tre' McKitty 2022, Trey Sermon 2021**) started exactly 1 week and that single
  start was a non-played (injury/bye) week → 0 played starts → N/A is the correct
  answer (division by zero is undefined). With the correct played-start gate: 0/0.
  Same pattern verified for `Adjusted Avg points` (played-week gate → 0/0).
- **picks roster gate**: `Avg PPG on team` and `% of starts made while rostered`
  share the EXACT same N/A mask (124 each; 0 disagreement) — N/A for the 97
  unmade picks PLUS 27 made picks whose drafted player never spent an NFL week on
  the drafting roster (NOVEL: **Damien Harris, Jakobi Meyers, Denzel Mims,
  Elijah Moore, Nico Collins, Jalin Hyatt, Quinshon Judkins, Emeka Egbuka,
  Cam Skattebo, Jayden Higgins**, etc.) — exactly the documented "N/A ONLY when
  the player was never on the team's roster for an NFL week." `% of starts == 0`
  (95 rows = on roster but never started) correctly carry `Weeks before first
  start == N/A` (a player who never started has no weeks-before-first-start).

### Real-0-vs-N/A (the "0 is meaningful, not N/A" direction) — CLEAN
- `transactions.Dropped total/avg points`: **90 genuine `0`s** (dropped a player
  who scored 0 post-drop) — all 90 carry a real `Player Dropped`; not leaked from
  N/A. The 352 no-drop rows are all N/A.
- `transactions.Faab`: real `$0` winning waiver claims rendered `0`, not N/A.
- `team_year.3-year roster retention rate`: real `0%` retention (NOVEL: **LWebs53
  2021, LWebs53 2022**) rendered `0`, not N/A.
- `team_all_time.Playoff win %`: BROsenzweig = real `0` (reached the playoffs but
  lost every playoff game) — correctly a `0`, distinct from JacobRosenzweig's
  N/A (never reached the playoffs).
- `team_year.Win % vs <opponent>`: real `0` when a manager played and lost ALL
  games vs an opponent — distinct from the N/A of self / no-games-played.

---

## Verification
- `pytest tests/ -q` (via `PYTHONPATH=src:lib python3 -m pytest`): **15 passed**
  in ~56s, 0 failed / 0 skipped — incl. the full-build
  `test_player_history_continuity` and `test_pick_chain_link_integrity` — run
  after the fix.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- The fix's effect isolated by comparing two FRESH builds (HEAD-clean vs
  my-fix): exactly 30 `Weeks between pickup and start` cells change (6 N/A→0 +
  24 undercount-by-1), **0 value→N/A regressions**; final build re-derives the
  column's N/A gate 0/0 bidirectional.
- Build artifacts reverted (`git checkout -- exports/`); only the `src/lotg.py`
  fix + this findings file remain. (The pre-existing build non-determinism in 4
  unrelated transactions rows / a few pick link-IDs is documented above but
  deliberately untouched — out of scope, not caused by this fix.)

## Conclusion
**Parts E + F are NOT clean — 1 real COMPUTATIONAL defect found and FIXED in
`src/lotg.py`** (a DATA bug, higher-priority than pure tooltip text), sitting in
BOTH part-pairs at once:

- **`Weeks between pickup and start`** compared a DATE-only player_week week
  string against a full DATETIME pickup threshold; the date-only prefix sorts
  before a same-calendar-day datetime, so the pickup-week player_week row was
  wrongly skipped. This (Part F) **silently showed 6 real `0`s as N/A** — added
  players who started in their very pickup week (Irv Smith, Marcus Mariota,
  Teddy Bridgewater, Isaiah Likely, Ronnie Rivers, Cooper Rush) — and (Part E)
  **undercounted 24 further rows by exactly one bench week**. Fixed by comparing
  on the date portion only (`add_date[:10]` / `drop_after[:10]`). 30 cells
  corrected, 0 regressions, 15/15 tests pass.

Everything else in Parts E/F is CLEAN at full population: all bounded columns
in-domain; every negative is a by-design signed column traced to its tooltip;
all internal logical constraints reconcile (Win?↔PF/PA on 808 team-weeks,
Record↔Win% on 48 team-seasons, exactly one Champion per season, championship
appearances↔finalists, elimination week↔bracket membership); no nan/inf/sentinel;
and every other conditionally-defined column renders N/A correctly in BOTH
directions (0 over-narrow, 0 over-broad), including the subtle adjusted-vs-
unadjusted played-week gates and the picks roster-presence gate, with NOVEL
examples throughout.
