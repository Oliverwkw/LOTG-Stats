"""Formulas sheet — the Equation column: every stat as an equation in raw API data.

`formulas.py` documents each stat in prose. This module restates each one as an
equation whose variables are only fields pulled straight from the source APIs
(Sleeper, ESPN for 2020, nflverse, KeepTradeCut) and the hand-curated data/
files the build reads.

* ENTRIES — one row per symbol: the raw API variables, the operators defined
  purely in them, the per-row context symbols, and the fitted / simulated models
  (Wins added's counterfactual lineup, Boldness's expected points, Price paid's
  money curve, Points above expectation's Poisson fit) written out in full.
* A symbol used by MIN_USES (5) or more equations — directly or through another
  entry's definition — is a glossary row at the top of the sheet; any other is
  defined in-cell, after the equation ("— where …"), in every cell that uses it.
* ⟨Stat⟩ — substitute the equation of that row of the Formulas sheet.

Every formulas._ROWS entry has exactly one equation in EQUATIONS, keyed by
(Stat, Sheet) (tests/test_formula_equations.py holds that 1:1).
"""

COLUMN = "Equation (API stats only)"
RAW_SHEET = "Raw API variables"
OPS_SHEET = "Defined operators"
CTX_SHEET = "Row context symbols"
MODEL_SHEET = "Model definitions"

import functools as _ft
import re as _re

# A symbol gets a glossary row only when MIN_USES or more equations use it,
# directly or through another glossary row's definition (user rule,
# 2026-10-04). Every other symbol is defined in-cell, appended to each
# equation that uses it ("— where …"). One symbol per row, so the rule is
# applied symbol by symbol.
MIN_USES = 5

_FN = r"(?<![\w$]){}\("          # function-style use: name(
_BARE = r"(?<![\w$']){}(?![\w'(])"   # bare use


def _fn(*names):
    return tuple(_FN.format(_re.escape(n)) for n in names)


def _bare(*names):
    return tuple(_BARE.format(_re.escape(n)) for n in names)


ALWAYS = None   # an entry whose pattern is ALWAYS is notation: always a glossary row

RAW, OPS, CTX, MOD = "raw", "ops", "ctx", "model"
SHEET_OF = {RAW: RAW_SHEET, OPS: OPS_SHEET, CTX: CTX_SHEET, MOD: MODEL_SHEET}

