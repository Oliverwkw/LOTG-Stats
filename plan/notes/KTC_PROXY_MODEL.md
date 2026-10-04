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
| **Routed anchored**, anchor ≤10 days old | last week's KTC | **0.998** (carry: 0.998) | 91 (carry: 93) |
| Routed anchored, anchor 11–45 days old | | **0.992** (carry: 0.990) | 182 (carry: 204) |
| Routed anchored, anchor 46–120 days old | | **0.974** (carry: 0.959) | 359 (carry: 449) |
| Routed anchored, anchor 121–400 days old | | **0.953** (carry: 0.883) | 447 (carry: 763) |

(Anchored rows: weekly data, players held out, 18k–39k rows per band;
2026-10-04 code.)

- **>90%: met** by stats alone (r 0.947 on months the model never saw).
- **±250 on every point: impossible from these inputs**, and provably so — see
  *Why not ±250 everywhere*.
- **r ≥ 0.98: met only with a KTC anchor under ~6 weeks old.** With a weekly
  feed that is the normal case, but at one week carrying KTC forward already
  scores 0.998 — the model's edge there is small (MAE 91 vs 93). It earns its
  keep as the anchor ages. Stats-only tops out near 0.95: it cannot see news.
- **Staleness is counted in games, not days** (2026-10-04, from the #467
  session): across an offseason a months-old KTC barely moves; once games are
  played it goes stale fast. The routed model moves off the anchor in
  proportion to NFL weeks played since it — see *Round 4*.
- **The last-season rehearsal** (n=114, skewed to movers): stats-only r 0.935,
  anchored 0.920, their mean **0.938 / MAE 248** — the end-of-season test
  decides between them.

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
toward the stats estimate), so the shipped model routes by anchor age, and
since 2026-10-04 also by football played since the anchor — see *Backtest of
the consolidated code* and *Round 4*.

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

`python plan/notes/ktc_proxy/ktc_proxy.py backtest` (rerun 2026-10-04 on the
final code). Monthly stats-only, frozen at 2025-03-01, scored on the 1,986 later
rows: **r 0.947, MAE 416, 40.8% within ±250, calib 276, bias −235**. Weekly
anchored, players held out, every anchor age (anchors 1, 2, 4, 8, 13, 26 and 52
observations back):

| Anchor age | n | Carry forward | Stats-only | Anchored, 1-period training | Anchored, multi-age training | **Routed** |
|---|---:|---|---|---|---|---|
| 0–10 days | 18,446 | 0.9979 / 93 | 0.932 / 653 | 0.9979 / 97 | 0.996 / 152 | **0.9981 / 91** |
| 11–45 days | 38,951 | 0.990 / 204 | 0.932 / 632 | 0.992 / 189 | 0.990 / 222 | **0.9925 / 182** |
| 46–120 days | 34,205 | 0.959 / 449 | 0.934 / 623 | 0.974 / 367 | 0.974 / 369 | **0.974 / 359** |
| 121–400 days | 28,643 | 0.883 / 763 | 0.937 / 515 | 0.944 / 483 | 0.953 / 448 | **0.953 / 447** |
| no NFL weeks since anchor | 46,431 | 0.992 / 173 | | | | **0.993 / 168** |
| 1–3 NFL weeks since | 25,367 | 0.984 / 254 | | | | **0.989 / 218** |
| 4+ NFL weeks since | 65,094 | 0.833 / 897 | | | | **0.956 / 430** |
| all | 136,892 | 0.920 / 532 | | | | **0.977 / 302** (calib 93) |

