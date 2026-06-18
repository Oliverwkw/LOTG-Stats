# Plan: backfilling data-driven N/As (categories 1, 7, 8)

## Confirmed facts (investigation 2026-06-17)
- KTC values today come from **dynasty-daddy**; its per-player history floor is **2021-04-16**
  (317 players all start exactly that day = when dynasty-daddy began capturing KTC).
- **KTC.com itself has daily 1QB values back to 2020-04-01.** Player pages
  (`/dynasty-rankings/players/<slug>-<ktcid>`) embed two `overallValue` arrays of
  `{"d":"YYMMDD","v":value}`; the lower-valued one is 1QB (the format we use), the higher
  is superflex. Verified on Josh Allen: 1QB array runs 200401..260617 (2020-04-01 →
  2026-06-17), 2270 daily points. **So 2020 IS backfillable from KTC.com directly — NOT by
  proxy.**
- KTC player pages carry a KTC numeric id + slug but NO sleeper_id → a sleeper_id→KTC_id
  crosswalk is required.
- Category 8 (player_year `Points` N/A, ~214 rows) verified 214/214 legit: every one has
  zero player_week rows that season (rostered but never on a scored roster). **No fix.**

## STATUS (2026-06-17): KTC backfill in progress
- ALL KTC values switched to **superflex** (`sf_trade_value`), always (league is SF).
- `scripts/ktc_backfill_scrape.py` built: (a) active players via current KTC pages
  (full daily SF history back to 2020-04), (b) retirees via Wayback rankings
  snapshots; crosswalk = KTC rankings playerID/slug + DP db_playerids mfl/ktc ids.
- Method (per spec): only the (player,date) cells dynasty-daddy is missing
  (checkpoints < its 2021-04-16 floor). Targets = players in any pre-floor KTC
  cell across picks+transactions+trades (250).
- Scraped + committed to `data/ktc_cache/backfill/<sleeper_id>.json` (SF, pre-floor):
  - 81 active players → full 2020-04..2021-04 daily history (draft-day + end-of-rookie).
  - 159 retirees → 2021-01-17 Wayback point (covers the end-of-rookie checkpoint).
- `ktc.py build_index` merges the backfill (pre-floor) under each sleeper_id.
- KTC=0 logic REFINED: 0 only when a player is off-rolls AND past their last KTC
  value (demonstrably dropped off by then). A pre-history/active-era date with no
  data → N/A (NOT 0) — a now-retired player was active+valuable at his 2020 draft.
- REMAINING: the 2020 Wayback snapshots (2020-09/10, 2021-01-19, 2021-04) hit a
  1MB cap on Wayback's id_ endpoint (server-side — confirmed on GitHub runners too,
  not just the sandbox) → retirees' 2020 *draft-day* value (and ~10 players incl.
  Drew Brees not in the 2021-01 snapshot) still N/A. Genuinely-obscure players → 0.
- COMMUNITY-SHEET BACKFILL (2026-06-17): a Google Sheet (gid=991742784) carries
  daily SF values for ~460 currently-rated players back to 2020-04-01 with NO 1MB
  cap → far broader/cleaner than the Wayback rankings for ACTIVE players.
  `scripts/ktc_sheet_backfill.py` ingests a CSV export and merges its pre-floor
  weekly SF series into data/ktc_backfill/<sleeper_id>.json (dedup; scraped/
  dynasty-daddy dates win). Filled 95 of the ~300 pre-floor player-value residual
  cells; 503/563 backfill files now have pre-floor data.
  - The sheet's 36 pick-label columns are 2024-2026 only (no pre-floor values) →
    no help for the 2020-21 pick gap (which is moot: 2020 had no on-platform pick
    trades). Retired players (Brees, A.J. Green, Robby Anderson, ...) are NOT
    columns in the sheet → still depend on the Wayback scrape + off-rolls-0 rule.
  - Wayback capture→sleeper mapping in ktc_backfill_scrape.py now keys on KTC's
    own playerID (== DP ktc_id), stable across name changes, name+pos fallback.

