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
        "Formula": "True if the picking team rostered another player who (a) is STILL on the roster at the pickup week, (b) was a STARTER in any of the previous 3 weeks (the pickup week and the two before it), and (c) plays the same NFL team, (d) same NFL position, and (e) averaged at least 10 PPG more than the added player over the last 5 played games.",
        "Notes": "Handcuff detection. Uses a 3-week starter window (so a cuff added right after the starter goes down still registers) BUT the reference player must still be rostered at pickup — a teammate dropped before the pickup is no longer insurance you hold (Item 8).",
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
        "Stat": "Length of tenure on team",
        "Sheet": "transactions",
        "Formula": "Days the ADDED player spent on this team: from the pickup Date to the next drop/trade off this team (Date dropped/traded), or to today if still rostered. N/A when the transaction has no added player (a pure drop) — no player whose tenure to measure; a genuine 0-day tenure (added then immediately moved) stays 0.",
        "Notes": "Calendar-day span of the tenure window used by the forward-looking PPG / Points Added metrics.",
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
        "Formula": "adjusted_diff × (1 + pct_starts) × (1 + pct_starts_injury_adjusted) + CUFF_BONUS. adjusted_diff is 'Difference of averages adjusted by position'. pct_starts is '% of starts made while rostered'. pct_starts_injury_adjusted is the injury-adjusted variant. CUFF_BONUS = 5 PPG when 'Cuff at time of pickup?' = True, else 0. An added player who was NEVER rostered for a full NFL week = 0 (added nothing measurable). N/A only for a pure drop (no added player).",
        "Notes": "Composite metric blending pure PPG difference with playing-time leverage and handcuff insurance. Tune CUFF_BONUS by editing the constant in src/lotg.py.",
    },
    {
        "Stat": "Points Added / Points Lost / Net points (+ Avg + Avg-adjusted-by-position variants)",
        "Sheet": "transactions",
        "Formula": "Points Added = the ADDED player's fantasy points summed over the weeks they STARTED for this team, from pickup until their next exit (drop/trade); 0 if no add. Points Lost = the DROPPED player's real NFL fantasy points (game log, 0 for any bye/injury/DNP week) summed over exactly those same started weeks — the opportunity cost of starting the add instead of the drop; 0 if no drop or no add. Net points = Points Added − Points Lost (0 for a pure drop). Avg variants = each divided by the number of started weeks, so swaps of different lengths are comparable (0 when no started weeks). 'Avg ... adjusted by position' variants scale the added side by the ADDED player's position and the lost side by the DROPPED player's position (× league_starter_avg / pos_avg) before averaging, so cross-position swaps are comparable.",
        "Notes": "Started weeks come from player_week (Starter/Bench == Starter) bounded by the pickup→next-exit window; the dropped player's counterfactual points come from the nflverse game log regardless of where they actually landed.",
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
        "Formula": "Same lookup at three future moments: 'end of season' = the Monday after this season's fantasy championship game (the day after NFL week-17 Sunday — the next championship after the move); '1 year later' / '2 years later' = exactly 1 and 2 calendar years after the transaction date itself. Future-dated references stay N/A.",
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
        "Formula": "Follows the ADDED player and the DROPPED player to their next/previous event ANYWHERE in the league — across teams and INCLUDING trades. Reference is a row pointer: '#N' = transactions.csv row N, 'T#N' = trades.csv row N, 'PH#N' = picks.csv (pick history) row N (1-indexed, final sorted order). A drafted player's chain STARTS at their picks draft row, so the 'previous' link on their first-ever event points to 'PH#N'.",
        "Notes": "Replaces the old single per-team 'Link to next/previous transaction'. The chain is date-ordered, so row numbers can look non-monotonic (the CSVs are grouped by team, not global date). A multi-row trade (e.g. a 3-team deal) counts as ONE event, so the link skips the trade's own other-team rows and lands on the next DISTINCT transaction/trade involving the player. Blank at the very ends of a player's chain (a drafted player's start is their PH# draft row) or when the row has no added/dropped player. In the xlsx every link cell is a clickable hyperlink to the target row (a per-asset list links to its first ref).",
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
        "Stat": "Assets received / Assets sent",
        "Sheet": "trades",
        "Formula": "Semicolon-joined list of everything that came to (received) or left (sent) the team in the trade, from that team's perspective: players, draft picks ('2025 1.05(B. Robinson)'), and FAAB ('$N FAAB'). FAAB comes from Sleeper's waiver_budget: on the SENT side it's summed per sending roster; on the RECEIVED side it's rendered PER SENDER (one '$N FAAB' asset per source roster), so a multi-sender 3-team deal shows e.g. '$4 FAAB' + '$15 FAAB' on the receiver rather than a lumped '$19 FAAB' — the two sides mirror and dollars conserve.",
        "Notes": "FAAB capture (Phase 7A) is what makes FAAB-only trades show real assets instead of blank both sides. Net-zero swaps — trades where nothing actually changed hands (no players/picks, FAAB nets to zero for every roster, e.g. a symmetric $5-for-$5 swap) — are deleted entirely from trades.csv and from all trade counts. Assets sent is attributed to the roster that actually GAVE UP each asset (player it dropped, pick's previous owner, FAAB sender), so a 3+ team trade lists each asset exactly once per side instead of every team claiming the whole pot.",
    },
    {
        "Stat": "Trade impact score",
        "Sheet": "trades",
        "Formula": "An overall measure of how impactful/good a trade was for the team — a composite, with WIN IMPACT heavily weighted, of five standardised (z-scored across all trades) player/asset signals (no KTC in the output), summed and scaled (×1500) into a KTC-like band. (1) WIN IMPACT, weight 2.0 — games the trade flipped PLUS a share of games flipped by later trades that re-used the received assets. Direct: for each post-trade week (over the player's whole tenure, NOT a 10-game window) a received asset started, net points = received starters − the top-k players traded away; if (actual weekly margin) vs (margin − net) crosses 0, ±1 game. Downstream: when a received asset is later re-traded, this trade is credited that later trade's win impact × the FRACTION of the later trade's sent-side KTC value (on the later trade's day) that came from this trade's assets — recursively, so a minor add-on bundled later for a stud earns only its small value share. (2) realized production, Avg net points, 0.8; (3) trade value incl. picks, Trade addition value, 0.5; (4) future capital, Pick value received, 0.5; (5) youth, −Asset difference in average age, 0.3. Continuous → percentile-ranks cleanly.",
        "Notes": "Item 3. Renamed from 'Team performance improvement' (it blends win impact with trade value, so it's a trade-impact/quality index, not a pure on-field-improvement metric — and pure performance improvement is inherently at odds with not punishing tank trades). Win impact uses nflverse points + team_week margins; KTC only proportions the downstream credit, not the output. Weights/scale tunable; games-flipped is the heavily-weighted core. ≈0.26 correlation with 'KTC value difference at end of season'.",
    },
    {
        "Stat": "O-Score",
        "Sheet": "picks / transactions / trades",
        "Formula": "An overall 0–100 score for the move: take FOUR stats, convert each to its PERCENTILE (0–100) across that sheet's rows, and average the four. The four (per sheet): picks → Avg points added, Pick-adjusted Difference in Player addition value, most-recent PICK-ADJUSTED-KTC difference (so market value is judged vs the draft-slot window, not absolute; points added stays absolute), Pick-adjusted Difference in Avg career PPG adjusted by position; transactions → Avg net points, Player addition value, most-recent-KTC, % of starts made while rostered; trades → Avg net points, Trade addition value, most-recent-KTC, Trade impact score. 'most-recent-KTC' = the percentile of the latest populated KTC value/difference on the row (picks scan 4yr→3yr→2yr→1yr→end-of-rookie→draft day; transactions/trades scan their 2yr→1yr→end-of-season→deal day). Percentiles use average tie-handling EXCEPT a value of exactly 0 (no production — e.g. the ~87% of adds that never started) is pushed to the bottom of its tie, so zeros cluster low rather than in the middle. O-Score = the average of the AVAILABLE percentiles: a 'droppable' component may be missing (on picks the pick-adjusted Player addition value of a player never rostered for a full week is dropped and the other three averaged), but every REQUIRED component must be present.",
        "Notes": "Item 4. ~50 = middle-of-the-pack, ~80+ a strong move. N/A only for: vet / unmade picks; pure-drop transactions; trades whose KTC is blank (one-sided, only untracked assets received); and retired / untracked players (no KTC). For picks, the 2021 vet/startup draft is excluded from every percentile pool. Percentiles are within each sheet (picks vs picks, etc.).",
    },
    {
        "Stat": "KTC value difference at deal time / end of season / 1 year later / 2 years later",
        "Sheet": "trades",
        "Formula": "(depth-adjusted KTC of received assets) − (depth-adjusted KTC of dropped assets) at each reference date. Depth tax (Item 2): on each side the assets' KTC values are sorted descending, the BEST counts in full, and each subsequent asset is discounted geometrically (2nd × 0.6, 3rd × 0.6², …) — so a side getting more pieces isn't over-credited (you can only start so many). A 1-for-1 is unchanged from the raw difference; a 3-scrubs-for-1-stud package is taxed (the scrubs' summed KTC no longer beats the stud). FAAB counts too (Fix 3): $1 FAAB is valued at the league-wide average KTC-per-$ implied by pure FAAB-for-asset trades, so a FAAB side carries real KTC value. Same date scheme as transactions.",
        "Notes": "Replaces the old naive Σreceived − Σsent. Depth factor 0.6 is tunable. Includes players (sleeper_id → dynasty-daddy slug), picks (dynasty-daddy round labels), and FAAB (avg KTC-per-$). Applied to trades only — transactions' Net KTC (1-for-1) is left as the raw difference.",
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
        "Notes": "Negative = team got younger. NFL rookies average ~22 at draft time; the Sept 1 anchor matches our late-August league rookie draft. Never blank (Phase 7C): when one side has no aged asset (FAAB-only or an empty give-away side) there is no measurable age differential, so it reports 0.",
    },
    {
        "Stat": "Number of teams involved",
        "Sheet": "trades",
        "Formula": "Count of distinct teams in the trade = this team + every counterparty. 2 for a normal swap, 3+ for a multi-team trade.",
        "Notes": "Phase 7B. Derived from Sleeper's roster_ids on the trade transaction.",
    },
    {
        "Stat": "Link to next transaction per asset / Link to previous transaction per asset",
        "Sheet": "trades",
        "Formula": "For each asset RECEIVED in the trade (in the same order as 'Assets received'), the reference to that asset's next / previous event in its cross-table chain — '#N' = transactions.csv row N, 'T#N' = trades.csv row N. Rendered as a ';'-joined list aligned 1:1 with 'Assets received'. PLAYERS resolve through the shared player chain (the same one the transaction added/dropped links use). DRAFT PICKS resolve through a separate pick chain to the next/prev TRADE that moved that pick — keyed by the pick's canonical identity (year, round, original owner), built from the received side only so the two mirror rows of one trade event don't link to each other; the pick chain deliberately does NOT continue into the player eventually drafted with the pick. FAAB carries 'N/A'.",
        "Notes": "In the xlsx these two columns are exploded into one clickable column PER received asset, the group label sitting in the first sub-column's header (the headers are NOT merged, so the trades sheet stays a sortable/filterable table): each cell shows the asset's NAME and hyperlinks to that asset's next/previous event (the CSV keeps the ';'-joined ref list). Phase 7B + pick chains + draft-row bridge — replaces the old per-team 'Link to next/previous transaction'. Follow a received player OR pick onward to wherever it next moved. The pick chain TERMINATES at the pick's draft row in picks ('PH#N' = picks row N), and a drafted player's chain (here and in the transaction added/dropped links) STARTS at that same draft row — so a pick's last trade links forward to the draft and the drafted player's first event links back to it, without the pick chain ever crossing into the player.",
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
        "Formula": "Per received player, their mean fantasy_points_ppr over NFL games from trade date through next drop/trade from this team. ALSO includes received DRAFT PICKS (Phase 7D): the player drafted with the pick contributes their mean PPG over their post-draft tenure on this team (draft ≈ late August of the pick year → next exit) — but only when this team actually made the selection (picks Team == this team); a pick flipped before the draft, or a not-yet-drafted future pick, contributes nothing. Aggregated as the mean across all these received assets.",
        "Notes": "Forward-looking — actual production while on this team, players and drafted picks alike. Sourced from nflverse, so injured/bye/suspended weeks (no game log row) are already excluded; only games actually played count.",
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
        "Formula": "V2 composite mirroring the transaction 'Player addition value': adj_diff × (1 + pct_starts) × (1 + pct_starts_injury_adjusted) + CUFF_BONUS(5). adj_diff = 'Difference of averages adjusted by position' (received-side adjusted on-team PPG − sent-side adjusted PPG; a side with no players contributes 0). pct_starts = average over the RECEIVED players of their '% of starts made while rostered' on this team over their post-trade tenure (trade → next exit); pct_starts_injury_adjusted divides starts by injury/bye-free weeks only. CUFF_BONUS (+5) is added once if ANY received player was a cuff at the trade — the team already rostered a STARTER on the same NFL team + position (still rostered at the trade week) whose last-5 PPG was 10+ above the received player's last-5, the same handcuff test as the transaction 'Cuff at time of pickup?'. PLUS a pick-value term: future picks (next 3 seasons only) on each side are valued with the SAME round weights tanking uses (1st=0.25, 2nd=0.09, 3rd=0.03, 4th=0.01) and the received−sent difference is scaled by a coefficient (currently 20 → a future 1st ≈ +5, about one cuff bonus) and added in, so pick-heavy hauls register. The pick term applies even when adj_diff is None, so a pick-only haul is no longer flat 0.",
        "Notes": "Item 7E. Players DRAFTED with received picks feed adj_diff (Phase 7D); the pick-value term only counts FUTURE (next-3-season) capital, so a current-season pick that gets drafted isn't double-counted. Playing-time leverage is over received players only. The pick coefficient (20) is tunable.",
    },
    {
        "Stat": "Points added / Points lost / Net points (+ Avg + Avg-adjusted-by-position variants)",
        "Sheet": "trades",
        "Formula": "RECEIVED assets = received players + the players THIS team drafted with received picks (their window starts at the draft, ~late Aug of the pick year). For each NFL week, let k = how many received assets STARTED for this team that week. Points added += the sum of those k starters' points. Points lost += the sum of the TOP-k players-traded-away by their real NFL points that week (each sent asset counted at most once per week, capped at the number actually sent) — the best plays you forwent by trading them. Sent picks contribute the player drafted with them. Net points = Points added − Points lost. Avg variants = each divided by the number of matched weeks (weeks with ≥1 received starter). 'Avg ... adjusted by position' variants scale EACH asset's points by its own position (× league_starter_avg / pos_avg) before summing — the lost side keeps the same top-k assets chosen by raw points, but sums their position-adjusted points.",
        "Notes": "The top-k 'maximize' rule generalizes the 1-for-1 transaction Points Lost to multi-asset trades: a received starter each week is matched against the single best player you gave up. Started weeks/points come from player_week; sent assets' counterfactual points from the nflverse game log.",
    },
    # -------------------------------- picks.csv (pick history) --------------------------------
    {
        "Stat": "Number",
        "Sheet": "picks",
        "Formula": "round.position, where position is the pick's place in DRAFT ORDER within the round (2.01 = first pick of round 2). For LINEAR drafts position == draft_slot. For SNAKE drafts (the 2021 rookie drafts) even rounds reverse, so the team at draft_slot 1 picks last in round 2 (2.08) and first in round 3 (3.01); position = team_count + 1 − draft_slot on even rounds.",
        "Notes": "Earlier builds labelled every round by raw draft_slot, which mis-numbered even rounds of the 2021 snake drafts (e.g. Trey Sermon showed 2.05 instead of 2.04). Player / Original Team / chain stay keyed by draft_slot — only the displayed number follows draft order. All post-2021 rookie drafts are linear, so they're unaffected. SYNTHETIC draft-day picks: '2.09' is the toilet-bracket reward pick (2024+), its drafted player = the FIRST commissioner-forced add on draft day, original team = the prior season's losers-bracket (toilet) champion, final team = whoever it was force-added to (one synthetic trade hop if they differ). '5.01, 5.02, …' are the 20-FAAB draft-day buys (2025+), the remaining draft-day commissioner adds in chronological order, original = final = buyer. These rows are removed from the transactions sheet and, for every slot-based comparison (pick-adjusted differences, Draft Value), 2.09 counts as a 2.08 and each 5.0X as a 4.08. Fires automatically each year from the draft-day commissioner-add pattern.",
    },
    {
        "Stat": "Original Team",
        "Sheet": "picks",
        "Formula": "The roster that ORIGINALLY owned this pick before any trades — i.e. the team in that draft-position slot per Sleeper's slot_to_roster_id mapping. For traded picks, this is the chain origin (the team whose own pick this is).",
        "Notes": "Distinct from 'Team'. ESPN-era picks (moved before Sleeper's tracking window) fall back to the slot owner; if that's also unavailable, the picker is used.",
    },
    {
        "Stat": "Team",
        "Sheet": "picks",
        "Formula": "The roster that actually MADE the selection (= last owner in the trade chain). Equals Original Team when the pick wasn't traded. (Formerly 'Final Team'.)",
        "Notes": "Pulled from Sleeper draft picks (roster_id field) and from the end of the reconstructed trade chain. For 2021 rookie-draft EVEN rounds (whose Sleeper picker data is corrupted), this is repaired from the roster ledger — the team that actually first rostered the drafted player.",
    },
    {
        "Stat": "Length of tenure on team",
        "Sheet": "picks",
        "Formula": "Days the DRAFTED player stayed on the team that drafted it (Team): from the draft anchor (≈ Aug 28 of the pick year, after offseason pick trades, before the rookie draft) to that player's next exit (drop/trade) off the team, or to today if still rostered. N/A for an unmade pick (a future pick with no player selected yet — 'Unknown') — no player whose tenure to measure, mirroring a transactions pure drop; every MADE pick is a number ≥ 0 (a genuine 0-day tenure, or a pick whose player can't be mapped to a game log, falls back to 0).",
        "Notes": "Pick analogue of the transactions 'Length of tenure on team'. Uses the same next-exit lookup; the draft anchor matches the 7D drafted-pick PPG window.",
    },
    {
        "Stat": "Avg PPG on team",
        "Sheet": "picks",
        "Formula": "Mean fantasy_points_ppr of the DRAFTED player over the NFL games they played while on the team that drafted them (Team), in the tenure window: draft anchor (≈ Aug 28 of the pick year) → next exit off the team (or today). N/A ONLY when the player was never on the team's roster for an NFL week (cut after the draft before week 1) — or for an unmade pick. If the player was rostered for ≥1 NFL week but logged no games (injured/inactive all tenure), it's 0, not N/A.",
        "Notes": "Pick analogue of the transactions 'Average PPG on team' / the 7D drafted-pick PPG; built on the nflverse game log (games actually played, so injured/bye/suspended weeks are excluded). Roster presence comes from player_week (starter or bench).",
    },
    {
        "Stat": "Avg PPG on team adjusted by position",
        "Sheet": "picks",
        "Formula": "Avg PPG on team × league_starter_avg / pos_avg[player_position] — normalises QB/RB/WR/TE scoring scales (a 12-PPG TE ≠ a 12-PPG QB). N/A / 0 exactly when Avg PPG on team is.",
        "Notes": "Same position normaliser used across transactions/trades adjusted metrics.",
    },
    {
        "Stat": "Avg career PPG",
        "Sheet": "picks",
        "Formula": "Mean fantasy_points_ppr of the DRAFTED player over every NFL game they played FROM THE DRAFT ONWARD (across all teams, not scoped to the drafting team). Vets are treated as rookies: only post-draft games count, so a startup/vet-draft player's pre-draft history is excluded. Injury-adjusted by construction (the nflverse log only has games played). NEVER N/A for a made pick — a player with no post-draft games (e.g. a vet drafted at the end of his career who never played again) is 0. N/A only for an unmade pick (no player).",
        "Notes": "Per user: the player's rate since being drafted (how the pick panned out), distinct from 'Avg PPG on team' (only their tenure on the drafting team). 'Career' is bounded below by the draft and by nflverse coverage (2021+).",
    },
    {
        "Stat": "Avg career PPG adjusted by position",
        "Sheet": "picks",
        "Formula": "Avg career PPG × league_starter_avg / pos_avg[player_position] — same position normaliser as the other adjusted metrics. 0 / N/A exactly when Avg career PPG is.",
        "Notes": "Position-normalised post-draft rate.",
    },
    {
        "Stat": "Age when drafted",
        "Sheet": "picks",
        "Formula": "The drafted player's age in years (decimal) at the draft anchor (≈ Aug 28 of the pick year), from their birth_date. N/A for an unmade pick or a player with no birth_date on record.",
        "Notes": "How old the player a pick became was on draft day.",
    },
    {
        "Stat": "KTC on draft day / at end of rookie year / 1 / 2 / 3 / 4 years after draft day",
        "Sheet": "picks",
        "Formula": "The DRAFTED player's KeepTradeCut value (1QB trade_value, via dynasty-daddy daily history) at six checkpoints relative to the draft (anchor ≈ Aug 28 of the pick year): the draft day itself; the end of the rookie year (≈ Feb 1 of the following year); and exactly 1, 2, 3, and 4 years after the draft day. Each is the same single-asset KTC lookup used for the transactions/trades KTC columns. N/A for an unmade pick, an untracked player, or a checkpoint date that is in the future or before KTC history begins (≈ April 2021).",
        "Notes": "Lets you watch a pick's player gain/lose dynasty value over its first four years. KTC history starts April 2021, so 'on draft day' is N/A for the very earliest picks and the 3/4-year marks are N/A until enough time has passed. (The former 5-year mark was dropped in favour of 3- and 4-year checkpoints.)",
    },
    {
        "Stat": "Pick-adjusted Difference in [stat] (one per position-adjusted average, Player addition value, and each KTC column)",
        "Sheet": "picks",
        "Formula": "This pick's value of the stat MINUS a comparison average over the 3-SLOT window around this pick (by OVERALL draft position, crossing round boundaries e.g. 1.08 → 2.01 → 2.02). Picks 1.01–1.04 (overall positions 1–4) use the ORIGINAL rule: a flat pooled mean of every non-vet pick value at the window slots — 1.01 uses {1.01,1.02}; otherwise {prev,this,next}. From 1.05 onward (position ≥ 5) the baseline is the mean of FOUR per-slot means: the three window slots PLUS a synthetic 'fourth pick' = the average of the two OUTER slot means, which up-weights the window's edges. E.g. 1.05: slots {1.04,1.05,1.06}, fourth = (avg(1.04) + avg(1.06))/2, baseline = (avg(1.04)+avg(1.05)+avg(1.06)+fourth)/4. The very last pick (4.08) uses the left-shifted window {4.06,4.07,4.08} with 4.06 & 4.08 as the outer ends. Companion to each of the 3 position-adjusted averages and the 5 KTC columns.",
        "Notes": "The 2021 vet/startup draft is excluded: its rows are N/A and it never enters a reference average. N/A when the pick's own stat is N/A (e.g. an unmade or never-rostered pick), and for vet rows.",
    },
    {
        "Stat": "Player addition value",
        "Sheet": "picks",
        "Formula": "Mirror of the transactions composite, with an ON-TEAM baseline (a pick gives up no player, so there is no 'dropped' side): (Avg PPG on team adjusted by position) × (1 + % of starts made while rostered by drafting team) × (1 + injury-adjusted % of starts) + CUFF_BONUS(5 when Cuff when drafted? is True). N/A when there is no on-team production to value (the player was never on the drafting team's roster for an NFL week) or for an unmade pick.",
        "Notes": "Per user: on-team baseline. Same CUFF_BONUS and leverage shape as the transactions 'Player addition value'.",
    },
    {
        "Stat": "Cuff when drafted?",
        "Sheet": "picks",
        "Formula": "True if, at the drafted player's FIRST week on the drafting team's roster, the team already rostered a STARTER on the same NFL team + position whose last-5 PPG was 10+ above them — the same handcuff test as 'Cuff at time of pickup?'. Evaluated at the first rostered week (not the draft date) because a rookie's NFL team/position isn't known until they actually play. False if the player was never rostered here (or an unmade pick).",
        "Notes": "Feeds the CUFF_BONUS in Player addition value.",
    },
    {
        "Stat": "Weeks before first start",
        "Sheet": "picks",
        "Formula": "Number of weeks the drafted player was on the drafting team's roster (starter or bench) before their FIRST start for that team, within the post-draft tenure window. N/A if the player never started for the drafting team (or an unmade pick).",
        "Notes": "Pick analogue of the transactions 'Weeks between pickup and start'.",
    },
    {
        "Stat": "Number of starts before next transaction",
        "Sheet": "picks",
        "Formula": "Count of weeks the drafted player STARTED for the drafting team between the draft and their next exit off that team (trade/drop). A number ≥ 0 for every made pick (0 if they never started here); N/A only for an unmade pick.",
        "Notes": "Pick analogue of the transactions 'Number of starts before next drop'.",
    },
    {
        "Stat": "% of starts made while rostered by drafting team",
        "Sheet": "picks",
        "Formula": "(starts for the drafting team) / (weeks rostered by the drafting team) over the post-draft tenure window. N/A when the player was never rostered for an NFL week by the drafting team (no denominator); 0 when rostered but never started.",
        "Notes": "Roster + start weeks from player_week. Pick analogue of the transactions '% of starts made while rostered'.",
    },
    {
        "Stat": "Injury adjusted % of starts made while rostered by drafting team",
        "Sheet": "picks",
        "Formula": "(starts in injury/bye-free weeks) / (injury/bye-free weeks rostered) over the same window — divides only by weeks the player was available. N/A when there were no injury-free rostered weeks (or an unmade pick).",
        "Notes": "Removes weeks the player couldn't have started (injury/bye) from the denominator, like the transactions injury-adjusted variant.",
    },
    {
        "Stat": "Points added",
        "Sheet": "picks",
        "Formula": "Σ of the drafted player's fantasy points over the weeks they STARTED for the drafting team (Team) within the tenure window (draft anchor → next exit). N/A for an unmade pick; a number ≥ 0 for every made pick (0 if the player never started here / can't be resolved).",
        "Notes": "Pick analogue of the trades 'Points added' (received-starter output), restricted to the player drafted with this pick.",
    },
    {
        "Stat": "Avg points added",
        "Sheet": "picks",
        "Formula": "Points added / number of weeks the drafted player started for this team in the window. N/A for an unmade pick; 0 for a made pick with no started weeks.",
        "Notes": "Per-start average of the started-week output.",
    },
    {
        "Stat": "Avg points added adjusted by position",
        "Sheet": "picks",
        "Formula": "(Σ position-adjusted started-week points) / started weeks, where each week's points are × league_starter_avg / pos_avg[position]. N/A for an unmade pick; 0 for a made pick with no started weeks.",
        "Notes": "Position-normalised variant of Avg points added.",
    },
    {
        "Stat": "Number",
        "Sheet": "picks",
        "Formula": "Canonical pick notation: '{round}.{slot:02d}' (e.g. '1.05' = round 1, slot 5). Slot is derived from draft_slot or pick_in_round, with fallback to ((pick_no − 1) mod team_count) + 1. Shown as bare '{round}' when slot is unknown.",
        "Notes": "Same notation is used inside trades.csv to substitute already-made picks with the slot they became (e.g. '2024 1.05(B. Robinson)').",
    },
    {
        "Stat": "Commissioner moved?",
        "Sheet": "picks",
        "Formula": "True if this pick's ownership shift wasn't recorded as a normal trade transaction. Detected when traded_picks_by_season shows a pick belonging to a non-original owner but no trade event in pick_trade_events explains the move (typical for picks moved >3 years before draft year, beyond Sleeper's trade-tracking window).",
        "Notes": "Such picks are NOT added to trades.csv (the move wasn't a trade); the assumption is a single move from original owner to current owner.",
    },
    {
        "Stat": "Trade 1 / Trade 2 / … (xlsx hyperlinks)",
        "Sheet": "picks",
        "Formula": "Each 'Trade N' cell shows the team that owned the pick after its Nth trade. In the xlsx, the cell also HYPERLINKS to the trades-sheet row of that trade (the one that moved the pick to that team) — refs come from the pick's canonical chain, aligned to the Trade N hops in order.",
        "Notes": "Best effort: a commissioner move (not a real trade) has no trades row, so a Trade N produced by such a move is left un-linked and can shift the alignment of later hops for that pick. CSV cells are plain team names (no hyperlinks).",
    },
    {
        "Stat": "Link to next transaction / Link to previous transaction",
        "Sheet": "picks",
        "Formula": "Bridges the pick and the drafted player through the draft row. 'Link to next transaction' = the drafted PLAYER's next event after the draft (their first transaction '#N' or trade 'T#N'). 'Link to previous transaction' = the PICK's last trade before the draft ('T#N'). Both are clickable row pointers in the xlsx (the same '#N' / 'T#N' / 'PH#N' scheme as the transactions/trades links). Blank when there is no such event (an unmade or never-traded pick / a player with no post-draft events).",
        "Notes": "The draft row is the player chain's START and the pick chain's TERMINAL, so 'next' walks into the player's career and 'previous' walks back into the pick's trade history.",
    },
    {
        "Stat": "Commissioner wash exclusion",
        "Sheet": "transactions / trades / all transaction & trade counts",
        "Formula": "A transaction is dropped entirely when every player it moves nets to zero on its own roster within the same calendar day AND a commissioner action was part of that player-day. I.e. a single-day commissioner correction that leaves the roster exactly as it started.",
        "Notes": "Covers: commissioner add+drop of a player; a player a team dropped that the commissioner re-added same day; an add the commissioner immediately undid; and a trade the commissioner reversed. These no-ops are excluded from every transaction/trade count and from the transactions.csv / trades.csv detail.",
    },
    # -------------------------------- player_week.csv --------------------------------
    {
        "Stat": "NFL team",
        "Sheet": "player_week (drives the 'same NFL team' / 'Number of NFL teams' / bye columns too)",
        "Formula": "The player's real NFL team that week, resolved deterministically: nflverse week-specific stats team → that season's nflverse stats team → nflverse WEEKLY ROSTER team (catches players on a roster but with no stats — IR / suspended / PUP, e.g. Calvin Ridley 2022 on JAX while suspended) → the '33rd' sentinel \"NFL\" only when the player has an NFL identity (gsis_id) but was on NO roster that season (a true free agent or retired). Players with no gsis (team DSTs / unmapped) keep Sleeper's team field.",
        "Notes": "The \"NFL\" sentinel replaces the old live-Sleeper-snapshot fallback, which returned the player's CURRENT team (wrong for a past season) and churned between builds for free agents — e.g. Odell Beckham 2022 flipped MIA↔NYG, cascading through his bye → Hardship → z-scored Luck across every team. A sentinel-team player is never flagged on bye (it has no schedule).",
    },
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
        "Formula": "Weekly = (0.27*OUT + 0.14*Sisenzweig - 0.14*Brosenzweig) * postboost + (0.36*OPP + 0.10*OWN) * GATE - 0.36*ADV + 0.12*EFF + 0.16*CLOSE - 0.25*LFH. LFH = 1 when the week is a 'Loss from hardship?' (a winnable game lost to injured starters), else 0 — a flat extra unlucky hit (~one typical weekly luck swing) on top of the ADV adversity term. OUT = Win(1/0.5/0) - pregame_p, where pregame_p = logistic(1.5 * mean of standardized full-season [MaxPF, PF, win%] differences vs opponent) — calibrated so winning to your talent nets ~0. OPP = z_week(-(opp PF - opponent's full-season avg PF)); OWN = z_week(PF - own full-season avg PF); ADV = z_week(Hardship + Starter-adjusted Hardship + 3*players on bye); EFF = z_week(Efficiency); CLOSE = sign(Margin)*max(0, 1-|Margin|/8); GATE = 1/(1+|Margin|/15); postboost = 1.8 in championship-bracket weeks (Final/Semifinal/3rd Place) else 1. z_week standardizes within each (year, week), clipped to +-2.5 then /2.5. team_year.Luck = the plain SUM of that season's weekly luck (no win% multiplier). team_all_time 'Avg yearly luck' = the MEAN of the per-season Luck totals (NOT the sum over all weeks).",
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
        "Stat": "Drafting skill / Trading skill / Transaction skill",
        "Sheet": "team_year / team_all_time",
        "Formula": "Sample-size-shrunk mean O-Score of the team's moves of that type: Drafting = the picks it MADE (picks.Final Team), Trading = the trades it was in (trades.Team), Transaction = the transactions it made (transactions.Team). Per (Team, Year) on team_year and per Team all-time. Shrinkage toward the league-neutral 50: skill = (n·mean + K·50) / (n + K), K=5, where n = the number of that team's moves with a non-N/A O-Score and mean = their average O-Score.",
        "Notes": "The shrinkage keeps a manager with 2 great moves from out-ranking one with 25 solid ones, and parks inactive managers near 50 rather than over-rewarding them; on team_year (small per-season samples) values pull harder toward 50. N/A for a (team, year) with no moves of that type (didn't draft / trade / transact). Moves with an N/A O-Score (vet picks, pure-drop transactions, one-sided untracked trades, retired players) drop out of the mean.",
    },
    {
        "Stat": "All-play win %",
        "Sheet": "team_year / team_all_time",
        "Formula": "Schedule-luck-free win rate: each week, score the team against EVERY other team (not just its actual opponent). Win % = (Σ over weeks of teams with strictly lower PF that week) / (Σ over weeks of other teams). Per (Team, Year) on team_year; pooled over all weeks on team_all_time. Ties count as neither a win nor a loss but stay in the denominator (so they depress the rate). Format 0–1, 4 decimals like Win %.",
        "Notes": "Reveals true scoring strength independent of who you were scheduled against — a team can be top-half (the existing flag) yet have a mediocre all-play %, or vice versa. N/A for a (team, year) with no games (e.g. the not-yet-played current/future season).",
    },
    {
        "Stat": "All-play win % minus Win %",
        "Sheet": "team_year / team_all_time",
        "Formula": "All-play win % − actual Win % (team_all_time uses 'All time win %'). Positive = the team's actual record UNDER-shot its all-play scoring strength (unlucky schedule / lost close games); negative = the record OVER-shot it (lucky schedule / won close games).",
        "Notes": "A compact schedule-luck read. N/A when all-play % is N/A (no games).",
    },
    {
        "Stat": "Loss from hardship? / Losses from hardship",
        "Sheet": "team_week (flag) / team_year + team_all_time (count)",
        "Formula": "team_week 'Loss from hardship?' = TRUE when a LOSS would have flipped to a win had the team's hurt would-be-starters been available. Build a counterfactual lineup from the team's ACTUAL STARTERS (at their real points) PLUS the injured/suspended players who MISSED (0 pts, byes excluded), each subbed in at their STARTER-ADJUSTED hardship value; take the best valid lineup of that pool (compute_optimal_lineup, so it's bounded to the lineup slots and a hurt player only helps by displacing a weaker actual starter). Flag = loss AND that healthy-lineup score > opponent's actual PF. team_year / team_all_time 'Losses from hardship' = the count per (Team, Year) / per Team.",
        "Notes": "Healthy BENCH players are deliberately excluded — this asks 'what if their hurt guys were available?', NOT 'what if they had also start/sat optimally', so it doesn't credit start/sit decisions they never made. Bounding to the lineup slots also stops a swarm of injured bench/IR players from manufacturing winnable losses (the earlier 'SA-Hardship + Margin > 0' rule over-counted heavily-injured teams). Counts injury AND suspension, never byes. Each flagged week also subtracts 0.25 from that week's Luck. Count is N/A for a (team, year) with no games; a real 0 stays 0.",
    },
    {
        "Stat": "Starter scoring volatility / Starter scoring floor / Starter scoring ceiling / Starter boom % / Starter bust %",
        "Sheet": "player_year / player_all_time",
        "Formula": "Computed over the player's STARTED weeks only (the 'Starter' prefix flags that bench weeks are excluded). Starter scoring volatility = standard deviation of started-week points. Starter scoring floor / ceiling = the lowest / highest single started-week points (absolute min / max, not a percentile). Starter boom % = share of started weeks scoring ≥ 20; Starter bust % = share scoring ≤ 5.",
        "Notes": "All N/A for a player who never started; volatility additionally N/A with fewer than 2 started weeks. Boom % / Bust % keep a real 0 for a player who started but never boomed / busted. Player_year is per season; player_all_time pools every started week.",
    },
    {
        "Stat": "Starter PAR / Starter PAR per game",
        "Sheet": "player_year / player_all_time",
        "Formula": "Points Above Replacement over started weeks (the 'Starter' prefix flags that only started weeks count). For each (year, week, position) the replacement level = the mean of the BOTTOM THIRD of that week's STARTED scores at the position (the 'last-startable' tier). Per started week, PAR_week = the player's points − that replacement level. Starter PAR = the season/all-time SUM of PAR_week; Starter PAR per game = its mean.",
        "Notes": "Captures value over a freely-startable option at the player's position, week by week (so a stud in a weak position week is rewarded; a low-end starter nets ~0 or negative). N/A for a player who never started.",
    },
    {
        "Stat": "One-man army? / Most bench points? / Most injured?",
        "Sheet": "team_week (flag) + team_year/team_all_time (Times count)",
        "Formula": "Weekly team awards (one winner per league-week, ties shared). One-man army? = the team whose single top starter supplied the greatest share of its PF that week (highest '% of points (if starter)' among any team's top starter). Most bench points? = the team with the highest total bench points. Most injured? = the team with the most injured players on its roster (starters + bench) that week. team_year / team_all_time carry 'Times One-man army?' / 'Times Most bench points?' / 'Times Most injured?' = how often the team won each.",
        "Notes": "Mirror the existing weekly-award pattern (Highest score?, Most efficient?, …). Most injured? requires at least one injury; a 0-injury week has no winner.",
        "Columns": ["One-man army?", "Most bench points?", "Most injured?",
                    "Times One-man army?", "Times Most bench points?", "Times Most injured?"],
    },
    {
        "Stat": "Captain? / Times as Captain?",
        "Sheet": "player_week (flag) + player_year/player_all_time (count)",
        "Formula": "Captain? = the single starter, league-wide, who supplied the highest share of his team's PF that week (max '% of points (if starter)'; alphabetical tie-break). The Captain's team is that week's One-man army. player_year / player_all_time carry 'Times as Captain?' = how often the player was weekly Captain.",
        "Notes": "One Captain per league-week.",
    },
    {
        "Stat": "Streaks (weekly award & condition streaks — terminal-encoded)",
        "Sheet": "team_week + player_week",
        "Formula": "For every weekly award and condition there is a running streak that is ALL-TIME — it counts consecutive qualifying weeks and does NOT reset between seasons. team_week: Highest/Lowest score, Narrowest victory, Largest blowout, Most/Least efficient, Top half, One-man army, Most bench points, Most injured (award streaks); Bottom half, 150+ PF (PF ≥ 150), Standings leader (regular-season weeks at #1 in cumulative standings), Quiet (0 transactions + 0 trades), and 'Win streak vs this opponent' (consecutive H2H wins vs that week's opponent). player_week: a streak per player award (Player/QB/RB/WR/TE of the week, Benchwarmer, Bench QB/RB/WR/TE, Highest/Lowest starter on team, Captain), plus point-threshold streaks (consecutive ROSTERED weeks scoring ≥ 10/20/30/40/50 points, starter OR bench).",
        "Notes": "TERMINAL ENCODING so each run lists once and the column stays sortable for top-N lists: a run shows its LENGTH only on its final week (the most recent week if still active, else the peak week before it reset); earlier weeks of the run read 'In Progress'; weeks not on a run read 0. Sorting a column descending surfaces each streak exactly once (numbers sort above the 'In Progress' text). Win streak / Loss streak are the exception — they keep their running within-season and cross-season columns unchanged (not terminal-encoded).",
        "Columns": [
            "Highest score streak", "Lowest score streak", "Narrowest victory streak",
            "Largest blowout streak", "Most efficient streak", "Least efficient streak",
            "Top half streak", "One-man army streak", "Most bench points streak",
            "Most injured streak", "Bottom half streak", "150+ PF streak",
            "Standings leader streak", "Quiet streak", "Win streak vs this opponent",
            "Win streak", "Loss streak", "Win streak counting previous season",
            "Loss streak counting previous season",
            "Player of the week streak", "QB of the week streak", "RB of the week streak",
            "WR of the week streak", "TE of the week streak", "Benchwarmer of the week streak",
            "Bench QB of the week streak", "Bench RB of the week streak",
            "Bench WR of the week streak", "Bench TE of the week streak",
            "Highest starter on team streak", "Lowest starter on team streak", "Captain streak",
            "10+ point streak", "20+ point streak", "30+ point streak",
            "40+ point streak", "50+ point streak",
        ],
    },
    {
        "Stat": "Playoff appearance streak / Winning season streak",
        "Sheet": "team_year",
        "Formula": "Season-grain streaks (the season is their natural 'week', so they live on team_year). Playoff appearance streak = consecutive seasons the team made the playoffs (top 4 by regular-season standings). Winning season streak = consecutive seasons finishing ≥ .500 (Win % ≥ 0.5). Both ALL-TIME (do not reset) and terminal-encoded like the weekly streaks (length on the final season of the run, 'In Progress' before, 0 when broken).",
        "Notes": "A season with no games yet (current/future) reads N/A.",
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
        "Columns": ["Offseason trades", "Inseason trades", "Total trades"],
    },
    {
        "Stat": "Top team / Last team",
        "Sheet": "player_year / player_all_time",
        "Formula": "Top team / Top Team = the fantasy team (manager) that rostered the player for the most TIME over the period (by rostered duration, not week count). Last team = the team that held the player at the END of the season (in-season window only, so an offseason move doesn't overwrite it).",
        "Notes": "Phase 3 definition. These are manager names (could link to team_all_time, but that's out of Phase 11D's player-name scope).",
        "Columns": ["Top team", "Top Team", "Last team"],
    },
    {
        "Stat": "Age / Rookie?",
        "Sheet": "player_week (+ player_year/all Age)",
        "Formula": "Age = the player's age as of that week (birth_date vs the week's date; per-season = mean weekly age ≈ mid-season). Rookie? = TRUE in the player's rookie NFL season.",
        "Notes": "Age is anchored to the week, not 'today', so historical weeks stay correct.",
        "Columns": ["Age", "Rookie?"],
    },

    # ================= Phase 11A: complete the coverage =================
    # -------------------------------- player_week --------------------------------
    {
        "Stat": "Injury? / Suspension? / Bye?",
        "Sheet": "player_week",
        "Formula": "Per player-week status flags. Bye? = the player's NFL team had no game that week (player scored 0). Suspension? = serving an NFL suspension. Injury? = on a roster, scored 0, did not play, and not a bye/suspension. Primary source is the in-house weekly Sleeper injury tracker (data/injury_tracker.csv); nflverse stats/injuries + curated overlays are the backup.",
        "Notes": "A player who scored > 0 is never flagged (you can play hurt). Suspension wins over injury; bye wins over both. byes excluded from Hardship.",
        "Columns": ["Injury?", "Suspension?", "Bye?"],
    },
    {
        "Stat": "% of points (if starter)",
        "Sheet": "player_week",
        "Formula": "A started player's share of his team's starting PF that week = player points / team PF. Blank for bench players.",
        "Notes": "Drives the weekly Captain / One-man army awards.",
        "Columns": ["% of points (if starter)"],
    },
    {
        "Stat": "Change from previous week / previous 5 weeks avg / career average to that point / overall career average",
        "Sheet": "player_week",
        "Formula": "Differences of the week's points vs: the prior played week; the mean of the previous 5 played weeks; the player's career PPG through the prior week; and the player's full-career PPG. All use full-season (NFLverse) scoring and exclude bye/injury/suspension non-played weeks from the baselines.",
        "Notes": "N/A when the baseline period doesn't exist yet (first week / no prior games).",
        "Columns": ["Change from previous week", "Change from previous 5 weeks avg",
                    "Change from career average to that point", "Change from overall career average"],
    },
    {
        "Stat": "Number of weeks on team / Total weeks as team starter to that point / Total weeks on bench to that point",
        "Sheet": "player_week",
        "Formula": "Running tenure counters for the player on his current team: consecutive weeks rostered, cumulative weeks started, and cumulative weeks benched, each through that week.",
        "Notes": "Reset when the player joins a new team.",
        "Columns": ["Number of weeks on team", "Total weeks as team starter to that point",
                    "Total weeks on bench to that point"],
    },
    {
        "Stat": "Number of consecutive weeks on bench before start (if starter) / excluding injury/bye",
        "Sheet": "player_week",
        "Formula": "On a week the player starts, how many consecutive weeks he sat on the bench immediately beforehand. The second variant doesn't count weeks the player was unavailable (injury/bye/suspension) as 'benched'.",
        "Notes": "Only populated on a starting week.",
        "Columns": ["Number of consecutive weeks on bench before start (if starter)",
                    "Number of consecutive weeks on bench before start excluding injury/bye (if starter)"],
    },
    {
        "Stat": "Start/sit reference: best-startable-bench & worst-benchable-starter diffs",
        "Sheet": "player_week",
        "Formula": "For a STARTER: 'Difference from best startable bench (if starter)' = his points minus the best-scoring eligible bench player he could have started; the bench player's name is 'Reference player name'. For a BENCH player: 'Difference from worst benchable starter (if bench)' = his points minus the weakest starter he could have replaced. 'Difference in averages of best/worst startables over previous 5 games' compares the same pair on their trailing-5 averages instead of that week's points. 'Cuff adjusted difference' folds in the handcuff signal. '- Activated Cuff?…' flags that a rostered handcuff (same NFL team/position, much higher recent PPG) was started while its starter was hurt.",
        "Notes": "These reference a specific player in a specific week (the Phase-11 hyperlink exception → link to player_week, not player_all_time).",
        "Columns": ["Difference from best startable bench (if starter)",
                    "Difference from worst benchable starter (if bench)", "Reference player name",
                    "Difference in averages of best/worst startables over previous 5 games",
                    "Cuff adjusted difference",
                    "- Activated Cuff? (Was a player of the same nfl team/position & who averages >10 PPG more over last 5 played games injured? Only for players with avg <10 PPG)"],
    },
    {
        "Stat": "Weekly player awards (Player/QB/RB/WR/TE of the week, Benchwarmer, Bench QB/RB/WR/TE, Highest/Lowest starter) + Times-as counts",
        "Sheet": "player_week (flag) + player_year/player_all_time (Times as … count)",
        "Formula": "One winner per (Year, Week) per award among the relevant pool. Player of the week = highest-scoring starter league-wide; QB/RB/WR/TE of the week = highest starter at that position; Benchwarmer of the week = lowest-scoring starter (no winner if 2+ tie at 0); Bench QB/RB/WR/TE = highest-scoring bencher at that position; Highest / Lowest starter on team = the team's top / bottom starter (per team, each week). Alphabetical tie-break. player_year / player_all_time carry 'Times as <award>?' = season / career counts.",
        "Notes": "Companion streak columns are documented in the Streaks entry.",
        "Columns": ["Player of the week?", "QB of the week?", "RB of the week?", "WR of the week?",
                    "TE of the week?", "Benchwarmer of the week?", "Bench QB of the week?",
                    "Bench RB of the week?", "Bench WR of the week?", "Bench TE of the week?",
                    "Highest starter on team?", "Lowest starter on team?",
                    "Times as Player of the week?", "Times as QB of the week?", "Times as RB of the week?",
                    "Times as WR of the week?", "Times as TE of the week?", "Times as Benchwarmer of the week?",
                    "Times as Bench QB of the week?", "Times as Bench RB of the week?",
                    "Times as Bench WR of the week?", "Times as Bench TE of the week?",
                    "Times as Highest starter on team?", "Times as Lowest starter on team?"],
    },
    {
        "Stat": "Number of transactions / Number of drops / Number of trades",
        "Sheet": "player_week / player_year / player_all_time / team_week / team_year / team_all_time / league_week / league_year / league_all_time",
        "Formula": "Counts of roster moves involving the row's subject: adds+drops (transactions), drops only, and trades. On player sheets they count moves of that player; on team/league sheets they count the team's / league's moves that period and roll week → year → all-time.",
        "Notes": "On the year/all-time TEAM/LEAGUE sheets 'Number of trades' is superseded by the distinct Offseason/Inseason/Total trades (multi-team trades counted once).",
        "Columns": ["Number of transactions", "Number of drops", "Number of trades"],
    },

    # -------------------------------- player_year / player_all_time --------------------------------
    {
        "Stat": "Avg points / Adjusted Avg points / Points (full season) / Avg points (full season)",
        "Sheet": "player_year / player_all_time / team_year / team_all_time (Avg points)",
        "Formula": "Avg points = mean points over weeks ROSTERED by the subject. Adjusted Avg points excludes bye/injury/suspension non-played weeks from the denominator (a per-played-week average). Points (full season) = the player's TOTAL NFLverse points that season/career (incl. weeks he wasn't rostered here); Avg points (full season) = its per-game mean.",
        "Notes": "Derived consumers use the Adjusted variants. Full-season columns come from NFLverse, not LOTG rosters.",
        "Columns": ["Avg points", "Adjusted Avg points", "Points (full season)", "Avg points (full season)"],
    },
    {
        "Stat": "PPG starter / bench (+ Adjusted) / PPG starter vs bench diff",
        "Sheet": "player_year / player_all_time",
        "Formula": "Points-per-game split by lineup role: PPG starter = mean points in started weeks; PPG bench = mean in benched weeks; the Adjusted variants drop bye/injury/suspension weeks from the denominator. 'PPG starter vs bench diff' = PPG starter − PPG bench (how much better the player did when started).",
        "Notes": "N/A when the player never started / never benched that period.",
        "Columns": ["PPG starter", "PPG bench", "Adjusted PPG starter", "Adjusted PPG bench",
                    "PPG starter vs bench diff"],
    },
    {
        "Stat": "% of points (highest/lowest team) + team names",
        "Sheet": "player_year / player_all_time",
        "Formula": "The player's highest and lowest single-week starter share of team PF over the period, with the team (manager) it happened on in 'Team for highest / lowest % of points'.",
        "Notes": "Uses the per-week '% of points (if starter)'.",
        "Columns": ["% of points (highest team)", "% of points (lowest team)",
                    "Team for highest % of points", "Team for lowest % of points"],
    },
    {
        "Stat": "Number of teams",
        "Sheet": "player_year / player_all_time",
        "Formula": "Distinct fantasy teams (managers) that rostered the player during the season / career, counting partial-week rosterings.",
        "Notes": "Phase 3 fix: counts every team that held the player at any point (Renfrow = 5).",
        "Columns": ["Number of teams"],
    },
    {
        "Stat": "Weeks as starter / Weeks missed due to injury / suspension",
        "Sheet": "player_year / player_all_time",
        "Formula": "Counts over the period: weeks the player was a starter; weeks missed (rostered, 0 pts) flagged injury; weeks missed flagged suspension.",
        "Notes": "League sheets carry the league-wide totals ('Number of weeks missed due to injury / suspensions').",
        "Columns": ["Weeks as starter", "Weeks missed due to injury", "Weeks missed due to suspension"],
    },
    {
        "Stat": "Change in points / avg points from previous season & from career",
        "Sheet": "player_year",
        "Formula": "Season-over-season and vs-career deltas of the player's full-season total and average points: 'Change in points from previous season', 'Change in avg points from previous season', 'Change in points from career', 'Change in avg points from career'.",
        "Notes": "N/A for a rookie year / when there's no prior season or career baseline.",
        "Columns": ["Change in points from previous season", "Change in avg points from previous season",
                    "Change in points from career", "Change in avg points from career"],
    },
    {
        "Stat": "Taxi-eligible",
        "Sheet": "player_all_time",
        "Formula": "TRUE if the player has never been a fantasy starter in any LOTG week (eligible to be stashed on a taxi/practice squad).",
        "Notes": "Keyed off Weeks-as-starter == 0 across the player's whole history; undrafted never-started rookies stay eligible.",
        "Columns": ["Taxi-eligible"],
    },

    # -------------------------------- team_week core --------------------------------
    {
        "Stat": "PF / Points against / Max PF / Margin / Win? / Efficiency",
        "Sheet": "team_week (+ rollups)",
        "Formula": "PF = the team's started-lineup points; Points against = opponent PF; Margin = PF − Points against; Win? = 1/0/0.5 (tie). Max PF = the team's best possible (optimal) lineup score that week; Efficiency = PF / Max PF (how close the actual lineup came to optimal).",
        "Notes": "Used throughout standings, Luck and the optimal-lineup metrics.",
        "Columns": ["PF", "Points against", "Max PF", "Margin", "Win?", "Efficiency"],
    },
    {
        "Stat": "Brosenzweig / Sisenzweig (+ Times)",
        "Sheet": "team_week (flag) + team_year/team_all_time (Times count)",
        "Formula": "League in-jokes for luck extremes: Brosenzweig = lost despite a top-half score that week (unlucky loss); Sisenzweig = won despite a bottom-half score (lucky win). team_year/all carry 'Times Brosenzweig' / 'Times Sisenzweig'.",
        "Notes": "Feed the Luck model.",
        "Columns": ["Brosenzweig", "Sisenzweig", "Times Brosenzweig", "Times Sisenzweig"],
    },
    {
        "Stat": "Weekly team awards (Highest/Lowest score, Narrowest victory, Largest blowout, Most/Least efficient, Top half) + Times counts",
        "Sheet": "team_week (flag) + team_year/team_all_time (Times count)",
        "Formula": "Per (Year, Week): Highest / Lowest score = max / min PF; Narrowest victory / Largest blowout = smallest / largest winning margin; Most / Least efficient = max / min Efficiency; Top half of league? = PF at or above the week's median. team_year/all carry 'Times <award>?' counts.",
        "Notes": "Companion streaks are in the Streaks entry.",
        "Columns": ["Highest score?", "Lowest score?", "Narrowest victory?", "Largest blowout?",
                    "Most efficient?", "Least efficient?", "Top half of league?",
                    "Times Highest score?", "Times Lowest score?", "Times Narrowest victory?",
                    "Times Largest blowout?", "Times Most efficient?", "Times Least efficient?",
                    "Times Top half of league?"],
    },
    {
        "Stat": "Increase in points from previous week / Roster & Starter turnover from previous week / Difference in pregame avg max PF from opponent",
        "Sheet": "team_week (+ league_week)",
        "Formula": "Increase in points from previous week = PF − prior week's PF (week 1 vs last season's final week). Roster / Starter turnover from previous week = number of roster / starting-lineup slots that changed vs the prior week. 'Difference in pregame avg max PF from opponent' = the team's trailing average Max PF minus the opponent's, a pregame talent gauge.",
        "Notes": "Turnover rolls up to season averages on the year/all-time sheets.",
        "Columns": ["Increase in points from previous week", "Roster turnover from previous week",
                    "Starter turnover from previous week", "Difference in pregame avg max PF from opponent"],
    },
    {
        "Stat": "Hardship: Number of (starter) injuries / suspensions, players on bye + Starter-adjusted Hardship",
        "Sheet": "team_week (+ league_week / team_year / team_all_time)",
        "Formula": "Weekly counts of the team's injured / suspended players and players on bye, plus starter-only variants ('Number of starter injuries / suspensions'). Starter-adjusted Hardship = expected points lost from injured/suspended would-be starters, each weighted by how likely they were to start (effective starter %).",
        "Notes": "Bye excluded from Hardship. Year/all-time carry the season sums (Weeks of injuries / starter injuries / starter suspensions).",
        "Columns": ["Number of Injuries", "Number of suspensions", "Number of players on bye",
                    "Number of starter injuries", "Number of starter suspensions",
                    "Starter-adjusted Hardship"],
    },
    {
        "Stat": "Luck",
        "Sheet": "team_week / team_year",
        "Formula": "Weekly composite of how much a team's RESULT diverged from its performance/schedule: rewards unlucky losses / strong-but-beaten weeks and penalizes lucky wins, gated by win/loss, with opponent-strength, own-strength, closeness, efficiency and a losses-from-hardship penalty. team_year Luck = Σ weekly Luck (see plan/LUCK_REWORK.md for the exact weighting).",
        "Notes": "Each loss-from-hardship week subtracts 0.25. Calibrated so winning-to-talent nets ≈ 0.",
        "Columns": ["Luck"],
    },

    # -------------------------------- team_year / team_all_time --------------------------------
    {
        "Stat": "Win % / Record / All time record / All time win % / Differential / Avg differential",
        "Sheet": "team_year / team_all_time",
        "Formula": "Win % = wins+½·ties over games; Record = 'W-L' (regular season). All time record / win % pool every season. Differential = Σ Margin (PF − PA) over the period; Avg differential = its per-game mean.",
        "Notes": "Standalone identity columns (Team/Year) aren't documented; these computed aggregates are.",
        "Columns": ["Win %", "Record", "All time record", "All time win %", "Differential", "Avg differential"],
    },
    {
        "Stat": "Record / Win % vs playoff teams / non-playoff teams / champion(s) / last place",
        "Sheet": "team_year / team_all_time",
        "Formula": "Head-to-head record and win% restricted to opponents in a class that season: playoff teams (top-4 seed), non-playoff teams, the champion, and the last-place team. team_all_time pools the per-season class memberships.",
        "Notes": "PR E fix C: N/A for an in-progress season (classes unknown until it ends). 'champion' vs 'champions' / singular-plural variants exist across year vs all-time.",
        "Columns": ["Record vs playoff teams", "Win % vs playoff teams", "Record vs non-playoff teams",
                    "Win % vs non-playoff teams", "Record vs champion", "Win % vs champion",
                    "Record vs champions", "Win % vs champions", "Record vs last place", "Win % vs last place"],
    },
    {
        "Stat": "Result / Week of playoff elimination / Championships",
        "Sheet": "team_year / team_all_time",
        "Formula": "Result = the team's finish that season (Champion / 2nd / 3rd / 4th / Missed playoffs / Last place) from the playoff & toilet brackets. Week of playoff elimination = the week the team was knocked out (0 if it won it all / didn't make the bracket as scored). Championships (all-time) = career title count.",
        "Notes": "PR E fix C: N/A for an in-progress season.",
        "Columns": ["Result", "Week of playoff elimination", "Championships"],
    },
    {
        "Stat": "Roster / starter turnover (weekly avg, in-season, off-season)",
        "Sheet": "team_year / team_all_time / league_year",
        "Formula": "Average weekly roster / starter turnover = mean of the week-over-week turnover. Inseason turnover = unique roster / starting-lineup players changed between Week 1 and the championship week. Offseason turnover = change from the prior season's championship roster to this season's Week-1 roster.",
        "Notes": "All-time = per-season average, not a sum.",
        "Columns": ["Average weekly roster turnover", "Average weekly starter turnover",
                    "Inseason roster turnover", "Inseason starter turnover",
                    "Offseason roster turnover", "Offseason starter turnover"],
    },
    {
        "Stat": "Draft Value / Number of first round picks made / Total number of picks made",
        "Sheet": "team_year / team_all_time",
        "Formula": "Draft Value = Σ pick-slot value of the picks the team actually MADE that season (1/(slot+1)-style curve). Plus the counts of first-round and total picks made.",
        "Notes": "Excludes the 2021 vet/startup draft.",
        "Columns": ["Draft Value", "Number of first round picks made", "Total number of picks made"],
    },
    {
        "Stat": "Future draft capital / Amount of FAAB spent / Change in win % from previous season",
        "Sheet": "team_year / team_all_time (+ team_week future cap, league sheets FAAB)",
        "Formula": "Future draft capital = value of picks the team currently HOLDS for the next 3 years (own retained + acquired − traded away). Amount of FAAB spent = Σ winning waiver bids. Change in win % from previous season = this season's Win % minus last season's.",
        "Notes": "team_week future cap updates on each trade; team_year uses the season-end snapshot.",
        "Columns": ["Future draft capital", "Amount of FAAB spent", "Change in win % from previous season"],
    },
    {
        "Stat": "Avg yearly luck / Avg PF / Avg max PF / Avg points against / Avg margin",
        "Sheet": "team_year / team_all_time (+ league_year / league_all_time)",
        "Formula": "Per-period means: Avg yearly luck = mean of season Luck totals (all-time); Avg PF / Avg max PF / Avg points against / Avg margin = per-game means of PF / Max PF / Points against / Margin.",
        "Notes": "League sheets carry the league-wide versions.",
        "Columns": ["Avg yearly luck", "Avg PF", "Avg max PF", "Avg points against", "Avg margin"],
    },
    {
        "Stat": "Weeks of injuries / starter injuries / starter suspensions / suspensions + league weeks-missed totals",
        "Sheet": "team_year / team_all_time / league_year / league_all_time",
        "Formula": "Season/career sums of injured / suspended player-weeks (and starter-only variants) for the team; the league sheets carry the league-wide 'Number of weeks missed due to injury / suspensions'.",
        "Notes": "Starter variants use the same starter heuristic as Starter-adjusted Hardship.",
        "Columns": ["Weeks of injuries", "Weeks of starter injuries", "Weeks of starter suspensions",
                    "Weeks suspensions", "Number of weeks missed due to injury",
                    "Number of weeks missed due to suspensions"],
    },

    # -------------------------------- roster composition (team + league) --------------------------------
    {
        "Stat": "Number of QB/RB/WR/TE started & rostered",
        "Sheet": "team_week / team_year / team_all_time / league_week / league_year / league_all_time",
        "Formula": "Counts of players at each position the team started / rostered. Week sheets are per-week counts; year/all-time count DISTINCT players over the period.",
        "Columns": ["Number of QB started", "Number of QB rostered", "Number of RB started",
                    "Number of RB rostered", "Number of WR started", "Number of WR rostered",
                    "Number of TE started", "Number of TE rostered"],
    },
    {
        "Stat": "Same-NFL-team concentration + NFL-team spread",
        "Sheet": "team_week / team_year / team_all_time / league_week / league_year / league_all_time",
        "Formula": "'Most number of <players/QBs/RBs/WR/TE> started/rostered from same NFL team' = the largest group of the team's started/rostered players sharing one NFL team. 'Number of NFL teams among starting/rostered players' = how many distinct NFL teams were represented.",
        "Notes": "Year/all-time take the max (concentration) and distinct counts over the period.",
        "Columns": ["Most number of players started from same NFL team",
                    "Most number of players rostered from same NFL team",
                    "Most number of QBs started from same NFL team",
                    "Most number of QBs rostered from same NFL team",
                    "Most number of RBs started from same NFL team",
                    "Most number of RBs rostered from same NFL team",
                    "Most number of WR started from same NFL team",
                    "Most number of WR rostered from same NFL team",
                    "Most number of TE started from same NFL team",
                    "Most number of TE rostered from same NFL team",
                    "Number of NFL teams among starting players",
                    "Number of NFL teams among rostered players"],
    },
    {
        "Stat": "Number of rookies / cuffs started & rostered",
        "Sheet": "team_week / team_year / team_all_time / league_week / league_year / league_all_time",
        "Formula": "Counts of rookies and handcuffs (cuffs) the team started / rostered. Week = per-week; year/all-time = DISTINCT players.",
        "Columns": ["Number of rookies started", "Number of rookies rostered",
                    "Number of cuffs rostered", "Number of cuffs started"],
    },
    {
        "Stat": "Scoring-threshold counts (donuts / under 10 / over 20-50) + highest-vs-lowest starter spread",
        "Sheet": "team_week / team_year / team_all_time (+ league sheets for the non-starter variants)",
        "Formula": "Counts of the team's players (and starter-only variants) whose week score was a donut (0), under 10, or over 20/30/40/50. 'Difference between highest and lowest starters' = top starter score − bottom starter score that week.",
        "Notes": "Week = per-week counts; year/all-time = sums.",
        "Columns": ["Number of donuts", "Number of starter donuts", "Number of players under 10",
                    "Number of starters under 10", "Number of players over 20", "Number of starters over 20",
                    "Number of players over 30", "Number of starters over 30", "Number of players over 40",
                    "Number of starters over 40", "Number of players over 50", "Number of starters over 50",
                    "Difference between highest and lowest starters"],
    },
    {
        "Stat": "Player average age / Startup draft players remaining",
        "Sheet": "team_week / team_year / team_all_time / league_week / league_year / league_all_time",
        "Formula": "Player average age = mean age of the team's rostered players (year/all-time = mean of weekly averages, ≈ mid-season age). Startup draft players remaining = how many of the team's original 2021 startup-draft picks it still rosters.",
        "Notes": "Age anchored to the week date, not 'today'.",
        "Columns": ["Player average age", "Startup draft players remaining"],
    },

    # -------------------------------- league sheets (spread / extremes) --------------------------------
    {
        "Stat": "League weekly spread & extremes",
        "Sheet": "league_week / league_year / league_all_time",
        "Formula": "PF = total league points that week. Highest starter score = the single best starter score in the league. PF Range / Margin range = max−min of team PF / game margin. 'Number of games within 5 / within 10' = close games by final margin. '(smallest) Playoff tiebreaker' = the tightest seeding tiebreaker margin that season.",
        "Notes": "Year/all-time aggregate the weekly league values.",
        "Columns": ["PF", "Highest starter score", "PF Range", "Margin range",
                    "Number of games within 5", "Number of games within 10",
                    "(smallest) Playoff tiebreaker"],
    },

    # -------------------------------- transactions --------------------------------
    {
        "Stat": "Player Added / Player Dropped / Date dropped/traded / type of transaction",
        "Sheet": "transactions",
        "Formula": "The added and dropped player names for the move, the date the added player later left the team ('Date dropped/traded'), and 'type of transaction (waiver/free agency)' = how the add happened (waiver claim vs free-agent pickup vs commissioner add).",
        "Notes": "Player names are hyperlink targets (Phase 11D).",
        "Columns": ["Player Added", "Player Dropped", "Date dropped/traded",
                    "type of transaction (waiver/free agency)"],
    },
    {
        "Stat": "Transaction/trade value: Net points / Avg net points (± position) / Avg points lost (± position)",
        "Sheet": "transactions / trades",
        "Formula": "Production the move netted the team: Net points = points the added/received player(s) scored for the team minus points the dropped/sent player(s) would have scored over the same window. 'Avg net points' = per-game; '… adjusted by position' scales by positional value. 'Avg points lost (± position)' = the dropped/sent side's per-game production over the window.",
        "Notes": "Windows run from the move to the player's next exit (or today if still rostered).",
        "Columns": ["Net points", "Avg net points", "Avg net points adjusted by position",
                    "Avg points lost", "Avg points lost adjusted by position",
                    "Average PPG of dropped player over same time"],
    },
    {
        "Stat": "Transaction KTC: player added/dropped at deal time / end of season / 1 & 2 years later (+ Net KTC)",
        "Sheet": "transactions",
        "Formula": "KeepTradeCut (1QB) value of the added and dropped player at four reference points relative to the move — deal day, that season's end, and 1 & 2 years later — plus 'Net KTC value …' = added-side value minus dropped-side value at each. Sourced from the dynasty-daddy KTC history.",
        "Notes": "N/A for an untracked player, a future reference date, or pre-April-2021 history.",
        "Columns": ["KTC value of player added at end of season", "KTC value of player added 1 year later",
                    "KTC value of player added 2 years later", "KTC value of player dropped at deal time",
                    "KTC value of player dropped at end of season", "KTC value of player dropped 1 year later",
                    "KTC value of player dropped 2 years later", "Net KTC value at end of season",
                    "Net KTC value 1 year later", "Net KTC value 2 years later"],
    },
    {
        "Stat": "Transaction lineage links (next/previous, added/dropped player)",
        "Sheet": "transactions",
        "Formula": "Cross-references to the next / previous transaction involving the same added or dropped player, so you can follow a player's move chain. In the xlsx these are clickable links to the referenced transaction row.",
        "Columns": ["Link to next transaction (added player)", "Link to previous transaction (added player)",
                    "Link to next transaction (dropped player)", "Link to previous transaction (dropped player)"],
    },

    # -------------------------------- trades --------------------------------
    {
        "Stat": "Team's traded with / trade KTC value difference (end of season / 1 & 2 years later)",
        "Sheet": "trades",
        "Formula": "Team's traded with = the counterparties in the deal. 'KTC value difference …' = (received-asset KTC) − (sent-asset KTC) at that season's end and 1 & 2 years later — i.e. who came out ahead by realized dynasty value over time.",
        "Notes": "Positive favors the row's team. N/A when references are in the future / untracked.",
        "Columns": ["Team's traded with", "KTC value difference at end of season",
                    "KTC value difference 1 year later", "KTC value difference 2 years later"],
    },

    # -------------------------------- picks --------------------------------
    {
        "Stat": "Player Picked",
        "Sheet": "picks",
        "Formula": "The player the pick was used on (blank/'Unknown' for an unmade pick).",
        "Notes": "Hyperlink target (Phase 11D).",
        "Columns": ["Player Picked"],
    },
    {
        "Stat": "Pick KTC checkpoints (draft day / end of rookie year / 1-4 years after)",
        "Sheet": "picks",
        "Formula": "The drafted player's KTC (1QB) value at six checkpoints relative to the draft: draft day (≈ Aug 28), end of rookie year (≈ Feb 1 after), and 1/2/3/4 years after draft day.",
        "Notes": "Future checkpoints and pre-history dates are N/A.",
        "Columns": ["KTC on draft day", "KTC at end of rookie year", "KTC 1 year after draft day",
                    "KTC 2 years after draft day", "KTC 3 years after draft day", "KTC 4 years after draft day"],
    },
    {
        "Stat": "Pick-adjusted Difference columns (value vs the pick's slot expectation)",
        "Sheet": "picks",
        "Formula": "Each 'Pick-adjusted Difference in <X>' = the pick's realized <X> minus the average <X> of a comparison set of nearby pick slots (the slot's expected return), so a positive value means the pick beat its draft position. Applies to Player addition value, the on-team / career / points-added adjusted PPGs, and each KTC checkpoint.",
        "Notes": "Comparison baseline = the 3-pick window around the slot plus a 4th averaged-outer pick (from slot 1.05 on); 1.01–1.04 use the pooled mean.",
        "Columns": ["Pick-adjusted Difference in Player addition value",
                    "Pick-adjusted Difference in Avg PPG on team adjusted by position",
                    "Pick-adjusted Difference in Avg career PPG adjusted by position",
                    "Pick-adjusted Difference in Avg points added adjusted by position",
                    "Pick-adjusted Difference in KTC on draft day",
                    "Pick-adjusted Difference in KTC at end of rookie year",
                    "Pick-adjusted Difference in KTC 1 year after draft day",
                    "Pick-adjusted Difference in KTC 2 years after draft day",
                    "Pick-adjusted Difference in KTC 3 years after draft day",
                    "Pick-adjusted Difference in KTC 4 years after draft day"],
    },
]


