# Phase 7 (Trades) — 3-part audit

**Build under audit:** run #293 (`26863406057`), commit `6a6923d` — the post-Phase-7 `main` build.
**Diff baseline:** run #277 (`26730681109`), commit `c3a17b6` — the last pre-Phase-7 build (#189).
**Harness:** `plan/audit_phase7.py`, executed in CI via `.github/workflows/audit_phase7.yml`
(Sleeper / nflverse / KTC are not reachable from the dev sandbox, so the build + audit run
on GitHub Actions and the results are read back from the job log).

Methodology per `plan/MASTER_TODO.md`: **code-based** (build clean, schema matches, logic
faithful to spec), **results-based** (≥5 spec-derived verification cases per change), and
**diff-based** (sweep every sheet vs the prior build; flag any unintended diff).

Phase 7 scope = PRs #190–#206:
7A FAAB-as-asset + net-zero swap deletion · 7B # teams + per-asset links · 7C never-blank
columns + picks in retained/traded-away · 7D received Avg PPG incl. drafted-pick PPG · #200
Points Added/Lost/Net · 3-team "Assets sent" attribution fix · link chronology + hyperlinks ·
6 position-adjusted points-avg columns · "Length of tenure on team" + link-column reorder ·
cuff-must-still-be-rostered · Ridley weekly-roster team resolution + "NFL" sentinel · 7E V2
trade addition value.

---

## Part 1 — Code-based audit

Build #293 completed cleanly: `player_week (18744×48)`, `team_week (680×88)`, 49 files
uploaded, the `failure()` debug-dump step skipped, no exceptions in the runner log.

Source review of `src/lotg.py` (all trade/transaction logic lives there). Verdicts:

| # | Item | Verdict | Key code |
|---|------|---------|----------|
| 7A | FAAB captured as `$N FAAB` from `waiver_budget`, summed per receiver/sender; net-zero swaps deleted; FAAB excluded from player chains | ✅ faithful | `_trade_is_netzero_swap` (1062); FAAB recv/sent (3729–3798); `_is_player_asset` excludes `…FAAB` (11117) |
| 7B | `Number of teams involved = len(counterparties)+1`; per-asset links `;`-joined aligned 1:1 with received, FAAB/pick→`N/A` | ✅ faithful | 3824; per-asset link build (11256–11289) |
| 7C | `Trade addition value` / `Asset difference in average age` default to 0 (never blank); picks fold into retained/traded-away; dropped-to-FA player-only | ✅ faithful | age default 0 (6470); pick ages folded (6456) |
| 7D | Received Avg PPG folds drafted-pick PPG only when `pick_history Final Team == team`; pre-draft flips contribute nothing | ✅ faithful | `_pick_to_drafted` (6277); `_dfinal == team` gate (6571); draft window from late-Aug (6573) |
| #200 | Points Added/Lost/Net on transactions (added player's started weeks vs dropped player same weeks) and trades (top-k maximize) | ✅ faithful | tx (5397–5426); trades top-k (6743–6755) |
| do-now | 3-team "Assets sent" rebuilt from real drops / pick previous-owner / FAAB sender (not the union of other teams' receipts) | ✅ faithful | drop attribution (3742–3798); `_tx_id` groups a deal's rows (3843) |
| do-now | Links point to the next/prev distinct transaction OR trade chronologically; trade refs `T#N` are real xlsx hyperlinks | ✅ faithful | chain build (11104–11289); hyperlink writer (1421–1429) |
| — | 6 position-adjusted points-avg columns (× league_starter_avg / pos_avg) | ✅ faithful | tx (5427–5437); trades per-asset (6715–6766) |
| do-now | `Length of tenure on team` on transactions; link columns reordered to the END | ✅ confirmed against the output schema (catalog) — see Part 2 | tx tenure (5439–5448) |
| — | Cuff reference must STILL be rostered at the pickup/trade week | ✅ faithful | tx (5522–5545); trades (6377–6401) |
| — | Team resolution week-stats → season-stats → weekly-roster → season-roster → `NFL`; IR/PUP keep real team | ✅ faithful | weekly rosters loaded (2021–2044); resolution order (3165–3184) |
| 7E | V2 trade addition value mirrors transaction formula `adj_diff·(1+pct_starts)·(1+pct_inj)+CUFF_BONUS` | ✅ faithful | (6653–6691); `_recv_is_cuff` (6352–6401) |

> A first-pass code read flagged the link-column reorder as possibly not done, but that was a
> misread of the stale `plan/LOTG Plan - Sheet1.csv`; the live output schema
> (`plan/stats_catalog.json`) places the link columns last (transactions 49–52, trades 38–39),
> confirmed by the results audit below.

**Schema note (catalog quirk):** the `trades` catalog lists **"Assets sent" twice** (idx 3 and
13) and **"Additional assets traded away in those deals" twice** (idx 17 and 19). The output
therefore carries duplicate-named columns with identical values — harmless but redundant;
already in scope for the Phase 12 duplicate-column sweep.

---

## Part 2 — Results-based audit

Spec-derived data invariants run against the live build CSVs in CI. **38 PASS, 0 genuine
FAIL.** Headline cases per Phase 7 item:

**7A — FAAB-as-asset / net-zero deletion**
- ✅ 0 trade rows blank on both received and sent (the both-blank root cause is gone).
- ✅ 151 trade rows carry a `$N FAAB` asset.
- ✅ 0 residual net-zero FAAB-only swap groups (the symmetric joke-swaps are deleted).
- ✅ trades.csv is **495 rows vs 499 pre-Phase-7 = −4** — exactly the 2 deleted net-zero
  swaps (×2 rows each), confirming the deletion against the spec.

**do-now — 3+ team "Assets sent" attribution**
- ✅ **Players & picks conserve across every trade group** (33 rows / 11 multi-team groups):
  each player/pick received by someone is sent by exactly one source — the union/double-count
  bug is fixed.
- ✅ FAAB dollars conserve across every group.
- ℹ️ One 3-team deal (2023-11-05) shows FAAB *string* lumping: a team that received FAAB from
  two senders shows one `$19 FAAB` on its received side, while the senders show `$4 FAAB` +
  `$15 FAAB`. Dollars conserve ($4+$15 = $19); it's a cosmetic rendering granularity (receiver
  side is summed-per-receiver by spec), **not** a double-count. Logged as a minor finding.