## 1. (orig) KTC backfill — one-time KTC.com scrape (the 2020-04 → 2021-04 gap)
1. Build sleeper_id→KTC_id crosswalk for the players we need (2020 startup picks + 2020/
   early-2021 transaction & trade players, ~250-400): parse the KTC dynasty-rankings page
   player array (name, position, KTC id), match by name+position to our bridge/pid_meta.
   Retired players not in the current rankings (e.g. Drew Brees) resolve via their KTC
   player-page slug/id (KTC keeps retired player pages with their 2020-21 history).
2. One-time scraper script (mirror `scripts/espn_dump_2020.py`): for each KTC_id fetch the
   player page, extract the **1QB** `overallValue` array, convert `YYMMDD`→ISO, write a
   per-player history JSON. Commit under `data/ktc_cache/` (same shape the index already
   reads) or `data/ktc_2020_backfill/`.
3. Wire into `lib/lotg_support/ktc.py::build_index`: merge scraped historical pairs with
   dynasty-daddy's so `value_at` sees 2020-04+ (same source — it just extends each series
   earlier).
4. Acceptance: 2020 startup picks' `KTC on draft day` / `end of rookie year` populated;
   2020 transactions/trades KTC populated; McCaffrey 2020 draft-day ≈ KTC's 2020-08 value.
- Pick-value history (future-pick trades) is a separate, smaller need; 2020 had no
  on-platform pick trades, so prioritize PLAYER histories.

## 2. KTC = 0 for retired players off the rolls — DONE (this branch)
- `lib/lotg_support/ktc.py`: `ValueIndex.active_sids` = today's KTC directory; `asset_value_at`
  returns **0** for a player off the rolls with no value at the checkpoint (no history, or
  the date is past their last recorded value). An ACTIVE player with no value at a
  pre-history date (e.g. a 2020 checkpoint before KTC) stays N/A.
- Effect: Brees + the 4 startup busts → KTC 0 → their O-Scores become computable; retired
  dropped players in transactions/trades → 0 instead of N/A.
- After the scrape, fewer 0s are needed (players KTC tracked in 2020 get real values; only
  the truly-off-rolls get 0).

## 3. Player-ID mapping errors (KEEP — do NOT drop)
- The committed `data/espn_2020_raw/player_id_map.csv` (espn_id→sleeper_id, 250 rows) may
  contain wrong sleeper_ids → wrong-player attributions in 2020.
- Confirmed symptom: DP names ("D.J. Moore") vs live Sleeper names ("DJ Moore") differ
  across sheets (picks vs player_week) — same player, inconsistent spelling, breaks
  cross-sheet name joins/links.
- Steps: (a) audit all 250 mappings — cross-check each mapped sleeper_id's live-Sleeper
  name+position vs the bridge/ESPN name+position, flag mismatches; (b) reconcile display
  names to one canonical source (Sleeper/pid_meta); (c) re-run no-teleport + spot-checks.

## 4. Category 7 residual — 2020 picks' "Avg PPG on team"
- The picks PPG pass keys off nflverse game logs; for 2020 it (a) misses a few players (5
  startup / 6 vet → N/A) and (b) uses generic nflverse scoring, not the league's actual
  2020 (non-PPR) points.
- Fix: for 2020 picks, compute on-team PPG / points-added from the adapter's actual
  player_week points (authoritative for 2020) instead of nflverse.

## 5. Category 8 — no action (verified legit, see facts above)

## Note for off-platform pick reconciliation (Phase 13 step 6)
How traded-pick KTC works today: `asset_value_at("YYYY R.S", ...)` maps the pick to
dynasty-daddy labels `YYYY Early/Mid/Late Nth`, choosing the quarter by slot
(Early=1-4, Mid=5-8, Late=9-12), and reads that pick's value history. Used by
`Pick value received` and `Change in pick value at draft time`. **Consider when
reconstructing 2020 off-platform pick trades:**
- Pick value history shares the 2021-04-16 dynasty-daddy floor → 2020 pick values
  don't exist there; the KTC.com one-time scrape would need to grab **pick**
  histories too (not just players) to value any 2020 pick trade.
- The Early/Mid/Late quarter mapping assumes a **12-team** league; ours is **8**, so
  slot→quarter is approximate — revisit the mapping when valuing reconstructed
  8-team pick trades.
