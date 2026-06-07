# PR E — In-season freshness audit

**Goal:** confirm the update timeline of every upstream data source, and list which
output columns go **stale or incorrect mid-season** (when the build runs during an
active NFL season rather than after it ends) plus the fix for each.

This is a **report only** — no output columns change in this PR. The fixes are
scoped as follow-up PRs (priority order at the bottom).

---

## 1. Upstream source update timelines

| Source | What it feeds | Update cadence in-season | Cached? |
|---|---|---|---|
| **Sleeper API** — `rosters`, `transactions/{wk}`, `matchups/{wk}` | team_week scores, rosters, all transactions/trades, who-started | **Live.** Matchup `points` populate *during* games (Sun→Mon) and finalize after MNF. Rosters/transactions update the moment a move is made. | No (mutable each week — never cached) |
| **Sleeper API** — `drafts`, `players/nfl` | draft picks, player metadata | drafts immutable after the draft; `players/nfl` mutable | drafts cached; `players/nfl` not |
| **nflverse** `stats_player_week_{season}` | played-detection, Hardship baseline, team-by-week NFL mapping | **~Tue–Wed AM ET** after a week's MNF (full-week release, not live) | yes (`.cache`) |
| **nflverse** `weekly_rosters_{season}` | NFL team per player per week | weekly, similar lag | yes |
| **nflverse** `injuries_{season}` | injury overlay | rolling through the week (Wed practice → game-day inactives) | yes |
| **nflverse** `players.csv` / `player_ids` | birth_date, rookie_season, position | infrequent (metadata) | yes |
| **DynastyProcess** `db_playerids`, `values-players`, `values-picks` | sleeper_id↔gsis_id mapping; *legacy* values fallback | infrequent | yes |
| **KTC via dynasty-daddy** `/player/all/today` (directory) | today's KTC snapshot | **6h** freshness on disk (effectively daily) | yes (6h TTL) |
| **KTC via dynasty-daddy** per-player history | all dated KTC checkpoints | immutable past | yes (indefinite) |

**Key takeaway:** Sleeper is *live* but nflverse lags ~2–3 days. The two go out of
sync for the most recent week between game day and the nflverse release. That gap
is the source of most in-season correctness issues below.

---

## 2. Columns that go stale / incorrect in-season

Grouped by root cause. "Affected" = columns that are wrong or provisional **only for
the current, not-yet-complete season** (historical seasons are always correct).

### A. The latest week is finalized too early  ⚠️ HIGHEST IMPACT
`last_completed_week()` (src/lotg.py ~1958) counts a week as complete as soon as
**any** team has `points > 0`. So from kickoff Sunday through the nflverse release
(~Wed), the in-progress week is treated as final even though (a) games are still
being played (partial Sleeper points) and (b) nflverse hasn't published it yet.

- **Affected (latest week only, until it settles):**
  - player_week: `Points`, `Starter/Bench` scoring, `Injury?` (see B), `Number of donuts`/`…under 10`, **every weekly award** (`Player of the week?`, `Captain?`, position-of-week, `Highest/Lowest starter on team?`) and **every weekly streak** (terminal values jump around).
  - team_week: `PF`, `Max PF`, `Efficiency`, `Win?`, `Margin`, all award flags (`Highest score?`, `One-man army?`, `Most bench points?`, `Most injured?`, …), all team streaks, `Starter-adjusted Hardship`, `Luck`, `Loss from hardship?`.
  - Everything downstream that sums the latest week (team_year/all, player_year/all, league sheets, manager skill, O-Score on current-season events).
- **Fix:** gate the trailing week. Only finalize a week once it is genuinely done —
  require all matchups to have nonzero points on **both** sides **and** that week to
  be present in `nflverse stats_player_week`. Until then, drop that week from the
  outputs (treat as not-yet-played). Implement as a guard in/around
  `last_completed_week` (an `nflverse_has_week(season, wk)` check).

