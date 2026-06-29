# Phase 13 — 3-part audit (run 397 vs run 395)

**Build under audit:** run #397 (`28396012374`), commit `65f8db8`, branch
`claude/phase-13-audit-tsapoy` — the post-Phase-13 head (after the round-1…round-12 audit fixes).
**Diff baseline:** run #395 (`27908698227`), commit `6d83635`, branch `main` — the last pre-fix
build (PR #318, "Startup draft players remaining = N/A").

Source changes between the two builds (in `65f8db8 ^6d83635`): `src/lotg.py` (±532),
`src/formulas.py` (±40), `src/espn_2020.py` (±26), `scripts/audit_player_history.py` (±5),
`tests/test_pick_chain_links.py` (+99) — the rest is `plan/AUDIT_*` documentation.

Methodology per `plan/MASTER_TODO.md`: **code-based** · **results-based** · **diff-based**.

---

## Part 1 — Code-based audit

- **Build clean.** Run #397 concluded `success`; the new test `tests/test_pick_chain_links.py`
  is in the same commit range and the CI build (which runs the suite) passed.
- **Schema stable.** Every one of the 13 sheets carries an **identical column count** in both
  builds (player_week 65, team_week 101, team_year 127, team_all_time 137, trades/picks 41,
  transactions/player_all_time 56, …). No column added, removed, renamed, or reordered.
- **Source scope bounded.** The only logic touched is `lotg.py` / `formulas.py` / `espn_2020.py`
  / the audit helper. The fixes folded in across rounds 2–12: FAAB/bids N/A gaps, the 2020
  ESPN-FAAB N/A-vs-0 rule, pid-collision de-duplication, player-name normalization, the
  commissioner-wash fix (stop deleting real same-day-reversed trades), build-determinism
  (tied-timestamp sort), and the 2020→2021 platform-seam.

Verdict: **clean** — schema-faithful, build green, changes confined to the intended files.

---

## Part 2 — Results-based audit (invariants on the #397 build)

| # | Invariant | Result |
|---|---|---|
| 1 | **No duplicate identity rows.** `player_year` keyed on (Player, Year), `player_all_time` on Player. | ✅ 0 dup keys in #397 (was 5 + 3 in #395 — see Part 3). |
| 2 | **2020 FAAB is N/A, not 0.** 2020 was on ESPN (no FAAB system). | ✅ all 128 2020 team-weeks now `N/A`. |
| 3 | **FAAB direction is monotonic 0→N/A** (a semantic correction, never N/A→0 nor a value swing). | ✅ 264/264 team-week changes are `0.0 → N/A`; 0 numeric value changed. |
| 4 | **picks / formulas / league_all_time unchanged** (KTC-drift control — picks.csv carries pick values). | ✅ byte-identical across the 8-day gap → no live-data drift confound. |
| 5 | **Schema invariants hold** (col counts per Part 1). | ✅ |
| 6 | **Name normalization is 1:1** (no row lost/gained, only renamed). | ✅ player_week 397-only vs 395-only key sets match year-for-year (17/17/8/10/15 across 2021–2025). |

**6/6 PASS.** No genuine FAIL.

---

## Part 3 — Diff-based audit (every sheet, #395 → #397)

Order-independent keyed per-column diff. `picks`, `formulas`, `league_all_time` are **identical**.
Changed sheets, with every changed column attributed to a Phase-13 fix:

| Sheet | rows 395→397 | Dominant changed columns | Attribution |
|---|---|---|---|
| `team_week` | 808 (=) | **Amount of FAAB spent (264)**, Number of transactions (20), Number of trades (18), Quiet streak (5) | FAAB N/A-vs-0 (2020 ESPN: 128 · 2021 seam: 136, all `0→N/A`); trade/tx counts from commissioner-wash restore |
| `team_year` | 56 (=) | Trading skill (27), Amount of FAAB spent (16), Transaction skill (11), Total/Inseason/Offseason trades, Number of transactions, Drafting skill | downstream of the trade-count / FAAB / draft-seam changes |
| `team_all_time` | 8 (=) | Trading skill (7), Number of transactions (5), Inseason/Total trades (5), Transaction skill (4) | aggregate of team_year |
| `league_week` | 101 (=) | Amount of FAAB spent (33), Number of transactions (9), Number of trades (2) | aggregate of team_week |
| `league_year` | 6 (=) | Number of transactions, Inseason/Total trades, FAAB, Offseason trades | aggregate |
| `player_week` | 21376 (=) | **Reference player name (51)**, Number of trades (2); 67 keys "moved" | player-name normalization (`Kenneth Gainwell → Kenny Gainwell` etc.) — 1:1, same physical rows |
| `player_year` | 1904 → **1901 (−3)** | Number of transactions (74), Number of drops (61); +8/−6 key churn | pid-collision **dedup** (removed dup rows for DJ Moore 2021, Justin Jefferson 2020/22/24, Tyler Johnson 2021) + tx/drop undercount fix + name normalization |
| `player_all_time` | 654 → **651 (−3)** | Number of transactions (70), Number of drops (58) | same dedup (DJ Moore, Justin Jefferson, Tyler Johnson) + tx/drop fix |
| `trades` | 519 → **527 (+8)** | (row-add) | commissioner-wash fix restores real same-day-reversed trades; some signature churn is name normalization |
| `transactions` | 1529 → **1539 (+10)** | (row-add) | restored trades' transaction legs + 2020/FAAB tx fixes; name-normalization churn |

**Every changed column traces to an intended Phase-13 fix.** Nothing outside the
FAAB / name-normalization / dedup / trade-count families moved — no points, PF, records, win%,
efficiency, age, or KTC-value column changed on its own.

### Cross-date confound — controlled
The two artifacts are 8 days apart (Jun 21 vs Jun 29). The risk is KTC/current-season drift
masquerading as a code change. It is ruled out: **`picks.csv` (the KTC pick-value sheet) and
`formulas.csv` are byte-identical**, Sleeper transaction history is immutable, and the 2026 NFL
season hasn't started. The diff therefore isolates **code**, not data drift.

---

## Summary of findings

**Phase 13 passes the 3-part audit (run 397 vs 395).** Build green, schema unchanged, 6/6
results invariants pass, and the full-sheet diff confirms every change is an intended fix:

| # | Finding | Severity | Disposition |
|---|---|---|---|
| 1 | **FAAB 0→N/A on 264 team-weeks** (2020 ESPN + 2021 seam). | None — intended | The N/A-vs-0 correction; 2020 had no FAAB system. |
| 2 | **−3 rows on player_year & player_all_time** from pid-collision dedup (DJ Moore, Justin Jefferson, Tyler Johnson). | None — intended | The dup-row / collision-pid-pad fix; 0 dup keys remain. |
| 3 | **+8 trades / +10 transactions** from the commissioner-wash fix. | None — intended | Real same-day-reversed trades are no longer deleted. |
| 4 | **Name normalization** (e.g. Kenneth→Kenny Gainwell) reshuffles 67 player_week keys and inflates the raw trade/tx "new-signature" count. | Cosmetic | 1:1 row mapping confirmed; net row delta is the reliable signal. |

No regression found. Each diff family maps to a specific Phase-13 commit; no unexpected sheet,
column, or value moved.

### Reproducing
Download `LOTG_outputs` from runs `28396012374` (#397) and `27908698227` (#395); run the keyed
per-column diff (`scratchpad/diff.py`).
