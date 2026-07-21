# Phase 14 — mandatory 3-part audit (digest + weekly health email)

Audit target: `origin/main` @ `35d3d71`, diffed against `cb6c1d5` (the last
pre-Phase-14 commit on main). Covers PRs **#358** (digest engine + delivery +
scheduling), **#365/#366** (credential re-encryption), **#367** (recipient split,
replay test email, weekly-highlight filters), **#368** (second weekly email —
dataset breakages + missed injuries).

Method: static read of the full diff; the committed `exports/` used as-is as the
data under test (no rebuild, per the standing audit convention); the digest
engine driven against real past seasons via its explicit `season=` / `week=`
parameters; and a pure rebuild-to-rebuild export pair extracted from git history
to test the weekly audit harness under its real operating conditions.

---

## Part 1 — Code-based audit: PASS with 4 findings

- Full suite green on this HEAD: `PYTHONPATH=src:lib pytest tests/ -q` → **51
  passed**, including the 5 new Phase-14 test modules (`test_digest`,
  `test_digest_send`, `test_audit_weekly`, `test_injury_coverage`,
  `test_send_audit_email`).
- CI: builds 438–445 all green. Note the "Send test digest email" workflow ran
  4× — runs 1–2 failed (pre-#365/#366 credentials), runs 3–4 succeeded, so SMTP
  delivery and `DIGEST_KEY` are confirmed working end-to-end.
- **No full `Build LOTG Stats` run on main has executed since Phase 14 merged**,
  so the in-pipeline digest / injury-coverage steps have never actually run in
  anger. All in-pipeline verification below is therefore local.
- Gating reviewed and correct: the league-wide send and the snapshot rotation
  are both gated to `github.ref == refs/heads/main` **and** (Tuesday cron **or**
  an explicit `send_email=true` dispatch). The Thursday pregame cron rebuilds
  the snapshot locally but never commits it, and `git add exports` in the
  exports-commit step cannot pick `data/digest/` up. No path emails the league
  from a PR or a branch.
- `--test` correctly targets `test_recipients` (okeimweiss only), not the
  league.

### Findings

**F1 (HIGH) — the weekly health email's headline check is a permanent false
alarm.** `scripts/audit_weekly.py` Part 1 asserts that completed-season rows are
immutable. That premise does not hold for this dataset. Diffing two
**consecutive builds with no code change in between** (`801df3c` → `a2f7d7e`,
runs 435 → 436) flags **1,956 past-season rows** across 5 sheets:

| sheet | flagged past rows | dominant drifting columns |
|---|---|---|
| transactions | 1,351 | `Link to previous/next transaction (added/dropped player)` (842/795/563/550), `O-Score` (106) |
| trades | 467 | `Link to next/previous transaction per asset` (328/325), `O-Score` (235) |
| picks | 126 | `Link to previous/next transaction` (106/70) |
| team_year | 11 | `Trading skill` |
| player_year | 1 | `Number of teams` |

Root cause is benign and by design: the `Link to …` columns are **row-index
references** that shift whenever the current season appends events, and
`O-Score` / skill columns are percentiles against an evolving universe. So the
health email will read **"⚠️ Issues need a look"** with 5–7 breakages every
single week, forever. `send_audit_email.py` swallows the audit's exit code, so
the workflow stays green — but the alert itself is pure noise, which defeats the
stated purpose of the feature. Suggested fix: exclude link-reference, O-Score
and skill/luck columns from the immutability comparison (or compare only a
pinned stable column subset per sheet).

**F2 (MEDIUM) — 10 season-`MAX`/level stats are projected as if cumulative.**
The `is_rate_stat()` name-marker heuristic misclassifies the whole
`Most number of {players,QBs,RBs,WRs,TE} {rostered,started} from same NFL team`
family. Empirically validating every team_year stat against its team_week
components (sum vs mean vs max), 10 of 39 classifiable stats are mislabelled —
all in that family. Concrete week-8 output:

> plehv79 is on pace for 1st-highest Most number of players rostered from same
> NFL team this season (12.8).
> *season-to-date actual = 6; all-time max in any completed season = 7.*

A stat capped by roster size is multiplied by 17/8, lands at an impossible
value, and therefore always ranks 1st — **53 such bogus lines** are generated at
week 8. Suggested fix: add `most number of` (or `same nfl team`) to
`_RATE_MARKERS`.

**F3 (LOW) — the snapshot is rotated and pushed *before* the email is sent.**
In `build.yml` the "Rotate digest snapshot" step commits and pushes
`ranks_snapshot.json` and then the "Send weekly digest email" step runs. If the
send fails, the week-over-week baseline has already advanced, so that week's
crossings are never reported to anyone. Swapping the two steps (or rotating only
after a confirmed send) closes it.

**F4 (LOW) — privacy + a stale comment.** `config/digest.yaml` commits **8 league
members' personal email addresses** to what is a **public** repo — scrapeable,
and permanent in git history. Worth a conscious decision (env/secret-sourced
recipient list, or accept it). Separately, the header comment in
`digest_test_email.yml` still says the test button emails "the
config/digest.yaml recipients"; since #367 it goes to `test_recipients` only.
The code is the safe one; the comment is stale.

---

## Part 2 — Results-based audit: PASS (9 cases verified against the CSVs)

Each digest claim was recomputed by hand from the committed exports.

1. **Single-week record (teams).** "plehv79's PF this week (60.0) is the
   3rd-lowest single week ever" — raw cell `59.96`; 3rd-lowest *distinct* PF of
   808 team-weeks (`45.36, 59.22, 59.96, …`), value unique. ✅
2. **Single-week record (players).** "Harold Fannin's % of points (if starter)
   … 3rd-highest" — raw `0.4236`; 3rd-highest distinct of 7,531 parsed
   player-weeks (`0.5238, 0.4249, 0.4236, …`), unique. ✅
3. **New single-season record.** "plehv79 sets a new single-season record for
   Times Lowest score? (7)" — 2025 value 7, best in any prior season 6. ✅
4. **Event highlight.** "2025 pick 3.08 (Jalen Milroe): Number of trades of 11 —
   1st-highest of any pick ever" — 11 is the max across all 548 picks, unique. ✅
5. **Two-sided dedup.** "The trade between AceMatthew and LWebs53 had the
   1st-largest Asset difference in average age of all time (20.6)" — the mirror
   rows (`+20.62` / `−20.62`) are correctly collapsed into **one** line naming
   both teams; 20.62 is the largest \|value\| on record. ✅
6. **Two-sided detection fires.** `matchup_highlights` on the biggest-margin
   week ever (2021 wk11) returns exactly "1st-largest Margin of all time
   (120.3)". `two_sided_columns` auto-detects `Margin` + `Difference in pregame
   avg max PF` on team_week and the 5 KTC/age differentials on trades — no
   hand-maintained list. ✅
7. **No spurious crossings.** `diff_snapshots(A, A)` on the real all-time sheets
   → **0** crossings. ✅
8. **A real crossing is phrased correctly.** Nudging the 4th-place team above
   3rd on `Max PF` yields exactly "BROsenzweig passes stevenb123 for 3rd-highest
   Max PF all-time" — right mover, right passed party, right rank, right end. ✅
9. **On-pace arithmetic.** Simulating 2025 through week 8 (horizon 17, scale
   17/8): rate stats carry as-is and cumulative stats scale linearly, matching
   hand computation to 1e-6 on every checked column. ✅

Offseason behaviour also confirmed against the committed build: `build_digest.py`
correctly reports `season=2026 weeks_completed=0` and skips without rotating the
snapshot; `injury_coverage.py` correctly reports the tracker as empty (first
capture 2026 wk1); the audit's Parts 2 and 3 are clean against the committed
exports (schema in order, 0 build ERROR/WARN, pytest log passing).

**Volume observation (not a defect).** A simulated week 8 → week 9 transition
produces 77 on-pace changes (70 team / 5 player / 2 league) plus 9–26 weekly
highlights, before crossings/events/records. That is several times the "~dozens
of lines" the plan targets, though entity-grouping compresses it. It is a direct
consequence of the deliberate over-inclusive design — flagged for awareness
only. Fixing F2 removes 53 of the bogus lines.

---

## Part 3 — Diff-based audit: PASS (fully additive)

`git diff --name-status cb6c1d5..35d3d71` — 25 files, of which **23 are pure
additions**. Only two existing files are modified:

- `.github/workflows/build.yml` (two crons replacing one, plus the four new
  digest steps — reviewed in Part 1),
- `plan/MASTER_TODO.md` (documentation).

**Zero changes to `src/`, zero changes to any of the 13 exported CSVs**, and no
change to any pre-existing library module. The new `data/audit/schema_baseline.json`
was verified in sync with the committed exports (Part 2 of the audit run: "every
pinned sheet has all its expected columns, in order"), and `exports/raw/injury_coverage.md`
matches what `injury_coverage.py` regenerates from the current exports.

No cell-level export sweep was required: the export files are byte-identical
across the whole Phase-14 range.

---

## Conclusion: 3-part audit is CLEAN on data, with 4 code findings

The dataset is untouched — Phase 14 is additive tooling and cannot regress any
stat. The digest engine's claims are arithmetically correct on every case
checked, its two-sided dedup and crossing phrasing are right, and its offseason
gating behaves.

Two findings are worth acting on before the 2026 season starts:

- **F1** — the weekly health email will cry wolf every week from its first run.
- **F2** — 53 impossible "on pace" lines per week from one misclassified stat
  family.

F3 and F4 are small and can ride along.

---

## Fixes applied (this branch)

**F1** — `audit_weekly.py` gains `is_volatile_column()` and drops those columns
from the completed-season comparison, reporting how many were exempted so the
exclusion stays auditable. 37 columns are exempt across the sheets. Verified on
the same pure rebuild-to-rebuild pair that produced the finding (`801df3c` →
`a2f7d7e`): **1,956 flagged rows across 5 sheets → 0**, i.e. Part 1 now reports
"✅ No completed-season row changed since the previous build". A synthetic test
confirms a *real* past-season stat change is still flagged.

> **Deliberately still in scope: the KTC-valued columns.** `KTC …` / `… value …`
> on picks / trades / transactions do not move build-to-build (they are stable
> across the pure pair) — they move only when the KTC cache is busted or
> refetched, which is exactly the class of incident worth an alert (cf. the
> earlier 401/403 stale-cache episodes). They are therefore left under the
> check. A run whose baseline spans a feature PR or a cache bust will still
> report them; that is correct behaviour, not noise.
>
> **This is now load-bearing**, because the Wednesday workflow was subsequently
> changed to rebuild cold with the caches regenerated (below). If KTC columns
> light up *every* week against a from-scratch rebuild, that is either a real
> reproducibility problem in the KTC layer or a signal to move them into
> `_VOLATILE_EXACT` — the first live Wednesday run decides which. Unknown until
> then: it cannot be tested offline.

### Follow-on: the Wednesday audit now runs a full cold-cache rebuild

`weekly_health_email.yml` previously audited the *committed* CSVs against an
older committed version — so it could only ever see what the Tuesday build had
already written, with warm caches. It now:

- snapshots the exports committed at HEAD as the baseline **before** building,
- runs a complete `python -m lotg` build with **no `actions/cache/restore`** —
  the same condition as ticking `force_refresh_cache` on the main build, so
  NFLverse / DynastyProcess / KTC are all re-fetched on top of the committed
  `.cache` baseline,
- runs pytest against that fresh build (Part 3 reads the fresh `pytest.log`),
- diffs fresh-vs-committed, and uploads the rebuilt CSVs + logs + the email as
  an artifact for any week that flags.

Part 1's question sharpens accordingly, from "did the last build change history?"
to **"does a from-scratch rebuild still reproduce the data we ship?"** — which is
the only form of the check that can catch an upstream source that changed
underneath us, started refusing requests, or stopped reproducing.

The run observes only: caches are not saved and `permissions: contents: read`
means nothing is pushed. The Tuesday build remains the sole owner of `exports/`
and of the cache keys. Cost is a cold-cache build (~1k KTC player histories
re-fetched) once a week; `timeout-minutes: 180`.

**F2** — `"most number of"` added to `_RATE_MARKERS` in `digest.py`, so the
`Most number of {players,QBs,RBs,WRs,TE} {rostered,started} from same NFL team`
family carries as a level instead of scaling. At week 8: **53 bogus lines → 11
correct ones**, now reporting the actual value at a sane rank ("2nd-highest …
(6)", actual 6, all-time high 7) instead of "1st-highest … (12.8)". No other
stat's classification changed (`Win %`, `Points against`, `Max PF`, `Hardship`,
`Efficiency`, `Player average age` all verified unchanged), and
`plan/phase14_phrasing.csv` was regenerated — exactly 20 rows differ, all in
that family.

**F3** — the send step now runs *before* the snapshot rotation in `build.yml`. An
SMTP failure fails the job, so the rotation is skipped and the week-over-week
baseline survives for a re-run instead of being consumed by an email nobody got.

**F4** — `mailer.recipients_from_env()` lets repo secrets `DIGEST_RECIPIENTS` /
`DIGEST_TEST_RECIPIENTS` / `DIGEST_AUDIT_RECIPIENTS` override the committed
lists; all three workflows pass them through, and `config/digest.yaml` documents
the swap. **The addresses are intentionally left in the YAML for now** so nothing
breaks before the secrets exist — set them, then blank the YAML lists. (Removing
them from HEAD does not erase them from git history.) The stale
`digest_test_email.yml` comment now correctly says the test button mails
`test_recipients` only.

Full suite green after the changes: **51 passed**, with new cases covering the
volatile-column exemption, the `Most number of …` classification, and the
recipient env override (including that a blank env var can't blackhole a send).

---

## Post-merge audit — build run 447 (cold cache), 2026-07-21

First live exercise of the Phase-14 pipeline: `Build LOTG Stats` #447 dispatched
with **`force_refresh_cache` ticked**, i.e. a full cold rebuild. Not the
Wednesday workflow itself (still unfired), but the same cache-regenerated
condition, so its uploaded artifact serves as the proxy. Audited by diffing that
artifact against the exports committed at `main`.

### The pipeline behaved

Every Phase-14 step ran correctly. Injury coverage reported the tracker empty;
the digest hit the offseason gate (`season=2026 weeks_completed=0`) and skipped
without rotating; **`send_email` was ticked yet no email reached the league** —
the offseason gate meant no HTML existed and the send no-op'd, exactly as
designed. F3's reordering is live (send, then rotate).

### The open KTC question is answered: KTC reproduces

Across a full cold rebuild only **16 rows** moved on KTC columns, all in rolling
windows:

| column | rows | trade dates |
|---|---|---|
| `KTC value difference 1 year later` | 12 | 2025-07-14 / 16 / 20 |
| `KTC value difference 2 years later` | 4 | 2024-07-14 / 18 |

— precisely one and two years before the run date. Every *fixed* KTC window
(deal time, end of season) reproduced byte-for-byte. So the F1 decision to keep
KTC under the immutability check was right; only the rolling variants needed
exempting. `"year later" / "years later" / "year after" / "years after"` added
to `_VOLATILE_SUBSTRINGS` (53 columns now exempt, up from 37).

### Finding — the pinned schema baseline was stale, and it was failing CI

`data/audit/schema_baseline.json` had been pinned from a committed export
snapshot predating #363, so every *correct* build flagged "player_all_time /
player_year: columns reordered" plus 3 new columns each. That also failed
`tests/test_audit_weekly.py::test_audit_weekly` in CI (run 447: 1 failed, 50
passed) via `check_real_exports_smoke`, which asserted the audit come back
schema-clean. Re-pinned from the run-447 build.

Re-pinning alone would have flipped the failure the other way — the *committed*
exports lack those 6 columns, so the smoke test would fail against them instead.
The real defect was the assertion itself: `exports/` is a committed replay cache
refreshed on a cadence, so it legitimately lags main's code between refreshes,
and a PR adding a column must not turn the suite red. `check_real_exports_smoke`
now *reports* schema drift and asserts only on build-log cleanliness. The teeth
stay where they belong — the weekly workflow runs `audit_schema` against a fresh
build, where a missing column really is a break (verified: 0 flags on the run-447
build, so that assertion still bites).

### Finding — committed exports were stale against main's own code

The last refresh (run 442, 07-18) landed *before* #363 and #364 the same day, so
`exports/` was shipping 6 columns that no longer exist in a real build and **761
win% cells the code no longer produces** (454 `Win % as starter` + 307 `Win %
while rostered`). Attribution is airtight: 454/454 and 307/307 of those changes
are committed-value → blank in the rebuild, exactly #364's "≥5 qualifying weeks"
gate. `A.J. Green 2021` shipped `1.0`; a real build says N/A.

Run 447 rebuilt the correct values and **discarded them** — "Only non-roster
churn and committed snapshot is 2d old (<6d); leaving exports/ as-is."

Fixed at the source: a run with `force_refresh_cache` ticked now **always**
commits. It is the only run that rebuilds every derived value from freshly
fetched sources, so its output is the most correct data the pipeline can
produce; discarding it as "non-roster churn" is precisely how the drift
happened.

**Follow-on: the Tuesday cron always commits too.** Reviewing the division of
labour — Tuesday owns `exports/`, Wednesday's cold rebuild only observes — showed
the premise didn't actually hold. The 6-day cadence rule was the only thing
making the Tuesday run commit, and in-season it doesn't fire: the Thursday
pregame run commits on any roster move, and **Thu 16:00 UTC → Tue 14:00 UTC is
just 4 days**, so on a quiet waiver week Tuesday's build was silently discarded.
That is the run the digest email is built from and the baseline Wednesday diffs
against, so its output has to be what the repo ships. It now commits
unconditionally. Verified across all four trigger shapes (box ticked / Tuesday
cron / Thursday cron / plain dispatch), the two no-commit cases being exactly
the ones that should leave `exports/` alone.

### Residual

After all three fixes, the same cold-rebuild-vs-committed audit drops from 4
confirmed to 2 — and both remaining flags are **true positives that clear
themselves**: the 694 stale `player_year` rows (fixed by the next refreshing
build) and the pytest-log flag recording the now-fixed baseline failure.