# (block, symbol, meaning, definition — for a raw variable its API source, patterns)
ENTRIES = [
    # ---- raw API variables ----
    (RAW, "p, t, y, w, d, x, k",
     "Indices: p player (Sleeper player_id), t team (Sleeper roster_id, labelled by its owner's display_name), y season, w week, d date (league / Eastern time), x transaction, k scoring stat.",
     "Sleeper /league/{id}/rosters (roster_id, owner_id), /users (display_name)", ALWAYS),
    (RAW, "pts(p,w)", "Fantasy points the league scored player p in week w.",
     "Sleeper GET /league/{id}/matchups/{w} → players_points[p]; 2020: ESPN mMatchup per-player appliedTotal", _fn("pts")),
    (RAW, "S(t,w)", "Starting lineup of roster t in week w, in slot order; '0' marks an empty slot.",
     "Sleeper matchups → starters; 2020: ESPN lineupSlotId ≠ bench", _fn("S")),
    (RAW, "R(t,w)", "Every player on roster t in week w (starters + bench + taxi + IR).",
     "Sleeper matchups → players; 2020: ESPN mRoster", _fn("R")),
    (RAW, "P(t,w)", "Roster t's raw matchup score in week w (Σ starters' points).",
     "Sleeper matchups → points; 2020: ESPN pointsByScoringPeriod", _fn("P")),
    (RAW, "o(t,w)", "Opponent: the other roster sharing t's matchup_id in week w.",
     "Sleeper matchups → matchup_id; 2020: ESPN schedule", _fn("o") + _bare("o")),
    (RAW, "slots(y)", "Lineup slots of season y, each a set of eligible positions.", "Sleeper GET /league/{id} → roster_positions", _fn("slots")),
    (RAW, "pws(y)", "First playoff week of season y.", "Sleeper GET /league/{id} → settings.playoff_week_start", _fn("pws")),
    (RAW, "rules(y,k)", "Points per unit of scoring stat k in season y.",
     "Sleeper GET /league/{id} → scoring_settings; 2018-20: the ESPN league's scoring table", _fn("rules")),
    (RAW, "WB(y)", "Winners' bracket matchups (round, t1, t2, winner, loser).", "Sleeper /league/{id}/winners_bracket", _fn("WB") + _bare("WB")),
    (RAW, "LB(y)", "Losers' bracket matchups.", "Sleeper /league/{id}/losers_bracket", _fn("LB") + _bare("LB")),
    (RAW, "type(x)", "Transaction type: waiver / free_agent / commissioner / trade.", "Sleeper /league/{id}/transactions/{round} → type; 2020: ESPN mTransactions2", _fn("type")),
    (RAW, "status(x)", "Transaction status: complete / failed.", "Sleeper transactions → status", _fn("status") + (r"status = complete", r"status complete")),
    (RAW, "d(x)", "Transaction date (ET).", "Sleeper transactions → status_updated", _fn("d")),
    (RAW, "ts(x)", "Transaction timestamp.", "Sleeper transactions → status_updated", _fn("ts")),
    (RAW, "adds(x)", "Player → roster map of players added.", "Sleeper transactions → adds", _fn("adds")),
    (RAW, "drops(x)", "Player → roster map of players dropped.", "Sleeper transactions → drops", _fn("drops")),
    (RAW, "rosters(x)", "Rosters involved in the transaction.", "Sleeper transactions → roster_ids", _fn("rosters")),
    (RAW, "bid(x)", "FAAB bid on a waiver claim.", "Sleeper transactions → settings.waiver_bid", _fn("bid")),
    (RAW, "dp(x)", "Draft picks traded: season, round, roster_id (original owner), previous_owner_id, owner_id.", "Sleeper transactions → draft_picks", _fn("dp")),
    (RAW, "wb(x)", "FAAB traded: sender, receiver, amount.", "Sleeper transactions → waiver_budget", _fn("wb")),
    (RAW, "round(pk)", "Round of draft pick pk.", "Sleeper /draft/{id}/picks → round", _fn("round")),
    (RAW, "pick_no(pk)", "Overall pick number.", "Sleeper /draft/{id}/picks → pick_no", _fn("pick_no") + _bare("pick_no")),
    (RAW, "dslot(pk)", "Draft slot of the pick.", "Sleeper /draft/{id}/picks → draft_slot", _fn("dslot", "draft_slot") + _bare("dslot")),
    (RAW, "pl(pk)", "Player picked.", "Sleeper /draft/{id}/picks → player_id", _fn("pl") + _bare("pl")),
    (RAW, "by(pk)", "Roster that made the pick.", "Sleeper /draft/{id}/picks → roster_id / picked_by", _fn("by") + (r"[(,] ?by ?[,)]", r"by = ", r"= by\b")),
    (RAW, "dd(Y)", "Draft day of the season-Y draft.", "Sleeper /draft/{id} → start_time", _fn("dd") + _bare("dd")),
    (RAW, "slot_to_roster_id", "Draft slot → original roster.", "Sleeper /draft/{id} → slot_to_roster_id", _fn("slot_to_roster_id") + _bare("slot_to_roster_id")),
    (RAW, "own(Y,r,t0)", "Current owner of the season-Y round-r pick originally t0's.", "Sleeper /league/{id}/traded_picks → season, round, roster_id, owner_id", _fn("own")),
    (RAW, "birth(p)", "Birth date.", "Sleeper /players/nfl → birth_date", _fn("birth")),
    (RAW, "posS(p)", "Fantasy position.", "Sleeper /players/nfl → position", _fn("posS") + _bare("posS")),
    (RAW, "teamS(p)", "NFL team.", "Sleeper /players/nfl → team", _fn("teamS")),
    (RAW, "yexp(p)", "Years of NFL experience.", "Sleeper /players/nfl → years_exp", _fn("yexp")),
    (RAW, "rookie_year(p)", "Rookie season.", "Sleeper /players/nfl → metadata (rookie year)", _fn("rookie_year")),
    (RAW, "injS(p)", "Injury status.", "Sleeper /players/nfl → injury_status", _fn("injS") + _bare("injS")),
    (RAW, "s(p,y,w,k)", "Player p's NFL stat k in week w of season y.", "nflverse stats_player_week_{y}", _fn("s")),
    (RAW, "npts(p,y,w)", "Σ_k rules(y,k)·s(p,y,w,k) — the NFL stat line scored with that season's league rules.",
     "nflverse stats_player_week × Sleeper scoring_settings (2018-20: the ESPN table)", _fn("npts") + _bare("npts")),
    (RAW, "posN(p,y,w)", "Position on the stat line.", "nflverse stats_player_week → position", _fn("posN")),
    (RAW, "teamN(p,y,w)", "NFL team on the stat line.", "nflverse stats_player_week → team", _fn("teamN") + _bare("teamN")),
    (RAW, "snap(p,y,w)", "Offense + defense + special-teams snaps.", "nflverse snap_counts_{y}", _fn("snap")),
    (RAW, "wr(p,y,w)", "Weekly NFL roster row (team, status, position).", "nflverse roster_weekly_{y}", _fn("wr")),
    (RAW, "ko(team,y,w)", "Kickoff (ET date and time) of the NFL team's week-w game; none = bye.", "nflverse schedules games.csv → gameday + gametime", _fn("ko")),
    (RAW, "gd(team,y,w)", "Game date (ET) of the NFL team's week-w game; none = bye.", "nflverse schedules games.csv → gameday", _fn("gd") + _bare("gd")),
    (RAW, "K(a,d)", "KeepTradeCut superflex value of asset a (player or pick) on date d.",
     "keeptradecut.com history (playerSuperflex / sf_trade_value), mirrored by dynasty-daddy.com from 2021-04-16", _fn("K")),
    (RAW, "ID bridge", "sleeper_id ↔ gsis_id ↔ KTC id crosswalk (a join key, not a stat).",
     "DynastyProcess db_playerids.csv, nflverse players.csv", ALWAYS),
    (RAW, "SUSP(p,y,w)", "Hand-curated suspension weeks.", "data/suspensions.csv", _fn("SUSP")),
    (RAW, "GDS(p,y,w)", "Hand-curated game-day active / inactive status for zero-snap weeks (2020-25).", "data/game_day_status.csv", _fn("GDS")),
    (RAW, "CPM", "Hand-curated off-platform commissioner pick moves.", "data/commissioner_pick_trades.csv", _bare("CPM")),
    (RAW, "MTX", "Hand-curated manual transactions.", "data/manual_transactions.csv", _bare("MTX")),
    # ---- defined operators ----
    (OPS, "[c]", "Iverson bracket.", "1 if condition c holds, else 0.", ALWAYS),
    (OPS, "⟨Stat⟩", "Cross-reference.", "Substitute that row's equation from this column.", ALWAYS),
    (OPS, "st(p,t,w)", "Started.", "[p ∈ S(t,w)].", _fn("st") + _bare("st")),
    (OPS, "ro(p,t,w)", "Rostered.", "[p ∈ R(t,w)]; bench = ro ∧ ¬st.", _fn("ro") + _bare("ro")),
    (OPS, "pos(p,y,w)", "Position that week.", "posN(p,y,w) if the stat line exists, else posS(p) (Travis Hunter pinned WR).", _fn("pos") + _bare("pos")),
    (OPS, "nfl(p,y,w)", "NFL team that week.", "teamN(p,y,w) → p's season teamN → wr(p,y,w).team → 'NFL' (no NFL team).", _fn("nfl")),
    (OPS, "APP(p,y,w)", "Appeared in the NFL game.", "[p has a stat line in s(·,y,w)] ∨ [snap(p,y,w) > 0].", _fn("APP") + _bare("APP")),
    (OPS, "BYE(p,w)", "Bye?", "[pts(p,w) = 0 ∧ (nfl(p,y,w) = 'NFL' ∨ no gd(nfl(p,y,w), y, w))].", _fn("BYE") + _bare("BYE")),
    (OPS, "SUS(p,w)", "Suspension?", "¬BYE(p,w) ∧ (SUSP(p,y,w) ∨ injS(p) = 'NA' that week).", _fn("SUS") + _bare("SUS")),
    (OPS, "INJ(p,w)", "Injury?", "ro ∧ pts(p,w) = 0 ∧ ¬APP(p,y,w) ∧ ¬BYE ∧ ¬SUS ∧ ¬[GDS(p,y,w) = active].", _fn("INJ") + _bare("INJ")),
    (OPS, "H(p,w)", "Healthy / played week.", "¬BYE(p,w) ∧ ¬INJ(p,w) ∧ ¬SUS(p,w).", _fn("H") + _bare("H")),
    (OPS, "seed(t,y)", "Regular-season standing.", "Rank of t by (Σ_{w ∈ REG} win(t,w), Σ_{w ∈ REG} P(t,w)), descending.", _fn("seed")),
    (OPS, "PF(t,w)", "Points for, with the semifinal +5.", "P(t,w) + 5·[w = pws(y) ∧ t is the better seed of a top-4 semifinal pair].", _fn("PF") + _bare("PF")),
    (OPS, "PA(t,w)", "Points against.", "PF(o(t,w), w).", _fn("PA") + _bare("PA")),
    (OPS, "win(t,w)", "Result.", "[PF > PA] + ½[PF = PA] (2026+ two-week final: PF summed over both weeks).", _fn("win") + _bare("win")),
    (OPS, "REG", "Regular-season weeks.", "{w < pws(y)}.", _bare("REG")),
    (OPS, "stage(t,w)", "Game type.", "From WB(y) / LB(y) rounds: Semifinal, Final, 3rd Place, Toilet Semis, Toilet Final, Toilet losers; 'Week N' for w ∈ REG.", _fn("stage")),
    (OPS, "PO", "Championship-bracket games.", "{w : stage(t,w) ∈ {Semifinal, Final}}.", _bare("PO")),
    (OPS, "champ(y)", "Champion.", "The winner of WB(y)'s Final.", _fn("champ")),
    (OPS, "N", "Number of teams.", "|{roster_id}|.", (r"(?<![\w$'])N(?![\w'(/])",)),
    (OPS, "OPT(X, y)", "Optimal lineup.", "Greedy best lineup of point set X by posS: top 1 QB, 2 RB, 3 WR, 1 TE, then FLEX from RB/WR/TE (2 FLEX from 2024), then 1 SUPERFLEX from QB/RB/WR/TE; returns the sum.", _fn("OPT")),
    (OPS, "MaxPF(t,w)", "Max PF.", "OPT({pts(p,w) : p ∈ R(t,w)}, y).", _fn("MaxPF") + _bare("MaxPF")),
    (OPS, "F(y,q)", "Position factor.", "mean{pts(p,w) : st, season y'} / mean{pts(p,w) : st, season y', pos(p) = q}; y' = y once week 5 of y is played, else y − 1.", _fn("F") + _bare("F")),
    (OPS, "age(p,d)", "Age.", "(d − birth(p)) / 365.25.", _fn("age")),
    (OPS, "agepk(Y,d)", "Age of a future season-Y pick.", "(d − Sep 1 of (Y − 22)) / 365.25.", _fn("agepk")),
    (OPS, "dw(y,w)", "Date a week is aged at.", "Sep 1 of y + 7(w − 1).", _fn("dw") + _bare("dw")),
    (OPS, "fw(d)", "Week of a date.", "The fantasy week whose Tuesday-Monday span contains d (a Tue/Wed move counts toward the coming week).", _fn("fw")),
    (OPS, "eos(y)", "Season end.", "The Monday after season y's championship week.", _fn("eos")),
    (OPS, "GL(p)", "NFL game log.", "p's games {(gd, npts(p,y,w)) : APP(p,y,w)} in date order.", _fn("GL") + _bare("GL")),
    (OPS, "avgN(p,d,n)", "Average of recent NFL games.", "Mean npts of the last min(n, available) GL(p) games with gd < d (ET day).", _fn("avgN")),
    (OPS, "ppg_nfl(p,[a,b))", "NFL points per game in a window.", "mean{npts(p,y,w) : APP(p,y,w), gd(nfl(p),y,w) ∈ [a,b)}.", _fn("ppg_nfl")),
    (OPS, "T", "Tenure.", "[start, e) of p on t from its acquisition.", _bare("T")),
    (OPS, "e", "Tenure end.", "The first date after the start with drops(x)[p] = t or p sent by t in a trade; else today.", (r"(?<![\w$'])e(?![\w'(^])",)),
    (OPS, "Wk(p,t,T)", "Tenure weeks.", "{w in T : ro(p,t,w) = 1}.", _fn("Wk") + _bare("Wk")),
    (OPS, "ppg_on(p,t,T)", "On-team points per game.", "Σ_{w ∈ Wk : H(p,w)} pts(p,w) / |{w ∈ Wk : H(p,w)}|.", _fn("ppg_on")),
    (OPS, "nst", "Tenure starts.", "Σ_{w ∈ Wk} st(p,t,w).", _bare("nst")),
    (OPS, "nH", "Tenure healthy weeks.", "|{w ∈ Wk : H(p,w)}|.", _bare("nH")),
    (OPS, "nstH", "Tenure healthy starts.", "Σ_{w ∈ Wk : H(p,w)} st(p,t,w).", _bare("nstH")),
    (OPS, "ω(r)", "Future-pick round weight.", "{1: 0.25, 2: 0.09, 3: 0.03, 4: 0.01}, 0 otherwise.", _fn("ω")),
    (OPS, "E_h(p,w)", "Hardship expectation.", "Over p's last 6 healthy weeks before w (league weeks with H, plus nflverse-only weeks at npts), drop the most recent and average the rest (one week: that week).", _fn("E_h") + _bare("E_h")),
    (OPS, "s_h(p,w)", "Hardship start share.", "Mean st over the same weeks as E_h (nflverse-only weeks = 0); 0 → mean st over p's next ≤ 5 healthy weeks of the season, for w ≥ 2 with < 5 prior league weeks.", _fn("s_h") + _bare("s_h")),
    (OPS, "TEST(q,p,w)", "Handcuff test.", "pos(q) = pos(p), nfl(q) = nfl(p), and (avg8(q) − avg8(p) ≥ 10, or avg8(q)·F(y,pos q) ≥ 13·F(y,TE), or q a top-12 pick of season y's rookie draft once held (2020: the first 12 NFL rookies of the startup)); avg8 = avgN(·, d, 8), q needing 8 games.", _fn("TEST")),
    (OPS, "CUFF(p,t,d)", "Handcuff at a move.", "∃ q ∈ R(t) at d with TEST(q,p).", _fn("CUFF")),
    (OPS, "Q_q", "Positional starter-score pool.", "{pts(p,w) : st, H, pos(p) = q, all seasons}.", _bare("Q_q", "Q_pos") + _fn("Q_pos")),
    (OPS, "qN", "Positional percentile bars.", "The N-th percentile of Q_q (q10, q25, q75, q90).", _bare("q10", "q25", "q75", "q90")),
    (OPS, "tier", "Positional scoring tier.", "Bust ≤ q10 < Lower < q25 ≤ Middle < q75 ≤ Upper < q90 ≤ Boom.", _bare("tier") + _fn("tier")),
    (OPS, "RL(q,w)", "Replacement level.", "Mean of the lowest third of {pts(p,w) : st, pos(p) = q} in week w.", _fn("RL")),
    (OPS, "pctl(v ; V)", "Percentile.", "100 · (average rank of v in V, ascending) / |V|; ties share the average rank.", _fn("pctl")),
    (OPS, "RUN", "Streak encoding.", "Terminal encoding of a boolean sequence: on a run's last element its length, 'In Progress' on earlier elements, 0 where false; skipped weeks read blank.", _bare("RUN") + (r"RUN_",)),
    (OPS, "z_wk", "Week standardiser.", "clip((v − mean_{y,w} v) / sd_{y,w} v, ±2.5) / 2.5 within each league week.", _fn("z_wk")),
    (OPS, "z_all", "Standardiser.", "(v − mean v) / sd v over all rows.", _fn("z_all")),
    (OPS, "DT(X,d)", "Depth-taxed KTC.", "Σ_i 0.6^(i−1)·K(X_(i), d), assets sorted by K descending; a FAAB amount valued at κ·amount.", _fn("DT")),
    (OPS, "κ", "KTC per FAAB $.", "100 (a locked league rule).", _bare("κ")),
    (OPS, "sd", "Standard deviation.", "Sample standard deviation (n − 1).", (r"(?<![\w$])sd[({_]",)),
    (OPS, "median", "Median.", "The middle value (mean of the two middle values for an even count).", _bare("median") + (r"median_",)),
    (OPS, "rank_X", "Rank.", "Rank by X, 1 = highest.", (r"rank_",)),
    (OPS, "clamp(v,a,b)", "Clamp.", "min(max(v,a),b).", _fn("clamp")),
    # ---- row context symbols ----
    (CTX, "a, r (add_drops)", "The added and dropped player.", "a = the p with adds(x)[p] = t; r = the p with drops(x)[p] = t.", ALWAYS),
    (CTX, "d0", "Move date.", "d(x).", _bare("d0")),
    (CTX, "y0", "Move season.", "The season the move is filed under.", _bare("y0")),
    (CTX, "e_a", "Added player's tenure end.", "e for a's tenure on t from d0.", _bare("e_a")),
    (CTX, "St", "Started tenure weeks.", "{w ∈ Wk(a,t,T) : st(a,t,w) = 1}.", _bare("St")),
    (CTX, "w*", "First start.", "min St (or the first started tenure week).", (r"w\*",)),
    (CTX, "Bd", "Waiver bidders.", "Rosters u with a counted claim on a in x's waiver run (type = waiver on a, status complete or failed, not failed for roster limit / insufficient FAAB / an already-played drop).", _bare("Bd")),
    (CTX, "c_u", "A bidder's counted claim.", "u's winning claim, else u's last-created claim on a.", _bare("c_u")),
    (CTX, "A", "Assets received (trades).", "adds(x)[p] = t, dp(x).owner_id = t, wb(x).receiver = t.", (r"(?<![\w$'/])A(?![\w'(])",)),
    (CTX, "B", "Assets sent (trades).", "drops(x)[p] = t, dp(x).previous_owner_id = t, wb(x).sender = t.", (r"(?<![\w$'/])B(?![\w'(])",)),
    (CTX, "A'", "Received players who played here.", "{q ∈ A players : Wk(q,t,T_q) ≠ ∅} ∪ {pl(pk) : pk ∈ A, by(pk) = t, own(pk) = t from d0 to the draft, Wk ≠ ∅}.", (r"A'",)),
    (CTX, "T_q", "A received player's tenure.", "[d0 (dd for a drafted pick), e_q).", (r"T_q",)),
    (CTX, "e*", "End of the received side.", "max_{q ∈ A'} e_q (open → today); A' = ∅ → min(today, d0 + 4 years).", (r"e\*",)),
    (CTX, "k_w", "Received starters in week w.", "Σ_{q ∈ A'} st(q,t,w).", _bare("k_w")),
    (CTX, "M", "Matched weeks.", "|{w : k_w ≥ 1}|.", _bare("M")),
    (CTX, "pk, Y (pick rows)", "The pick and its draft season.", "pk = the pick, Y = its draft season.", ALWAYS),
    (CTX, "ov", "Overall pick.", "(round − 1)·N + dslot; 2021 vet picks continue after the startup's last.", _bare("ov") + _fn("ov")),
    (CTX, "base(v)", "Draft-slot baseline.", "rookie_picks: window S_ov = {ov−1, ov, ov+1} (ov = 1 → {1,2}; last → the last three), all classes pooled; m_s = mean of v over picks at slot s; base = mean(m_{ov−1}, m_ov, m_{ov+1}, ½(m_{ov−1} + m_{ov+1})) for ov ≥ 5, else the mean of every v in S_ov. non_rookie_picks: the mean of v over the 8 nearest other picks by ov on the same side of the startup / vet seam.", _fn("base")),
    (CTX, "d_a", "Acquisition date (player_additions).", "The date the tenure starts.", _bare("d_a")),
    (CTX, "y_w", "Season of week w.", "y such that w is a week of season y.", _bare("y_w")),
    (CTX, "N_w", "Teams playing in week w.", "|{t : o(t,w) defined}|.", _bare("N_w")),
    (CTX, "n(t,o)", "Head-to-head games.", "|{w : o(t,w) = o}|.", _fn("n")),
    (CTX, "last(y)", "Last place.", "The roster with seed(·,y) = N.", _fn("last")),
    (CTX, "w1", "Week 1.", "The first week of the season.", _bare("w1")),
    (CTX, "wF", "Championship week.", "The season's last week.", _bare("wF")),
    (CTX, "w_final(y)", "Final's week.", "The week of WB(y)'s Final.", _fn("w_final")),
    (CTX, "kick(y)", "Season kickoff.", "min over teams of gd(team, y, 1).", _fn("kick")),
    (CTX, "w_kick", "Week's first kickoff.", "The roster as of week w's first game.", _bare("w_kick")),
    (CTX, "asof", "As-of clock.", "The latest week whose games are final, or the latest roster move if later.", _bare("asof")),
    (CTX, "ref", "Start/sit reference player.", "For a starter, the best startable bench player by pts; for a bench player, the worst benchable starter.", _bare("ref")),
    (CTX, "avg5(q)", "5-game regular-season average.", "Mean npts(q) over q's last 5 regular-season NFL games before week w (APP; a snap with no stat line = 0).", _fn("avg5")),
    (CTX, "U", "Player-team tenure weeks.", "p's weeks with ro(p,t,w) = 1 in this stint run.", _bare("U")),
    (CTX, "τ", "A tier.", "τ ∈ {Boom, Upper, Middle, Lower, Bust}.", _bare("τ")),
    (CTX, "age*(q,d)", "Asset age.", "age(q,d) for a player; agepk(Y,d) for a season-Y pick.", (r"age\*",)),
    (CTX, "SIS", "Sisenzweig flag.", "⟨Sisenzweig⟩(t,w).", _bare("SIS")),
    (CTX, "BROS", "Brosenzweig flag.", "⟨Brosenzweig⟩(t,w).", _bare("BROS")),
    (CTX, "LFH", "Loss from hardship flag.", "⟨Loss from hardship?⟩(t,w).", _bare("LFH")),
    (CTX, "Hard", "Hardship.", "⟨Hardship⟩(t,w).", _bare("Hard")),
    (CTX, "SAHard", "Starter-adjusted Hardship.", "⟨Starter-adjusted Hardship⟩(t,w).", _bare("SAHard")),
    (CTX, "μPF, μMax, μwin", "Season means.", "Means of PF, MaxPF, win over all of t's games in season y (subscript o: the opponent's).", (r"μPF", r"μMax", r"μwin")),
    # ---- model definitions: Wins added (lotg_support.wins_added) ----
    (MOD, "RES(a,b)", "Result of a score pair.", "[a > b] + ½[a = b] after rounding both to 0.01.", _fn("RES")),
    (MOD, "w0", "Move's first week.", "The first league week whose last game is on or after d0.", _bare("w0")),
    (MOD, "G", "The move's games.", "t's games from w0 through the latest week (each week one game; 2026+: the two Final weeks against the same opponent are one game, PF summed).", _bare("G")),
    (MOD, "GU(move)", "Given-up players.",
     "For each player g the move sent (a sent pick: pl of that pick, from his first week as a rookie): active in weeks [max(w0, start), end], end = the earlier of (a) the week completing a run of 4 straight weeks with g in no R(·,w), (b) the week before t's later move that receives g back.", _fn("GU") + _bare("GU")),
    (MOD, "LIN(move)", "Received lineage.",
     "Items (player, share s, group j, acquired, ended). Start: every asset received, s = 1, j = 0. Walk t's later moves m' in time order: a received pick drafted by t becomes pl(pick) at dd (same s, j); every live item that m' sends ends at d(m'); a drop ends the lineage; a trade's received assets join as group j+1 with s' = clamp(Σ_{items i sent} s_i·K(i, d(m')) / Σ_{assets t sent in m'} K(·, d(m')), 0, 1) (FAAB valued 0; no K on the side → Σ s_i / |sent|). Present in week w: on R(t,w), acquired ≤ w's last game day, ended after w's start.", _fn("LIN") + _bare("LIN")),
    (MOD, "a3(p,w)", "3-game average.", "Mean npts(p) over p's last 3 NFL games before week w (undefined with < 3).", _fn("a3") + _bare("a3")),
    (MOD, "val(p,w)", "Entry value.", "pts(p,w) (any roster, else npts(p,y,w), else 0) if p ∈ ∪_u S(u,w), else min(that, 1.5·a3(p,w)).", _fn("val")),
    (MOD, "proven(p,w)", "Proven player.", "a3(p,w) defined or p ∈ ∪_u S(u,w).", _fn("proven") + _bare("proven")),
    (MOD, "elig_y(p)", "Season eligibility.", "{posS(p)} ∪ {the single position of every one-position slot p started in during season y}.", _fn("elig_y") + _bare("elig_y")),
    (MOD, "LEGAL(L, y)", "Legal lineup.", "A matching of the players of L into slots(y) exists, each into a slot whose positions meet elig_y(p).", _fn("LEGAL") + _bare("LEGAL")),
    (MOD, "LCF(t,w; OUT, IN)", "Counterfactual lineup points.",
     "Kp = S(t,w) ∖ OUT (kept starters), C = slots of starters in OUT (cleared), E_r = slots really empty; arrivals Arr = proven players of IN not on R(t,w) (or on it via OUT); bench Bn = proven players of R(t,w) ∖ S(t,w) ∖ OUT ∖ Arr. Fill bar f = the |C|-th highest a3 among Arr ∪ Bn able to take a cleared slot; plausible(q) = a3(q) ≥ f − 5. Candidates L = (Kp ∖ Dp) ∪ Ar ∪ Fl: Ar ⊆ Arr; Dp ⊆ Kp matched one-to-one to displacers in Ar with val(u) > val(k) and a3(u) ≥ a3(k) − 5; |Ar| − |Dp| ≤ |C| + |E_r|; Fl ⊆ Bn of size ≤ max(0, |C| − (|Ar| − |Dp|)) taken greedily (plausible first, then val) while LEGAL; L must be LEGAL and, if it holds any real bench player, all of Kp. LCF = Σ_{q ∈ L*} val(q,w), L* maximising (|L|, −#implausible entrants, Σ val) lexicographically.", _fn("LCF") + _bare("LCF")),
    (MOD, "WA(move)", "Wins added.",
     "Σ_{g ∈ G} Σ_{b ∈ {0,1}^J} Π_j s_j^{b_j}(1 − s_j)^{1 − b_j} · [RES(PF_t(g), PF_o(g)) − RES(PF^cf_t(g,b), PF^cf_o(g))]. J = LIN groups with 0 < s_j < 1 that had a starter in g (largest 6; others with s ≥ ½ and all s = 1 groups counted removed). PF^cf_t(g,b) = Σ_{w ∈ g} [LCF(t,w; OUT_w(b), IN_w) + PF(t,w) − Σ_{q ∈ S(t,w)} pts(q,w)], OUT_w(b) = present LIN players of removed groups, IN_w = GU players active in w. PF^cf_o(g) = Σ_{w ∈ g} [LCF(o,w; GU players on R(o,w), group-0 received players o sent and no longer holds) + PF(o,w) − Σ_{S(o,w)} pts], or PF(o,w) when both sets are empty. A game where no lineup can change returns 0.", _fn("WA") + _bare("WA")),
    # ---- model definitions: Boldness (lotg_support.boldness) ----
    (MOD, "GLb(p,y,w)", "Boldness game log.", "p's nflverse games in seasons y−2, y−1 and y before week w, each scored with season y's rules, with (season y_g, NFL team team_g, points npts_g); n_g = p's games after g in that window.", _fn("GLb") + _bare("GLb")),
    (MOD, "π_pos(y)", "Veteran prior.", "Mean npts per appearance at pos in season y−1 (y−2 if empty), scored with season y's rules.", _fn("π_pos")),
    (MOD, "π_R(y,pos,b)", "NFL-round rookie prior.", "Mean rookie-season npts per appearance of NFL rookies at (pos, NFL draft bucket b ∈ {R1, R2, R3, R4-7, UDFA}) over seasons 2018..y−1 (≥ 20 appearances, else the pos mean, else π_pos(y)).", _fn("π_R")),
    (MOD, "SP_y(ov,pos)", "Rookie-draft slot prior.", "max(0, β0 + β1·ln ov + β_pos), (β) = least squares weighted by √games over earlier seasons' LOTG rookie picks (rookie-year npts per game; needs ≥ 30 picks).", _fn("SP_y")),
    (MOD, "E_base(p,y,w)", "Base expectation.",
     "(Σ_{g ∈ GLb} ω_g·npts_g + k·π) / (Σ_g ω_g + k), ω_g = 0.5^(y − y_g) · 0.5^(n_g/8) · (0.5 if y_g < y and team_g ≠ p's team in week w, else 1). Veteran: k = 2, π = π_pos(y). Rookie (rookie_season = y): fd = max(0, 1 − (w − 1)/4), k = 3·fd + 2(1 − fd), π = (3·fd·π_r + 2(1 − fd)·π_pos(y)) / k, π_r = SP_y(ov,pos) if drafted in that season's LOTG rookie draft, else π_R(y,pos,b).", _fn("E_base") + _bare("E_base")),
    (MOD, "touch(p,w)", "Touches.", "QB: attempts + sacks + carries; RB: carries + receptions; WR / TE: targets + carries (regular season, s(p,y,w,k)).", _fn("touch") + _bare("touch")),
    (MOD, "NMU(team,pos,w)", "Next man up.", "Among the players at (team, pos) present in w and (once the team has played) used by it this season, the one with the most head-to-head wins, a pair compared on Σ touch over the season's earlier weeks both played for the team (no shared game or a tie → E_base), then E_base.", _bare("NMU") + _fn("NMU")),
    (MOD, "XP(p,y,w)", "Expected points.",
     "max(E_base(p), a_pos·E_base(q) + b_pos·E_base(p)) if p = NMU and q = the absent teammate with the highest E_base, where q sat out (no game-log row in w; a live week: injS(q) ∈ {Out, IR, PUP, Sus, NA, DNR}), is on wr(·,y,w) for that team, played for it earlier this season (last season counts when w ≤ 4), and E_base(q) > E_base(p); else E_base(p). (a_pos, b_pos) = least squares without intercept of the backup's actual npts on (E_base(q), E_base(p)) over every NFL next-man-up event 2019-2025 (≥ 30 per position).", _fn("XP")),
    (MOD, "FITS(L, Σ)", "Startable together.", "L can be matched into the slot list Σ by elig_y (bipartite matching).", _fn("FITS") + _bare("FITS")),
    (MOD, "BLV(V, Σ)", "Best lineup value.", "Σ of values taken best-first, each kept while FITS still holds and its value > 0 (exact: the startable sets form a matroid).", _fn("BLV")),
    # ---- model definitions: Price paid (lotg_support.acquisition) ----
    (MOD, "Field_d", "The day's market.", "K(p, last quote ≤ d) over every player quoted within 30 days of d (365 before 2021-04-16), K > 0, sorted descending.", _bare("Field_d")),
    (MOD, "k0(d)", "Market anchor.", "Field_d's 49th value.", _fn("k0") + _bare("k0")),
    (MOD, "k10(d)", "Top-10 level.", "Mean of Field_d's top 10.", _fn("k10") + _bare("k10")),
    (MOD, "k100(d)", "Depth level.", "Field_d's 100th value.", _fn("k100") + _bare("k100")),
    (MOD, "Ā", "Board anchor.", "Mean of k0(dd) over the rookie draft days.", _bare("Ā")),
    (MOD, "bd(ov)", "Draft board.", "Per-slot mean of K(pl, dd) over rookie picks (rounds 1-4, all classes), made non-increasing in ov by isotonic regression (pool adjacent violators, weighted by picks per slot), linear between observed slots, flat beyond.", _fn("bd") + _bare("bd")),
    (MOD, "ρ(ov)", "Ratio board.", "The bd curve built on K(pl, dd)/k0(dd), all rookie classes.", _fn("ρ")),
    (MOD, "ρ_Y(ov)", "Class ratio board.", "ρ on rookie class Y only.", _fn("ρ_Y")),
    (MOD, "ρ_nr(ov)", "Startup ratio board.", "ρ on the startup + 2021 vet board.", _fn("ρ_nr")),
    (MOD, "MC(k)", "Money curve.", "o_L = the last regular slot (4.08 → 32), k_L = bd(o_L), k_1 = bd(1); r = (1000 / (k_L/κ))^(1/(o_L − 4.5)); slotk(k) = 1 − (k − k_1)/max(bd(1) − bd(2), 1) if k ≥ k_1, o_L if k ≤ k_L, else bd⁻¹(k) by interpolation. MC(k) = k/κ if k ≤ k_L, else (k_L/κ)·r^(o_L − slotk(k)).", _fn("MC")),
    (MOD, "$_d(k)", "Market curve.", "1000·2.619^((k − k0)/max(k10 − k0, 1)) if k ≥ k0; else [1000·8.26^((k − k0)/max(k0 − k100, 1))]^0.5 · [MC(k·Ā/k0)·1000/MC(Ā)]^0.5 (no field that day: MC(k)).", (r"\$_d\(",)),
    (MOD, "ℓ_d(y)", "Replacement line.", "n_rep(y) = (|slots(y)| excl. IR)·N − (N if y ≥ 2025, else 0); ℓ = $_d(Field_d[n_rep]) (a thinner field: the ratio Field_d'[n_rep]/k0(d') from the nearest covering date d' = d ± 7j, times k0(d)).", (r"ℓ",)),
    (MOD, "P_d(k)", "Price above replacement.", "s·ln(1 + e^(($_d(k) − ℓ_d)/s)), s = ℓ_d/2.5.", (r"P_d\(",)),
    (MOD, "$pick_d(Y, r, sl)", "A pick on the board.", "r ≥ 5 (a 5.0X): 20. Else ov = (r − 1)·N + sl, ρ* = 0.75·ρ(ov) + 0.25·ρ_Y(ov) (ρ(ov) before class Y is drafted), $pick = $_d(ρ*·k0(d)) (no field: MC(ρ*·Ā)). Startup / vet pick: $_d(ρ_nr(ov)·k0(d)).", (r"\$pick",)),
    (MOD, "π_d(t0, sl)", "Projected slot odds.", "Before Y−1's regular season ends (k weeks played): score = α_k·z(RS) + (1 − α_k)·z(IS), z = rank z-score, RS = Σ of t0's top 15 K on d, IS = wins + Σ PF/10⁵ (Max-PF-ordered drafts, 2026 on: the bottom N−4 by record then ordered by Σ MaxPF), α_k = 1 (k = 0), ½ (k ≤ 3), max(0, ½(8 − k)/5); rank i (1 = projected worst) → π(sl) ∝ exp(−(sl − i)²/(2σ_k²)), σ_k = (2.75, 2.35, 2.00, 1.90, 1.65, 1.55, 1.55, 1.55, 1.55, 1.40, 1.35, 1.35, 1.25, 1.00)[min(k,13)]. After it: the bottom four by the draft's rule (σ = 0.75 for placement drafts through 2024, else exact), the playoff four uniform over 5-8, after the semifinals losers over 5-6 and winners over 7-8.", (r"π_d\(",)),
    (MOD, "$asset_d(q)", "An asset in FAAB $.", "FAAB: its amount. A player: P_d(K(q,d)). A traded pick (Y, r, sl?): order set and sl known → $pick_d(Y,r,sl); deciding season Y−1 next up or under way → Σ_sl π_d(t0,sl)·$pick_d(Y,r,sl); else mean_sl $pick_d(Y,r,sl); then × 0.95^max(Y − the next draft after d, 0).", (r"\$asset",)),
    # ---- model definitions: Points above expectation (lotg_support.acquisition) ----
    (MOD, "φ_c", "Price feature.", "Free 0, waiver ln(1 + bid), rookie / startup ln(ov), trade ln(1 + Price paid).", (r"φ",)),
    (MOD, "q_c", "Price percentile.", "The within-channel percentile of sgn_c·φ_c (sgn = −1 for picks, +1 otherwise).", (r"q_c",)),
    (MOD, "σ_y", "Season scale.", "S̄ / S_y, S_y = mean{pts(p,w) : st, season y}, S̄ = mean of S_y over seasons on their own baseline.", (r"σ_y", r"σ_\{")),
    (MOD, "cf_k", "Never-cut series.", "Elapsed week k = 1, 2, … counts league weeks from the first whose last game is on or after d_a; cf_k = (pts(p,w_k) on any roster, else npts(p,y,w_k), else 0)·F(y_{w_k}, pos)·σ_{y_{w_k}} up to the last week played.", (r"cf_k",)),
    (MOD, "held", "Held weeks.", "{(k, x_k = pts(p,w_k)·F(y_{w_k}, pos)·σ_{y_{w_k}}) : w_k ∈ Wk}.", (r"∈ held", r"\|held\|", r"_\{held\}", r"_\{\(k, x_k\) ∈ held\}")),
    (MOD, "no_k", "Offseasons crossed.", "y_{w_k} − y_{w_1}.", _bare("no_k")),
    (MOD, "xd(k, no, φ, q, pos, c)", "Expectation design.", "Per channel c (indicator m_c): m_c·[1, ℓk, (ℓk − κ_j)_+, no, (no − h)_+ for h = 1..S_off−1] and, paid channels, m_c·[sgn_c·clip(φ − e_i, 0, e_{i+1} − e_i), φ·ℓk, φ·no] (e_i = φ's quintile edges in c), plus m_c·[pos₃, pos₃·ℓk]; shared: pos₃·(ln k − κ_j)_+ (global knots), pos₄·no, and (paid) pos₄·q·no, pos₄·q·ln k (free fit: pos₃·(no − h)_+). ℓk = min(ln k, ln kmax_c), kmax_c = max(8, 95th percentile of k in c); knots κ_j = ln{2, 4, 8, 17, 34, 68, 136, …} < kmax; S_off = the most offseasons reached by ≥ 40 additions; pos₃ = RB/WR/TE dummies, pos₄ = all four.", _fn("xd") + _bare("xd")),
    (MOD, "λ̂(xd)", "Fitted expectation.", "exp(clip(xd·β̂, −20, 10)), β̂ maximising Σ_rows [cf_k·xd·β − e^(xd·β)] − 15‖β‖² (Newton / IRLS, ridge 30) over every never-cut week of every priced addition, fitted separately for free agency and for the paid channels pooled; a price-ramp coefficient with the wrong sign is pinned at 0 and the fit repeated until none is.", (r"λ̂",)),
]


