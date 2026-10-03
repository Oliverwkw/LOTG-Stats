# A KTC proxy: estimating KeepTradeCut values without KeepTradeCut

**Question.** "Use the information we have (stats, age, NFL draft pick, whatever
else) to create a stat on the same scale as KTC that has >90% correlation with
KTC — a backup if KTC's popularity or data availability changes." Follow-ups
asked for every point within ±250, then "as close as you possibly can", then
r ≥ 0.98, with this note to be re-tested **at the end of the 2026 season**.

**Short answer** (asked 2026-10-02/03; superflex KTC, the build's `sf_trade_value`):

| Option | What it needs | Pearson r vs KTC | Mean abs. error |
|---|---|---:|---:|
| **Stats-only** | nflverse only — no KTC after training | **0.947** (frozen 19 months, scored on later months) | 416 |
| **Routed anchored**, anchor ≤10 days old (= carry it forward) | last week's KTC | **0.998** | 93 |
| Routed anchored, anchor 11–45 days old | | **0.992** (carry: 0.990) | 192 (carry: 204) |
| Routed anchored, anchor 46–120 days old | | **0.972** (carry: 0.959) | 377 (carry: 449) |
| Routed anchored, anchor 121–400 days old | | **0.952** (carry: 0.883) | 450 (carry: 763) |

(Anchored rows: weekly data, players held out, 18k–39k rows per band.)

- **>90%: met** by stats alone (r 0.947 on months the model never saw).
- **±250 on every point: impossible from these inputs**, and provably so — see
  *Why not ±250 everywhere*.
- **r ≥ 0.98: met only with a KTC anchor under ~6 weeks old.** With your weekly
  feed that is the normal case — but at one week, carrying KTC forward unchanged
  already scores 0.998 and **no model beat it**, so the routed model simply
  carries it. The model earns its keep as the anchor ages. Stats-only tops out
  near 0.95: it cannot see news.
- **The last-season rehearsal disagrees on one point** (n=114, Oct 2025 → Jan
  2026): with a ~100-day anchor, stats-only (0.935) beat anchored (0.909). See
  *Rehearsal*. The end-of-season test decides it.

Nothing here changes the build or `exports/`. Code:
`plan/notes/ktc_proxy/ktc_proxy.py` (run by hand; see *Reproduce*).

## The data

- **Target:** superflex KTC from `data/ktc_backfill/*.json` (KTC.com per-player
  history graphs — genuinely daily: 63–77% of consecutive days change in
  2020–21) and `exports/raw/ktc_provenance.csv` (values at transaction dates,
  2020–2026). 881 players, QB/RB/WR/TE. One value per player per month (or week)
  = the median of that period's daily values.
- **The sample is not KTC's universe.** It is the players this league drafted,
  traded or picked up, so r on KTC's full list could differ either way.
- **Density:** daily for 2020 – early 2021; after that only transaction-date
  checkpoints plus some daily stretches. This matters — see trap 1.
- **Inputs, all as of each row's date (no look-ahead except where noted):**
  nflverse regular-season stats (last three completed seasons + current season
  to date), Over The Cap contracts via nflverse (cap %, guarantees, years left),
  depth-chart rank (weekly charts to 2024, daily ESPN snapshots 2025+), offensive
  snap share, NFL draft slot and age (DynastyProcess ids), career best PPG /
  games / elite seasons, and calendar time.
- **Fetched from:** github.com/nflverse (reachable from the cloud sandbox).
  dynasty-daddy.com and keeptradecut.com are **blocked** from the sandbox; CI
  reaches dynasty-daddy.

## How the stats-only model got from 0.86 to 0.95

Every step measured the same way: players held out entirely (5-fold), and a
model trained before 2025-03-01 scored on 2025-03 → 2026-10 ("future").

| Step | Held-out-player r | Future r | Future MAE | Future within ±250 |
|---|---:|---:|---:|---:|
| Age, draft slot, last 3 seasons' PPR stats | 0.858 | 0.889 | 736 | — |
| + current season to date | 0.899 | 0.909 | 688 | — |
| + contract | 0.908 | 0.913 | 662 | — |
| + depth chart | 0.910 | 0.919 | 655 | — |
| defect fixes + yardage features | 0.914 | 0.919 | 661 | 19.9% |
| + calendar time & career features | 0.921 | 0.920 | 520 | 30.8% |
| + snap share | 0.917 | 0.922 | 509 | 32.6% |
| **predict √KTC instead of log(KTC)** | 0.931 | 0.941 | 449 | 36.4% |
| 3-model ensemble + 1-year recency half-life | **0.938** | **0.949** | **412** | **41.7%** |

**Tested and dropped (no measurable gain):** injury-report status, weeks on
injured reserve, team change, teammate competition at the position, team
offense, team QB quality, height/weight/40 time, monotonic constraints,
isotonic calibration. Several had patchy coverage (team change known for 69% of
rows), so these are weak negatives, not proof the signals are useless.

**What is left in the stats-only error:**
- **Market-level drift.** KTC's overall level moved (sample mean 3,043 in 2020,
  ~2,100 in 2022–24, 2,602 in 2026). A frozen model holds the last level it saw;
  in the future window KTC ran 10–30% above it by mid-2026. Knowing the level
  each month would cut MAE 412 → 374. Retraining while KTC exists fixes most of
  it (monthly-retrained stats-only: r 0.967, MAE 288).