(r / MAE.) Routing (`RoutedAnchored`): to 120 days, the 1-period model (with
games-since-anchor features), moved off the anchor by lam = g ÷ (g + 1), g = NFL
weeks since the anchor — no games, no move; beyond 120 days, the multi-age model
unshrunk; capped at KTC's 9,999. Previous version (carry ≤10 days, no games
features): all 0.977 / 310. The 0–10-day band is mostly 2020–21, the only
stretch of dense daily history; on 2022+ weekly rows carry forward scored r
0.994, MAE 60 (n 2,994, scratch run).

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
| M1 | Carry 2026-10-03 KTC to season end (~100-day anchor, ~14 NFL weeks) | r 0.833 / MAE 897 (4+ NFL weeks band) | r 0.769 / MAE 408 |
| M2 | Stats-only, frozen | r 0.934 / MAE 623 (held-out players) | r 0.935 / MAE 275 |
| M3 | Routed anchored on 2026-10-03 KTC, frozen | r 0.956 / MAE 430 (4+ NFL weeks band) | r 0.920 / MAE 259 |
| M5 | Mean of M2 and M3 *(added after the 2026-10-03 rehearsal)* | — | **r 0.938 / MAE 248** |
| M4 | Weekly, previous week's KTC: carry vs routed anchored | r 0.998 / MAE 93 vs 91 | r 0.993 / MAE 48 vs 45 (n=302); 80% ranges 84.6% |

*Re-registered 2026-10-04:* M3 and M4 now use the games-weighted routing
(*Round 4*), and the run prints M4's 80% ranges recalibrated each week on
earlier weeks' errors. The comparison and the criteria below are unchanged.

**What would count as holding up:** M2 r ≥ 0.90 (the original bar); M3 beats M1
on both r and MAE. **What would count as failing:** M2 below 0.90, or M3 not
beating M1 — either means the backtests flattered the model. **Open question
the test settles:** M3 vs M2 vs M5 for a ~100-day-old anchor in-season (the
backtest says M3; the rehearsal says M5, then M2). **Not expected:** M4 anchored
beating M4 carry by much — a one-week KTC move is news (backtest MAE 91 vs 93).
**Ranges:** M4's recalibrated 80% ranges should cover 75–85%.
Expect M2's MAE to read high if KTC's overall level shifts during the season;
the run prints the mean signed error — check it before blaming the
player-level model.

### Rehearsal on last season (run 2026-10-03)

The same command with `--freeze 2025-10-03 --eval 2026-01-13 --tol-days 30`
(anchor = latest KTC in the 30 days before the freeze; target = KTC within 30
days of the eval date — the stored history is too sparse for ±4 days: only 9
players qualified). Results are in the table above (rerun 2026-10-04 on the
final code; M1/M2 unchanged, M3 0.909 / 278 → 0.920 / 259 with the games-weighted
routing).

- **The sample is skewed.** After 2021 the repo's KTC values exist mostly at
  transaction dates, so these 114 are players this league traded or picked up —
  fringe backs and in-season movers (Rico Dowdle 1,925 → 3,435, Malik Davis
  224 → 1,472, Austin Ekeler 2,441 → 362). Carry-forward's r 0.769 vs 0.959 in
  the broad backtest is that skew.
- **On movers, stats beat a stale anchor.** The worst M3 misses are in-season
  role changes the stats model sees and a 3-month-old KTC does not.
- **Level drift showed up:** mean signed error M2 −156, M3 −68 (both low).
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

## What #467 (points above expectation) taught this model — tested 2026-10-04