@_ft.lru_cache(maxsize=1)
def _compiled():
    return [(sym, None if pats is ALWAYS else [_re.compile(p) for p in pats])
            for _b, sym, _m, _d, pats in ENTRIES]


@_ft.lru_cache(maxsize=None)
def _uses(text):
    """Glossary symbols the text mentions directly."""
    return frozenset(sym for sym, pats in _compiled() if pats and any(p.search(text) for p in pats))


@_ft.lru_cache(maxsize=None)
def _closure(text):
    """Symbols the text needs, directly or through their definitions."""
    defs = {sym: (m + " " + d if b == RAW else d) for b, sym, m, d, _p in ENTRIES}
    seen, stack = set(), list(_uses(text))
    while stack:
        sym = stack.pop()
        if sym in seen:
            continue
        seen.add(sym)
        stack += list(_uses(defs[sym]) - seen)
    return frozenset(seen)


def usage():
    """{symbol: number of equations that need it}."""
    count = {sym: 0 for _b, sym, _m, _d, _p in ENTRIES}
    for eq in EQUATIONS.values():
        for sym in _closure(eq):
            count[sym] += 1
    return count


@_ft.lru_cache(maxsize=1)
def kept_symbols():
    n = usage()
    return frozenset(sym for _b, sym, _m, _d, pats in ENTRIES if pats is ALWAYS or n[sym] >= MIN_USES)


def glossary():
    """[(sheet, symbol, meaning, definition)] for the symbols that earn a row."""
    keep = kept_symbols()
    return [(SHEET_OF[b], sym, m, (f"API field: {d}" if b == RAW else d))
            for b, sym, m, d, _p in ENTRIES if sym in keep]


def expanded(key):
    """A row's equation with every symbol below MIN_USES defined in-cell."""
    eq = EQUATIONS[key]
    need = _closure(eq) - kept_symbols()
    if not need:
        return eq
    parts = [(f"{sym} = {_clause(m)} ({d})" if b == RAW else f"{sym} = {_clause(d)}")
             for b, sym, m, d, _p in ENTRIES if sym in need]
    return eq + "  — where " + "; ".join(parts)


def _clause(text):
    """A definition as an in-cell clause: no closing period, and a leading
    capitalised word lower-cased only when it opens a sentence ('The first
    league week …' → 'the first …'). A symbol or a name that leads the text
    ('Kp = …', 'Sep 1 …', 'Bust ≤ q10 …') keeps its case: the word after it
    does not start with a lower-case letter."""
    t = text.strip().rstrip(".")
    words = t.split(" ", 2)
    first = words[0]
    nxt = words[1] if len(words) > 1 else ""
    if (first[:1].isupper() and first[1:].isalpha() and first[1:].islower()
            and nxt[:1].islower()):
        t = first.lower() + t[len(first):]
    return t


def glossary_for(key):
    """[(sheet, symbol, meaning, definition)] — the glossary rows the equation
    of (Stat, Sheet) `key` relies on, in glossary order (the symbols it defines
    in-cell are already in its text)."""
    need = _closure(EQUATIONS[key]) & kept_symbols()
    return [g for g in glossary() if g[1] in need]


