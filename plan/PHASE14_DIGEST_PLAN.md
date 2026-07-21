# Phase 14 — In-season weekly digest email

Status: **engine + delivery + scheduling landed;** delivery verified end-to-end.

## The model (what a weekly email reports)

For **every** numeric stat across all sheets (~779), the email reports any change
to that stat's **top-5 or bottom-5** since the previous email. The live in-season
run does this by snapshotting every ranking each week and diffing the next week —
no reconstruction. Sheet-specific valuation ("constraints"): all-time sheets rank
entities by the actual value; year sheets rank the in-progress season by its
**on-pace** projection (cumulative × weeks; rate as-is); week sheets rank each
single week; event sheets (picks/trades/transactions) rank each event, and only
fire when that column's standing changed that week. **The only universal
exclusions are (a) a value shared by more than 5 entities at the extreme — the
`>5-tied` rule, which is how 0/1 flags and flat/cumulative columns fall out — and
(b) single-row `league_all_time` (no ranking → round-number milestones instead).**
Items are **grouped by entity** ("plehv79 set these single-season records: …").

**Offseason test email is minimal** (champion + a note) — there's no previous
email to diff against, and derived all-time/year rollups can't be reconstructed
for a single past week from final exports. During the season the test button
replays the last real weekly email, which is complete.