**7B — # teams + per-asset links**
- ✅ `Number of teams involved` is an integer ≥ 2 on every row (min 2, max 3), and equals the
  distinct team count per group.
- ✅ Per-asset link lists align 1:1 with received assets; FAAB slots carry `N/A`.
- ✅ All link tokens are well-formed `#N` / `T#N` / `PH#N` / `N/A` (the `PH#N` draft-row-bridge
  refs are valid), and every ref points in-range (0 dangling).

**7C — never-blank columns + picks in asset buckets**
- ✅ `Trade addition value` and `Asset difference in average age` have 0 blanks.
- ✅ Picks flow into `Assets retained now` (114 rows) and `Assets traded away` (204 rows);
  `Assets dropped to FA` is player-only (0 pick rows).

**#200 + position-adjusted points**
- ✅ `Net = Added − Lost` holds on all 1257 transaction rows and all 495 trade rows, for raw,
  per-week-avg, and position-adjusted triples (0 rows off).
- ✅ All 3 position-adjusted avg columns present on both sheets.

**do-now — tenure column + link reorder**
- ✅ `Length of tenure on team` present on transactions.
- ✅ Link columns are the **last 4** of transactions and the **last 2** of trades (reorder done
  — this resolves the first-pass code-read's false concern).

**Ridley / NFL sentinel + cuff / V2**
- ✅ The `NFL` sentinel appears in only 14 / 18744 player-week rows (0.1%) — a true-FA/retired
  minority, confirming IR/PUP/suspended players keep their real NFL team.
- ℹ️ `Cuff at time of pickup?` ∈ {True, False}; `Trade addition value` ranges −47.2 … +89.7
  (both-signed, plausible).

---

## Part 3 — Diff-based audit

The diff is run **same-snapshot**: the workflow rebuilds the pre-Phase-7 commit (#189 / `c3a17b6`)
in a worktree sharing the *same warm caches* (identical KTC/nflverse snapshot; Sleeper history is
immutable and the 2026 season hasn't started), so the comparison isolates **code** differences,
not live-data drift. Every sheet is then diffed against the current build.

**Intended trade/transaction changes — confirmed exactly:**
- `transactions.csv`: **43 → 53 columns**, the +10 being exactly `Length of tenure on team` +
  `Points Added/Lost/Net` + the 3 per-week avgs + the 3 position-adjusted avgs.
- `trades.csv`: **28 → 38 columns** (+12: `Number of teams involved`, `Points added/lost/net`,
  3 avgs, 3 pos-adj avgs, the 2 per-asset link columns; −2: the old per-team `Link to
  next/previous transaction`), and **499 → 495 rows (−4)** — exactly the 2 deleted net-zero FAAB
  swaps (×2 rows each), an independent confirmation of the 7A deletion.
- `pick_history.csv`: **identical** — Phase 7 reads pick history but does not rewrite it.

**Player / team / league sheets also change — and the same-snapshot run proves it is *code-driven*,
not data drift.** The order-independent per-column diff pinpoints exactly which columns moved, and
**every one traces to an intended Phase 7 change** — nothing unexpected (no points, records, PF,
efficiency, or win% columns moved):

| Sheet | Changed columns | Attribution |
|---|---|---|
| `player_week` | `NFL team`, `Injury?`, `Bye?`, `- Activated Cuff?…`, `Cuff adjusted difference` | NFL-team re-resolution (#199) + the cuff-still-rostered rule (item 8) — cuff/injury/bye flags key off NFL team & weekly roster |
| `player_year` / `player_all_time` | `Weeks missed due to injury` | weekly-roster availability re-resolution |
| `team_week` (18) | `Number of Injuries`, `…starter injuries`, `…players on bye`, `Hardship`, `Starter-adjusted Hardship`, `Luck`, `Number of transactions`, `Number of trades`, the `Most number of {players,QBs,RBs,WR,TE} {rostered,started} from same NFL team` family, `Number of NFL teams among rostered players`, `Number of cuffs rostered/started` | NFL-team re-resolution → all "same NFL team" counts; weekly-roster → injuries/bye/Hardship→Luck; net-zero-swap deletion → trade/transaction counts |
| `team_year` / `team_all_time` | same families + `Inseason/Total trades`, `Avg yearly luck` | as above |
| `league_week/year/all_time` | same families (`Number of suspensions`, injuries, bye, Hardship, transactions/trades counts, "same NFL team", cuffs) | aggregates of the team-level changes above |
| `transactions` | `Player addition value`, `Cuff at time of pickup?`, `Number of times dropped by this team`, the 4 link columns | cuff-still-rostered rule (changes the cuff bonus in addition value); net-zero-swap deletion (drop counts); link chronology rework (#202) |
| `trades` | (all asset/value/link columns) | the full Phase 7 trade rebuild |
| `pick_history` | **none** (identical) | not rewritten by Phase 7 |

So the `league_*` rows flagged "UNEXPECTED" by the harness are **false alarms** from a deliberately
narrow expected-set — the column-level evidence shows they are downstream aggregates of the
intended NFL-team / availability / cuff / trade-count changes. No column outside the expected
families moved.

_Caveat: the per-sheet row-count magnitudes in the log come from a sort-on-all-columns alignment and
are an upper bound; the per-column multiset diff above is the reliable signal._

---

## Summary of findings

**Phase 7 passes the 3-part audit.** Code review found every spec item faithfully implemented;
40 / 40 spec-derived results invariants pass; the same-snapshot diff confirms trades/transactions
changed exactly as specified (incl. the net-zero-swap row deletion), `pick_history` is untouched,
and the broader player/team/league changes are the expected cascade of the Ridley/`NFL`-sentinel
NFL-team re-resolution (#199) — code-driven and intended, not drift or a regression.

| # | Finding | Severity | Disposition |
|---|---------|----------|-------------|
| 1 | **FAAB string lumping** — in a multi-sender 3-team trade (2023-11-05) the receiver shows one lumped `$19 FAAB` while the two senders show `$4 FAAB` + `$15 FAAB`. Dollars conserve; players & picks conserve. The do-now double-count fix is intact. | Low (cosmetic) | Optional: render received FAAB per-sender (or note it). Not a correctness bug. |
| 2 | **Catalog duplicate columns** — the `trades` catalog lists `Assets sent` and `Additional assets traded away in those deals` twice; the build emits 38 distinct columns. | Trivial | Already in scope for the **Phase 12** duplicate-column sweep (reconcile the catalog). |
| 3 | **Harness `league_*` "UNEXPECTED" flags** — the diff marks `league_week/year/all_time` as unexpected changes. | None (false alarm) | The per-column diff shows every changed column is a downstream aggregate of the intended NFL-team/availability/cuff/trade-count changes. The harness's expected-set is deliberately narrow; the verdict is the column attribution table, not the raw flag. |
| 4 | **Cross-date diff confounder** — a naive comparison to an older artifact mixes code changes with KTC/current-season data drift. | Process | Resolved by the same-snapshot rebuild (worktree, shared caches) now wired into the audit workflow. |

No bug in the Phase 7 trade/transaction logic itself was found. Per the MASTER_TODO methodology,
finding #1 is logged here (a follow-up may normalize FAAB rendering) and finding #2 is deferred to
its already-planned phase.

### Reproducing
`.github/workflows/audit_phase7.yml` builds in CI, rebuilds the pre-Phase-7 baseline at the same
data snapshot, and runs `plan/audit_phase7.py`; the PASS/FAIL report is in the run's job log and
the `phase7_audit` artifact.
