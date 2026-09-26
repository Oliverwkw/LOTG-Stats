# Round 14 — #446 pre/post-merge audit, then the full 9-part battery (2026-09-26)

Run mid-week 3 of 2026 (weeks 1-2 final; the build writes a week only once it is
final, so the in-progress week never reaches the exports).

## 1. PR #446 — 3-part audit, before and after merge

| Run | What | Role |
|---|---|---|
| 561 | #446 branch | round 1 |
| 562 | main's exact commit, same time (`audit-base-446`) | baseline, so live mid-week drift cancels |
| 563 | #446 + the digest snapshot migration (c0401c9) | round 2 |
| 564 | main after merging #447 + #446 | post-merge; committed exports (0399ff5) |

- **Code:**
  - Clean build logs; `position baseline 2026: … using 2025's` logged.
  - pytest 478 passed / 2 expected skips on 561 and 564.
  - 562 and 563 show one failure, a new live Sleeper status pair `('Doubtful', 'Inactive')`, fixed by #447.
- **Results:** 80 independent recomputes from player_week / team_week, not using the PR's test helpers. All correct:
  - the PPG grid and every position-adjusted twin, with 2026 on 2025's factor;
  - the playoff split, where regular season + playoff + 3rd Place/toilet starts = `Weeks as starter`;
  - team playoff points and the clutch index;
  - the renamed labels;
  - the player_additions grid and the add_drops twins.

  The two "failures" were errors in the check itself: a ratio of near-zero numbers, and the documented 0-fill of the points-added family.
- **Diff vs 562:** every change traces to #446; `audit_weekly` reports ✅ CLEAN. Three items were not in the PR's expected-diff list:
  - 5 add_drops differences blanked, not 3. The extra two are 2026-season moves the offline build could not see.
  - 2026 week 2 cuff counts: +1 for Oliverwkw and shmuel256. The handcuff TE-equivalent threshold now uses 2025's factor.
  - Adjusted values on older trades that involve 2026 rookies / 2026 weeks.
- **Fix added (c0401c9):** the digest reads the renamed count columns' prior under their new names (`digest.migrate_snapshot_columns`). Without it, Tuesday's digest would find no prior for 53 board slots + 12 team_all_time columns, and be blind to those boards for a week.
- **Post-merge:** run 564 is cell-identical to 563.

## 2. Full 9-part battery (on run 563 = #446's code; fixes verified on run 565)

| Part | Scope | Result |
|---|---|---|
| 1 | Cross-sheet reconciliation: every column shared by two grains classified sum / mean / max / min / last, and every partial chased | **3 defects** (below) + 1 doc defect |
| 2 | Stat-family hand-checks (Efficiency, Margin, PA = opponent PF, Win?, win %, all-play, Win Variance Σ = 0, league margins, positional points, % of points) | CLEAN. 12 PF ≠ Σ starters rows = the Semifinal +5 home bonus (by design). |
| 3 | N/A vs 0, both directions (FAAB era, waiver/FA Faab, 2020 bids, drop / tenure gates, never-started, 1-start volatility, playoff split) | CLEAN. 1 needs-judgment: 2020 `Offseason trades` now counts the startup slot swap (#404) that #321 had made N/A. |
| 4 | Edge cases (ties, name collisions, two rosters in one week, short lineups, 2026 in progress) | CLEAN |
| 5 | Identical / redundant columns (all sheets, incl. #446's 64 new ones) | CLEAN. The degenerate "Most number of QBs / TE started from same NFL team" (always 1) is by design. |
| 6 | Data-quality gaps (all-blank, constant, junk tokens, literal N/A) | CLEAN. `Commissioner moved?` all False is by design. |
| 7 | Metric accuracy / odd results (position factors by season, playoff-split extremes, team playoff points vs record) | **1 defect**: digest KTC attribution (below). Factors are stable 2020-2025 (QB 0.80-0.84, TE 1.20-1.37). |
| 8 | Asset-story tracking | CLEAN. 712 players, 0 continuity breaks; chain / coverage guards pass. |
| 9 | Cell-by-cell type / range sweep | CLEAN. Negative points (turnovers) and a 48-year-old (Brady) are real. |

### Defects found and fixed (PR: audit-9part-fixes-0926)

1. **player_week `Number of Add/Drops` / `Number of drops`.** These came from raw Sleeper transactions on Sleeper's own week:
   - Commissioner-washed waiver runs were counted three times (Jerome Ford 2023 wk1: 3 vs 1 on player_year).
   - 319 / 196 player-weeks sat off the documented Tuesday-Monday week.

   They are now rebuilt from the final add_drops rows on team_week's clock.
2. **Trade week on the UTC date.** A Monday-night ET trade landed a week late:
   - league_week `Number of trades` (6 weeks) and its `Total transactions`;
   - player_week `Number of trades` (14 player-weeks).

   `_trade_is_offseason` and the manual-row week now use the league day too; no row moved on those two.
3. **Digest attribution.** "KTC at pickup", "KTC change by end of season" and the "… at deal time" columns were read as live KTC. #445's re-dated 2021 Henry Ruggs trade therefore led the league email's lede as news. They are dated checkpoints now, and both lines move to "Changes from edits".
4. **Formulas docs:**
   - Commissioner adds are counted as free agency adds; the notes said "excluded".
   - Offseason trades' kickoff was stated as "Sept 7" instead of per season.
5. **Health email.** The week being played was reported as "unfinalized (Tuesday capture never landed)" on any mid-week run. `injury_capture_health` now judges finished weeks only.

**Verification (run 565):** the data diff vs 564 is exactly items 1-2 (319 / 196 / 14 player-weeks, 6 league weeks) plus the Formulas text. Nothing else moved. The new guards in `tests/test_add_drop_breakdown.py` fail on run 563's exports and pass on 565's, both under pandas 3 string inference (CI) and pandas 2.

### Needs human judgment (not changed)

- 2020 `Offseason trades` = 1 for AceMatthew / LWebs53 (the draft-day slot swap).
- **Digest lead item:** a 2020 add's `Player addition value` still reads as "new" because the team transacted this week. This follows the documented "if new data could also explain it, it goes on top" rule.
- The 12 Semifinal-bonus rows make the positional `% of points from …` columns sum to < 100%.
- The MASTER_TODO item for the bench-health columns' post-merge 3-part audit (line ~704) is still unticked. Their guard, `test_bench_health_columns`, passes on every run above.

## 3. Emails

- **League digest (561 → 565):**
  - Records (gold) / Leaderboard changes (navy) / edits render in that order.
  - The HTML is well-formed, with no nan / None / N/A / "2023.0".
  - Re-rendered locally in pandas-3 mode, it is byte-identical to CI's.
  - `send_digest --skip-empty` stops before SMTP without credentials.
- **Health email:** for committed main vs a same-code rebuild it renders "✅ all clear" once fix 5 is in.