# Output columns of the Formulas sheet (in order). "Columns" is INTERNAL
# coverage metadata (the exact column names an entry documents, used by
# the coverage check below + tests/test_formulas_coverage.py) and is NOT emitted.
_OUTPUT_FIELDS = ["Stat", "Sheet", "Formula", "Notes"]


def build_output(context):
    return pd.DataFrame([{k: r.get(k, "") for k in _OUTPUT_FIELDS} for r in _ROWS])


# --- Phase 11A coverage check (shared by the build-time assert and the test) ---
import re as _re

# Pure identity / label columns exempt from needing a formula entry.
IDENTITY_ALLOWLIST = {
    "player", "player id", "team", "year", "week", "week name", "position",
    "position started in (if starter)", "nfl team", "opponent",
    "opponent team (raw)", "starter/bench", "season", "date", "points", "etc",
}
# Dynamically generated per-opponent / per-team / pick-hop columns, documented generically.
_GENERATED_PREFIXES = ("record vs ", "win % vs ", "longest win streak vs ",
                       "team for ", "trade ")


def _norm(s):
    return _re.sub(r"\s+", " ", str(s).strip().lower())


def documented_columns():
    """Normalized set of every column name an entry documents (Stat tokens + Columns)."""
    out = set()
    for e in _ROWS:
        for part in str(e.get("Stat", "")).split("/"):
            out.add(_norm(part))
        for c in (e.get("Columns") or []):
            out.add(_norm(c))
    return out


def undocumented_columns(catalog):
    """Return the sorted list of output columns (across the data sheets in
    `catalog`, a {sheet: [cols]} dict) that have no Formulas entry and aren't
    identity/generated. Empty when coverage is complete."""
    documented = documented_columns()
    data_sheets = ["Player-Week", "Player-year", "Player-all-time",
                   "team-week", "team-year", "team-all-time",
                   "league-week", "league-year", "league-all-time",
                   "transactions", "trades", "picks"]
    seen, missing = set(), []
    for sheet in data_sheets:
        for col in (catalog.get(sheet) or []):
            n = _norm(col)
            if n in seen:
                continue
            seen.add(n)
            if n in IDENTITY_ALLOWLIST or n in documented:
                continue
            if any(n.startswith(p) for p in _GENERATED_PREFIXES):
                continue
            missing.append(col)
    return sorted(missing)