**Zero-centered / two-sided stats** (a matchup's margin is +M / −M; a trade's
KTC or age differential is +X / −X) are detected from the data — a column whose
paired rows hold mirror values — and handled specially: ranked by **absolute
value** (biggest blowout / closest game; most lopsided / most even trade) with
**both sides named in one row** ("the matchup between X and Y had the 3rd-
smallest margin of all time"). These are pulled out of the ordinary single-week
and event highlights so a two-sided stat never double-reports its mirror rows.
The seven such columns today: team_week `Margin` + `Difference in pregame avg max
PF from opponent`, and trades `Asset difference in average age` + the four `KTC
value difference …` columns. Like everything else they're diffed week over week
(`paired_keys` in the snapshot), so only newly-notable pairs fire.

## Behaviour

Two scheduled runs on `build.yml` (Phase 14 owns the canonical weekly pipeline):

- **Tuesday 14:00 UTC (~10am ET)** — build → digest → **email** → rotate the
  ranks snapshot. This is also the weekly exports refresh.
- **Thursday 16:00 UTC (~12pm ET)** — pregame build (fresh rosters/stats before
  TNF). Builds the digest preview but **no email** and **no snapshot rotation**.

Both self-gate to in-season (nothing emails in the offseason). `workflow_dispatch`
has a `send_email` toggle for a manual send.

The digest is **over-inclusive**: it auto-discovers *every* numeric column across
the ranked sheets — no hand-curated "headline" list. Per-section rules
(`CROSSING_CONFIG`, `PROJECTION_WINDOW`):

1. **All-time crossings**, diffing this week's snapshot vs last week's:
   - **players** (`player_all_time`): top AND bottom 5. *"Kyler Murray passes JJ
     McCarthy for 4th-lowest Points all-time (-0.4)."*
   - **teams** (`team_all_time`): **any movement among the 8** (full board),
     reported once from the riser's side. *"BROsenzweig passes shmuel256 for
     3rd-highest Max PF all-time."*
   - **league** (`league_all_time`): single row → no leaderboard; instead a
     **milestone** when a major total (`MAJOR_LEAGUE_STATS`) crosses a round
     number. *"League Total trades passes 200 (now 204)."*
2. **Yearly on-pace** (`player_year`, `team_year`, `league_year`): project the
   in-progress season to full-season pace, ranked vs completed seasons.
   Cumulative stats scale by weeks played; rate/level stats carry as-is.
   **Withheld until week 3.** Windows: players/teams top & bottom 5;
   **league_year `floor(#seasons/3)` capped at 5**.
3. **New single-season records** — the **weekly-counting stats** (awards
   `Times ...`, result-flips `Wins/Losses from hardship|byes`) can't be
   projected "on pace" (max one per week), so instead the digest alerts when the
   season's **actual** value sets a new all-time single-season record — the most
   that stat has been in **any** season (`yearly_records`, diffed so it re-fires
   only when the record is beaten/extended). *"AceMatthew sets a new single-season
   record for Times One-man army? (11) — most in any season."* **Boolean season
   flags** (0/1, e.g. #363's `Rostered by champion?`) get neither on-pace nor a
   record — they surface only via their all-time count crossings.

All yearly ranking (on-pace and records) is against completed single seasons
**across every year**, not just the current one.

4. **Single-week records (this week)** — the **weekly sheets** (`player_week`,
   `team_week`, `league_week`) are pulled in directly: the just-completed week's
   values are ranked against **every week ever recorded**, and the top/bottom 5
   (both ends — some stats go negative) are surfaced. *"shmuel256's PF this week
   (201.4) is the 2nd-highest single week ever."* Values shared by more than 5
   week-rows (the 0-piles on percentile/streak columns, routinely-tied maxes) are
   skipped so it stays to a handful of genuine extremes.

### Recipients
`config/digest.yaml` has two lists: **`recipients`** (the whole league — the real
Tuesday in-season email) and **`test_recipients`** (`okeimweiss@gmail.com` only —
the test button). `send_digest.py` picks the right one via `_recipients_for()`.

### Test email
`.github/workflows/digest_test_email.yml` is a one-click button: **Actions →
"Send test digest email" → Run workflow** (needs `DIGEST_KEY`; fails loudly if
missing). The test email = a "delivery is working" banner **plus a replay of the
most recent real digest** (`data/digest/last_digest.html`). In the offseason that
seed is the **post-championship wrap** (champion + the season's new records + its
biggest single weeks), generated by `build_digest.py --replica`
(`build_replica_html`). Each real Tuesday send overwrites `last_digest.html`, so
the test always replays the latest genuine email. The button appears in the
Actions UI once the workflow is on the default branch (after merge).

5. **Event highlights** (`picks`, `trades`, `transactions`) — the event-log
   sheets are pulled in too: each event's value is ranked against **every event
   of that kind ever**, and the top/bottom 5 surface. *"plehv79's move for Jacory
   Croskey-Merritt: Faab of 120 — 1st-highest of any transaction ever."* /
   *"2025 pick 3.08 (Jalen Milroe): Number of trades of 11 — 1st-highest of any
   pick ever."* In the live digest they're diffed (only newly-notable events
   fire); in the wrap they're the season's notable events.

### Season wrap (offseason test email / post-championship)
The wrap can't diff (one-time email), so it stands in with everything that
doesn't need a week-over-week baseline: the **champion**, **season-long final
results** (the on-pace stats resolved to "X finished with the Nth-highest … of
any season" — no "on pace"), **new single-season records**, the **biggest single
weeks**, and the season's **notable picks / trades / transactions**. Player
placements use top/bottom 3; the tiny team & league pools use records-only
(all-time single-season best/worst). All-time *movement* (who passed whom) needs
the weekly snapshots we only collect live, so it appears in real in-season emails,
not this offseason seed.

### Weekly-highlight quality filters
Single-week records only consider genuine per-week values. Excluded: streak /
tenure / "this season" columns (name markers), **structurally cumulative**
columns (monotonic non-decreasing across a season per entity — caught regardless
of name), and **season-summary** columns that read "In Progress" until the finale
(they'd falsely spike as a "record" at the championship week).

**Only changes are reported.** All-time crossings are inherently sparse (all-time
values barely move week to week). On-pace standings ARE also diffed week over
week — a team that's still "on pace for 3rd" is silent; only entrants and rank
moves print. That's what keeps an over-inclusive digest readable: a realistic
week is ~a few dozen lines, not the ~900 standings tracked. The first week that
carries on-pace data baselines silently.

## Files

- `lib/lotg_support/digest.py` — pure engine: `discover_numeric_columns`,
  `rank_column`, `build_snapshot`, `diff_snapshots` (crossings),
  `project_on_pace` + `pace_rank_map` + `diff_pace` (on-pace changes),
  `phrasing_catalog`, `render_digest_html`. No network / email.
- `scripts/build_digest.py` — CLI: reads `exports/` + prior snapshot, writes
  `exports/raw/weekly_digest.html`, rotates `data/digest/ranks_snapshot.json`;
  in-season gate; `--force`; `--phrasing-csv PATH`.
- `scripts/send_digest.py` — SMTP send from `config/digest.yaml` recipients +
  `SMTP_USERNAME`/`SMTP_PASSWORD` env. Safe no-op when HTML is missing, the
  digest is empty (`--skip-empty`), or creds are absent.
- `config/digest.yaml` — recipients (`okeimweiss@gmail.com`, extensible) +
  non-secret sender settings.
- `plan/phase14_phrasing.csv` — the "how every stat is phrased if it changes"
  catalog (779 stats: sheet, scope, scale, rise/fall phrasing, incl. two-sided
  extremes). Regenerate with
  `build_digest.py --phrasing-csv`.
- `tests/test_digest.py` — discovery, both-end crossings, small-board window cap,
  week-3 gate, projection ranking (cumulative vs rate), pace-diff, phrasing,
  render, real-exports smoke.

## Design notes

- **In-season gate = `weeks_completed >= 1`**, counted from distinct `team_week`
  weeks (the build only writes a `team_week` row once a week is final).
- **Window cap** = `min(WINDOW, n//2)` so the top/bottom ends never overlap on
  the 8-team league (a mid-table swap would otherwise report at both ends).
- **Snapshot rotation** commits `data/digest/ranks_snapshot.json` only on the
  Tuesday send run, so consecutive emails diff exactly one week apart. Thursday
  rebuilds it locally but never commits it.
- **Rate vs cumulative** classification (`is_rate_stat`) drives projection
  scaling and is surfaced per-column in the phrasing CSV so edge calls (e.g.
  "Tanking") can be reviewed and corrected.

## Delivery credentials (encrypted in the repo)

The sending account (`lotgstats@gmail.com`) + password are AES-256 encrypted into
`config/digest_credentials.enc`. The decryption key is the single **`DIGEST_KEY`**
GitHub Actions secret — never committed. `scripts/send_digest.py` decrypts the
blob at send time (via `openssl`); `SMTP_USERNAME`/`SMTP_PASSWORD` env vars
override it if ever needed. Re-encrypt with `scripts/encrypt_digest_credentials.py`.

### Setup required before emails send
1. Add the repo secret **`DIGEST_KEY`** (value provided out-of-band).
2. **Swap in a Gmail App Password.** Gmail rejects plain-password SMTP; the
   account needs 2FA + a 16-char app password
   (https://myaccount.google.com/apppasswords). Then re-encrypt:
   `DIGEST_KEY=<key> python scripts/encrypt_digest_credentials.py --username lotgstats@gmail.com --password '<app password>'`
   and commit the updated `config/digest_credentials.enc`.

Until `DIGEST_KEY` exists the send step logs a skip and the pipeline stays green.

## Second weekly email — dataset-health check (breakages + missed injuries)

Besides the league-wide Tuesday digest, a **second weekly email** goes **only to
the maintainer** (`config/digest.yaml` `audit_recipients` = okeimweiss) alerting
on two things: **dataset breakages** and **missed injuries**. Rendered + sent by
`scripts/send_audit_email.py`, scheduled by
`.github/workflows/weekly_health_email.yml` (Wednesday 15:00 UTC, a day after the
Tuesday build commits refreshed `exports/`, after nflverse settles). It's a
**weekly heartbeat** — it sends even on a clean week (a short "✅ all clear"), so
a silent inbox means the check didn't run, not that nothing's wrong. Uses the
same `DIGEST_KEY`-encrypted credentials as the digest (safe no-op when absent).

**Dataset breakages** come from the 3-part audit engine (`scripts/audit_weekly.py`,
also runnable standalone — it prints a Markdown report and exits non-zero on any
confirmed problem):

1. **Unexpected diffs** — completed-season immutability. The workflow materialises
   the *previous* committed version of each season-scoped sheet from git (the
   commit before the last one that changed it) and the script diffs full past-
   season rows (season `< current`); any add / remove / change to a completed
   season is flagged. Current-season rows churn in-season and are exempt. The
   in-progress season is read from the played-stat sheets (team_year/week,
   player_year/week) so future draft years in `picks` don't misread it.
2. **Schema breaks** — every sheet's columns are pinned in
   `data/audit/schema_baseline.json`; a missing / renamed / reordered column
   fails, a new column is noted. Re-pin intentionally with `--update-schema`.
3. **Build errors** — scans the last `===== Build start =====` segment of
   `exports/raw/build_debug.log` plus `pytest.log`; transient network blips
   (403/404/Tunnel/URLError/timeouts) and current-season preseason noise are
   ignored, real ERROR lines / tracebacks / test failures / a non-zero
   data-quality sanity count are flagged.

**Missed injuries** come from `scripts/injury_coverage.py`, which reports how well
the in-house weekly Sleeper injury tracker (`data/injury_tracker.csv`, the build's
primary injury/suspension source) covers the played weeks. Three sections:
**capture health** (per captured week, the injury / suspension / bye / healthy
breakdown of snapshotted players), **week gaps** (in-season weeks that were played
per `team_week` but have no tracker capture — the Monday capture job missed them
and the build silently fell back to the lagging nflverse feed), and a **build
cross-check** (per week, how many `player_week` rows the build flagged
Injury?/Suspension?/Bye?). The **week gaps** are the "missed injuries" surfaced in
the health email; the full report is also written to `exports/raw/injury_coverage.md`
by a non-gating `build.yml` step (committed with the build, downloadable). The
tracker starts empty (first capture 2026 week 1), so it cleanly reads "no captures
yet" until the season begins and becomes populated from there.

## Remaining (next sub-PRs)

- [ ] Review `plan/phase14_phrasing.csv` and prune / reword any stats whose
      change-phrasing isn't wanted (e.g. adjust the rate/cumulative call).
- [ ] **3-part audit** once a real in-season build + email round-trip exists.
