"""Formulas sheet — documents every non-trivial computed stat in the dataset.

This sheet is read-only documentation. It's static (not derived from
the league's data), so the build just emits the table verbatim.

Add new rows here whenever you ship a stat whose formula isn't
obvious from the column name. Aim to be inclusive — when in doubt,
add it. Each entry has:
  Stat:    The exact column name as it appears in its sheet.
  Sheet:   Which sheet the stat lives on (transactions, trades,
           team_week, player_week, etc.).
  Formula: Plain-English or pseudo-code definition of the calculation.
  Notes:   Edge cases, data sources, semantic gotchas.
"""
import pandas as pd

FILE_NAME = "formulas.csv"
PLAN_KEY = "Formulas"
FRAME_KEY = "formulas"


_ROWS = [
    # -------------------------------- transactions.csv --------------------------------
    {
        "Stat": "Faab",
        "Sheet": "transactions",
        "Formula": "Sleeper's `settings.waiver_bid` for the winning waiver claim. 0 for free-agent / commissioner adds.",
        "Notes": "Only populated for type=waiver rows. Free-agent adds don't go through FAAB.",
    },
    {
        "Stat": "Total FAAB bid",
        "Sheet": "transactions",
        "Formula": "Sum of `waiver_bid` across every claim (winning + losing) for this player in this week's waiver run.",
        "Notes": "Captures total FAAB the league burned on the player. The winning bid is the top of this stack.",
    },
    {
        "Stat": "FAAB difference over second place",
        "Sheet": "transactions",
        "Formula": "winning_bid − max(other valid bids ≤ winning_bid).",
        "Notes": "Bids strictly greater than the winning bid are excluded — they were invalidated (roster full, insufficient FAAB) and don't represent real competition. N/A for uncontested waivers.",
    },
    {
        "Stat": "FAAB premium %",
        "Sheet": "transactions",
        "Formula": "(winning_bid − runner_up) / winning_bid × 100.",
        "Notes": "How much of the winning bid was a premium over the runner-up, normalized by bid size so it's comparable across big and small auctions (a $50-over-$40 win = the same 20% as $5-over-$4). Bounded 0–100; 100 vs a $0 runner-up. Blank only when there was no valid runner-up. Replaces the old 'FAAB % difference over second place' (which divided by the runner-up and blew up / was undefined for small or $0 runner-ups).",
    },
    {
        "Stat": "Number of bids",
        "Sheet": "transactions",
        "Formula": "Count of every waiver attempt (complete + failed) on this player in this week's waiver run.",
        "Notes": "Includes losing bids — describes interest, not auction wins.",
    },
    {
        "Stat": "Average PPG on team",
        "Sheet": "transactions",
        "Formula": "Forward-looking. Mean fantasy points for the added player over the NFL games that fall between this pickup's Date and Date dropped/traded (open-ended if the player is still rostered). Uses nflverse fantasy_points_ppr; falls back to pw when nflverse has no record.",
        "Notes": "Captures what the added player actually delivered while on THIS team. Includes all NFL weeks in the tenure window, whether the player was started or benched.",
    },
    {
        "Stat": "Average PPG of dropped player over same time",
        "Sheet": "transactions",
        "Formula": "Mean fantasy points for the dropped player over the SAME tenure window as Average PPG on team (pickup → next drop/trade of the added player). Sourced from nflverse so it covers the dropped player even after they left this team's roster.",
        "Notes": "Lets you compare 'what we got' vs 'what we'd have gotten by keeping him'. Blank when no dropped player or no NFL games in the window.",
    },
    {
        "Stat": "PPG of 5 games before pickup",
        "Sheet": "transactions",
        "Formula": "Mean fantasy points across the added player's 5 most-recent PLAYED NFL games BEFORE the pickup date. If fewer than 5 played games exist on record, averages whatever's available (2 games → mean of 2).",
        "Notes": "Trailing snapshot of the player's NFL form at the time of pickup. Used for cuff detection and as a backward-looking complement to 'Average PPG on team'. Sourced from nflverse so unrostered weeks count.",
    },
    {
        "Stat": "Difference of averages",
        "Sheet": "transactions",
        "Formula": "Average PPG on team − Average PPG of dropped player over same time. Both numbers use the forward-looking tenure window.",
        "Notes": "Positive = the pickup outperformed the dropped player over the time he was rostered. Treats a missing side as 0; this can over- or under-state when only one side resolves.",
    },
    {
        "Stat": "Difference of averages adjusted by position",
        "Sheet": "transactions",
        "Formula": "added_adj − dropped_adj, where adj = (forward-looking tenure PPG) × all_starter_avg / pos_avg[player_position]. all_starter_avg and pos_avg are league-wide all-time starter averages from player_week.",
        "Notes": "Normalises QB/RB/WR/TE scoring scales so a 12-PPG TE doesn't read the same as a 12-PPG QB. Uses forward-looking PPG (what the player did on this team), not pre-pickup snapshot.",
    },
    {
        "Stat": "Age difference",
        "Sheet": "transactions",
        "Formula": "added_player_age − dropped_player_age, in years (decimal), computed at the pickup date from each player's birth_date.",
        "Notes": "Negative when the team replaced an older player with a younger one (typical 'getting younger' move).",
    },
    {
        "Stat": "Cuff at time of pickup?",
        "Sheet": "transactions",
        "Formula": "True if, in any of the previous 3 weeks (the pickup week and the two before it), the picking team rostered another player who was a STARTER and: (1) plays the same NFL team, (2) plays the same NFL position, (3) averaged at least 10 PPG more than the added player over the last 5 played games.",
        "Notes": "Handcuff detection. Relaxed from the pickup week only to a 3-week starter window so a cuff added right after the starter goes down still registers.",
    },
    {
        "Stat": "Weeks between pickup and start",
        "Sheet": "transactions",
        "Formula": "Count of player_week rows for (Team, Player Added) with Starter/Bench != 'Starter' between the pickup date and the player's first start on this team.",
        "Notes": "Bounded above by Date dropped/traded — if the player was let go before ever starting, this column is blank.",
    },
    {
        "Stat": "Number of starts before next drop",
        "Sheet": "transactions",
        "Formula": "Count of player_week rows for (Team, Player Added) with Starter/Bench == 'Starter' between Date and Date dropped/traded.",
        "Notes": "If the player was never dropped, counts all starts through end of dataset.",
    },
    {
        "Stat": "% of starts made while rostered",
        "Sheet": "transactions",
        "Formula": "(Number of starts before next drop) / (weeks rostered between Date and Date dropped/traded).",
        "Notes": "Includes bye and injury weeks in the denominator — measures gross start rate.",
    },
    {
        "Stat": "Injury adjusted % of starts made while rostered",
        "Sheet": "transactions",
        "Formula": "Like '% of starts made while rostered' but exclude weeks where Bye? or Injury? is True from BOTH numerator and denominator.",
        "Notes": "Measures start rate when the player was actually available.",
    },
    {
        "Stat": "Player addition value",
        "Sheet": "transactions",
        "Formula": "adjusted_diff × (1 + pct_starts) × (1 + pct_starts_injury_adjusted) + CUFF_BONUS. adjusted_diff is 'Difference of averages adjusted by position'. pct_starts is '% of starts made while rostered'. pct_starts_injury_adjusted is the injury-adjusted variant. CUFF_BONUS = 5 PPG when 'Cuff at time of pickup?' = True, else 0.",
        "Notes": "Composite metric blending pure PPG difference with playing-time leverage and handcuff insurance. Tune CUFF_BONUS by editing the constant in src/lotg.py.",
    },
    {
        "Stat": "KTC value of player added at deal time",
        "Sheet": "transactions",
        "Formula": "Player's KTC sf_trade_value on the pickup date (superflex format, matching league setup).",
        "Notes": "Sourced from dynasty-daddy.com's KTC scrape — values match keeptradecut.com exactly. History back to April 2021.",
    },
    {
        "Stat": "KTC value of player added/dropped at end of season / 1 year later / 2 years later",
        "Sheet": "transactions",
        "Formula": "Same lookup, at the Monday after the fantasy championship game of Season, Season+1, and Season+2 respectively (championship Monday = the day after NFL week-17 Sunday). Future-dated references stay N/A.",
        "Notes": "Captures whether the pickup held value (or the drop turned out to be a mistake).",
    },
    {
        "Stat": "Net KTC value at deal time / end of season / 1 year later / 2 years later",
        "Sheet": "transactions",
        "Formula": "(KTC of added player) − (KTC of dropped player), at each reference point. Missing side treated as 0.",
        "Notes": "Positive = team got more KTC value than they gave up.",
    },
    {
        "Stat": "Date dropped/traded",
        "Sheet": "transactions",
        "Formula": "First subsequent date this team dropped or traded the added player. Pulled from the event log of all team×player movements.",
        "Notes": "Blank if the player is still rostered (or wasn't an add row).",
    },
    {
        "Stat": "Link to next/previous transaction (added player) / (dropped player)",
        "Sheet": "transactions",
        "Formula": "Follows the ADDED player and the DROPPED player to their next/previous event ANYWHERE in the league — across teams and INCLUDING trades. Reference is a row pointer: '#N' = transactions.csv row N, 'T#N' = trades.csv row N (1-indexed, final sorted order).",
        "Notes": "Replaces the old single per-team 'Link to next/previous transaction'. The chain is date-ordered, so row numbers can look non-monotonic (the CSVs are grouped by team, not global date). Blank at the ends of a player's chain or when the row has no added/dropped player. (Trades.csv keeps its own per-team link chain.)",
    },
    {
        "Stat": "Number of times picked up by this team",
        "Sheet": "transactions",
        "Formula": "Running 1-indexed counter of acquisitions of (Team, Player) in chronological order — INCLUDING trades (a player received in a trade counts as a pickup), interleaved with waiver/FA adds by date.",
        "Notes": "If a team picks up the same player twice (by any mix of add or trade-in), the second reads 2.",
    },
    {
        "Stat": "Number of times dropped by this team",
        "Sheet": "transactions",
        "Formula": "Running 1-indexed counter of departures of (Team, Player Dropped) in chronological order — INCLUDING trades away (a player traded out counts as a drop).",
        "Notes": "Mirror of 'Number of times picked up by this team'. N/A on a transaction row that didn't drop anyone (a pure pickup).",
    },
    {
        "Stat": "Tanking",
        "Sheet": "transactions / trades",
        "Formula": "Marginal CHANGE in the team's Tanking score caused by THIS move, holding everything else constant: (1/6)*Δt3_age + (1/9)*Δfuture_cap. PF/MaxPF terms are unaffected by a roster move so they drop out. Δt3_age = -(avg_age_post - avg_age_pre)/(L_AvgAge - 21), where avg_age is 'Team age including picks' (entities = rostered players + future picks); avg_age_pre = A (the team's roster age that week, from team_week), N = that week's entity count, and avg_age_post = (N*A - Σsent_age + Σrecv_age)/(N - k_sent + k_recv). For transactions the assets are the added/dropped players; for trades they are the players AND picks received/sent (picks use expected future-rookie age). Δfuture_cap = round-weighted future picks received - sent ({R1:0.25, R2:0.09, R3:0.03, R4:0.01}, only picks 1-3 seasons out); waiver/FA transactions move no picks so this is 0. Week-of-move derived from Date (Sept 7 = wk1, capped 1..17), with adjacent-week fallback for A/N.",
        "Notes": "Pre/post-transaction tanking delta (replaces the old per-week team-level lookup). Positive = the move made the team younger and/or richer in picks (more tanking); negative = dealt picks/youth for win-now talent. Current-year rookie picks aren't tradeable mid-season, so the t4 (this-year pick) term is ~0 and omitted.",
    },
    # -------------------------------- trades.csv --------------------------------
    {
        "Stat": "KTC value difference at deal time / end of season / 1 year later / 2 years later",
        "Sheet": "trades",
        "Formula": "Σ(KTC of received assets) − Σ(KTC of dropped assets) at each reference date. Same date scheme as transactions.",
        "Notes": "Includes both players (sleeper_id → dynasty-daddy slug) and picks. Picks resolve to dynasty-daddy generic round labels ('2024 Early 1st', 'Mid 1st', 'Late 1st') and average for '??'-slot picks.",
    },
    {
        "Stat": "Pick value received",
        "Sheet": "trades",
        "Formula": "Σ(KTC value of just the pick assets received) at deal time. Players excluded.",
        "Notes": "Highlights pick-heavy trades. Blank when the trade had no picks on the received side.",
    },
    {
        "Stat": "Change in pick value at draft time",
        "Sheet": "trades",
        "Formula": "For each '??'-slot pick received: (KTC at Sept 1 of pick's draft year — the post-draft snapshot once the pick resolved into a rookie) − (KTC at deal time). Sum across picks.",
        "Notes": "Captures whether the team did better or worse than the at-trade generic estimate once the slot was actually drawn. Picks whose drafts are still in the future don't contribute.",
    },
    {
        "Stat": "Assets retained now",
        "Sheet": "trades",
        "Formula": "Of the assets this team received in this trade, those they currently hold (no subsequent trade-out AND no subsequent free-agent drop). Pick labels display as 'YYYY R.SLOT(F. Last)' for drafted picks, generic for not-yet-drafted.",
        "Notes": "V2 of the chain — drops to FA are now broken out into their own column.",
    },
    {
        "Stat": "Assets traded away",
        "Sheet": "trades",
        "Formula": "Of the assets this team received in this trade, those whose first subsequent exit event was a TRADE (not a drop to FA).",
        "Notes": "Determined by whichever exit event came first: trade vs FA drop. Earliest event wins.",
    },
    {
        "Stat": "Assets dropped to FA",
        "Sheet": "trades",
        "Formula": "Of the assets this team received in this trade, those whose first subsequent exit event was a DROP to free agency (via transactions.csv, not a trade). Picks excluded (picks can't be dropped to FA).",
        "Notes": "Joined off the transactions drop log: any 'Player Dropped' entry from this team after the trade date. New in V2 of the chain.",
    },
    {
        "Stat": "Return from trades",
        "Sheet": "trades",
        "Formula": "Aggregated received-side of the NEXT trade(s) where this team gave up any asset from this trade's received side.",
        "Notes": "'What this trade's haul turned into one hop later'. Pick labels resolve to specific slot + drafted player where available, e.g. '2024 1.05(B. Robinson)'.",
    },
    {
        "Stat": "Additional assets traded away in those deals",
        "Sheet": "trades",
        "Formula": "Other assets given up in those immediate-next trades alongside this trade's haul.",
        "Notes": "Quantifies the cost of converting the haul. Dedups across multiple downstream hops.",
    },
    {
        "Stat": "Return from trades of trades...of trades. Keep going until present day",
        "Sheet": "trades",
        "Formula": "Recursive walk: follow each received asset through every subsequent trade by this team, collecting received assets at each hop. Terminates when an asset has no further trade-out event.",
        "Notes": "Full chain. Picks display with their drafted player when known.",
    },
    {
        "Stat": "Asset difference in average age",
        "Sheet": "trades",
        "Formula": "mean(age of received assets at trade date) − mean(age of sent assets at trade date). Players use Sleeper's birth_date. Picks count as future rookies: synthetic birth_date = Sept 1 of (pick_year − 22), so a 2026 pick traded mid-2025 'expects' a ~21-year-old rookie. Earlier trades of further-out picks come out younger, which lines up with intuition.",
        "Notes": "Negative = team got younger. NFL rookies average ~22 at draft time; the Sept 1 anchor matches our late-August league rookie draft.",
    },
    {
        "Stat": "Team age including picks",
        "Sheet": "team_week / team_year / team_all_time / league_week / league_year / league_all_time",
        "Formula": "Per (team, year, week): mean over rostered player ages AND future picks held by this team at that week's date. Pick ages use _pick_expected_age — synthetic birth date Sept 1 of (pick_year − 22). Per-week pick ownership is tracked by walking pick_trade_events with their real trade dates. Commissioner-moved picks (in traded_picks but no matching trade event) are treated as 'always with the current owner'. team_year / team_all_time / league_* aggregations average team_week values.",
        "Notes": "Used in the tanking calculation in place of the rostered-only age average. A team accumulating future draft capital reads younger — which is the tank signal we want.",
    },
    {
        "Stat": "Avg PPG of received players on team",
        "Sheet": "trades",
        "Formula": "Per received player, their mean fantasy_points_ppr over NFL games from trade date through next drop/trade from this team. Aggregated as mean across received players.",
        "Notes": "Forward-looking — actual production while on this team. Sourced from nflverse.",
    },
    {
        "Stat": "Avg PPG of sent players over same time",
        "Sheet": "trades",
        "Formula": "Per sent player, mean fantasy_points_ppr over the COLLECTIVE tenure span of the received players (trade date through latest drop of any received player). Aggregated as mean across sent players.",
        "Notes": "Measures 'what we'd have gotten by keeping the sent players over the same span'.",
    },
    {
        "Stat": "Avg PPG of received players in 5 games before trade",
        "Sheet": "trades",
        "Formula": "Per received player, mean fantasy_points_ppr over their 5 most-recent NFL games before trade date. Aggregated as mean across received players. <5 games → average what's available.",
        "Notes": "Backward-looking snapshot of received players' form at trade time.",
    },
    {
        "Stat": "Trade addition value",
        "Sheet": "trades",
        "Formula": "Difference of averages adjusted by position. (V1 simplification — trades don't have a meaningful cuff bonus or playing-time leverage multiplier, so we keep it linear.)",
        "Notes": "Mirror of the 'Player addition value' metric on transactions but without the cuff / pct-starts adjustments.",
    },
    # -------------------------------- pick_history.csv --------------------------------
    {
        "Stat": "Original Team",
        "Sheet": "pick_history",
        "Formula": "The roster that ORIGINALLY owned this pick before any trades — i.e. the team in that draft-position slot per Sleeper's slot_to_roster_id mapping. For traded picks, this is the chain origin (the team whose own pick this is).",
        "Notes": "Distinct from 'Final Team'. ESPN-era picks (moved before Sleeper's tracking window) fall back to the slot owner; if that's also unavailable, the picker is used.",
    },
    {
        "Stat": "Final Team",
        "Sheet": "pick_history",
        "Formula": "The roster that actually MADE the selection (= last owner in the trade chain). Equals Original Team when the pick wasn't traded.",
        "Notes": "Pulled from Sleeper draft picks (roster_id field) and from the end of the reconstructed trade chain.",
    },
    {
        "Stat": "Number",
        "Sheet": "pick_history",
        "Formula": "Canonical pick notation: '{round}.{slot:02d}' (e.g. '1.05' = round 1, slot 5). Slot is derived from draft_slot or pick_in_round, with fallback to ((pick_no − 1) mod team_count) + 1. Shown as bare '{round}' when slot is unknown.",
        "Notes": "Same notation is used inside trades.csv to substitute already-made picks with the slot they became (e.g. '2024 1.05(B. Robinson)').",
    },
    {
        "Stat": "Commissioner moved?",
        "Sheet": "pick_history",
        "Formula": "True if this pick's ownership shift wasn't recorded as a normal trade transaction. Detected when traded_picks_by_season shows a pick belonging to a non-original owner but no trade event in pick_trade_events explains the move (typical for picks moved >3 years before draft year, beyond Sleeper's trade-tracking window).",
        "Notes": "Such picks are NOT added to trades.csv (the move wasn't a trade); the assumption is a single move from original owner to current owner.",
    },
    {
        "Stat": "Commissioner wash exclusion",
        "Sheet": "transactions / trades / all transaction & trade counts",
        "Formula": "A transaction is dropped entirely when every player it moves nets to zero on its own roster within the same calendar day AND a commissioner action was part of that player-day. I.e. a single-day commissioner correction that leaves the roster exactly as it started.",
        "Notes": "Covers: commissioner add+drop of a player; a player a team dropped that the commissioner re-added same day; an add the commissioner immediately undid; and a trade the commissioner reversed. These no-ops are excluded from every transaction/trade count and from the transactions.csv / trades.csv detail.",
    },
    # -------------------------------- player_week.csv --------------------------------
    {
        "Stat": "Activated Cuff?",
        "Sheet": "player_week",
        "Formula": "True if this player STARTED this week AND is a handcuff that week: their own last-5 avg is < 10, and a same-NFL-team/same-position teammate who averages ≥ 10 PPG more (over last 5 played games) is injured/suspended. The injured teammate does NOT need to have been a starter.",
        "Notes": "Item 10: an 'activated' cuff is one that BECOMES A STARTER. The broader 'rostered handcuff' condition (same logic without the start requirement) drives team_*.'Number of cuffs rostered'; this started version drives 'Number of cuffs started'. team_year/all_time + league_year/all_time count DISTINCT cuff players, not player-weeks.",
    },
    {
        "Stat": "Difference from best startable bench",
        "Sheet": "player_week",
        "Formula": "(Starter's points) − (highest-scoring eligible bench player who could have been started instead) in the same week.",
        "Notes": "Measures whether the lineup decision was correct. Negative = bench out-scored the starter (bad call).",
    },
    {
        "Stat": "Difference from worst benchable starter",
        "Sheet": "player_week",
        "Formula": "(Bench player's points) − (lowest-scoring starter that could have been benched).",
        "Notes": "Mirror metric for bench rows.",
    },
    # -------------------------------- team_week / team_year --------------------------------
    {
        "Stat": "Tanking",
        "Sheet": "team_week / team_year / team_all_time",
        "Formula": "Per-week: (1/6)*(1 - (AvgPF - 2/3*L_PF) / (L_PF/3)) + (1/6)*(1 - (AvgMaxPF - L_PF) / (L_MaxPF - L_PF)) + (1/6)*(1 - (AvgAge - 21) / (L_AvgAge - 21)) + (1/6)*pick_sum_this_year + (1/9)*future_draft_capital. AvgPF/MaxPF/Age are season-to-date expanding means through that week; L_* are league-wide season-to-date averages. team_year.Tanking = final week's expanding-mean value. team_all_time.Tanking = mean of per-season values.",
        "Notes": "Positive when the team is under-scoring vs league while accumulating draft capital. Per-week values aggregate by 'last week' (team_year) and 'mean of seasons' (team_all_time) — never summed, since each weekly value is already a season-to-date mean and summing would over-count.",
    },
    {
        "Stat": "Luck (team_all_time: 'Avg yearly luck')",
        "Sheet": "team_week / team_year (Luck); team_all_time (Avg yearly luck)",
        "Formula": "Weekly = (0.27*OUT + 0.14*Sisenzweig - 0.14*Brosenzweig) * postboost + (0.36*OPP + 0.10*OWN) * GATE - 0.36*ADV + 0.12*EFF + 0.16*CLOSE. OUT = Win(1/0.5/0) - pregame_p, where pregame_p = logistic(1.5 * mean of standardized full-season [MaxPF, PF, win%] differences vs opponent) — calibrated so winning to your talent nets ~0. OPP = z_week(-(opp PF - opponent's full-season avg PF)); OWN = z_week(PF - own full-season avg PF); ADV = z_week(Hardship + Starter-adjusted Hardship + 3*players on bye); EFF = z_week(Efficiency); CLOSE = sign(Margin)*max(0, 1-|Margin|/8); GATE = 1/(1+|Margin|/15); postboost = 1.8 in championship-bracket weeks (Final/Semifinal/3rd Place) else 1. z_week standardizes within each (year, week), clipped to +-2.5 then /2.5. team_year.Luck = the plain SUM of that season's weekly luck (no win% multiplier). team_all_time 'Avg yearly luck' = the MEAN of the per-season Luck totals (NOT the sum over all weeks).",
        "Notes": "Captures the luck in a result: OUT rewards winning relative to a pregame talent estimate (upsets = lucky); the closeness-GATEd OPP/OWN credit an opponent collapsing / your studs popping only when it swung a close game (a blowout isn't luck); ADV is heavily subtracted so heavy injuries/byes = very bad luck; Bros/Sis accent bad-beats/steals; CLOSE rewards nail-biter wins. Because pregame_p nets out winning, summing gives a season stat that tracks Win-Variance-style over/under-achievement (a juggernaut champion is only mildly lucky; a low-scoring overachiever is very lucky). All-time uses the AVERAGE of seasonal luck rather than a raw sum: weekly luck is ~zero-sum, but adversity is a persistent team trait, so summing every week ever lets a chronically healthy/injured team pile up unbounded luck that also grows with tenure — averaging keeps all-time on a single-season scale and fair across differing tenures. Full derivation + scorecard in plan/LUCK_REWORK.md.",
    },
    {
        "Stat": "Hardship",
        "Sheet": "team_week / team_year",
        "Formula": "Sum of opponent average max PF over the season for the team.",
        "Notes": "Higher = tougher schedule.",
    },
    {
        "Stat": "Win Variance",
        "Sheet": "team_year",
        "Formula": "-1 × (standings_place − (pf_place + maxpf_place) / 2).",
        "Notes": "Negative when a team finishes better than their PF / Max PF percentile would predict (over-performance via luck or close-game wins).",
    },
    {
        "Stat": "Highest / Lowest Win % vs a team",
        "Sheet": "team_all_time",
        "Formula": "Across all individual opponents this team has actually played (≥1 all-time game), the max / min of 'Win % vs <opponent>'. 'Team for highest/lowest Win %' holds the matching opponent handle.",
        "Notes": "Opponents never played are excluded so 'lowest' isn't trivially 0. On team_all_time the per-opponent vs-columns are regrouped — all 'Win % vs …' together, then all 'Record vs …' together.",
    },
    {
        "Stat": "UPST",
        "Sheet": "team_week / league_week / league_year / league_all_time",
        "Formula": "team_week: 1 if the team won while its pregame avg Max PF was below the opponent's (an upset win). League sheets sum those flags (week = upsets that week; year/all-time = total upsets).",
        "Notes": "Formerly duplicated on the league sheets as 'Number of wins with pregame avg max PF from opponent' — that redundant column was removed; UPST is the single source.",
    },
    {
        "Stat": "Number of starting donuts",
        "Sheet": "league_week / league_year / league_all_time",
        "Formula": "League-wide sum of team_week 'Number of starter donuts' (started players who scored exactly 0).",
        "Notes": "Companion to 'Number of donuts' (all rostered players). Starter-only version.",
    },
    {
        "Stat": "Highest / Lowest starter score",
        "Sheet": "league_week / league_year / league_all_time",
        "Formula": "Max / min single-starter fantasy score league-wide over the period (week / season / all-time). 'Difference between highest and lowest starters' is their gap.",
        "Notes": "The lowest can be negative (a started QB with a net-negative game).",
    },
    {
        "Stat": "Offseason / Inseason / Total trades",
        "Sheet": "team_year / team_all_time / league_year / league_all_time",
        "Formula": "DISTINCT trade events (by trade timestamp) the team / league was in: Offseason = dated before that season's kickoff (Sept 7); Inseason = on/after kickoff; Total = Offseason + Inseason. Year sheets are per season; all-time sheets sum across seasons (a trade lives in one season). Each trade counts once regardless of how many teams were involved.",
        "Notes": "Replaces the single 'Number of trades' on the year/all-time sheets (which summed per team and multi-counted multi-team trades). The per-WEEK sheets keep 'Number of trades' — an offseason trade rolls into Week 1's weekly count only if within 7 days before kickoff. Rookies started/rostered and 'Number of NFL teams among …' on league_year/all_time are likewise distinct-across-the-period.",
    },
]


def build_output(context):
    return pd.DataFrame(_ROWS)
