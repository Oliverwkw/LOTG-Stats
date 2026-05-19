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
        "Stat": "FAAB % difference over second place",
        "Sheet": "transactions",
        "Formula": "(winning_bid − runner_up) / runner_up × 100.",
        "Notes": "Blank when runner-up bid was 0 (undefined / div-by-zero) or there was no valid runner-up.",
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
        "Formula": "True if the picking team's roster at the pickup week contains another STARTER who: (1) plays the same NFL team, (2) plays the same NFL position, (3) averaged at least 10 PPG more than the added player over the last 5 played games.",
        "Notes": "Handcuff detection. Roster snapshot uses player_week rows for that (team, year, week). 35 True rows across the dataset to date.",
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
        "Formula": "Same lookup, at: Jan 5 of (Season + 1), Jan 5 of (Season + 2), Jan 5 of (Season + 3) respectively. Future-dated references stay N/A.",
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
        "Stat": "Number of times picked up by this team",
        "Sheet": "transactions",
        "Formula": "Running 1-indexed counter per (Team, Player Added) sorted chronologically.",
        "Notes": "If a team picks up the same player twice, the second pickup reads 2 in this column.",
    },
    {
        "Stat": "Tanking",
        "Sheet": "transactions / trades",
        "Formula": "team_week.Tanking for the (Team, Season, week-of-transaction). Week is derived from Date: Sept 7 of Season = week 1, each subsequent Thursday is the next week, floored to 1 and capped at 17. Falls back to adjacent weeks then team_year.Tanking if the exact week is missing (e.g., offseason transactions).",
        "Notes": "Per-week lookup gives the team's tank state AT THE TIME of the decision, rather than the season aggregate. Useful for evaluating mid-season pickups.",
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
        "Formula": "For each '??'-slot pick received: (KTC at Sept 5 of pick's draft year) − (KTC at deal time). Sum across picks.",
        "Notes": "Captures whether the team did better or worse than the at-trade generic estimate once the slot was actually drawn. Picks whose drafts are still in the future don't contribute.",
    },
    # -------------------------------- player_week.csv --------------------------------
    {
        "Stat": "Activated Cuff?",
        "Sheet": "player_week",
        "Formula": "True if a STARTING player on the same NFL team and same position with last-5-game avg ≥ 10 PPG higher than this player was INJURED in this week. Only computed for players whose own last-5 avg is < 10.",
        "Notes": "Distinct from 'Cuff at time of pickup' — that's static at pickup; this fires each week the cuff window activates.",
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
        "Stat": "Luck",
        "Sheet": "team_week / team_year",
        "Formula": "(Wins) − (Expected wins from PF distribution). Expected wins is the average rank-percentile of the team's PF across all matchups in the same week.",
        "Notes": "Positive = won more games than PF would predict.",
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
        "Stat": "UPST",
        "Sheet": "league_week",
        "Formula": "Count of matchups where the lower-PF-percentile team beat the higher-PF-percentile team.",
        "Notes": "Aggregate 'upsets' for the week.",
    },
]


def build_output(context):
    return pd.DataFrame(_ROWS)