# {(Stat, Sheet) of a formulas._ROWS entry: its equation}
EQUATIONS = {
    ('Faab', 'add_drops'):
        'bid(x) if type(x) = waiver; 0 if type(x) ∈ {free_agent, commissioner}',
    ('Total FAAB bid', 'add_drops'):
        "Σ_{u ∈ Bd} bid(c_u), Bd = {teams u with a valid waiver claim on a in x's waiver run}, c_u = u's winning claim, else u's last-created claim on a (claims = transactions with type = waiver, status ∈ {complete, failed}, adds[a] = u; invalid = failed for roster limit / insufficient FAAB / locked drop)",
    ('FAAB difference over second place', 'add_drops'):
        'bid(x) − max({bid(c_u) : u ∈ Bd∖{t}, bid(c_u) ≤ bid(x)} ∪ {0})',
    ('FAAB premium %', 'add_drops'):
        '100 · (bid(x) − max({bid(c_u) : u ∈ Bd∖{t}, bid(c_u) ≤ bid(x)} ∪ {0})) / bid(x); blank if bid(x) = 0',
    ('Number of bids', 'add_drops'):
        '|Bd|',
    ('Average PPG on team', 'add_drops'):
        'ppg_on(a, t, T) = Σ_{w ∈ Wk : H(a,w)} pts(a,w) / |{w ∈ Wk : H(a,w)}|; blank if Wk = ∅, 0 if no H week',
    ('Average PPG of dropped player over same time', 'add_drops'):
        'ppg_nfl(r, [d0, e_a)) = mean{ npts(r,y,w) : APP(r,y,w), gd(r,y,w) ∈ [d0, e_a) }; blank if r = ∅ or no game',
    ('PPG of 5 games before pickup', 'add_drops / player_additions'):
        "avgN(a, d0, 5) = mean of npts over a's last min(5, n) games in GL(a) with gd < d0 (ET day)",
    ('Difference of averages', 'add_drops'):
        'ppg_on(a,t,T) − ppg_nfl(r, [d0, e_a))  (a missing side = 0; blank if both missing)',
    ('Difference of averages adjusted by position', 'add_drops'):
        'ppg_on(a,t,T) · F(y0, pos(a)) − ppg_nfl(r, [d0, e_a)) · F(y0, pos(r))  (missing side = 0)',
    ('Age difference', 'add_drops'):
        'age(a, d0) − age(r, d0),  age(p,d) = (d − birth(p)) / 365.25',
    ('Cuff at time of pickup?', 'add_drops'):
        'CUFF(a, t, d0)',
    ('Weeks between pickup and start', 'add_drops'):
        '|{w ∈ Wk : w < w*}|, w* = min{w ∈ Wk : st(a,t,w) = 1}; blank if no such w*',
    ('Number of starts before next drop', 'add_drops / player_additions'):
        'nst = Σ_{w ∈ Wk(p,t,T)} st(p,t,w)  (p = added / acquired player)',
    ('Length of tenure on team', 'add_drops'):
        "e_a − d0 (days), e_a = min{d(x') > d0 : drops(x')[a] = t or a sent by t in a trade}, else today",
    ('% of starts made while rostered', 'add_drops'):
        'Σ_{w ∈ Wk} st(a,t,w) / |Wk|',
    ('Injury adjusted % of starts made while rostered', 'add_drops'):
        'Σ_{w ∈ Wk : H(a,w)} st(a,t,w) / |{w ∈ Wk : H(a,w)}|',
    ('Player addition value', 'add_drops'):
        '[ppg_on(a,t,T)·F(y0,pos a) − ppg_nfl(r,[d0,e_a))·F(y0,pos r)] · (1 + Σ_{Wk} st / |Wk|) · (1 + Σ_{Wk:H} st / |{Wk : H}|) + 5·[CUFF(a,t,d0)]; 0 if Wk = ∅',
    ('Points Added', 'add_drops'):
        'Σ_{w ∈ St} pts(a,w),  St = {w ∈ Wk : st(a,t,w) = 1}',
    ('Points Lost', 'add_drops'):
        'Σ_{w ∈ St} npts(r, y_w, w)  (0 for a week r has no NFL stat line)',
    ('Net points', 'add_drops'):
        'Σ_{w ∈ St} (pts(a,w) − npts(r,y_w,w))',
    ('Avg points added', 'add_drops'):
        'Σ_{w ∈ St} pts(a,w) / |St|  (0 if St = ∅)',
    ('Avg points lost', 'add_drops'):
        'Σ_{w ∈ St} npts(r,y_w,w) / |St|  (0 if St = ∅)',
    ('Avg net points', 'add_drops'):
        'Σ_{w ∈ St} (pts(a,w) − npts(r,y_w,w)) / |St|  (0 if St = ∅)',
    ('Avg points added adjusted by position', 'add_drops'):
        'Σ_{w ∈ St} pts(a,w) · F(y_w, pos(a)) / |St|',
    ('Avg points lost adjusted by position', 'add_drops'):
        'Σ_{w ∈ St} npts(r,y_w,w) · F(y_w, pos(r)) / |St|',
    ('Avg net points adjusted by position', 'add_drops'):
        'Σ_{w ∈ St} [pts(a,w)·F(y_w,pos a) − npts(r,y_w,w)·F(y_w,pos r)] / |St|',
    ('KTC value of player added at deal time', 'add_drops'):
        'K(a, d0)',
    ('KTC value of player dropped at deal time', 'add_drops'):
        'K(r, d0)',
    ('Net KTC value at deal time', 'add_drops'):
        'K(a, d0) − K(r, d0)  (missing side = 0)',
    ('KTC value of player added at end of season', 'add_drops'):
        "K(a, eos(y0)),  eos(y) = the Monday after y's championship week",
    ('KTC value of player added 1 year later', 'add_drops'):
        'K(a, d0 + 1 year)',
    ('KTC value of player added 2 years later', 'add_drops'):
        'K(a, d0 + 2 years)',
    ('KTC value of player dropped at end of season', 'add_drops'):
        'K(r, eos(y0))',
    ('KTC value of player dropped 1 year later', 'add_drops'):
        'K(r, d0 + 1 year)',
    ('KTC value of player dropped 2 years later', 'add_drops'):
        'K(r, d0 + 2 years)',
    ('Net KTC value at end of season', 'add_drops'):
        'K(a, eos(y0)) − K(r, eos(y0))  (missing side = 0)',
    ('Net KTC value 1 year later', 'add_drops'):
        'K(a, d0+1y) − K(r, d0+1y)  (missing side = 0)',
    ('Net KTC value 2 years later', 'add_drops'):
        'K(a, d0+2y) − K(r, d0+2y)  (missing side = 0)',
    ('Player Added', 'add_drops'):
        'a = the p with adds(x)[p] = t  (labelled full_name(p))',
    ('Player Dropped', 'add_drops'):
        'r = the p with drops(x)[p] = t  (labelled full_name(p))',
    ('type of add/drop (waiver/free agency)', 'add_drops'):
        'type(x) ∈ {waiver, free_agent, commissioner}',
    ('Date dropped/traded', 'add_drops'):
        "e_a = min{d(x') > d0 : drops(x')[a] = t or a sent by t in trade x'}; blank if none",
    ('Link to next transaction (added player)', 'add_drops'):
        "row of argmin_{x'} {d(x') : d(x') > d0, a ∈ adds(x') ∪ drops(x') ∪ trade assets(x') ∪ {pl(pk)}}",
    ('Link to previous transaction (added player)', 'add_drops'):
        "row of argmax_{x'} {d(x') : d(x') < d0, a ∈ adds(x') ∪ drops(x') ∪ trade assets(x') ∪ {pl(pk)}}",
    ('Link to next transaction (dropped player)', 'add_drops'):
        "row of argmin_{x'} {d(x') : d(x') > d0, r ∈ adds(x') ∪ drops(x') ∪ trade assets(x')}",
    ('Link to previous transaction (dropped player)', 'add_drops'):
        "row of argmax_{x'} {d(x') : d(x') < d0, r ∈ adds(x') ∪ drops(x') ∪ trade assets(x') ∪ {pl(pk)}}",
    ('Number of times picked up by this team', 'add_drops'):
        "|{x' : d(x') ≤ d0, adds(x')[a] = t or a received by t in trade x'}|",
    ('Number of times dropped by this team', 'add_drops'):
        "|{x' : d(x') ≤ d0, drops(x')[r] = t or r sent by t in trade x'}|; blank if r = ∅",
    ('Tanking', 'add_drops / trades / non_rookie_picks / rookie_picks / player_additions'):
        '(1/6) · −(Āge_post − Āge_pre) / (L̄age(y0) − 21) + (1/9) · (Σ_{picks recv} ω(round) − Σ_{picks sent} ω(round)), picks of seasons y0+1 … y0+5 (2.09 as a 2nd, 5.0X as a 4th); Āge_pre = mean({age(p,dw) : p ∈ R(t,w)} ∪ {agepk(Y,dw) : future picks held, next 3 seasons}), Āge_post = (N·Āge_pre − Σ_sent age* + Σ_recv age*) / (N − n_sent + n_recv), L̄age = league mean of Āge',
    ('Assets received', 'trades'):
        '{p : adds(x)[p] = t} ∪ {pick : dp(x).owner_id = t} ∪ {amount : wb(x).receiver = t}',
    ('Assets sent', 'trades'):
        '{p : drops(x)[p] = t} ∪ {pick : dp(x).previous_owner_id = t} ∪ {Σ amount : wb(x).sender = t}',
    ('Number of assets received', 'trades'):
        '|{p : adds(x)[p] = t}| + |{pick : dp(x).owner_id = t}|',
    ('Number of assets traded away', 'trades'):
        '|{p : drops(x)[p] = t}| + |{pick : dp(x).previous_owner_id = t}|',
    ('Total number of assets in trade', 'trades'):
        '|keys(adds(x))| + |dp(x)|  (each asset once; FAAB excluded)',
    ('Trade impact score', 'trades'):
        '0.6 · Σ_j w_j · (v_j − μ_j) / σ_j  (μ_j, σ_j = mean and population sd of v_j over all trade rows; a missing WA / pick value = 0, other missing terms skipped), (v_j, w_j) = (⟨Wins added⟩, 2.0), (⟨Avg net points⟩, 0.8), (⟨Trade addition value⟩, 0.5), (Σ_{picks recv} K(pick, d0), 0.5), (mean_A age*(·,d0) − mean_B age*(·,d0), −0.3)',
    ('Wins added', 'add_drops / trades'):
        'WA(move)',
    ('Wins added per season', 'add_drops / trades'):
        "WA(move) × 17 / |G|  (|G| = t's games from w0 to now; the 2026+ two-week final counts once); N/A when |G| = 0",
    ('O-Score', 'add_drops / trades / non_rookie_picks / rookie_picks'):
        "mean_{j=1..4} pctl(v_j ; v_j over the sheet's rows), a v_j of exactly 0 ranked lowest in its tie; add_drops v = ⟨Avg net points adjusted by position⟩, ⟨Player addition value⟩, latest K checkpoint, ⟨% of starts made while rostered⟩; trades v = ⟨Avg net points adjusted by position⟩, ⟨Trade addition value⟩, latest K checkpoint, ⟨Trade impact score⟩; pick sheets v = ⟨Avg points added adjusted by position⟩, ⟨Pick-adjusted Difference in Player addition value⟩, latest pick-adjusted K, ⟨Pick-adjusted Difference in Avg career PPG adjusted by position⟩ (each pick sheet ranked separately); pure drop: ½ · the same mean",
    ('O-Score draft-slot de-trend', 'non_rookie_picks'):
        'clamp(O − 0.75 · ((α + β·ln n) − Ō), 0, 100),  n = overall pick number (startup then 2021 vet draft), (α, β) = least squares of O on ln n with β ≤ 0, Ō = mean O',
    ('Dropped avg points', 'add_drops'):
        'mean{ npts(r,y,w) : the first ≤ 17 games of GL(r) with gd ≥ d0 }; 0 if none',
    ('Dropped total points', 'add_drops'):
        'Σ{ npts(r,y,w) : the first ≤ 17 games of GL(r) with gd ≥ d0 }',
    ('KTC value difference at deal time', 'trades'):
        'DT(A, d0) − DT(B, d0),  DT(X,d) = Σ_i 0.6^(i−1)·K(X_(i), d) with K(X_(1)) ≥ K(X_(2)) ≥ …, a FAAB amount valued at κ·amount (κ = 100); a pick with no quote on d0 = the mean K of the same pick 1-3 classes later at the same lead time',
    ('KTC value difference at end of season', 'trades'):
        'DT(A, eos(y0)) − DT(B, eos(y0))',
    ('KTC value difference 1 year later', 'trades'):
        'DT(A, d0+1y) − DT(B, d0+1y)',
    ('KTC value difference 2 years later', 'trades'):
        'DT(A, d0+2y) − DT(B, d0+2y)',
    ('Pick value received', 'trades'):
        'Σ_{pick ∈ dp(x), owner_id = t} K(pick, d0)',
    ('Change in pick value at draft time', 'trades'):
        'Σ_{pick ∈ dp(x), owner_id = t, draft done} (K(pick, Sep 1 of its year) − K(pick, d0))',
    ('Assets retained now', 'trades'):
        "{q ∈ A : no x' with d(x') > d0 removing q from t}",
    ('Assets traded away', 'trades'):
        '{q ∈ A : first exit of q from t after d0 is a trade}',
    ('Assets dropped to FA', 'trades'):
        "{q ∈ A players : first exit of q from t after d0 is drops(x')[q] = t}",
    ('Return from trades', 'trades'):
        "∪ {assets received by t in x'} over trades x' with d(x') > d0 where t sends some q ∈ A (first hop)",
    ('Additional assets traded away in those deals', 'trades'):
        "∪ {assets sent by t in x'} ∖ A over the same first-hop trades x'",
    ('Return from trades of trades...of trades. Keep going until present day', 'trades'):
        "closure: A_0 = A, A_{k+1} = ∪ received(x') over trades x' sending any q ∈ A_k; result = A_∞ at today",
    ('Asset difference in average age', 'trades'):
        'mean_{q ∈ A} age*(q, d0) − mean_{q ∈ B} age*(q, d0),  age*(p,d) = age(p,d), age*(pick of year Y, d) = agepk(Y,d) = (d − Sep 1 of (Y − 22)) / 365.25; 0 if a side is empty',
    ('Number of teams involved', 'trades'):
        '|rosters(x)|',
    ('Link to next transaction per asset', 'trades'):
        "for each q ∈ A: row of the first event x' (add/drop, trade or draft pick) on q with d(x') > d0",
    ('Link to previous transaction per asset', 'trades'):
        "for each q ∈ A: row of the last event x' on q with d(x') < d0",
    ('Team age including picks', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'mean({age(p, dw(y,w)) : p ∈ R(t,w)} ∪ {agepk(Y, dw(y,w)) : picks held by t, Y ∈ next 3 drafts}); year/all-time/league = mean of the weekly values',
    ('Avg PPG of received players on team', 'trades'):
        "mean_{q ∈ A'} ppg_on(q, t, T_q),  A' = received players with Wk ≠ ∅ ∪ players drafted by t with a received pick held from d0 to the draft",
    ('Avg PPG of sent players over same time', 'trades'):
        "mean_{s ∈ B} ppg_nfl(s, [d0, e*)),  e* = last exit of A' from t (open → today; no A' → min(today, d0 + 4y))",
    ('Avg PPG of received players in 5 games before trade', 'trades'):
        'mean_{q ∈ A} avgN(q, d0, 5)',
    ('Difference of averages', 'trades'):
        "mean_{q ∈ A'} ppg_on(q,t,T_q) − mean_{s ∈ B} ppg_nfl(s, [d0, e*)); N/A if A' = ∅",
    ('Difference of averages adjusted by position', 'trades'):
        "mean_{q ∈ A'} ppg_on(q,t,T_q)·F(y0,pos q) − mean_{s ∈ B} ppg_nfl(s,[d0,e*))·F(y0,pos s); N/A if A' = ∅",
    ('Trade addition value', 'trades'):
        "[mean_{A'} ppg_on(q,t,T_q)·F(y0,pos q) − mean_B ppg_nfl(s,[d0,e*))·F(y0,pos s)] · (1 + mean_{q ∈ A players} nst_q/|Wk_q|) · (1 + mean_{q ∈ A players} Σ_{Wk_q : ¬INJ ∧ ¬BYE} st / |{Wk_q : ¬INJ ∧ ¬BYE}|) + 5·[∃ q ∈ A : CUFF(q,t,d0)] + 20·(Σ_{picks recv} ω(round) − Σ_{picks sent} ω(round)) over every future pick in the deal (no horizon cap); pick term alone when no received player was rostered",
    ('Points added', 'trades'):
        "Σ_w Σ_{q ∈ A'} st(q,t,w) · pts(q,w)",
    ('Points lost', 'trades'):
        "Σ_w Σ_{top k_w s ∈ B by npts(s,y,w)} npts(s,y,w),  k_w = Σ_{q ∈ A'} st(q,t,w)",
    ('Net points', 'trades'):
        "Σ_w [Σ_{q ∈ A'} st(q,t,w)·pts(q,w) − Σ_{top k_w s ∈ B} npts(s,y,w)]",
    ('Avg points added', 'trades'):
        "Σ_w Σ_{A'} st·pts / M,  M = |{w : k_w ≥ 1}|",
    ('Avg points lost', 'trades'):
        'Σ_w Σ_{top k_w of B} npts / M',
    ('Avg net points', 'trades'):
        "Σ_w [Σ_{A'} st·pts − Σ_{top k_w of B} npts] / M",
    ('Avg points added adjusted by position', 'trades'):
        "Σ_w Σ_{q ∈ A'} st(q,t,w)·pts(q,w)·F(y_w,pos q) / M",
    ('Avg points lost adjusted by position', 'trades'):
        'Σ_w Σ_{top k_w s ∈ B by raw npts} npts(s,y,w)·F(y_w,pos s) / M',
    ('Avg net points adjusted by position', 'trades'):
        "Σ_w [Σ_{A'} st·pts·F − Σ_{top k_w of B} npts·F] / M",
    ('Number', 'non_rookie_picks / rookie_picks'):
        "round(pk) '.' (pick_no(pk) − (round(pk) − 1)·N), N = teams; '??' before the draft; 2.09 / 5.0X = synthetic award picks",
    ('Original Team', 'non_rookie_picks / rookie_picks'):
        'slot_to_roster_id(draft)[draft_slot(pk)] (= traded_picks.roster_id of the pick)',
    ('Team', 'player_week / team_week / team_year / team_all_time / add_drops / trades / non_rookie_picks / rookie_picks'):
        'picked_by(pk) roster  (= traded_picks.owner_id at the draft)',
    ('Length of tenure on team', 'non_rookie_picks / rookie_picks'):
        'e − dd(Y),  e = first exit of pl(pk) from by(pk) after dd(Y), else today',
    ('Avg PPG on team', 'non_rookie_picks / rookie_picks / player_additions'):
        'ppg_on(p, t, [s, e)) = Σ_{w ∈ Wk : H(p,w)} pts(p,w) / |{w ∈ Wk : H(p,w)}|,  s = dd(Y) (picks) or acquisition date (player_additions)',
    ('Avg PPG on team adjusted by position', 'non_rookie_picks / rookie_picks'):
        'ppg_on(pl, by, [dd, e)) · F(Y, pos(pl))',
    ('Avg career PPG', 'non_rookie_picks / rookie_picks'):
        'mean{ npts(pl,y,w) : APP(pl,y,w), gd ≥ dd(Y) }; 0 if none',
    ('Avg career PPG adjusted by position', 'non_rookie_picks / rookie_picks'):
        'mean{ npts(pl,y,w) : APP, gd ≥ dd(Y) } · F(Y, pos(pl))',
    ('Age when drafted', 'non_rookie_picks / rookie_picks'):
        'age(pl, dd(Y)) = (dd(Y) − birth(pl)) / 365.25',
    ('Player addition value', 'non_rookie_picks / rookie_picks'):
        'ppg_on(pl,by,[dd,e))·F(Y,pos pl) · (1 + nst/170) · (1 + nst/|Wk|) · (1 + nstH/nH) + 5·[CUFF(pl, by, dd)]',
    ('Cuff when drafted?', 'non_rookie_picks / rookie_picks'):
        "CUFF(pl, by, dd(Y))  (reference roster = R(by) at draft open ∪ by's earlier picks in that draft)",
    ('Weeks before first start', 'non_rookie_picks / rookie_picks'):
        '|{w ∈ Wk : w < w*}|, w* = min{w ∈ Wk : st(pl,by,w) = 1}',
    ('Number of starts before next transaction', 'non_rookie_picks / rookie_picks'):
        'Σ_{w ∈ Wk(pl, by, [dd,e))} st(pl,by,w)',
    ('% of starts made while rostered by drafting team', 'non_rookie_picks / rookie_picks'):
        'Σ_{w ∈ Wk} st(pl,by,w) / |Wk|',
    ('Injury adjusted % of starts made while rostered by drafting team', 'non_rookie_picks / rookie_picks'):
        'Σ_{w ∈ Wk : H} st(pl,by,w) / |{w ∈ Wk : H(pl,w)}|',
    ('Points added', 'non_rookie_picks / rookie_picks'):
        'Σ_{w ∈ Wk} st(pl,by,w) · pts(pl,w)',
    ('Avg points added', 'non_rookie_picks / rookie_picks'):
        'Σ_{Wk} st·pts / Σ_{Wk} st  (0 if no start)',
    ('Avg points added adjusted by position', 'non_rookie_picks / rookie_picks'):
        'Σ_{Wk} st·pts·F(y_w,pos pl) / Σ_{Wk} st',
    ('Commissioner moved?', 'non_rookie_picks / rookie_picks'):
        '[owner_id(pick) ≠ roster_id(pick) ∧ no trade x with pick ∈ dp(x)]',
    ('Number of trades', 'non_rookie_picks / rookie_picks'):
        '|{x : type(x) = trade, pick ∈ dp(x)}| + |{CPM moves of pick}|',
    ('Link to next transaction', 'non_rookie_picks / rookie_picks'):
        "row of argmin_{x'} {d(x') > dd(Y) : pl ∈ adds ∪ drops ∪ trade assets(x')}",
    ('Link to previous transaction', 'non_rookie_picks / rookie_picks'):
        'row of argmax_{x} {d(x) < dd(Y) : type = trade, pick ∈ dp(x)}',
    ('Commissioner wash exclusion', 'add_drops / trades / all add/drop & trade counts'):
        'drop the tx set X if ∃ commissioner tx in X ∧ ∀ (p, roster): Σ_{x ∈ X, same ET day} ([adds(x)[p] = roster] − [drops(x)[p] = roster]) = 0  (trades: every asset returns)',
    ('NFL team', 'player_week'):
        "nfl(p,y,w) = teamN(p,y,w) → teamN(p,y,·) season → wr(p,y,w).team → 'NFL'",
    ('Game slot', 'player_week'):
        "slot(ko(nfl(p,y,w),y,w)) by ET weekday and hour, relative to the week's Sunday: before Sunday → weekday; Sunday <13 morning, <16 early, <19 late, else SNF; after Sunday → MNF (Monday) / weekday; no game → Bye; nfl = 'NFL' → N/A",
    ('Activated Cuff?', 'player_week'):
        'st(p,t,w) ∧ ∃ q ∈ R(t,w_kick): nfl(q)=nfl(p), pos(q)=pos(p), TEST(q,p,w) ∧ INJ(q,w)',
    ('Difference from best startable bench', 'player_week'):
        'pts(p,w) − max{ pts(b,w) : b ∈ R(t,w)∖S(t,w), b eligible for some slot p could vacate }',
    ('Difference from worst benchable starter', 'player_week'):
        'pts(p,w) − min{ pts(s,w) : s ∈ S(t,w), p eligible for slot(s) }  (empty slot = 0)',
    ('Tanking', 'team_week / team_year / team_all_time'):
        "(1/6)(1 − (P̄F_t − ⅔L̄)/(L̄/3)) + (1/6)(1 − (M̄ax_t − L̄)/(L̄max − L̄)) + (1/6)(1 − (Āge_t − 21)/(L̄age − 21)) + (1/6)·Σ_{pk : by(pk) = t, draft of y} 1/(pick_no(pk) + 1) + (1/9)·Σ_{picks held, seasons y+1 … y+5} ω(round); P̄F_t, M̄ax_t, Āge_t = t's season-to-date means of PF, MaxPF and team age incl. picks, L̄ = league means; team_year = the final week's value, team_all_time = mean of seasons",
    ("Luck (team_all_time: 'Avg yearly luck')", 'team_week / team_year (Luck); team_all_time (Avg yearly luck)'):
        "Luck(t,w) = (0.27·OUT + 0.14·SIS − 0.14·BROS)·(1.8 if stage(t,w) ∈ PO else 1) + (0.36·OPP + 0.10·OWN)·GATE − 0.36·ADV + 0.12·EFF + 0.16·CLOSE − 0.25·LFH; OUT = win(t,w) − 1/(1 + e^(−1.5·δ)), δ = ⅓[z_all(μMax_t − μMax_o) + z_all(μPF_t − μPF_o) + z_all(μwin_t − μwin_o)] (z_all over every team-week row), OPP = z_wk(−(PA(t,w) − μPF_o)), OWN = z_wk(PF(t,w) − μPF_t), ADV = z_wk(Hard + SAHard + 3·Σ_{p ∈ R(t,w)} BYE(p,w)), EFF = z_wk(PF/MaxPF), CLOSE = sgn(m)·max(0, 1 − |m|/8), GATE = 1/(1 + |m|/15), m = PF − PA; 0 with no opponent; team_year = Σ_w Luck(t,w), team_all_time 'Avg yearly luck' = mean over seasons of Σ_w Luck",
    ('Hardship', 'team_week / team_year / team_all_time / league_week'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) = 0 ∧ (INJ ∨ SUS) ∧ ¬BYE] · max(0, E_h(p,w)); year/all-time/league = Σ',
    ('Win Variance', 'team_year / team_all_time'):
        '−(rank_stand(t,y) − (rank_ΣPF(t,y) + rank_ΣMaxPF(t,y)) / 2)',
    ('Drafting skill', 'team_year / team_all_time'):
        '(Σ_i ν_i·⟨O-Score⟩_i + 5·50) / (Σ_i ν_i + 5) over the picks t made, ν = 1 rookie pick, 0.5 startup / 2021 vet pick',
    ('Trading skill', 'team_year / team_all_time'):
        '(Σ_{trade rows of t} ⟨O-Score⟩_i + 5·50) / (n + 5)',
    ('Add/Drop skill', 'team_year / team_all_time'):
        "(Σ_i ν_i·⟨O-Score⟩_i + 5·50) / (Σ_i ν_i + 5) over t's add_drops rows, ν = 1 add / swap, ⅓ pure drop",
    ('All-play win %', 'team_year / team_all_time'):
        'Σ_w |{u ≠ t : PF(u,w) < PF(t,w)}| / Σ_w (N_w − 1)',
    ('All-play win % minus Win %', 'team_year / team_all_time'):
        'Σ_w |{u ≠ t : PF(u,w) < PF(t,w)}| / Σ_w (N_w − 1) − Σ_w win(t,w) / |{w}|',
    ('Playoff PF minus regular-season PF', 'team_all_time'):
        'mean_{w : stage ∈ PO} PF(t,w) − mean_{w ∈ REG} PF(t,w)',
    ('Playoff win % minus regular-season win %', 'team_all_time'):
        'mean_{w : stage ∈ PO} win(t,w) − mean_{w ∈ REG} win(t,w)',
    ('Loss from hardship?', 'team_week'):
        '[win(t,w) = 0 ∧ OPT({pts(p,w) : p ∈ S(t,w)} ∪ {max(0,E_h(q,w))·s_h(q,w) : q ∈ R(t,w), pts=0, INJ ∨ SUS, s_h > 0}, y) > PA(t,w)]',
    ('Losses from hardship', 'team_year / team_all_time'):
        'Σ_w ⟨Loss from hardship?⟩(t,w)',
    ('Loss from bye?', 'team_week'):
        '[win(t,w) = 0 ∧ PF(t,w) + G_bye(t,w) > PA(t,w) + G_bye(o,w)], G_bye(t,w) = OPT(S(t,w) pts ∪ {max(0,E_h(q,w))·s_h(q,w) : q ∈ R, pts = 0, BYE(q,w)}) − OPT(S(t,w) pts)',
    ('Losses from byes', 'team_year / team_all_time'):
        'Σ_w ⟨Loss from bye?⟩(t,w)',
    ('Loss from hardship (2-sided)?', 'team_week'):
        '[win(t,w) = 0 ∧ PF + G_h(t,w) > PA + G_h(o,w)], G_h(t,w) = OPT(S pts ∪ {max(0,E_h)·s_h : q ∈ R, pts = 0, INJ ∨ SUS}) − OPT(S pts)',
    ('Win from hardship (2-sided)?', 'team_week'):
        '[win(t,w) = 1 ∧ PF + G_h(t,w) < PA + G_h(o,w)]',
    ('Losses from hardship (2-sided)', 'team_year / team_all_time'):
        'Σ_w ⟨Loss from hardship (2-sided)?⟩(t,w)',
    ('Wins from hardship (2-sided)', 'team_year / team_all_time'):
        'Σ_w ⟨Win from hardship (2-sided)?⟩(t,w)',
    ('Win from bye?', 'team_week'):
        '[win(t,w) = 1 ∧ PF + G_bye(t,w) < PA + G_bye(o,w)]',
    ('Wins from byes', 'team_year / team_all_time'):
        'Σ_w ⟨Win from bye?⟩(t,w)',
    ('Starter scoring volatility', 'player_year / player_all_time'):
        'sd{ pts(p,w) : st(p,·,w) = 1 }  (sample sd, ≥ 2 weeks)',
    ('Starter scoring floor', 'player_year / player_all_time'):
        'min{ pts(p,w) : st(p,·,w) = 1 }',
    ('Starter scoring ceiling', 'player_year / player_all_time'):
        'max{ pts(p,w) : st(p,·,w) = 1 }',
    ('Starter boom %', 'player_year / player_all_time'):
        "|{w : st ∧ H(p,w), pts(p,w) ≥ q90(Q_pos)}| / |{w : st ∧ H}|,  Q_q = {pts(p',w') : st, H, pos(p') = q, all seasons}",
    ('Starter upper quartile %', 'player_year / player_all_time'):
        '|{w : st ∧ H, q75(Q_pos) ≤ pts < q90(Q_pos)}| / |{w : st ∧ H}|',
    ('Starter middle 50% %', 'player_year / player_all_time'):
        '|{w : st ∧ H, q25(Q_pos) ≤ pts < q75(Q_pos)}| / |{w : st ∧ H}|',
    ('Starter lower quartile %', 'player_year / player_all_time'):
        '|{w : st ∧ H, q10(Q_pos) < pts < q25(Q_pos)}| / |{w : st ∧ H}|',
    ('Starter bust %', 'player_year / player_all_time'):
        '|{w : st ∧ H, pts ≤ q10(Q_pos)}| / |{w : st ∧ H}|',
    ('Consistency percentile', 'player_year / player_all_time'):
        "pctl(−sd_st(p) ; {−sd_st(p') : p' same pos (and season on player_year)}),  sd_st(p) = sd{pts(p,w) : st}",
    ('Floor percentile', 'player_year / player_all_time'):
        'pctl(min{pts(p,w) : st} ; same over players of pos(p) (and season))',
    ('Ceiling percentile', 'player_year / player_all_time'):
        'pctl(max{pts(p,w) : st} ; same over players of pos(p) (and season))',
    ('Starter PAR', 'player_year / player_all_time'):
        "Σ_{w : st(p,·,w)} (pts(p,w) − RL(pos p, w)),  RL(q,w) = mean of the lowest ⌈⅓⌉ of {pts(p',w) : st(p',·,w), pos(p') = q}",
    ('Starter PAR per game', 'player_year / player_all_time'):
        'mean_{w : st(p,·,w)} (pts(p,w) − RL(pos p, w))',
    ('Rostered scoring volatility', 'player_year / player_all_time'):
        'sd{ pts(p,w) : ro(p,·,w) ∧ H(p,w) }  (≥ 2 weeks)',
    ('Rostered scoring floor', 'player_year / player_all_time'):
        'min{ pts(p,w) : ro ∧ H }',
    ('Rostered scoring ceiling', 'player_year / player_all_time'):
        'max{ pts(p,w) : ro ∧ H }',
    ('Rostered boom %', 'player_year / player_all_time'):
        '|{w : ro ∧ H, pts ≥ q90(Q_pos)}| / |{w : ro ∧ H}|',
    ('Rostered upper quartile %', 'player_year / player_all_time'):
        '|{w : ro ∧ H, q75(Q_pos) ≤ pts < q90(Q_pos)}| / |{w : ro ∧ H}|',
    ('Rostered middle 50% %', 'player_year / player_all_time'):
        '|{w : ro ∧ H, q25(Q_pos) ≤ pts < q75(Q_pos)}| / |{w : ro ∧ H}|',
    ('Rostered lower quartile %', 'player_year / player_all_time'):
        '|{w : ro ∧ H, q10(Q_pos) < pts < q25(Q_pos)}| / |{w : ro ∧ H}|',
    ('Rostered bust %', 'player_year / player_all_time'):
        '|{w : ro ∧ H, pts ≤ q10(Q_pos)}| / |{w : ro ∧ H}|',
    ('Positional scoring percentile', 'player_week'):
        '100 · |{v ∈ Q_pos(p) : v ≤ pts(p,w)}| / |Q_pos(p)|; blank if ¬H(p,w)',
    ('Starter positional-tier streaks', 'player_week'):
        "RUN over p's weeks with st ∧ H (others skipped) of [tier(pts(p,w)) = τ], tier from q10/q25/q75/q90 of Q_pos",
    ('Rostered positional-tier streaks', 'player_week'):
        "RUN over p's weeks with ro ∧ H (others skipped) of [tier(pts(p,w)) = τ]",
    ('% of starters in each positional scoring tier', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{(p,w) : p ∈ S(t,w), H(p,w), tier(pts(p,w)) = τ}| / |{(p,w) : p ∈ S(t,w), H}|  (league sheets: over all t; year/all-time: pooled)',
    ('Rostered consistency percentile', 'player_year / player_all_time'):
        'pctl(−sd{pts : ro ∧ H} ; same over players of pos(p) (and season))',
    ('Rostered floor percentile', 'player_year / player_all_time'):
        'pctl(min{pts : ro ∧ H} ; same over pos(p) (and season))',
    ('Rostered ceiling percentile', 'player_year / player_all_time'):
        'pctl(max{pts : ro ∧ H} ; same over pos(p) (and season))',
    ('One-man army?', 'team_week'):
        '[t ∈ argmax_u max_{p ∈ S(u,w)} pts(p,w) / PF(u,w)]',
    ('Most bench points?', 'team_week'):
        '[t ∈ argmax_u Σ_{p ∈ R(u,w)∖S(u,w)} pts(p,w)]',
    ('Most injured?', 'team_week'):
        '[t ∈ argmax_u Σ_{p ∈ R(u,w)} INJ(p,w) ∧ that max ≥ 1]',
    ('Times One-man army?', 'team_year / team_all_time'):
        'Σ_w ⟨One-man army?⟩(t,w)',
    ('Times Most bench points?', 'team_year / team_all_time'):
        'Σ_w ⟨Most bench points?⟩(t,w)',
    ('Times Most injured?', 'team_year / team_all_time'):
        'Σ_w ⟨Most injured?⟩(t,w)',
    ('Captain?', 'player_week'):
        "[(p,t) = argmax_{(p',u) : p' ∈ S(u,w)} pts(p',w) / PF(u,w)]  (alphabetical tie-break)",
    ('Times as Captain?', 'player_year / player_all_time'):
        'Σ_w ⟨Captain?⟩(p,w)',
    ('Highest score streak', 'team_week'):
        'RUN_t,w [PF(t,w) = max_u PF(u,w)]',
    ('Lowest score streak', 'team_week'):
        'RUN_t,w [PF(t,w) = min_u PF(u,w)]',
    ('Narrowest victory streak', 'team_week'):
        'RUN_t,w [win(t,w) = 1 ∧ PF − PA = min_{winners u} (PF(u,w) − PA(u,w))]',
    ('Largest blowout streak', 'team_week'):
        'RUN_t,w [win(t,w) = 1 ∧ PF − PA = max_{winners u} (PF(u,w) − PA(u,w))]',
    ('Most efficient streak', 'team_week'):
        'RUN_t,w [PF/MaxPF(t,w) = max_u PF/MaxPF(u,w)]',
    ('Least efficient streak', 'team_week'):
        'RUN_t,w [PF/MaxPF(t,w) = min_u PF/MaxPF(u,w)]',
    ('Top half streak', 'team_week'):
        'RUN_t,w [PF(t,w) ≥ median_u PF(u,w)]',
    ('One-man army streak', 'team_week'):
        'RUN_t,w ⟨One-man army?⟩',
    ('Most bench points streak', 'team_week'):
        'RUN_t,w ⟨Most bench points?⟩',
    ('Most injured streak', 'team_week'):
        'RUN_t,w ⟨Most injured?⟩',
    ('Bottom half streak', 'team_week'):
        'RUN_t,w [PF(t,w) < median_u PF(u,w)]',
    ('150+ PF streak', 'team_week'):
        'RUN_t,w [PF(t,w) ≥ 150]',
    ('Standings leader streak', 'team_week'):
        "RUN_t,w [rank by (Σ_{w' ≤ w, REG} win, Σ_{w' ≤ w, REG} PF) = 1]",
    ('Quiet streak', 'team_week'):
        'RUN_t,w [no tx x with t ∈ rosters(x) ∪ adds/drops roster and fw(d(x)) = w]',
    ('Win streak vs this opponent', 'team_week'):
        'RUN over weeks of t vs the same o of [win(t,w) = 1]',
    ('Player of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{(p',u) : p' ∈ S(u,w)} pts(p',w)]",
    ('QB of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪S(·,w), pos = QB} pts(p',w)]",
    ('RB of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪S(·,w), pos = RB} pts(p',w)]",
    ('WR of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪S(·,w), pos = WR} pts(p',w)]",
    ('TE of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪S(·,w), pos = TE} pts(p',w)]",
    ('Benchwarmer of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmin_{p' ∈ ∪S(·,w)} pts(p',w)]",
    ('Bench QB of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪(R∖S)(·,w), pos = QB} pts(p',w)]",
    ('Bench RB of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪(R∖S)(·,w), pos = RB} pts(p',w)]",
    ('Bench WR of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪(R∖S)(·,w), pos = WR} pts(p',w)]",
    ('Bench TE of the week streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ ∪(R∖S)(·,w), pos = TE} pts(p',w)]",
    ('Highest starter on team streak', 'player_week'):
        "RUN_p over H weeks of [p = argmax_{p' ∈ S(t,w)} pts(p',w)]",
    ('Lowest starter on team streak', 'player_week'):
        "RUN_p over H weeks of [p = argmin_{p' ∈ S(t,w)} pts(p',w)]",
    ('Captain streak', 'player_week'):
        'RUN_p over H weeks of ⟨Captain?⟩(p,w)',
    ('10+ point streak', 'player_week'):
        'RUN_p over H weeks of [pts(p,w) ≥ 10]',
    ('20+ point streak', 'player_week'):
        'RUN_p over H weeks of [pts(p,w) ≥ 20]',
    ('30+ point streak', 'player_week'):
        'RUN_p over H weeks of [pts(p,w) ≥ 30]',
    ('40+ point streak', 'player_week'):
        'RUN_p over H weeks of [pts(p,w) ≥ 40]',
    ('50+ point streak', 'player_week'):
        'RUN_p over H weeks of [pts(p,w) ≥ 50]',
    ('Win streak', 'team_week'):
        "c(t,w) = (c(t,w−1) + 1)·[win(t,w) = 1], reset to 0 at each season's week 1",
    ('Loss streak', 'team_week'):
        'c(t,w) = (c(t,w−1) + 1)·[win(t,w) = 0], reset each season',
    ('Win streak counting previous season', 'team_week'):
        'c(t,w) = (c(t,w−1) + 1)·[win(t,w) = 1], carried across seasons',
    ('Loss streak counting previous season', 'team_week'):
        'c(t,w) = (c(t,w−1) + 1)·[win(t,w) = 0], carried across seasons',
    ('Playoff appearance streak', 'team_year'):
        'RUN over seasons y of [seed(t,y) ≤ 4],  seed = rank by (Σ_{REG} win, Σ_{REG} PF)',
    ('Winning season streak', 'team_year'):
        'RUN over seasons y of [Σ_{w ∈ REG} win(t,w) ≥ (pws(y) − 1)/2]  (in progress: clinched → 1, out of reach → 0, else N/A)',
    ('Highest Win % vs a team', 'team_all_time'):
        'max_{o : n(t,o) ≥ 1} Σ_{w : o(t,w) = o} win(t,w) / n(t,o)',
    ('Lowest Win % vs a team', 'team_all_time'):
        'min_{o : n(t,o) ≥ 1} Σ_{w : o(t,w) = o} win(t,w) / n(t,o)',
    ('Team for highest Win %', 'team_all_time'):
        'argmax_{o : n(t,o) ≥ 1} Σ_{o(t,w)=o} win / n(t,o)',
    ('Team for lowest Win %', 'team_all_time'):
        'argmin_{o : n(t,o) ≥ 1} Σ_{o(t,w)=o} win / n(t,o)',
    ('UPST', 'team_week / league_week / league_year / league_all_time'):
        "team_week: [win(t,w) = 1 ∧ pavg(t,w) < pavg(o,w)], pavg(t,w) = mean_{w' < w, same y} MaxPF(t,w'); N/A for w ≤ 3. league: Σ_t of it",
    ('Donuts (starters)', 'league_week / league_year / league_all_time'):
        'Σ_t Σ_w Σ_{p ∈ S(t,w)} [pts(p,w) = 0]',
    ('Highest starter score', 'league_week / league_year / league_all_time'):
        'max{ pts(p,w) : p ∈ ∪_t S(t,w), w ∈ period }',
    ('Lowest starter score', 'league_week / league_year / league_all_time'):
        'min{ pts(p,w) : p ∈ ∪_t S(t,w), w ∈ period }',
    ('Offseason trades', 'team_year / team_all_time / league_year / league_all_time'):
        '|{ts(x) : type(x) = trade, t ∈ rosters(x), d(x) < kick(y)}|,  kick(y) = min_team gd(team, y, 1); league: over all t',
    ('Inseason trades', 'team_year / team_all_time / league_year / league_all_time'):
        '|{ts(x) : type(x) = trade, t ∈ rosters(x), d(x) ≥ kick(y)}|',
    ('Total trades', 'team_year / team_all_time / league_year / league_all_time'):
        '|{ts(x) : type(x) = trade, t ∈ rosters(x), season(x) = y}|',
    ('Top team', 'player_all_time'):
        'argmax_t [Σ_{tenures of p on t} (in-season seconds of the tenure, open tenures to asof) + 604800·|{w : ro(p,t,w)}|]',
    ('Top Team', 'player_year'):
        'argmax_t Σ_{tenures of p on t within season y} days on t',
    ('Last team', 'player_year / player_all_time'):
        "t with ro(p,t,w_last) = 1, w_last = p's last rostered in-season week of y (all-time: of his last rostered season)",
    ('Age', 'player_week / player_year'):
        'age(p, dw(y,w)) = (Sep 1 of y + 7(w−1) − birth(p)) / 365.25; player_year = mean_w',
    ('Rookie?', 'player_week / player_year'):
        '[y = rookie_year(p)],  rookie_year = Sleeper metadata rookie year, else current season − yexp(p)',
    ('Injury?', 'player_week'):
        'INJ(p,w) = ro(p,·,w) ∧ pts(p,w) = 0 ∧ ¬APP(p,y,w) ∧ ¬BYE(p,w) ∧ ¬SUS(p,w) ∧ ¬[GDS(p,y,w) = active]',
    ('Suspension?', 'player_week'):
        "SUS(p,w) = ¬BYE(p,w) ∧ (SUSP(p,y,w) ∨ injS(p) = 'NA' for week w)",
    ('Bye?', 'player_week'):
        "BYE(p,w) = [pts(p,w) = 0 ∧ (nfl(p,y,w) = 'NFL' ∨ no game for nfl(p,y,w) in week w of schedules)]",
    ('% of points (if starter)', 'player_week'):
        'pts(p,w) / PF(t,w) if st(p,t,w) = 1, else blank',
    ('Change from previous week', 'player_week'):
        "pts(p,w) − pts(p,w⁻),  w⁻ = p's previous week with H; blank if ¬H(p,w)",
    ('Change from previous 5 weeks avg', 'player_week'):
        "pts(p,w) − mean{pts(p,w') : the 5 latest w' < w with H(p,w')}",
    ('Change from career average to that point', 'player_week'):
        "pts(p,w) − mean{pts(p,w') : w' < w, H(p,w')}",
    ('Change from overall career average', 'player_week'):
        "pts(p,w) − mean{pts(p,w') : all w' with H(p,w')}",
    ('Number of weeks on team', 'player_week'):
        "|{w' ≤ w : contiguous run of weeks with ro(p,t,w') = 1}|",
    ('Per-team tenure metrics (terminal-encoded)', 'player_week'):
        "over p's tenure weeks U = {w : ro(p,t,w)}: % of starts = Σ_U st / |U|; % of team points = Σ_U st·pts(p,w) / Σ_U Σ_{q ∈ S(t,w)} pts(q,w); weeks = |U|; points/PPG as starter = Σ_U st·pts, ÷ Σ_U st; bench = same with (1 − st); top/bottom starter weeks = Σ_U [p = argmax/argmin_{S(t,w)} pts]; value shown on the tenure's last week (RUN encoding)",
    ('Player tenure totals (not per team)', 'player_year / player_all_time'):
        'rostered = Σ_w ro(p,·,w); % of starts = Σ st / Σ ro; total points as starter = Σ st·pts(p,w); % of league points = Σ st·pts / Σ_{t,w} Σ_{q ∈ S(t,w)} pts(q,w)',
    ('Healthy weeks rostered', 'player_year / player_all_time'):
        '|{w : ro(p,·,w) ∧ H(p,w)}|',
    ('Healthy weeks on bench', 'player_year / player_all_time'):
        '|{w : ro ∧ ¬st ∧ H(p,w)}|',
    ('Healthy % of starts', 'player_year / player_all_time'):
        'Σ_{w : ro ∧ H} st(p,·,w) / |{w : ro ∧ H}|; N/A if 0',
    ('Total points on bench', 'player_year / player_all_time'):
        'Σ_{w : ro ∧ ¬st} pts(p,w)',
    ('Number of consecutive weeks on bench before start (if starter)', 'player_week'):
        "if st(p,t,w): |{maximal run of w' < w with ro ∧ ¬st}|",
    ('Number of consecutive weeks on bench before start excluding injury/bye (if starter)', 'player_week'):
        "if st(p,t,w): |{maximal run of w' < w with ro ∧ ¬st, weeks with ¬H skipped}|",
    ('Difference from best startable bench (if starter)', 'player_week'):
        'if st(p,t,w): pts(p,w) − max{pts(b,w) : b ∈ R(t,w)∖S(t,w), b slot-eligible}',
    ('Difference from worst benchable starter (if bench)', 'player_week'):
        'if ¬st(p,t,w): pts(p,w) − min{pts(s,w) : s ∈ S(t,w), p eligible for slot(s)} (empty slot = 0)',
    ('Reference player name', 'player_week'):
        "the argmax b (starter row) / argmin s (bench row) of the two equations above; 'Empty slot' if S(t,w) has a '0'",
    ('Difference in averages of best/worst startables over previous 5 games', 'player_week'):
        "avg5(p) − avg5(ref),  avg5(q) = mean of npts(q,·,·) over q's last 5 regular-season NFL games before week w (stat line or snap; snap-only = 0); ref = the best startable bench / worst benchable starter",
    ('Cuff adjusted difference', 'player_week'):
        '(pts(p,w) − pts(ref,w)) · (½ if ⟨Activated Cuff?⟩(p,w) else 1)',
    ('- Activated Cuff? (Did he start while a teammate he is the handcuff for was injured?)', 'player_week'):
        'st(p,t,w) ∧ ∃ q ∈ R(t,w_kick): nfl(q)=nfl(p), pos(q)=pos(p), TEST(q,p,w) ∧ INJ(q,w)',
    ('Player of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t S(t,w)} pts(p',w)]",
    ('Times as Player of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨Player of the week?⟩(p,w)',
    ('QB of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t S(t,w), pos = QB} pts(p',w)]",
    ('Times as QB of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨QB of the week?⟩(p,w)',
    ('RB of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t S(t,w), pos = RB} pts(p',w)]",
    ('Times as RB of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨RB of the week?⟩(p,w)',
    ('WR of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t S(t,w), pos = WR} pts(p',w)]",
    ('Times as WR of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨WR of the week?⟩(p,w)',
    ('TE of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t S(t,w), pos = TE} pts(p',w)]",
    ('Times as TE of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨TE of the week?⟩(p,w)',
    ('Benchwarmer of the week?', 'player_week'):
        "[p = argmin_{p' ∈ ∪_t S(t,w)} pts(p',w)], none if ≥ 2 tie at 0",
    ('Times as Benchwarmer of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨Benchwarmer of the week?⟩(p,w)',
    ('Bench QB of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t R∖S(t,w), pos = QB} pts(p',w)]",
    ('Times as Bench QB of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨Bench QB of the week?⟩(p,w)',
    ('Bench RB of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t R∖S(t,w), pos = RB} pts(p',w)]",
    ('Times as Bench RB of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨Bench RB of the week?⟩(p,w)',
    ('Bench WR of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t R∖S(t,w), pos = WR} pts(p',w)]",
    ('Times as Bench WR of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨Bench WR of the week?⟩(p,w)',
    ('Bench TE of the week?', 'player_week'):
        "[p = argmax_{p' ∈ ∪_t R∖S(t,w), pos = TE} pts(p',w)]",
    ('Times as Bench TE of the week?', 'player_year / player_all_time'):
        'Σ_w ⟨Bench TE of the week?⟩(p,w)',
    ('Highest starter on team?', 'player_week'):
        "[p = argmax_{p' ∈ S(t,w)} pts(p',w)]",
    ('Times as Highest starter on team?', 'player_year / player_all_time'):
        'Σ_w ⟨Highest starter on team?⟩(p,w)',
    ('Lowest starter on team?', 'player_week'):
        "[p = argmin_{p' ∈ S(t,w)} pts(p',w)]",
    ('Times as Lowest starter on team?', 'player_year / player_all_time'):
        'Σ_w ⟨Lowest starter on team?⟩(p,w)',
    ('Number of Add/Drops', 'player_week / player_year / player_all_time / team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{x : type(x) ∈ {waiver, free_agent, commissioner}, status = complete, subject ∈ adds(x) ∪ drops(x) (player) or roster of x = t (team) or any (league), fw(d(x)) ∈ period}|',
    ('Number of waiver adds', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{x counted in Number of Add/Drops : type(x) = waiver, adds(x) ≠ ∅}|',
    ('Number of free agency adds', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{x counted : type(x) ∈ {free_agent, commissioner}, adds(x) ≠ ∅}|',
    ('Number of pure drops', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{x counted : adds(x) = ∅, drops(x) ≠ ∅}|',
    ('Total transactions', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '⟨Number of Add/Drops⟩ + |{trades : t ∈ rosters(x), fw(d(x)) ∈ period}|  (year/all-time: distinct ts(x))',
    ('Number of drops', 'player_week / player_year / player_all_time'):
        '|{x : drops(x)[p] defined, fw(d(x)) ∈ period}|',
    ('Number of trades', 'player_week / player_year / player_all_time / team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{x : type(x) = trade, subject ∈ assets(x) / rosters(x), fw(d(x)) ∈ period}|',
    ('Avg points', 'player_year / player_all_time / team_year / team_all_time'):
        'mean{ pts(p,w) : ro(p,t,w) = 1 }  (team sheets: per team)',
    ('Adjusted Avg points', 'player_year / player_all_time'):
        'mean{ pts(p,w) : ro ∧ H(p,w) }',
    ('Points (full season)', 'player_year'):
        'Σ_w npts(p,y,w) over all APP weeks of y',
    ('Points (full career)', 'player_all_time'):
        'Σ_{y,w} npts(p,y,w) over all APP weeks',
    ('Avg points (full season)', 'player_year'):
        'Σ_w npts(p,y,w) / |{w : APP(p,y,w)}|',
    ('Avg points (full career)', 'player_all_time'):
        'Σ_{y,w} npts(p,y,w) / |{(y,w) : APP(p,y,w)}|',
    ('PPG starter', 'player_year / player_all_time'):
        'mean{ pts(p,w) : st(p,·,w) = 1 }',
    ('PPG bench', 'player_year / player_all_time'):
        'mean{ pts(p,w) : ro ∧ ¬st }',
    ('Adjusted PPG starter', 'player_year / player_all_time'):
        'mean{ pts(p,w) : st ∧ H }',
    ('Adjusted PPG bench', 'player_year / player_all_time'):
        'mean{ pts(p,w) : ro ∧ ¬st ∧ H }',
    ('PPG starter vs bench diff', 'player_year / player_all_time'):
        'mean{pts : st ∧ H} − mean{pts : ro ∧ ¬st ∧ H}  (missing side = 0)',
    ('Number of teams', 'player_year / player_all_time'):
        '|{t : ∃ w ∈ period, ro(p,t,w) = 1}|',
    ('Weeks as starter', 'player_year / player_all_time'):
        'Σ_w st(p,·,w)',
    ('Win % as starter', 'player_year / player_all_time'):
        'Σ_{w : st(p,t,w)} win(t,w) / |{w : st(p,t,w), game played}|; N/A if that count < 5',
    ('Win % while rostered', 'player_year / player_all_time'):
        'Σ_{w : ro(p,t,w)} win(t,w) / |{w : ro(p,t,w), game played}|; N/A if < 5',
    ('Rostered by champion?', 'player_year'):
        'champ(y) = winner of the Final in WB(y); rostered = [∃ w ∈ y : ro(p, champ, w)]; started = [∃ w : st(p, champ, w)]; started in final = [st(p, champ, w_final)]',
    ('Championships rostered by', 'player_all_time'):
        'Σ_y [∃ w : ro(p,champ(y),w)]; Σ_y [∃ w : st(p,champ(y),w)]; Σ_y [st(p,champ(y),w_final(y))]',
    ('Weeks missed due to injury', 'player_year / player_all_time'):
        '|{w : ro(p,·,w) ∧ pts(p,w) = 0 ∧ INJ(p,w)}|',
    ('Weeks missed due to suspension', 'player_year / player_all_time'):
        '|{w : ro(p,·,w) ∧ pts(p,w) = 0 ∧ SUS(p,w)}|',
    ('Change in points from previous season', 'player_year'):
        'Σ_w npts(p,y,w) − Σ_w npts(p,y−1,w)',
    ('Change in avg points from previous season', 'player_year'):
        'Σ_w npts(p,y,w)/n(p,y) − Σ_w npts(p,y−1,w)/n(p,y−1),  n = |{w : APP}|',
    ('Change in points from career', 'player_year'):
        "Σ_w npts(p,y,w) − (Σ_{y' < y} Σ_w npts(p,y',w)) / |{y' < y with games}|",
    ('Change in avg points from career', 'player_year'):
        "Σ_w npts(p,y,w)/n(p,y) − Σ_{y' < y} Σ_w npts(p,y',w) / Σ_{y' < y} n(p,y'); blank if n(p,y) < 2",
    ('Taxi-eligible', 'player_all_time'):
        "[current season = p's first season with any ro(p,·,w) ∧ Σ_w st(p,·,w) = 0]",
    ('PF', 'team_week'):
        'PF(t,w) = P(t,w) + 5·[w = pws(y) ∧ t is the better regular-season seed of a semifinal pair]',
    ('Points against', 'team_week / team_year / team_all_time'):
        'PA(t,w) = PF(o(t,w), w); year/all-time = Σ_w',
    ('Max PF', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'MaxPF(t,w) = OPT({pts(p,w) : p ∈ R(t,w)}, y); year/all-time/league = Σ',
    ('Margin', 'team_week'):
        'PF(t,w) − PA(t,w)',
    ('Margin entering SNF / Monday / last game', 'team_week'):
        "IN(t,w,T) − IN(o(t,w),w,T), IN(t,w,T) = PF(t,w) − Σ_{p ∈ S(t,w), ko(nfl(p,y,w),y,w) ≥ T} pts(p,w); T = first Sunday ko ≥ 19:00 (SNF) / first ko after Sunday (Monday) / max ko over S(t,w) ∪ S(o,w) if ≥ Sunday 19:00 (last game); no such T → N/A",
    ('Comebacks entering SNF / Monday / last game', 'team_week'):
        "M = IN(t,w,T) − IN(o(t,w),w,T); margin overcome MO = −M when win(t,w) = 1 ∧ M < 0; points overcome D = PF(o(t,w),w) − IN(t,w,T) when win(t,w) = 1 ∧ D > 0; else N/A; D / PF(o(t,w),w); MO / IN(o(t,w),w,T); D / L and MO / L, L = |{p ∈ S(t,w) : ko(nfl(p,y,w),y,w) ≥ T}| (N/A when L = 0); own share (PF(t,w) − IN(t,w,T)) / PF(t,w) — IN as in ⟨Margin entering SNF / Monday / last game⟩",
    ('Comeback size', 'team_week'):
        "μ(p,w) = (Σ_{w'<w, same season} pts(p,w') + 4·avg_{y−1}(p) + 6·m_pos(<w)) / (n + 4·[played y−1] + 6); z(T) = (IN(t,w,T) − IN(o,w,T) + Σ_{p ∈ S(t,w), ko ≥ T} μ − Σ_{p ∈ S(o,w), ko ≥ T} μ) / (2.1·√Σ_{p ∈ S(t,w) ∪ S(o,w), ko ≥ T} max(μ,1)); size = max_{i<j} max(0, −z(T_i)) · Φ(z(T_j)), z(T_end) ↦ Φ = win(t,w); stage: i = T only; plain: T_i over every matchup kickoff but the first",
    ('Win?', 'team_week'):
        'win(t,w) = [PF > PA] + ½[PF = PA]  (2026+ two-week final: PF summed over both weeks)',
    ('Efficiency', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'PF / MaxPF  (period: Σ PF / Σ MaxPF)',
    ('Boldness', 'player_week'):
        'max(0, max{XP(b,y,w) : b ∈ R(t,w) ∖ S(t,w), H(b,w), FITS(Fs ∖ {p} ∪ {b}, Σ_Fs)} − XP(p,y,w)) for a starter p; Fs = S(t,w) minus empty slots and dead starts (¬H ∧ pts = 0), Σ_Fs = their slots; N/A on bench rows, empty slots and dead starts',
    ('Lineup Boldness', 'team_week / team_year / team_all_time'):
        "max(0, BLV({XP(q,y,w) : q ∈ Fs ∪ {b ∈ R(t,w) ∖ S(t,w) : H(b,w)}}, Σ_Fs) − Σ_{q ∈ Fs} XP(q,y,w)), Fs = S(t,w) minus empty slots and dead starts, Σ_Fs = the filled slots; team_year / team_all_time = mean over weeks played; N/A before the season's first game",
    ('Empty slots', 'team_week / team_year / team_all_time'):
        "|{i : S(t,w)[i] = '0' ∨ (¬H(S(t,w)[i],w) ∧ pts(S(t,w)[i],w) = 0)}|  (2020: ESPN slots left empty); year/all-time = Σ",
    ('Brosenzweig', 'team_week'):
        '[win(t,w) = 0 ∧ |{u : PF(u,w) > PF(t,w)}| = 1]',
    ('Sisenzweig', 'team_week'):
        '[win(t,w) = 1 ∧ |{u : PF(u,w) < PF(t,w)}| = 1]',
    ('Times Brosenzweig', 'team_year / team_all_time'):
        'Σ_w ⟨Brosenzweig⟩(t,w)',
    ('Times Sisenzweig', 'team_year / team_all_time'):
        'Σ_w ⟨Sisenzweig⟩(t,w)',
    ('Highest score?', 'team_week'):
        '[PF(t,w) = max_u PF(u,w)]',
    ('Times Highest score?', 'team_year / team_all_time'):
        'Σ_w [PF(t,w) = max_u PF(u,w)]',
    ('Lowest score?', 'team_week'):
        '[PF(t,w) = min_u PF(u,w)]',
    ('Times Lowest score?', 'team_year / team_all_time'):
        'Σ_w [PF(t,w) = min_u PF(u,w)]',
    ('Narrowest victory?', 'team_week'):
        '[win(t,w) = 1 ∧ PF − PA = min_{u : win(u,w) = 1} (PF(u,w) − PA(u,w))]',
    ('Times Narrowest victory?', 'team_year / team_all_time'):
        'Σ_w ⟨Narrowest victory?⟩(t,w)',
    ('Largest blowout?', 'team_week'):
        '[win(t,w) = 1 ∧ PF − PA = max_{u : win(u,w) = 1} (PF(u,w) − PA(u,w))]',
    ('Times Largest blowout?', 'team_year / team_all_time'):
        'Σ_w ⟨Largest blowout?⟩(t,w)',
    ('Most efficient?', 'team_week'):
        '[PF/MaxPF(t,w) = max_u PF/MaxPF(u,w)]',
    ('Times Most efficient?', 'team_year / team_all_time'):
        'Σ_w ⟨Most efficient?⟩(t,w)',
    ('Least efficient?', 'team_week'):
        '[PF/MaxPF(t,w) = min_u PF/MaxPF(u,w)]',
    ('Times Least efficient?', 'team_year / team_all_time'):
        'Σ_w ⟨Least efficient?⟩(t,w)',
    ('Top half of league?', 'team_week'):
        '[PF(t,w) ≥ median_u PF(u,w)]',
    ('Times Top half of league?', 'team_year / team_all_time'):
        'Σ_w [PF(t,w) ≥ median_u PF(u,w)]',
    ('Increase in points from previous week', 'team_week / league_week / league_year'):
        "PF(t,w) − PF(t,w−1)  (w = 1: previous season's last week); league: Σ_t; year = mean",
    ('Increase in efficiency from previous week', 'team_week'):
        'PF(t,w)/MaxPF(t,w) − PF(t,w−1)/MaxPF(t,w−1)',
    ('Roster turnover from previous week', 'team_week'):
        'max(|R(t,w)|, |R(t,w−1)|) − |R(t,w) ∩ R(t,w−1)|',
    ('Starter turnover from previous week', 'team_week / league_week'):
        'max(|S(t,w)|, |S(t,w−1)|) − |S(t,w) ∩ S(t,w−1)|',
    ('Difference in pregame avg max PF from opponent', 'team_week'):
        "pavg(t,w) − pavg(o,w),  pavg(t,w) = mean_{w' < w, same y} MaxPF(t,w'); N/A for w ≤ 3",
    ('Number of Injuries', 'team_week / league_week'):
        'Σ_{p ∈ R(t,w)} INJ(p,w)',
    ('Number of suspensions', 'team_week / league_week'):
        'Σ_{p ∈ R(t,w)} SUS(p,w)',
    ('Number of players on bye', 'team_week / league_week'):
        'Σ_{p ∈ R(t,w)} BYE(p,w)',
    ('Number of starter injuries', 'team_week'):
        'Σ_{p ∈ R(t,w)} [pts = 0 ∧ INJ ∧ ¬BYE ∧ s_h(p,w) > 0]',
    ('Number of starter suspensions', 'team_week'):
        'Σ_{p ∈ R(t,w)} [pts = 0 ∧ SUS ∧ ¬BYE ∧ s_h(p,w) > 0]',
    ('Starter-adjusted Hardship', 'team_week / team_year / team_all_time / league_week'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) = 0 ∧ (INJ ∨ SUS) ∧ ¬BYE] · max(0, E_h(p,w)) · s_h(p,w)',
    ('Luck', 'team_week / team_year'):
        'Luck(t,w) = (0.27·OUT + 0.14·SIS − 0.14·BROS)·(1.8 if stage(t,w) ∈ PO else 1) + (0.36·OPP + 0.10·OWN)·GATE − 0.36·ADV + 0.12·EFF + 0.16·CLOSE − 0.25·LFH; OUT = win(t,w) − 1/(1 + e^(−1.5·δ)), δ = ⅓[z_all(μMax_t − μMax_o) + z_all(μPF_t − μPF_o) + z_all(μwin_t − μwin_o)] (z_all over every team-week row), OPP = z_wk(−(PA(t,w) − μPF_o)), OWN = z_wk(PF(t,w) − μPF_t), ADV = z_wk(Hard + SAHard + 3·Σ_{p ∈ R(t,w)} BYE(p,w)), EFF = z_wk(PF/MaxPF), CLOSE = sgn(m)·max(0, 1 − |m|/8), GATE = 1/(1 + |m|/15), m = PF − PA; 0 with no opponent; team_year = Σ_w Luck(t,w)',
    ('Win %', 'team_year'):
        'Σ_{w ∈ y} win(t,w) / |{games of t in y}|',
    ('Record', 'team_year'):
        "'Σ_w [win = 1]' − 'Σ_w [win = 0]' over all games of y",
    ('All time record', 'team_all_time'):
        "'Σ [win = 1]' − 'Σ [win = 0]' over all games",
    ('All time win %', 'team_all_time'):
        'Σ_{all w} win(t,w) / |{games}|',
    ('Regular season record', 'team_year / team_all_time'):
        "'Σ_{w ∈ REG} [win = 1]' − 'Σ_{w ∈ REG} [win = 0]'",
    ('Regular season win %', 'team_year / team_all_time'):
        'Σ_{w ∈ REG} win(t,w) / |{w ∈ REG}|',
    ('Playoff record', 'team_all_time'):
        'W-L over w with stage(t,w) ∈ {Semifinal, Final}',
    ('Playoff win %', 'team_all_time'):
        'Σ_{stage ∈ {Semifinal, Final}} win / count',
    ('Toilet bowl record', 'team_all_time'):
        'W-L over w with stage(t,w) ∈ {Toilet Semis, Toilet Final}',
    ('Toilet bowl win %', 'team_all_time'):
        'Σ_{stage ∈ {Toilet Semis, Toilet Final}} win / count',
    ('Third place game record', 'team_all_time'):
        'W-L over w with stage(t,w) = 3rd Place',
    ('Toilet losers game record', 'team_all_time'):
        'W-L over w with stage(t,w) = Toilet losers',
    ('Differential', 'team_year / team_all_time'):
        'Σ_w (PF(t,w) − PA(t,w))',
    ('Avg differential', 'team_year / team_all_time'):
        'Σ_w (PF − PA) / |{games}|',
    ('Record vs playoff teams', 'team_year / team_all_time'):
        'W-L over w with seed(o(t,w), y) ≤ 4',
    ('Win % vs playoff teams', 'team_year / team_all_time'):
        'Σ_{w : seed(o,y) ≤ 4} win / count',
    ('Record vs non-playoff teams', 'team_year / team_all_time'):
        'W-L over w with seed(o(t,w), y) > 4',
    ('Win % vs non-playoff teams', 'team_year / team_all_time'):
        'Σ_{w : seed(o,y) > 4} win / count',
    ('Record vs champion', 'team_year'):
        'W-L over w with o(t,w) = champ(y)',
    ('Win % vs champion', 'team_year'):
        'Σ_{o(t,w) = champ(y)} win / count',
    ('Record vs champions', 'team_all_time'):
        'W-L over all y, w with o(t,w) = champ(y)',
    ('Win % vs champions', 'team_all_time'):
        'Σ_{o(t,w) = champ(y)} win / count, pooled over seasons',
    ('Record vs last place', 'team_year / team_all_time'):
        'W-L over w with o(t,w) = last(y),  last(y) = the team with seed = N',
    ('Win % vs last place', 'team_year / team_all_time'):
        'Σ_{o(t,w) = last(y)} win / count',
    ('Result', 'team_year'):
        '1st-4th = place in WB(y) (Final winner/loser, 3rd-place winner/loser); 5th-8th = rank of non-playoff teams by (Σ win, Σ PF) (2020-24 incl. toilet bracket games, 2025+ REG only)',
    ('Week of playoff elimination', 'team_year'):
        "0 if seed(t,y) ≤ 4; else min{w ∈ REG : |{u ≠ t : W_u(w)/n_u > (W_t(w) + n_t − g_t(w))/n_t}| ≥ 4}, W_u(w) = Σ_{w' ≤ w, REG} win(u,w'), g_u(w) = REG games played through w, n_u = REG games; no such week → the last REG week; blank for an incomplete season",
    ('Championships', 'team_all_time'):
        'Σ_y [t = champ(y)]',
    ('Number of playoff appearances', 'team_all_time'):
        'Σ_y [seed(t,y) ≤ 4]',
    ('Number of championship appearances', 'team_all_time'):
        'Σ_y [t plays the Final of WB(y)]',
    ('Number of last place finishes', 'team_all_time'):
        'Σ_y [seed(t,y) = N]  (last in the regular-season standings; completed seasons)',
    ('Average weekly roster turnover', 'team_year / team_all_time'):
        'mean_w (max(|R(t,w)|, |R(t,w−1)|) − |R(t,w) ∩ R(t,w−1)|); all-time = mean of season values',
    ('Average weekly starter turnover', 'team_year / team_all_time'):
        'mean_w (max(|S(t,w)|, |S(t,w−1)|) − |S(t,w) ∩ S(t,w−1)|)',
    ('Inseason roster turnover', 'team_year / team_all_time / league_year'):
        '|R(t,w1) ∖ R(t,wF)| + |R(t,wF) ∖ R(t,w1)|,  w1 = week 1, wF = championship week; all-time = mean',
    ('Inseason starter turnover', 'team_year / team_all_time / league_year'):
        '|S(t,w1) ∖ S(t,wF)| + |S(t,wF) ∖ S(t,w1)|',
    ('Offseason roster turnover', 'team_year / team_all_time / league_year'):
        '|R(t,wF of y−1) ∖ R(t,w1 of y)| + |R(t,w1 of y) ∖ R(t,wF of y−1)|',
    ('Offseason starter turnover', 'team_year / team_all_time / league_year'):
        '|S(t,wF of y−1) ∖ S(t,w1 of y)| + |S(t,w1 of y) ∖ S(t,wF of y−1)|',
    ('Draft Value', 'team_year / team_all_time'):
        'Σ_{pk : by(pk) = t, rookie draft of y} 1 / (dslot(pk) + 1),  dslot = pick in round (2.09 → 8, 5.0X → 8)',
    ('Number of first round picks made', 'team_year / team_all_time'):
        '|{pk : by(pk) = t, rookie draft of y, round(pk) = 1}|',
    ('Total number of picks made', 'team_year / team_all_time'):
        '|{pk : by(pk) = t, rookie draft of y}|',
    ('3-year roster retention rate', 'team_year / team_all_time'):
        '|R(t,w1 of y) ∩ R(t,w1 of y+3)| / |R(t,w1 of y)|; all-time = mean',
    ('Future draft capital', 'team_week / team_year / team_all_time'):
        'Σ_{(Y, r) : own(Y,r,·) = t at the date, Y ∈ y+1 … y+5} ω(r),  ω = {1: .25, 2: .09, 3: .03, 4: .01}; team_year = the season-end value',
    ('Points per QB started', 'league_week / league_year / league_all_time'):
        'Σ_{t,w} Σ_{p ∈ S(t,w), posS(p) = QB} pts(p,w) / Σ_{t,w} |{p ∈ S(t,w) : posS(p) = QB}|',
    ('Points per WR started', 'league_week / league_year / league_all_time'):
        'Σ_{t,w} Σ_{p ∈ S(t,w), posS(p) = WR} pts(p,w) / Σ_{t,w} |{p ∈ S(t,w) : posS(p) = WR}|',
    ('Points per RB started', 'league_week / league_year / league_all_time'):
        'Σ_{t,w} Σ_{p ∈ S(t,w), posS(p) = RB} pts(p,w) / Σ_{t,w} |{p ∈ S(t,w) : posS(p) = RB}|',
    ('Points per TE started', 'league_week / league_year / league_all_time'):
        'Σ_{t,w} Σ_{p ∈ S(t,w), posS(p) = TE} pts(p,w) / Σ_{t,w} |{p ∈ S(t,w) : posS(p) = TE}|',
    ('Combined points', 'team_week'):
        "PF(t,w) + PF(o,w)  (on the winner's row)",
    ('Combined Max PF', 'team_week'):
        'MaxPF(t,w) + MaxPF(o,w)',
    ('Combined efficiency', 'team_week'):
        '(PF(t,w)/MaxPF(t,w) + PF(o,w)/MaxPF(o,w)) / 2',
    ('Combined bench points', 'team_week'):
        '(MaxPF(t,w) + MaxPF(o,w)) − (PF(t,w) + PF(o,w))',
    ('Combined points from QBs', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w), posS = QB} pts(p,w)',
    ('Combined points from WRs', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w), posS = WR} pts(p,w)',
    ('Combined points from RBs', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w), posS = RB} pts(p,w)',
    ('Combined points from TEs', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w), posS = TE} pts(p,w)',
    ('Combined QBs started', 'team_week'):
        'Σ_{u ∈ {t,o}} |{p ∈ S(u,w) : posS = QB}|',
    ('Combined WRs started', 'team_week'):
        'Σ_{u ∈ {t,o}} |{p ∈ S(u,w) : posS = WR}|',
    ('Combined RBs started', 'team_week'):
        'Σ_{u ∈ {t,o}} |{p ∈ S(u,w) : posS = RB}|',
    ('Combined TEs started', 'team_week'):
        'Σ_{u ∈ {t,o}} |{p ∈ S(u,w) : posS = TE}|',
    ('Combined points per QB started', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{S(u,w), QB} pts / Σ_{u ∈ {t,o}} |{S(u,w), QB}|',
    ('Combined points per WR started', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{S(u,w), WR} pts / Σ_{u ∈ {t,o}} |{S(u,w), WR}|',
    ('Combined points per RB started', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{S(u,w), RB} pts / Σ_{u ∈ {t,o}} |{S(u,w), RB}|',
    ('Combined points per TE started', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{S(u,w), TE} pts / Σ_{u ∈ {t,o}} |{S(u,w), TE}|',
    ('Combined donuts (starters)', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w)} [pts(p,w) = 0]',
    ('Combined players under 10 pts (starters)', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w)} [pts(p,w) < 10]',
    ('Combined players over 20 pts (starters)', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w)} [pts(p,w) > 20]',
    ('Combined players over 30 pts (starters)', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w)} [pts(p,w) > 30]',
    ('Combined players over 40 pts (starters)', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w)} [pts(p,w) > 40]',
    ('Combined players over 50 pts (starters)', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ S(u,w)} [pts(p,w) > 50]',
    ('Combined % of starters boom', 'team_week'):
        '½ Σ_{u ∈ {t,o}} |{p ∈ S(u,w) : H, pts ≥ q90(Q_pos)}| / |{p ∈ S(u,w) : H}|',
    ('Combined % of starters bust', 'team_week'):
        '½ Σ_{u ∈ {t,o}} |{p ∈ S(u,w) : H, pts ≤ q10(Q_pos)}| / |{p ∈ S(u,w) : H}|',
    ('Combined starter injuries', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ R(u,w)} [pts = 0 ∧ INJ ∧ ¬BYE ∧ s_h > 0]',
    ('Combined players on bye', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ R(u,w)} BYE(p,w)',
    ('Combined starter-adjusted Hardship', 'team_week'):
        'Σ_{u ∈ {t,o}} Σ_{p ∈ R(u,w)} [pts = 0 ∧ (INJ ∨ SUS) ∧ ¬BYE]·max(0,E_h)·s_h',
    ('Combined rookies started', 'team_week'):
        'Σ_{u ∈ {t,o}} |{p ∈ S(u,w) : y = rookie_year(p)}|',
    ('Combined starter turnover from previous week', 'team_week'):
        'Σ_{u ∈ {t,o}} (max(|S(u,w)|, |S(u,w−1)|) − |S(u,w) ∩ S(u,w−1)|)',
    ('Amount of FAAB spent', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{x : type = waiver, status = complete, roster = t, fw(d(x)) ∈ period} bid(x)',
    ('Change in win % from previous season', 'team_year'):
        'Σ_{w ∈ y} win / n_y − Σ_{w ∈ y−1} win / n_{y−1}',
    ('Change in efficiency from previous season', 'team_year'):
        'Σ_{y} PF / Σ_{y} MaxPF − Σ_{y−1} PF / Σ_{y−1} MaxPF',
    ('Avg yearly luck', 'team_all_time'):
        'mean_y Σ_{w ∈ y} Luck(t,w)',
    ('Avg PF', 'league_year / league_all_time'):
        'Σ_{t,w} PF(t,w) / |{(t,w) games}|',
    ('Avg max PF', 'team_year / team_all_time / league_year / league_all_time'):
        'Σ_w MaxPF(t,w) / |{w}|  (league: over all t)',
    ('Avg points against', 'team_year / team_all_time'):
        'Σ_w PA(t,w) / |{w}|',
    ('Avg margin', 'league_week / league_year / league_all_time'):
        'mean{ PF(t,w) − PA(t,w) : win(t,w) = 1 }  (one row per game)',
    ('Weeks of injuries', 'team_year / team_all_time'):
        'Σ_w Σ_{p ∈ R(t,w)} INJ(p,w)',
    ('Weeks of starter injuries', 'team_year / team_all_time'):
        'Σ_w Σ_{p ∈ R(t,w)} [pts = 0 ∧ INJ ∧ ¬BYE ∧ s_h > 0]',
    ('Weeks of starter suspensions', 'team_year / team_all_time'):
        'Σ_w Σ_{p ∈ R(t,w)} [pts = 0 ∧ SUS ∧ ¬BYE ∧ s_h > 0]',
    ('Weeks suspensions', 'team_year / team_all_time'):
        'Σ_w Σ_{p ∈ R(t,w)} SUS(p,w)',
    ('Number of weeks missed due to injury', 'league_year / league_all_time'):
        'Σ_{t,w} Σ_{p ∈ R(t,w)} INJ(p,w)',
    ('Number of weeks missed due to suspensions', 'league_year / league_all_time'):
        'Σ_{t,w} Σ_{p ∈ R(t,w)} SUS(p,w)',
    ('Number of QB started', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ S(t,w) : posS(p) = QB}|  (year/all-time: |∪_w {…}| distinct)',
    ('Number of QB rostered', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ R(t,w) : posS(p) = QB}|  (year/all-time: distinct)',
    ('Number of RB started', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ S(t,w) : posS(p) = RB}|',
    ('Number of RB rostered', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ R(t,w) : posS(p) = RB}|',
    ('Number of WR started', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ S(t,w) : posS(p) = WR}|',
    ('Number of WR rostered', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ R(t,w) : posS(p) = WR}|',
    ('Number of TE started', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ S(t,w) : posS(p) = TE}|',
    ('Number of TE rostered', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ R(t,w) : posS(p) = TE}|',
    ('Points from QBs', 'team_week / team_year / team_all_time'):
        'Σ_{p ∈ S(t,w), posS(p) = QB} pts(p,w)  (and RB / WR / TE); year/all-time = Σ_w',
    ('% of points from QBs', 'team_week / team_year / team_all_time'):
        'Σ_w Σ_{p ∈ S(t,w), posS = QB} pts(p,w) / Σ_w Σ_{p ∈ S(t,w)} pts(p,w)  (and RB / WR / TE)',
    ('Stacks', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        "Σ_{q ∈ S(t,w), posS(q) = QB} |{p ∈ S(t,w) : posS(p) ∈ {RB, WR, TE}, nfl(p) = nfl(q) ≠ 'NFL'}|",
    ('Most number of players started from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ S(t,w) : nfl(p,y,w) = team}|; year/all-time/league = max',
    ('Most number of players rostered from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ R(t,w) : nfl(p,y,w) = team}|',
    ('Most number of QBs started from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ S(t,w) : posS(p) = QB, nfl(p,y,w) = team}|',
    ('Most number of QBs rostered from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ R(t,w) : posS(p) = QB, nfl(p,y,w) = team}|',
    ('Most number of RBs started from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ S(t,w) : posS(p) = RB, nfl(p,y,w) = team}|',
    ('Most number of RBs rostered from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ R(t,w) : posS(p) = RB, nfl(p,y,w) = team}|',
    ('Most number of WR started from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ S(t,w) : posS(p) = WR, nfl(p,y,w) = team}|',
    ('Most number of WR rostered from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ R(t,w) : posS(p) = WR, nfl(p,y,w) = team}|',
    ('Most number of TE started from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ S(t,w) : posS(p) = TE, nfl(p,y,w) = team}|',
    ('Most number of TE rostered from same NFL team', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_team |{p ∈ R(t,w) : posS(p) = TE, nfl(p,y,w) = team}|',
    ('Number of NFL teams among starting players', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{nfl(p,y,w) : p ∈ S(t,w)}|  (year/all-time/league: distinct over the union)',
    ('Number of NFL teams among rostered players', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{nfl(p,y,w) : p ∈ R(t,w)}|',
    ('Number of rookies started', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ S(t,w) : y = rookie_year(p)}|  (year/all-time: distinct p)',
    ('Number of rookies rostered', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ R(t,w) : y = rookie_year(p)}|',
    ('Number of cuffs rostered', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '|{p ∈ R(t,w) : ∃ q ∈ R(t,w_kick), q ≠ p, nfl(q)=nfl(p), pos(q)=pos(p), TEST(q,p,w)}|',
    ('Number of cuffs started', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{p ∈ S(t,w)} [∃ q ∈ R(t,w_kick): nfl(q)=nfl(p), pos(q)=pos(p), TEST(q,p,w) ∧ INJ(q,w)]',
    ('Donuts (roster)', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) = 0 ∧ (st(p,t,w) ∨ H(p,w))]; year/all-time = Σ_w',
    ('Donuts (starters)', 'team_week / team_year / team_all_time'):
        'Σ_{p ∈ S(t,w)} [pts(p,w) = 0]',
    ('Players under 10 pts (roster)', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) < 10 ∧ (st(p,t,w) ∨ H(p,w))]',
    ('Players under 10 pts (starters)', 'team_week / team_year / team_all_time'):
        'Σ_{p ∈ S(t,w)} [pts(p,w) < 10]',
    ('Players over 20 pts (roster)', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) > 20]',
    ('Players over 20 pts (starters)', 'team_week / team_year / team_all_time'):
        'Σ_{p ∈ S(t,w)} [pts(p,w) > 20]',
    ('Players over 30 pts (roster)', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) > 30]',
    ('Players over 30 pts (starters)', 'team_week / team_year / team_all_time'):
        'Σ_{p ∈ S(t,w)} [pts(p,w) > 30]',
    ('Players over 40 pts (roster)', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) > 40]',
    ('Players over 40 pts (starters)', 'team_week / team_year / team_all_time'):
        'Σ_{p ∈ S(t,w)} [pts(p,w) > 40]',
    ('Players over 50 pts (roster)', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'Σ_{p ∈ R(t,w)} [pts(p,w) > 50]',
    ('Players over 50 pts (starters)', 'team_week / team_year / team_all_time'):
        'Σ_{p ∈ S(t,w)} [pts(p,w) > 50]',
    ('Difference between highest and lowest starters', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'max_{p ∈ S(t,w)} pts(p,w) − min_{p ∈ S(t,w)} pts(p,w)',
    ('Player average age', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'mean_{p ∈ R(t,w)} age(p, dw(y,w)); year/all-time = mean of weekly means',
    ('Startup draft players remaining', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        'team: |{pk ∈ startup 2020 : by(pk) = t, pl(pk) ∈ R(t,w)}|; league: |{pk ∈ startup 2020 : pl(pk) ∈ ∪_u R(u,w)}|',
    ('% of players drafted', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '100 · |{p ∈ R(t,w) : p = pl(pk), by(pk) = t, continuously on t since dd}| / |R(t,w)|',
    ('% of 3rd year+ players drafted', 'team_week / team_year / team_all_time / league_week / league_year / league_all_time'):
        '100 · |{p ∈ R(t,w) : y − rookie_year(p) ≥ 2, drafted by t, held since}| / |{p ∈ R(t,w) : y − rookie_year(p) ≥ 2}|',
    ('PF', 'league_week / league_year / league_all_time'):
        'Σ_t PF(t,w); year/all-time = Σ_w',
    ('PF Range', 'league_week / league_year / league_all_time'):
        'max_t PF(t,w) − min_t PF(t,w)',
    ('Margin range', 'league_week / league_year / league_all_time'):
        'max_games |PF − PA| − min_games |PF − PA|',
    ('Number of games within 5', 'league_week / league_year / league_all_time'):
        '|{games : |PF − PA| ≤ 5}|',
    ('Number of games within 10', 'league_week / league_year / league_all_time'):
        '|{games : |PF − PA| ≤ 10}|',
    ('(smallest) Playoff tiebreaker', 'league_year'):
        'min{ |Σ_REG PF(u) − Σ_REG PF(v)| : u, v adjacent in the standings, Σ_REG win(u) = Σ_REG win(v) }',
    ("Team's traded with 1", 'trades'):
        'the 1st roster in rosters(x) ∖ {t}',
    ("Team's traded with 2", 'trades'):
        'the 2nd roster in rosters(x) ∖ {t}',
    ('Player Picked', 'non_rookie_picks / rookie_picks'):
        'pl(pk) = picks[pk].player_id',
    ('KTC on draft day', 'non_rookie_picks / rookie_picks'):
        'K(pl, dd(Y))',
    ('KTC at end of rookie year', 'non_rookie_picks / rookie_picks'):
        'K(pl, Feb 1 of Y+1)',
    ('KTC 1 year after draft day', 'non_rookie_picks / rookie_picks'):
        'K(pl, dd(Y) + 1 year)',
    ('KTC 2 years after draft day', 'non_rookie_picks / rookie_picks'):
        'K(pl, dd(Y) + 2 years)',
    ('KTC 3 years after draft day', 'non_rookie_picks / rookie_picks'):
        'K(pl, dd(Y) + 3 years)',
    ('KTC 4 years after draft day', 'non_rookie_picks / rookie_picks'):
        'K(pl, dd(Y) + 4 years)',
    ('Pick-adjusted Difference in Player addition value', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨Player addition value⟩ of each pick',
    ('Pick-adjusted Difference in Avg PPG on team adjusted by position', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨Avg PPG on team adjusted by position⟩ of each pick',
    ('Pick-adjusted Difference in Avg career PPG adjusted by position', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨Avg career PPG adjusted by position⟩ of each pick',
    ('Pick-adjusted Difference in Avg points added adjusted by position', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨Avg points added adjusted by position⟩ of each pick',
    ('Pick-adjusted Difference in KTC on draft day', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨KTC on draft day⟩ of each pick',
    ('Pick-adjusted Difference in KTC at end of rookie year', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨KTC at end of rookie year⟩ of each pick',
    ('Pick-adjusted Difference in KTC 1 year after draft day', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨KTC 1 year after draft day⟩ of each pick',
    ('Pick-adjusted Difference in KTC 2 years after draft day', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨KTC 2 years after draft day⟩ of each pick',
    ('Pick-adjusted Difference in KTC 3 years after draft day', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨KTC 3 years after draft day⟩ of each pick',
    ('Pick-adjusted Difference in KTC 4 years after draft day', 'non_rookie_picks / rookie_picks'):
        'v(pk) − base(v), v = ⟨KTC 4 years after draft day⟩ of each pick',
    ('Addition type', 'player_additions'):
        'type(x) ∈ {waiver, free_agent, commissioner} → Waiver / Free agency / Commissioner; trade → Trade; draft pick → Draft',
    ('Link to addition', 'player_additions'):
        'row of the source event (add_drops x, trade x, or pick pk) that started tenure T',
    ('Number of times added by this team', 'player_additions'):
        '|{acquisitions of p by t with date ≤ d_a}|',
    ('Tenure (days)', 'player_additions'):
        'e − d_a (days),  e = first exit of p from t after d_a, else build date',
    ('Tenure (NFL weeks)', 'player_additions'):
        '|Wk(p,t,T)| = |{w : ro(p,t,w) = 1, w within [d_a, e)}|',
    ('Games played on team', 'player_additions'):
        '|{w ∈ Wk : H(p,w)}|',
    ('Injured weeks on team', 'player_additions'):
        '|{w ∈ Wk : INJ(p,w)}|',
    ('Bench weeks on team', 'player_additions'):
        '|Wk| − Σ_{w ∈ Wk} st(p,t,w)',
    ('Healthy bench weeks on team', 'player_additions'):
        '|{w ∈ Wk : H}| − Σ_{w ∈ Wk : H} st(p,t,w)',
    ('Bench points on team', 'player_additions'):
        'Σ_{w ∈ Wk} (1 − st(p,t,w)) · pts(p,w)',
    ('Player addition value', 'player_additions'):
        '(Σ_{Wk} st·pts·F(y_w, pos p) / Σ_{Wk} st) · (1 + Σ_{Wk} st / 170) · (1 + Σ_{Wk} st / |Wk|); 0 with no start',
    ('Price paid (FAAB)', 'player_additions'):
        'waiver with bid > 0: bid(x); free agency or a $0 claim: 0; commissioner: N/A; draft: $pick_dd(Y, r, slot) (startup / vet: the startup board); trade: (Σ_{u ∈ B} $asset_d0(u)) · $asset_d0(p) / Σ_{q ∈ A} $asset_d0(q), N/A if any asset is unvalued',
    ('Points above expectation (total)', 'player_additions'):
        'Σ_{(k, x_k) ∈ held} x_k − Σ_{(k, ·) ∈ held} λ̂(xd(k, no_k, φ_c, q_c, pos, c)); 0 with no held week; N/A without a channel or price',
    ('Points above expectation (rate)', 'player_additions'):
        '[Σ_{held} x_k − Σ_{held} λ̂(xd(k, no_k, φ_c, q_c, pos, c))] / |held|',
    ('Age at pickup', 'player_additions'):
        'age(p, d_a) = (d_a − birth(p)) / 365.25',
    ('Cuff at pickup?', 'player_additions'):
        'CUFF(p, t, d_a)  (Draft row: CUFF at the draft)',
    ('KTC at pickup', 'player_additions'):
        'K(p, d_a)',
    ('KTC at end of season', 'player_additions'):
        'K(p, Feb 1 of y(d_a)+1); blank if in the future',
    ('KTC 1 year after pickup', 'player_additions'):
        'K(p, d_a + N years), N = 1..4; blank if in the future',
    ('KTC change by end of season', 'player_additions'):
        'K(p, checkpoint) − K(p, d_a)',
    ('PPG starter per rostered week', 'player_year / player_all_time'):
        'Σ_w st(p,·,w)·pts(p,w) / Σ_w ro(p,·,w)',
    ('Adjusted PPG starter per rostered week', 'player_year / player_all_time'):
        'Σ_{w : H} st(p,·,w)·pts(p,w) / |{w : ro ∧ H}|',
    ('Adjusted Avg points added', 'player_additions'):
        'Σ_{w ∈ Wk : H} st·pts(p,w) / Σ_{w ∈ Wk : H} st  (0 if none)',
    ('Avg points added per rostered week', 'player_additions'):
        'Σ_{w ∈ Wk} st·pts(p,w) / |Wk|',
    ('Adjusted Avg points added per rostered week', 'player_additions'):
        'Σ_{w ∈ Wk : H} st·pts(p,w) / |{w ∈ Wk : H}|',
    ('Avg points per rostered week on team', 'player_additions'):
        'Σ_{w ∈ Wk} pts(p,w) / |Wk|',
    ('PPG bench on team', 'player_additions'):
        'Σ_{w ∈ Wk} (1 − st)·pts(p,w) / Σ_{w ∈ Wk} (1 − st)',
    ('Adjusted PPG bench on team', 'player_additions'):
        'Σ_{w ∈ Wk : H} (1 − st)·pts(p,w) / Σ_{w ∈ Wk : H} (1 − st)',
    ("Position factor (every 'adjusted by position' column)", 'all player / move sheets'):
        "F(y,q) = mean{pts(p,w) : st, season y'} / mean{pts(p,w) : st, season y', pos(p) = q},  y' = y if ≥ 5 weeks of y are played, else y − 1",
    ('Regular-season PPG starter', 'player_all_time'):
        'Σ_{w ∈ REG} st(p,·,w)·pts(p,w) / Σ_{w ∈ REG} st(p,·,w)',
    ('Playoff PPG starter', 'player_all_time'):
        'Σ_{w : stage ∈ PO} st·pts(p,w) / Σ_{w : stage ∈ PO} st',
    ('Regular-season games started', 'player_all_time'):
        'Σ_{w ∈ REG} st(p,·,w)',
    ('Playoff games started', 'player_all_time'):
        'Σ_{w : stage ∈ PO} st(p,·,w)',
    ('Regular-season points as starter', 'player_all_time'):
        'Σ_{w ∈ REG} st(p,·,w)·pts(p,w)',
    ('Playoff points as starter', 'player_all_time'):
        'Σ_{w : stage ∈ PO} st(p,·,w)·pts(p,w)',
    ('Regular-season points', 'team_all_time'):
        'Σ_{w ∈ REG} PF(t,w)',
    ('Playoff points', 'team_all_time'):
        'Σ_{w : stage(t,w) ∈ PO} PF(t,w)',
    ('Playoff minus regular-season PPG starter', 'player_all_time'):
        'Σ_{PO} st·pts / Σ_{PO} st − Σ_{REG} st·pts / Σ_{REG} st',
    ('Avg points adjusted by position', 'player_year / player_all_time'):
        'mean{ pts(p,w)·F(y,pos p) : ro(p,·,w) }',
    ('Adjusted Avg points adjusted by position', 'player_year / player_all_time'):
        'mean{ pts(p,w)·F(y,pos p) : ro ∧ H }',
    ('PPG starter adjusted by position', 'player_year / player_all_time'):
        'mean{ pts(p,w)·F(y,pos p) : st }',
    ('Adjusted PPG starter adjusted by position', 'player_year / player_all_time'):
        'mean{ pts(p,w)·F(y,pos p) : st ∧ H }',
    ('PPG bench adjusted by position', 'player_year / player_all_time'):
        'mean{ pts(p,w)·F(y,pos p) : ro ∧ ¬st }',
    ('Adjusted PPG bench adjusted by position', 'player_year / player_all_time'):
        'mean{ pts(p,w)·F(y,pos p) : ro ∧ ¬st ∧ H }',
    ('PPG starter per rostered week adjusted by position', 'player_year / player_all_time'):
        'Σ_{w : st} pts(p,w)·F(y,pos p) / Σ_w ro(p,·,w)',
    ('Adjusted PPG starter per rostered week adjusted by position', 'player_year / player_all_time'):
        'Σ_{w : st ∧ H} pts(p,w)·F(y,pos p) / |{w : ro ∧ H}|',
    ('PPG starter vs bench diff adjusted by position', 'player_year / player_all_time'):
        'mean{pts·F : st ∧ H} − mean{pts·F : ro ∧ ¬st ∧ H}  (missing side = 0)',
    ('Starter PAR per game adjusted by position', 'player_year / player_all_time'):
        'mean_{w : st} (pts(p,w) − RL(pos p, w))·F(y,pos p)',
    ('Avg points (full season) adjusted by position', 'player_year'):
        'Σ_w npts(p,y,w)·F(y,pos p) / |{w : APP(p,y,w)}|',
    ('Avg points (full career) adjusted by position', 'player_all_time'):
        'Σ_y Σ_w npts(p,y,w)·F(y*,pos p) / |{(y,w) : APP}|,  y* = y (pre-league backfill seasons: the first league season)',
    ('Change in avg points from previous season adjusted by position', 'player_year'):
        'Σ_w npts(p,y,w)·F(y)/n(p,y) − Σ_w npts(p,y−1,w)·F(y−1)/n(p,y−1)',
    ('Change in avg points from career adjusted by position', 'player_year'):
        "Σ_w npts(p,y,w)·F(y)/n(p,y) − Σ_{y' < y} Σ_w npts(p,y',w)·F(y'*) / Σ_{y' < y} n(p,y'); blank if n(p,y) < 2",
    ('PPG as team starter adjusted by position', 'player_week'):
        "Σ_{w ∈ U : st} pts(p,w)·F(y_w,pos p) / Σ_{w ∈ U} st,  U = p's tenure weeks on t (RUN encoding)",
    ('PPG as team starter adjusted by position this season', 'player_week'):
        'Σ_{w ∈ U ∩ y : st} pts(p,w)·F(y,pos p) / Σ_{w ∈ U ∩ y} st',
    ('Difference in averages of best/worst startables over previous 5 games adjusted by position', 'player_week'):
        'avg5(p)·F(y,pos p) − avg5(ref)·F(y,pos ref)',
    ('Cuff adjusted difference adjusted by position', 'player_week'):
        '(avg5(p)·F(y,pos p) − avg5(ref)·F(y,pos ref)) · (½ if ⟨Activated Cuff?⟩ else 1)',
    ('Average PPG on team adjusted by position', 'add_drops'):
        'ppg_on(a,t,T)·F(y0, pos a)',
    ('Average PPG of dropped player over same time adjusted by position', 'add_drops'):
        'ppg_nfl(r, [d0, e_a))·F(y0, pos r)',
    ('PPG of 5 games before pickup adjusted by position', 'add_drops / player_additions'):
        'avgN(a, d0, 5)·F(y0, pos a)',
    ('Dropped avg points adjusted by position', 'add_drops'):
        'mean{npts(r) over his first ≤ 17 games with gd ≥ d0}·F(y0, pos r)',
    ('Avg PPG of received players on team adjusted by position', 'trades'):
        "mean_{q ∈ A'} ppg_on(q,t,T_q)·F(y0, pos q)",
    ('Avg PPG of sent players over same time adjusted by position', 'trades'):
        'mean_{s ∈ B} ppg_nfl(s,[d0,e*))·F(y0, pos s)',
    ('Avg PPG of received players in 5 games before trade adjusted by position', 'trades'):
        'mean_{q ∈ A} avgN(q,d0,5)·F(y0, pos q)',
    ('Adjusted Avg points added adjusted by position', 'player_additions'):
        'Σ_{w ∈ Wk : H} st·pts(p,w) / Σ_{w ∈ Wk : H} st · F(y(d_a), pos p)',
    ('Avg points added per rostered week adjusted by position', 'player_additions'):
        'Σ_{w ∈ Wk} st·pts(p,w) / |Wk| · F(y(d_a), pos p)',
    ('Adjusted Avg points added per rostered week adjusted by position', 'player_additions'):
        'Σ_{w ∈ Wk : H} st·pts(p,w) / |{w ∈ Wk : H}| · F(y(d_a), pos p)',
    ('Avg points per rostered week on team adjusted by position', 'player_additions'):
        'Σ_{w ∈ Wk} pts(p,w) / |Wk| · F(y(d_a), pos p)',
    ('PPG bench on team adjusted by position', 'player_additions'):
        'Σ_{Wk} (1 − st)·pts / Σ_{Wk} (1 − st) · F(y(d_a), pos p)',
    ('Adjusted PPG bench on team adjusted by position', 'player_additions'):
        'Σ_{Wk : H} (1 − st)·pts / Σ_{Wk : H} (1 − st) · F(y(d_a), pos p)',
    ('Regular-season PPG starter adjusted by position', 'player_all_time'):
        'Σ_{w ∈ REG : st} pts(p,w)·F(y_w,pos p) / Σ_{w ∈ REG} st',
    ('Playoff PPG starter adjusted by position', 'player_all_time'):
        'Σ_{w ∈ PO : st} pts(p,w)·F(y_w,pos p) / Σ_{w ∈ PO} st',
    ('Playoff minus regular-season PPG starter adjusted by position', 'player_all_time'):
        'Σ_{PO : st} pts·F / Σ_{PO} st − Σ_{REG : st} pts·F / Σ_{REG} st',
}