`lotg_support.acquisition` prices every asset **relative to that day's KTC
market** (the field's 49th player = $1,000; the top by standing over the top
10), because KTC's level drifts — the same problem as this model's biggest
remaining error. Tested here, stats-only frozen at 2025-03-01, scored on later
months (single model; `calib` = n-weighted RMS of mean error per KTC quintile,
#467's calibration check):

| Stats-only variant | r | MAE | within ±250 | calib | bias |
|---|---:|---:|---:|---:|---:|
| current (raw target + calendar feature) | **0.9485** | 419 | 40.6% | 286 | −244 |
| market-relative target, last training level held | 0.9447 | 461 | 34.8% | 238 | −166 |
| market-relative target, previous month's level | 0.9344 | 512 | 42.1% | 374 | +146 |
| current × previous month's level | 0.9442 | **401** | **47.7%** | **153** | **+43** |
| current + draft slot forced monotone (#467's isotonic slot curve) | 0.9472 | 421 | — | — | — |

- **The market-relative target did not help — with the level we can estimate
  here.** This repo's stored KTC is too sparse after 2020 to rebuild the field
  (players per week: 280 in 2020, 10–34 after), so the level was estimated as the
  monthly median of KTC ÷ model estimate. That swings 0.85–1.08 within 2024 on
  sample composition alone. #467's anchor is read off KTC's full daily field,
  which this cloud sandbox cannot reach. **Untested, and the most promising next
  step:** export the build's daily anchor (49th player, top-10 mean) and train on
  KTC ÷ anchor.
- **Scaling by last month's level helps MAE and calibration, not r.** It needs a
  live KTC feed, and with one the anchored model is better anyway.
- **The calibration check is adopted.** r 0.95 hid a −244 mean error; the
  season-end run now prints `calib` and `bias` for every option.
- **A monotone draft-slot constraint is neutral** (rookies and 2nd-years: MAE
  388 → 393).
- **Confirmed design choices:** never price with hindsight (#467's look-back
  found it no closer to team behaviour; this model is as-of throughout); KTC's
  9,999 cap bunches the top 3–4 players, part of the top-tier error here.
- **Not transferable without data:** #467 prices picks on a market-relative
  board (draft-day KTC by slot × the day's anchor). That is how this proxy would
  value rookie picks without KTC, but the repo holds no pick KTC history to
  test it.

## Round 4: ideas from the #467 session — tested 2026-10-04

Read for ideas: the session that built #467 (its last ~7.5 hours, where the
pricing design was argued out; the first ~24 hours are mostly build logs and
were not read) and #389's design note. Each idea was tested as below; "future" =
stats-only frozen at 2025-03-01 scored on later months (single model, baseline
r 0.9485 / MAE 419), "held-out" = 5-fold by player.

| Idea (source) | Result | Kept? |
|---|---|---|
| **Information arrives with games, not days** (#467: pick odds firm up by week 8) | Stale anchors (n 79k): across an offseason, carrying a months-old KTC beat every model (r 0.984 / MAE 278); with 4+ NFL weeks since, carry fell to 0.853 / 870. Moving off the anchor by lam = g ÷ (g + 1) gave the best routing at every age ≤120 days (table in *Backtest*) | **Yes** |
| Production value: projected PPG above positional replacement, with a position age curve fit on 2012–24 (#467 option D) | held-out r 0.9374 → 0.9405; future MAE 419 → 428 (95% CI of the change −2 to +23) | No |
| Prior/in-season blend by games played (#467's roster → record blend) | held-out 0.9399 / 509; future MAE 430 | No |
| Same slot in earlier classes, same career stage (#467's unquoted-pick estimate) | future MAE 424 | No |
| Separate models per position (#389: pooling hid the slot signal) | future MAE 444 (pooled 419) | No — the trees already split by position |
| Separate rookie / veteran models | future MAE 442 | No |
| Blend the stats estimate into stale anchored predictions | MAE ±2 at every weight | No |
| Cap predictions at KTC's 9,999 | 195 of 137k rows affected; KTC ≥7,500 MAE 425 → 419 | **Yes** |
| 80% prediction ranges (#467's odds spread) | Frozen widths cover only 52–62% of later values (level drift); recalibrated each month on the previous 3 months' errors: **78% stats-only, 80% anchored**; weekly in the rehearsal: 84.6% | **Yes, recalibrated only** |

**The stats-only backup is at a wall with these inputs.** Every player-level
feature tried helps on unseen players but not on later months; later-month
error is dominated by market-level drift (bias −235), which needs the build's
daily field anchor (see the #467 section above).

## Not done

- No helper in `lib/` and no tests: this is an archived experiment, per the
  asker (note pushed to main without a PR, 2026-10-04). Promoting it means `lib/lotg_support/` + `tests/` +
  a thin `scripts/` CLI, additive only.
- Rookie draft picks are not modelled.
- No offseason news / injury feed, and no non-KTC rankings (ADP) — the two
  inputs most likely to move the stats-only ceiling.
