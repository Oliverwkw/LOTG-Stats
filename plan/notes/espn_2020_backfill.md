# Phase 13 — ESPN 2020 backfill: source notes

The league spent its **first season (2020) on ESPN** before moving to Sleeper (2021+).
Goal: integrate the full 2020 season into the dataset, filling every column to the
maximum extent possible. Prefer pulling **from the ESPN source API**, not the emails.

## League identity
- ESPN **leagueId 34086** ("The League"), season **2020**.
- Read API: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2020/segments/0/leagues/34086`
  with views `mDraftDetail, mMatchup, mRoster, mTeam, mTransactions2, mSettings`.
  Private league → needs `espn_s2` + `SWID` cookies (commissioner has access; the
  owner okeimweiss does not). Public toggle by the commissioner removes the cookie need.

## 2020 rules (confirmed by user)
- **8 teams** (same managers as now; team names differ from both Sleeper and the
  mid-2020 renamed names in the trade emails).
- **16-round snake startup draft**, **superflex**.
- **Smaller rosters** than Sleeper era; **16-week season**; **playoffs in weeks 15–16**
  (vs 16–17 now) — bracket worked the same.
- **No FAAB** in 2020 → FAAB columns N/A for 2020.
- **Picks ARE tradeable, but only OFF-platform** (ESPN couldn't trade picks on-platform),
  so 2020 pick trades must be reconstructed from emails + human memory (step 6). The one
  on-platform "pick trade" email is the startup-draft slot swap.
- KTC has no pre-Aug-2021 history → 2020 KTC columns stay N/A (same as current pre-2021).

## STATUS: real 2020 dump captured (2026-06-15)
Pulled the full season for **leagueId 34086 / 2020** with the commissioner's cookies
(SWID `{9A624356-…}` = `MRTDahBoss` = AceMatthew, the commish). Raw JSON banked at
**`data/espn_2020_raw/`** (37 MB, uncommitted): combined + 9 per-view files + 18 week
files + `transactions_all.json` + `player_universe.json`. Re-scrape not needed — this is
the one-time pull.

**Transaction gotcha (fixed in the script):** season-level `mTransactions2` returns only a
~6-row recent slice. The FULL log comes from `mTransactions2` pulled **per scoringPeriod**
(weeks 1–17), deduped by id → **688 transactions**: DRAFT 152, FREEAGENT 151, WAIVER 60,
TRADE_ACCEPT 19, TRADE_UPHOLD 14, TRADE_PROPOSAL 91, TRADE_DECLINE 80, TRADE_VETO 11,
ROSTER 28, FUTURE_ROSTER 82. The `/communication/` activity feed 404s for this season — don't
use it.

**Draft:** 152 picks = **19 rounds × 8 teams**, snake (R1 1→8, R2 8→1). Lineup/scoring per
week live in the matchup where `matchupPeriodId == week` → `home/away.rosterForCurrentScoringPeriod`
(lineupSlotId = starter/bench) + `pointsByScoringPeriod` (team weekly PF).

## Loader (src/espn_2020.py) + completeness verdict (2026-06-15)
`src/espn_2020.py` parses the dump into normalized draft / weekly-lineups / transactions,
joining ESPN playerId → identity via DynastyProcess `espn_id` (8,129 mapped). Self-test:
- **Draft**: 152 picks (19 rds), 152/152 players resolved, R1.01 Oliverwkw→McCaffrey. ✓
- **Weekly**: all 18 scoring periods, 8 team-weeks each, **0 missing PF, 0 unresolved players**. ✓
- **Adds/drops**: 361 moves across all 8 managers, 361/361 resolved — **public, complete**. ✓
- **Waiver bids**: every waiver `bidAmount=0` → no FAAB in 2020 → "Number of bids" **N/A**. ✓

### ⚠️ Trade player-legs are PRIVATE to participants (key finding)
A trade's player swap lives only on the `TRADE_PROPOSAL` (UPHOLD/ACCEPT/VETO carry
`items:null`, linked by `relatedTransactionId`). Proposals are visible only to the two
teams involved, so with **AceMatthew's cookies** we get full legs for his ~7 trades but the
~5 non-Ace executed trades (JJ, Diggs 3-for-3, Mike/Corey Davis, etc.) come back with EMPTY
legs. League-wide we DO see which trades executed (14 UPHOLD → 12 unique) and their dates.
**Resolution:** take executed-trade legs from the **trade emails** (full legs + teams +
dates for 34086, authoritative) and use the ESPN **UPHOLD** outcome to confirm execution
(exclude the vetoed Fitz/Cook trade) — i.e. "only track tradeuphold". (Alternatively, pull
with each manager's cookies, but the emails are in hand and complete.)

## Trade layer (off the emails) + no-teleport validation (2026-06-15)
`parse_email_trades()` reads the saved ESPN trade emails (leagueId 34086 only, vetoed
excluded), and resolves each emailed player to the exact ESPN playerId by ROSTER MOVEMENT
(the player who actually changed hands that week) — robust to suffixes (II/V/Jr), the
Robby Anderson→Robbie Chosen rename (`_NAME_ALIAS`), and same-name collisions (two David
Johnsons). Banked to `data/espn_2020_raw/email_trades.json` (13 executed trades, 37 legs).

**No-teleport validation (the real chain-completeness test):** every week-to-week roster
ownership change must be explained by draft / add / drop / trade. Result: **38 unexplained
"teleports" without trades → 1 with the email trade layer.** The lone remainder is Taysom
Hill (shmuel added off waivers AND traded to Oliverwkw inside wk11 → no prior roster week
to read "from"); closed by side-aware email parsing (tag player→email side→owner). So with
the email trades, player history chains are complete (no teleports).

### ⚠️ "Number of bids" (competing waiver claims) — NOT recoverable from one manager
Correction: "Number of bids" = how many MANAGERS claimed a player on waivers (not FAAB).
Waiver claims are private per-manager; with AceMatthew's cookies we see only his own
pending/failed claims + the winning EXECUTED add — not other managers' losing claims. So the
competing-claim count needs ALL 8 managers' cookies pooled, else it's N/A for 2020. DECISION
PENDING (chase 8 cookie sets vs accept N/A).

## VERIFIED teamId → owner → current manager (the parser's join key)
Confirmed by matching the user's draft-day mapping against the real R1 draft order + owner
display names (6/8 corroborate directly by name; MRT→Ace and 5A3K→shmuel by draft-order):
| teamId | 2020 team name (end of season) | owner SWID | displayName | Manager |
|---|---|---|---|---|
| 1 | Drake and Moss | {7E9AF97E-…} | Stevenz6m7tw_ | stevenb123 |
| 2 | Alvin and The Charkmonks | {BD8F55D8-…} | 5A3K | shmuel256 |
| 3 | Green Bay Packers | {EF20D8DB-…} | ljwheat3 | LWebs53 |
| 4 | Assault and  BatTarik | {E29A0AAE-…} | Ben64 | BROsenzweig |
| 5 | Calvin And Lobbs | {B7E2A2A0-…} | Oliver1761 | Oliverwkw |
| 6 | A Gentle Brees | {01AC4242-…} | airjac2828633 | JacobRosenzweig |
| 7 | The Hospital | {9A624356-…} | MRTDahBoss | AceMatthew |
| 8 | BROWN on ODELL | {62AE8037-…} | plehvo8922911 | plehv79 |
(Map by **teamId/owner**, never team name — names were changed repeatedly mid-2020.)

## Draft-day team → current manager mapping (2020 startup, user-provided)
| 2020 ESPN team (draft day) | Current manager |
|---|---|
| Super Mario Dynasty | Oliverwkw |
| U cant handle The Drewth | LWebs53 |
| On the Mark | JacobRosenzweig |
| NY Drafters | AceMatthew |
| New York Giants | stevenb123 |
| Joe Bowden and Kamara Harris | plehv79 |
| Bashar Hafez al-Rashaad | BROsenzweig |
| Ifeadi Odenigbo | shmuel256 |

(Managers also RENAMED teams mid-2020; the trade emails use those later names, e.g.
SHMU=shmuel256, BO=BROsenzweig, DAM=?, LJW=LWebs53, MRT=?. Reconcile via owner identity
in the ESPN API, not team name.)

## R1 startup draft order (snake), from the draft-results email (2020-09-10)
1 Super Mario Dynasty — Christian McCaffrey · 2 U cant handle The Drewth — Saquon Barkley ·
3 On the Mark — Ezekiel Elliott · 4 NY Drafters — Dalvin Cook · 5 New York Giants — Lamar
Jackson · 6 Joe Bowden and Kamara Harris — Patrick Mahomes · 7 Bashar Hafez al-Rashaad —
Michael Thomas · 8 Ifeadi Odenigbo — Clyde Edwards-Helaire (then snake back R2).

## Emails on hand (fallback / cross-check, leagueId 34086 only)
~13 trade emails for 34086 (incl. 1 startup-draft slot swap, 1 VETOED trade to exclude).
The other emails are different ESPN leagues (UChicago '24 = 57687541, UChi Fantasy =
54022297) and must be ignored.
