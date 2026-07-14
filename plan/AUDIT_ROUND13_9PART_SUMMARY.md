# Round 13 — 9-part RUN battery audit (summary)

The standard 9-part RUN3 battery (the 10-part audit minus the ESPN-2020-specific
Part 10), run as **3 sub-agents, one at a time** (sequential), each owning a
3-part group, under the standing **over-inclusive** reporting rule (flag every
anomaly; classify defect / by-design / needs-judgment; never silently drop;
prefer false positives).

**Build under audit:** the fresh Round-13 committed export baseline (deterministic
offline rebuild, previously audited fully-CLEAN by the 10-part battery and verified
byte-identical across two builds). No rebuild; audited in place. Population: 6
seasons 2020-2025, 8 teams, 808 team-weeks, 21,376 player-weeks, 514 picks (future
pool through 2030), 1,510 transactions.

## Result: 0 confirmed defects across all 9 parts

| Agent | Parts | Scope | Result |
|-------|-------|-------|--------|
| 1 | 1-3 | cross-sheet reconciliation; stat-family hand-checks; N/A-vs-0 sweep | CLEAN |
| 2 | 4-6 | edge cases; duplicate-column sweep; data-quality gaps | 0 defects (1 needs-judgment) |
| 3 | 7-9 | metric-accuracy/odd-result hunt; no-teleport; cell-by-cell sweep | 0 defects (2 needs-judgment) |

**Verification:** `pytest tests/` → 46 passed / 0 failed. Part 8: 5,645 link
references scanned → 0 out-of-range, 0 teleports. All RUN3 cross-sheet invariants
reconcile to Δ=0. 2020 reconciles identically to every other season.

## Over-inclusive items surfaced (no confirmed defects)

### Worth a decision — corroborated by two agents

**`player_year` "Number of teams" offseason-bleed** (Agent 2 finding 4-J1,
independently corroborated by Agent 3 Part 7). The tenure fiscal-year window is
Sep→Sep (`src/lotg.py:12713`), so the *following* dynasty offseason's roster churn
is filed under the *prior* season's `player_year` row. **108 rows across 2020-2024**
show `Number of teams` greater than the player's actual weekly team count while
carrying 0 in-year trades and 0 transactions. Flagship: **Davante Adams 2024 = 4
teams** despite being on one team all 17 weeks with zero 2024 moves — those moves
are his *2025*-dated trades. Per-season distribution: 2020:9 / 2021:18 / 2022:23 /
2023:31 / 2024:27 / 2025:0 (2025 is un-inflated only because its next offseason
isn't loaded — a boundary asymmetry). This is internally inconsistent with
`Number of trades` and with `trades.csv` season attribution. Pre-existing
(Phase-3A.2), affects all seasons uniformly — **not** a 2020 regression. Both
agents classify it NEEDS-HUMAN-JUDGMENT (leaning defect); the fix is a definitional
window choice, so it is surfaced rather than auto-applied.

### Minor / awareness

- **League-level `Efficiency` definition** (Agent 1 C-1): league_week/league_year
  Efficiency is the mean of team efficiencies, not PF/MaxPF of the displayed pooled
  PF & Max PF columns (98/101 weeks differ). Internally consistent, but the two
  displayed columns don't reproduce the shown Efficiency — a human may want the
  tooltip clarified.
- **`%` unit split** (Agent 3): some similarly-named "%"/"win %" columns are on a
  0-1 scale and others on 0-100 — cosmetic, but worth normalizing/labeling.
- **transactions O-Score populated offline** while picks/trades O-Score empty
  (Agent 1 C-2): the blanket "all O-Score empty offline" characterization is
  imprecise — pure-drop transactions carry a real O-Score offline. Not a defect.

### By-design / documented (per-agent docs have full detail)

Inseason-trades vs Σ team_week (different counting method); player_year additive
counters ≥ Σ player_week (offseason events have no week row); league Total-trades
parity (3-team trades + per-grain dedup); starter boom%/volatility N/A when the
lone start scored 0; future-pick skeletons; zero-event startup cornerstones +
initial-roster vets; 188 tx-only pad rows (all with ≥1 real event, 0 phantom);
`Commissioner moved?` uniformly False (overlay injects legs as real trades);
retired-rostered legends; "In Progress" active-streak sentinel; 2020 = 16 weeks.

## Per-part findings documents

- `plan/AUDIT_ROUND13_9PART_PARTS123.md`
- `plan/AUDIT_ROUND13_9PART_PARTS456.md`
- `plan/AUDIT_ROUND13_9PART_PARTS789.md`