- **News the inputs cannot see** (see below).
- **The top tier.** KTC 7,500+ is where errors are largest (MAE ~1,280 frozen).

## Why not ±250 everywhere

- **Identical inputs, different KTC.** 905 rows sit in groups where a player's
  informational inputs were identical but KTC moved by more than 500. Cam Akers:
  7,331 in March 2021, 3,458 in July 2021 (Achilles, offseason, no game played);
  Deshaun Watson moved 3,814 with no stat change. Even a perfect model on these
  inputs misses ≥4.4% of rows by more than 250 — a lower bound.
- **KTC moves faster than that.** Month to month, 31% of a player's moves exceed
  250 (median 137).
- **A model that "hits every point" is a lookup table.** Player id + date as
  inputs reproduces the training data exactly (100% within 250, max error 1)
  and drops to 40% within 250 on later months.

## Anchored model — and a correction

The anchored model predicts √KTC − √(anchor KTC) from the stats features plus
the anchor, its age, the stats estimate now and at the anchor, and how far KTC
sat from the stats estimate at the anchor.

**Correction to what was said mid-analysis:** results first reported as "last
month's KTC + stats" (r 0.972) used each player's *previous stored* KTC, which
after 2021 is a median of **62 days** old and often a full year (the 20 worst
misses mostly had 4–12-month-old anchors). The weekly table in the short answer
is the true weekly test: rows whose anchor is ≤10 days old, from the dense
daily data, players held out.

**Where the anchored error lives:** 109 rows (5.8%) where KTC moved >1,000 since
the anchor carry 48% of the squared error. On several, the stats-only estimate
had already seen the move and the anchored model under-used it (Drake Maye
Jul 2026: anchor 6,601 → KTC 9,362; stats-only 9,236, anchored 6,518). Training
on anchors of many ages (1 week → 1 year) was tried for this: it helps only for
anchors over ~4 months old and *hurts* fresh ones (it pulls a 1-week anchor
toward the stats estimate), so the shipped model routes by anchor age — see
*Backtest of the consolidated code*.

## Traps found (and fixed) along the way

1. **Anchor age.** The stored history is sparse after 2021 — "previous row" is
   not "last week". Always report anchor age with an anchored result.
2. **Franchise tag vs extension.** Lamar Jackson's 2023 tag and 2023 extension
   share a `year_signed`; an arbitrary pick read "−2 years left". Tie-break on
   contract value.
3. **nflverse contract namesakes.** A 2017 WR "Kenneth Walker" contract is keyed
   to Kenneth Walker III's GSIS id. Require the contract position to match.
4. **Preseason "0 games".** Before week 1 the current-season stats are missing,
   not zero.
5. **Log target.** Training on log(KTC) and exponentiating squeezed the top end
   (Bijan 9,994 → ~7,200). √KTC fixed most of it.
6. **Year-granularity contracts.** A contract counts from April of its signing
   year, so a few offseason rows see a deal some months early. Height/weight are
   today's values. Both are small look-aheads; everything else is as-of.

## Backtest of the consolidated code

`python plan/notes/ktc_proxy/ktc_proxy.py backtest` (2026-10-03). Monthly
stats-only, frozen at 2025-03-01, scored on the 1,986 later rows: **r 0.947,
MAE 416, 40.8% within ±250**. Weekly anchored, players held out, every anchor
age (anchors 1, 2, 4, 8, 13, 26 and 52 observations back):

| Anchor age | n | Carry forward | Stats-only | Anchored, 1-period training | Anchored, multi-age training | **Routed** |
|---|---:|---|---|---|---|---|
| 0–10 days | 18,446 | **0.9979 / 93** | 0.932 / 653 | 0.9978 / 98 | 0.995 / 161 | **0.9979 / 93** |
| 11–45 days | 38,951 | 0.990 / 204 | 0.932 / 632 | **0.992 / 192** | 0.990 / 228 | **0.992 / 192** |
| 46–120 days | 34,205 | 0.959 / 449 | 0.934 / 623 | **0.972 / 377** | 0.974 / 378 | **0.972 / 377** |
| 121–400 days | 28,643 | 0.883 / 763 | 0.937 / 515 | 0.942 / 496 | **0.952 / 450** | **0.952 / 450** |
| all | 136,892 | 0.920 / 532 | | | | **0.977 / 310** |

(r / MAE.) Routing (`RoutedAnchored`): carry the anchor when ≤10 days old,
1-period model to 120 days, multi-age model beyond. The 0–10-day band is mostly
2020–21, the only stretch of dense daily history; on 2022+ weekly rows carry
forward scored r 0.994, MAE 60 (n 2,994, scratch run).