### B. False injuries from the nflverse lag
The injury gap-fill (src/lotg.py ~2300 & ~2385) marks a rostered player
`Injury? = True` for weeks they're missing from `played_players_by_week` (nflverse)
between their first and last played week. If a recent week is *included* (Sleeper
says it's done) but nflverse hasn't published it, players who actually played look
injured.

- **Partly mitigated already:** the fill is bounded to `season_max_week` (the last
  week nflverse actually has) and only fires for players with ≥1 active game, and
  never overwrites an existing key. So a **fully** missing latest week creates no
  false injuries. Residual risk = a week nflverse published only **partially**.
- **Affected (if it fires):** `Injury?`, `Weeks missed due to injury`, `Hardship`,
  `Starter-adjusted Hardship`, `Losses from hardship` / `Loss from hardship?`,
  `Luck`, `Number of starter injuries`, `Most injured?` + streak.
- **Fix:** same trailing-week gate as (A) makes this moot. Defensively, cap the
  gap-fill upper bound at the last week with *complete* nflverse coverage.

### C. Standings, playoffs & finish are provisional mid-season
`playoff_teams_by_season`, `champion_by_season`, `last_place_by_season`,
`standings_place_by_season`, `season_finish`/`Result` (src/lotg.py ~10437+) are
computed from the regular-season games **played so far**. Mid-season the "top 4"
are the current leaders, not the eventual playoff teams, and `champion` falls back
to `standings[0]` — i.e. the **current leader gets mislabeled "Champion."**

- **Affected (current season):** `Record/Win % vs playoff teams`,
  `… vs non-playoff teams`, `… vs champion`, `… vs last place`, `Result`/finish,
  `Week of playoff elimination`, `Tanking`, and the season-grain
  `Playoff appearance streak` / `Winning season streak` (their current-season cell).
  Standings-leader streak is fine (it's defined week-by-week on cumulative standings).
- **Fix:** treat playoff seeding / champion / last-place / Result as **N/A for the
  in-progress season** (gate on "season has reached its championship week"). Prior
  seasons unaffected. This stops the mid-season leader being labeled champion and
  keeps the "vs champion / vs playoff teams" buckets from using a provisional set.

### D. O-Score (and manager skill) are provisional for current-season events
O-Score averages percentiles of partial-season stats (`Avg points added`, career
PPG, most-recent KTC) for current-season picks/transactions/trades, so they drift
as the season plays out.

- **Affected (current-season rows only):** `O-Score` on picks/transactions/trades;
  `Drafting skill` / `Trading skill` / `Transaction skill` (team_year/all) which
  aggregate O-Score.
- **Fix:** acceptable as "provisional," but ideally exclude current-season events
  from manager-skill (and/or label current-season O-Score) until the season ends.
  Low risk, medium value.

### E. KTC freshness — mostly fine, one minor lag
- Future checkpoints are correctly `N/A` (guarded `if tgt > today: continue`). ✓
- KTC directory is 6h-fresh, so "today's" values are current. ✓
- **Minor:** for a current-season pick, the **most-recent KTC** used by O-Score is
  the latest *checkpoint* ≤ today (e.g. the Aug-28 draft-day value), so it can be a
  few weeks/months stale versus today's live value. Affected: `O-Score` KTC
  component on recent picks. **Fix (optional):** add a "current KTC" point or use
  today's snapshot for the most-recent-KTC component. Low priority.

### F. "To-date" tenure windows — correct by design (not a bug)
`Length of tenure on team`, `Avg PPG on team`, `Points added`, and the trades
sent/received PPG windows use **today** as the open end for still-rostered assets
(src/lotg.py ~5993, ~7122, ~7583). These are correct "as-of-today" values that
simply grow during the season. **No fix** — document that they're live.

### G. Age — correct
Per-week `Age` is anchored to the week's date (`approx_date = Sep 1 + 7·(wk−1)`),
and per-season ages to mid-season. Historically correct. **No fix.**

---

## 3. Recommended follow-up order

1. **Fix A — trailing-week gate** (`nflverse_has_week` + both-sides-final check).
   Single highest-leverage fix; also resolves B. *(new PR)*
2. **Fix C — provisional-season gate** for champion/playoff/last-place/Result so the
   in-progress season stops emitting misleading "final" values. *(new PR)*
3. **Fix D — exclude current-season events from manager skill** (or flag provisional
   O-Score). *(small PR)*
4. **Fix E — current-KTC component** for recent-pick O-Score. *(optional, low priority)*

Items F and G need no change.