## End-of-season test (pre-registered 2026-10-03)

**Purpose:** see how the options hold up on data none of them has seen. Models
are **frozen at 2026-10-03** (trained only on KTC dated on or before it).

**Run at season end** (nominally 2027-01-12, the Tuesday after week 18; any
later date works):

```bash
pip install pandas scikit-learn scipy pyarrow
python plan/notes/ktc_proxy/ktc_proxy.py season-end \
    --freeze 2026-10-03 --eval 2027-01-12 --tol-days 4 \
    --ktc-csv <weekly KTC: sleeper_id,date,ktc (superflex)> \
    --out plan/notes/ktc_proxy/season_end_2026.csv
```

The KTC CSV must cover both dates and the weeks between (dynasty-daddy keeps
daily history, so it can be pulled after the fact — CI can reach it, the cloud
sandbox cannot). Universe: players with a KTC value within ±4 days of both
dates.

**Options compared and what the backtests say to expect:**

| | Option | Backtest (46–120-day band) | 2025 rehearsal (n=114) |
|---|---|---|---|
| M1 | Carry 2026-10-03 KTC to season end (~100-day anchor) | r 0.959 / MAE 449 | r 0.769 / MAE 408 |
| M2 | Stats-only, frozen | r 0.934 / MAE 623 (held-out players) | r 0.935 / MAE 275 |
| M3 | Routed anchored on 2026-10-03 KTC, frozen | r 0.972 / MAE 377 | r 0.909 / MAE 278 |
| M5 | Mean of M2 and M3 *(added after the rehearsal)* | — | r 0.934 / MAE 258 |
| M4 | Weekly, previous week's KTC: carry vs 1-period anchored | r 0.998 / MAE 93 vs 98 | r 0.993 / MAE 48 vs 49 (n=302) |

**What would count as holding up:** M2 r ≥ 0.90 (the original bar); M3 beats M1
on both r and MAE. **What would count as failing:** M2 below 0.90, or M3 not
beating M1 — either means the backtests flattered the model. **Open question
the test settles:** M3 vs M2 vs M5 for a ~100-day-old anchor in-season (the
backtest says M3, the rehearsal says M2/M5). **Not expected:** M4 anchored
beating M4 carry by anything meaningful — a one-week KTC move is news.
Expect M2's MAE to read high if KTC's overall level shifts during the season;
the run prints the mean signed error — check it before blaming the
player-level model.

### Rehearsal on last season (run 2026-10-03)

The same command with `--freeze 2025-10-03 --eval 2026-01-13 --tol-days 30`
(anchor = latest KTC in the 30 days before the freeze; target = KTC within 30
days of the eval date — the stored history is too sparse for ±4 days: only 9
players qualified). Results are in the table above.

- **The sample is skewed.** After 2021 the repo's KTC values exist mostly at
  transaction dates, so these 114 are players this league traded or picked up —
  fringe backs and in-season movers (Rico Dowdle 1,925 → 3,435, Malik Davis
  224 → 1,472, Austin Ekeler 2,441 → 362). Carry-forward's r 0.769 vs 0.959 in
  the broad backtest is that skew.
- **On movers, stats beat a stale anchor.** The worst M3 misses are in-season
  role changes the stats model sees and a 3-month-old KTC does not.
- **Level drift showed up:** mean signed error M2 −156, M3 −76 (both low).
- **The season-end run has the full weekly feed** (±4 days, every KTC-listed
  player), so it is the fairer test; the rehearsal is a smoke test of the code
  and a warning about movers.

## Reproduce

```bash
pip install pandas scikit-learn scipy pyarrow       # tested: sklearn 1.9.1, pandas 3.0.6
OMP_NUM_THREADS=4 python plan/notes/ktc_proxy/ktc_proxy.py backtest   # ~45 min on 4 cores
```

Run one job at a time, or cap threads (`OMP_NUM_THREADS=2` each): two
sklearn jobs fighting over the same cores slowed a run more than tenfold.
Downloads go to `.cache/ktc_proxy/` (gitignored). The scratch scripts that
produced the step-by-step tables above were consolidated into this one file;
its backtest reproduces them closely but not exactly (monthly stats-only frozen
at 2025-03-01: r 0.947 / MAE 416 here vs 0.949 / 412 in the scratch run — the
consolidated version also reads 2019 snap, depth-chart and weekly files the
scratch run lacked). The step-by-step table is from the scratch runs and is not
regenerated by `backtest`; the *Backtest* and *Rehearsal* numbers are.

## Not done

- No helper in `lib/` and no tests: this is an archived experiment, per the
  asker ("no PR for now"). Promoting it means `lib/lotg_support/` + `tests/` +
  a thin `scripts/` CLI, additive only.
- Rookie draft picks are not modelled.
- No offseason news / injury feed, and no non-KTC rankings (ADP) — the two
  inputs most likely to move the stats-only ceiling.
