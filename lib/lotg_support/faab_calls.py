"""The league's calls about player value (the 2026-10 league chat and Oliver's reviews), as TESTS on a board.

Nothing here sets a value. The general rules in `faab_value` are fitted so the board passes these, and the same
list is the regression test afterwards: if a later season's data breaks one, it shows up as a failed check,
never as a hand edit. Each test returns a hinge loss in log units (0 = passes). A call names the board it was
made about (2026-10-24); it is a test of that date's board only.

Each group of calls is judged on the board of the day it was made (CALL_DATES: the first review of the 2026-10-24
board, the second review on 2026-10-25, the league chat thread of 2026-10-25/26, dated by its last day), so data
that arrived after a call (a later game, a later KTC move) never counts for or against it. Where the inputs hold no
full board for a call's date, the latest full board before it stands in (see `faab_value.Evidence.call_boards`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CALLS_DATE = "2026-10-24"                                  # the reviewed board (reviewed_board_<date>.csv)
CALL_DATES = ("2026-10-24", "2026-10-25", "2026-10-26", "2026-11-03", "2026-11-18", "2026-11-20", "2026-11-22", "2026-11-23", "2026-11-24")
# first review, second review, league chat consensus (10-26), chat (TLaw/Lamar, 11-03), votes (11-18), chat (top WRs / Ladd, 11-20)
# Oliver 2026-11-09: McConkey cut to a low first / top-2 second, Coker to at least a mid second (his breakout call folded
# in), Henderson's low-first call dropped (it was Oliver's, not the league's); prices are the 2026 pick board's slots.
LOW_FIRST = ["Dak Prescott", "Justin Herbert", "Jordan Love", "Omarion Hampton", "Denzel Boston",
             "A.J. Brown", "Bo Nix", "Bucky Irving", "Luther Burden", "Emeka Egbuka",
             "Parker Washington", "Bryce Young"]
UNDER_FIRST = ["George Kittle", "Matthew Stafford", "Baker Mayfield", "Jadarian Price"]   # Etienne: left to the system (2026-10-25)
REVIEW_AT = {"Tucker Kraft": 800}      # Oliver 2026-11-09: Kraft's reviewed $918 was a bit high; his call centres on $800
MID_TE = ["Sam LaPorta", "Colston Loveland", "Isaiah Likely", "George Kittle", "Tyler Warren", "Kenyon Sadiq", "Tucker Kraft", "Harold Fannin"]
TOP3 = ["Josh Allen", "Jahmyr Gibbs", "Bijan Robinson"]
# Tolerances (round 4, Oliver 2026-11-09): with 3% random noise on every board value about 8 passing calls flip, so a
# call that misses by a hair is not evidence. A range call ("about $1,000", ">= $900") passes within 5% of its bounds;
# a player-over-player call only when extremely close (within 1%). A call's loss is capped (CALL_CAP, log units: a
# miss by about 65%), so no single call can outweigh the trades (Coker + McConkey were 29% of the objective).
# Rating-page votes that count as calls (Oliver 2026-11-10: "anything unanimous with 3+ people in agreement"): every
# league team that answered (3+ teams, each team's latest answer) said the same thing about the value it was shown on that
# board. "about right" = within VOTE_BAND of the value shown (the vote page's own band); "too low" / "too high" = above /
# below it; a pick = that player over the other. (date, kind, player, shown value or other player)
VOTE_BAND = 0.15
VOTE_CALLS = (
    ("2026-10-24", "up", "Jaxson Dart", 281), ("2026-10-24", "right", "Omar Cooper Jr.", 806),
    ("2026-10-24", "down", "Eli Stowers", 142), ("2026-10-24", "right", "DJ Moore", 266),
    ("2026-10-24", "down", "Chuba Hubbard", 972), ("2026-10-24", "over", "Michael Pittman Jr.", "Isaac TeSlaa"),
    ("2026-10-24", "over", "Jaxson Dart", "DJ Moore"),
    ("2026-10-26", "right", "Jalen Coker", 367), ("2026-10-26", "right", "Tyler Warren", 909),
    ("2026-10-26", "over", "Isaiah Likely", "TreVeyon Henderson"), ("2026-10-26", "right", "Garrett Wilson", 1037),
    ("2026-11-18", "over", "Garrett Wilson", "Elijah Sarratt"), ("2026-11-18", "over", "Omar Cooper Jr.", "George Kittle"),
    ("2026-11-18", "over", "Tucker Kraft", "Brian Thomas Jr."), ("2026-11-18", "up", "Garrett Wilson", 123),
    ("2026-11-18", "down", "Elijah Sarratt", 146), ("2026-11-18", "down", "Jordyn Tyson", 1667),
    ("2026-11-18", "down", "Javonte Williams", 1332),
)
RANGE_TOL = float(np.log(1.05))
PAIR_TOL = float(np.log(1.01))
CALL_CAP = 0.5

MISSING = set()
SUFFIXES = (" Jr.", " Sr.", " II", " III", " IV", " V")

def resolve(n, index):
    """the board's spelling of a call's name: exact, else the one board name that is it plus a suffix (Jr., II, III:
    Sleeper's names carry them, the calls were written without; a silent miss skipped the call, found 2026-11-22)"""
    if n in index: return n
    m = [n + s for s in SUFFIXES if n + s in index]
    return m[0] if len(m) == 1 else n

def calls(v, ref=None, qbs=()):
    """v: Series name -> value (one board for every call), or {call date: Series} (each group on the board of the
    day it was made; a date with no board uses the latest earlier one). ref: Series of the board Oliver reviewed
    (for 'looks alright'). Returns list of (call, loss)."""
    on = lambda d: v if not isinstance(v, dict) else v[max([k for k in v if k <= d] or [min(v)])]
    B = on(CALL_DATES[0])
    def g(n):
        x = float(B.get(resolve(n, B.index), np.nan))
        if np.isnan(x): MISSING.add(n)     # a call naming a player not on the board is skipped: check_names() lists them
        return x
    def gt(a, b, m=0.03): return max(0.0, np.log(g(b)) - np.log(g(a)) + m - PAIR_TOL) if not (np.isnan(g(a)) or np.isnan(g(b))) else 0.0
    def h(x, tol): return max(0.0, x - tol)          # a hinge with its dead zone
    def rng(n, lo, hi): x = g(n); return 0.0 if np.isnan(x) else max(0.0, np.log(lo) - np.log(x) - RANGE_TOL) + max(0.0, np.log(x) - np.log(hi) - RANGE_TOL)
    t = []
    rest = B.drop([n for n in TOP3 if n in B.index]).max()
    t += [(f"{n} above everyone outside the top 3", h(np.log(rest) - np.log(g(n)) + 0.02, PAIR_TOL)) for n in TOP3]
    hi_, lo_ = max(g(n) for n in TOP3), min(g(n) for n in TOP3)
    t += [("top 3 within 15%", h(np.log(hi_ / lo_) - np.log(1.15), RANGE_TOL)), ("top 3 at most about $4,300 (5 firsts is an overpay; top end lower than the reviewed board)", rng("Josh Allen", 3700, 4300) + rng("Jahmyr Gibbs", 3700, 4300))]
    q = B[[n for n in B.index if n in set(qbs)]].sort_values(ascending=False)
    if len(q) > 10:
        t += [("Allen QB1", h(np.log(q.drop("Josh Allen").max()) - np.log(g("Josh Allen")) + 0.02, PAIR_TOL)),
              ("Lamar QB2", h(np.log(q.drop(["Josh Allen", "Lamar Jackson"]).max()) - np.log(g("Lamar Jackson")) + 0.02, PAIR_TOL)),
              ("Hurts QB4 (out for the year)", h(np.log(g("Jalen Hurts")) - np.log(q.drop("Jalen Hurts").iloc[2]), PAIR_TOL)),
              ("Daniels outside the top 10 QBs", h(np.log(g("Jayden Daniels")) - np.log(q.drop("Jayden Daniels").iloc[9]), PAIR_TOL))]
    t += [("Burrow > Mendoza", gt("Joe Burrow", "Fernando Mendoza")), ("Burrow > Tyson", gt("Joe Burrow", "Jordyn Tyson")),
          ("Lamar - Burrow < Tet", h((g("Lamar Jackson") - g("Joe Burrow")) / g("Tetairoa McMillan") - 1.0, RANGE_TOL)),
          ("Herbert > Stafford", gt("Justin Herbert", "Matthew Stafford"))]
    for a in ["Puka Nacua", "Ja'Marr Chase", "Amon-Ra St. Brown"]:
        t += [(f"{a} > CeeDee", gt(a, "CeeDee Lamb")), (f"{a} > Nabers", gt(a, "Malik Nabers"))]
    jj = B.drop("Justin Jefferson").nlargest(12).iloc[-1]
    t += [("Jefferson top 12", h(np.log(jj) - np.log(g("Justin Jefferson")), PAIR_TOL))]
    t += [("Walker >= Tet", gt("Kenneth Walker", "Tetairoa McMillan", 0.0)), ("Bijan > Tet", gt("Bijan Robinson", "Tetairoa McMillan")),
          ("Bijan > Jeanty", gt("Bijan Robinson", "Ashton Jeanty")), ("Tate > Tyson", gt("Carnell Tate", "Jordyn Tyson")),
          ("Tate > LaPorta", gt("Carnell Tate", "Sam LaPorta")), ("AJ Brown > Ladd", gt("A.J. Brown", "Ladd McConkey")),
          ("Egbuka > Singleton", gt("Emeka Egbuka", "Nicholas Singleton")), ("Likely > Stowers", gt("Isaiah Likely", "Eli Stowers")),
          ("Loveland > 1.4x Kittle", h(np.log(1.4 * g("George Kittle")) - np.log(g("Colston Loveland")), RANGE_TOL)),
          ("Jamo > Hunter", gt("Jameson Williams", "Travis Hunter")), ("Hunter > Addison", gt("Travis Hunter", "Jordan Addison"))]
    t += [("Odunze near Addison", h(np.log(0.8 * g("Jordan Addison")) - np.log(g("Rome Odunze")), RANGE_TOL)),
          ("BTJ below Addison (fell off)", gt("Jordan Addison", "Brian Thomas", 0.0)), ("MHJ below Addison (fell off)", gt("Jordan Addison", "Marvin Harrison", 0.0))]
    t += [("Henry about a first", rng("Derrick Henry", 850, 1250)), ("Golden about $1,000", rng("Matthew Golden", 850, 1250)),
          ("KC about $1,000", rng("KC Concepcion", 850, 1250)),
          ("Lemon below the 1.05", rng("Makai Lemon", 600, 1250)), ("Mixon (no team) cheap", rng("Joe Mixon", 1, 120))]
    t += [(f"{n} a low first", rng(n, 750, 1200)) for n in LOW_FIRST]
    t += [("Derrick Henry a mid-low first (1.07-1.04, $783-1,135)", rng("Derrick Henry", 783, 1135))]   # Oliver 2026-11-10
    t += [("Ladd McConkey a low first / top-2 second ($453-1,200)", rng("Ladd McConkey", 453, 1200)),
          ("Jalen Coker at least a mid second (>= $222)", rng("Jalen Coker", 222, 99999))]
    t += [(f"{n} just under a first", rng(n, 600, 1050)) for n in UNDER_FIRST]
    t += [("McBride below ARSB", gt("Amon-Ra St. Brown", "Trey McBride")), ("Bowers below Jefferson", gt("Justin Jefferson", "Brock Bowers")),
          ("McBride <= $2,700", rng("Trey McBride", 1, 2700)), ("Bowers <= $2,700", rng("Brock Bowers", 1, 2700)),
          ("Stowers <= $300", rng("Eli Stowers", 1, 300)), ("Strange <= $300", rng("Brenton Strange", 1, 300))]
    for n, was in [("Chuba Hubbard", 1500), ("Isaiah Likely", 1252), ("Sam LaPorta", 1286), ("C.J. Stroud", 1252), ("Jordyn Tyson", 1377)]:
        t += [(f"{n} below the ${was:,} flagged as too high", rng(n, 1, 0.85 * was))]
    # second review (2026-10-25)
    B = on(CALL_DATES[1])
    t += [("Walker > CMC", gt("Kenneth Walker", "Christian McCaffrey")), ("Kyren > Tet", gt("Kyren Williams", "Tetairoa McMillan")),
          ("Nabers > Tet", gt("Malik Nabers", "Tetairoa McMillan")), ("London > Olave", gt("Drake London", "Chris Olave")),
          ("London > Golden", gt("Drake London", "Matthew Golden")), ("London > Tate", gt("Drake London", "Carnell Tate", 0.0)),
          ("Jeremiyah Love > Egbuka", gt("Jeremiyah Love", "Emeka Egbuka")), ("Jeremiyah Love > Golden", gt("Jeremiyah Love", "Matthew Golden")),
          ("Zay > AJ Brown", gt("Zay Flowers", "A.J. Brown")), ("Zay > Golden", gt("Zay Flowers", "Matthew Golden")),
          ("Nico up (>= $1,300)", rng("Nico Collins", 1300, 99999)), ("Zay up (>= $1,300)", rng("Zay Flowers", 1300, 99999)),
          ("Jefferson up (>= $2,500)", rng("Justin Jefferson", 2500, 99999)), ("Hurts down (<= $1,800)", rng("Jalen Hurts", 1, 1800)),
          ("Rice up (>= $800)", rng("Rashee Rice", 800, 99999)), ("Michael Wilson up (>= $400)", rng("Michael Wilson", 400, 99999)),
          ("Ollie Gordon down (<= $350)", rng("Ollie Gordon", 1, 350)), ("Etienne down (<= $450)", rng("Travis Etienne", 1, 450)),
          ("Antonio Williams down (<= $300)", rng("Antonio Williams", 1, 300)),
          ("CeeDee > Kyren", gt("CeeDee Lamb", "Kyren Williams")), ("Nabers > London", gt("Malik Nabers", "Drake London")),
          ("Jacobs about a first (>= $900)", rng("Josh Jacobs", 900, 99999)), ("Bucky about a first (>= $900)", rng("Bucky Irving", 900, 99999)),
          ("Addison at best a second (<= $350)", rng("Jordan Addison", 1, 350)), ("Bucky > Tuten", gt("Bucky Irving", "Bhayshul Tuten")),
          ("Jamo down (<= $1,200)", rng("Jameson Williams", 1, 1200)),
          ("Rice down (<= $1,250)", rng("Rashee Rice", 1, 1250)), ("Nico > Rice", gt("Nico Collins", "Rashee Rice")), ("Zay > Rice", gt("Zay Flowers", "Rashee Rice")),
          ("Mahomes > Goff", gt("Patrick Mahomes", "Jared Goff")), ("Mahomes near Lamar (>= 90%)", h(np.log(0.9 * g("Lamar Jackson")) - np.log(g("Patrick Mahomes")), RANGE_TOL)),
          ("Hurts < Mahomes", gt("Patrick Mahomes", "Jalen Hurts")), ("Hurts < Maye", gt("Drake Maye", "Jalen Hurts")), ("Hurts < Caleb", gt("Caleb Williams", "Jalen Hurts")),
          ("Parker Washington like a breakout (>= $700)", rng("Parker Washington", 700, 99999))]
    # league chat consensus (2026-10-25/26, the Bucky/Tuten thread): Tuten ~2.01-2.03, Monangai a mid-low second,
    # Hampton at least Bucky, Henderson at least a high second
    B = on(CALL_DATES[2])
    t += [("Tuten about a 2.01-2.03 ($395-615)", rng("Bhayshul Tuten", 395, 615)), 
          # Monangai a mid-low second ($180-361) retired 2026-11-24 (Oliver): replaced by the 11-24 call below
          ("Hampton >= Bucky", gt("Omarion Hampton", "Bucky Irving", 0.0)), ("Henderson at least a high second (>= $615)", rng("TreVeyon Henderson", 615, 99999)),
          ("Bucky a 1.06-1.07 ($783-875)", rng("Bucky Irving", 783, 875))]                  # Shmuel 1.07, Oliver 1.06, Ben 1.07
    # league chat 2026-11-03 (the TLaw trade-block thread): Lawrence at least Lamar (Ben, Peter, Sam's offer, Oliver)
    B = on(CALL_DATES[3])
    t += [("TLaw >= Lamar (chat 2026-11-03)", gt("Trevor Lawrence", "Lamar Jackson", 0.0))]
    # league chat 2026-11-20 (Ben, Sam, Oliver; Steve on Ladd): JSN, Chase, Puka in that order, a tier above CeeDee,
    # Jefferson and Nabers, Puka above ARSB; Ladd about WR20-25 in dynasty, below Parker Washington, Nico, Pickens, Watson
    B = on(CALL_DATES[5])
    t += [("JSN > Chase (chat 2026-11-20)", gt("Jaxon Smith-Njigba", "Ja'Marr Chase")), ("Chase > Puka (chat 2026-11-20)", gt("Ja'Marr Chase", "Puka Nacua"))]
    nxt = max(g(n) for n in ["CeeDee Lamb", "Justin Jefferson", "Malik Nabers"])
    t += [(f"{n} above CeeDee/Jefferson/Nabers (chat 2026-11-20)", h(np.log(nxt) - np.log(g(n)) + 0.03, PAIR_TOL))
          for n in ["Jaxon Smith-Njigba", "Ja'Marr Chase"]]
    # Puka's lower bounds from that chat (above ARSB, above CeeDee/Jefferson/Nabers) are judged on the 11-24 board below
    # (Oliver 2026-11-24): on 11-20 he carried the Out-tag dock (x0.51), since replaced by IR (x0.83) + his suspension cut
    t += [(f"Ladd below {n} (chat 2026-11-20)", gt(n, "Ladd McConkey")) for n in ["Parker Washington", "Nico Collins", "George Pickens", "Christian Watson"]]
    # Oliver 2026-11-22: Chase Brown is too high: streaks of single-digit games and a pass-first offense; at most $1,500
    B = on(CALL_DATES[6])
    t += [("Chase Brown <= $1,500 (Oliver 2026-11-22)", rng("Chase Brown", 1, 1500))]
    # Oliver 2026-11-22: Kenneth Walker too low: a big year in a new place (Seattle -> Kansas City)
    t += [("Kenneth Walker above the $2,294 flagged as too low (Oliver 2026-11-22)", rng("Kenneth Walker", 1.15 * 2294, 99999))]
    # Oliver 2026-11-22: Penix "worth at least a 3rd or two" (a late 3rd, 3.08, is $58 on the 2026-11-21 board)
    t += [("Penix at least a 3rd (>= $58; Oliver 2026-11-22)", rng("Michael Penix", 58, 99999))]
    # Oliver 2026-11-22: Fannin too high: run-first offense, low ceiling (boom weeks only so big), inconsistent
    t += [("Harold Fannin below the $1,901 flagged as too high (Oliver 2026-11-22)", rng("Harold Fannin Jr.", 1, 0.85 * 1901))]
    # Oliver 2026-11-23 (prices: the 2026-11-23 pick board's slots), loose "less than" calls on purpose: TreVeyon
    # Henderson under $500 (he thinks a low second at best); the 2026 first-round rookies who underperformed are worth less
    # than the slot they went at (Makai Lemon 1.05, Jadarian Price 1.06, KC Concepcion 1.07, Kenyon Sadiq 1.08); Emmett
    # Johnson less than a first (under 1.08, $625; he thinks a good/high second), still Kenneth Walker's backup. The 10-24/10-26 Henderson and Sadiq calls stand (each on its own day's board).
    B = on(CALL_DATES[7])
    t += [("Henderson under $500 (Oliver 2026-11-23)", rng("TreVeyon Henderson", 1, 500)),
          ("Makai Lemon below his 1.05 (< $1,064; Oliver 2026-11-23)", rng("Makai Lemon", 1, 1064)),
          ("Jadarian Price below his 1.06 (< $889; Oliver 2026-11-23)", rng("Jadarian Price", 1, 889)),
          ("KC Concepcion below his 1.07 (< $796; Oliver 2026-11-23)", rng("KC Concepcion", 1, 796)),
          ("Kenyon Sadiq below his 1.08 (< $625; Oliver 2026-11-23)", rng("Kenyon Sadiq", 1, 625)),
          ("Emmett Johnson less than a first (< $625, the 1.08; Oliver 2026-11-23)", rng("Emmett Johnson", 1, 625))]
    # Oliver 2026-11-23 (on the 11-24 board, his first game back): Kyle Monangai around $360 after 1.8 PPR on his return
    B = on(CALL_DATES[8])
    t += [("Monangai around $360 after a bad return (Oliver 2026-11-23)", rng("Kyle Monangai", 1, 360))]
    # Oliver 2026-11-24: Puka back under Chase (expiring contract + conduct suspension), still above ARSB (the 11-20 chat order)
    t += [("Chase > Puka (Oliver 2026-11-24)", gt("Ja'Marr Chase", "Puka Nacua")), ("Puka > ARSB (chat 2026-11-20, judged 11-24)", gt("Puka Nacua", "Amon-Ra St. Brown"))]
    nxt = max(g(n) for n in ["CeeDee Lamb", "Justin Jefferson", "Malik Nabers"])
    t += [("Puka Nacua above CeeDee/Jefferson/Nabers (chat 2026-11-20, judged 11-24)", h(np.log(nxt) - np.log(g("Puka Nacua")) + 0.03, PAIR_TOL))]
    # Oliver 2026-11-24 (round 7, all "fairly loose"): injury cuts too steep on Alec Pierce / Terry McLaurin / Ricky Pearsall /
    # Jalen McMillan; Dameon Pierce and Xavier Legette worthless; Rhamondre Stevenson, Anthony Richardson, Tank Dell higher;
    # Brian Robinson Jr. about a pair of 4ths on IR (Bijan Robinson's long-term handcuff)
    t += [("Alec Pierce up from $40 (> $50)", rng("Alec Pierce", 50, 99999)), ("Terry McLaurin up from $40 (> $45)", rng("Terry McLaurin", 45, 99999)),
          ("Ricky Pearsall up (> $45)", rng("Ricky Pearsall", 45, 99999)), ("Jalen McMillan up (> $45)", rng("Jalen McMillan", 45, 99999)),
          ("Dameon Pierce near worthless (< $20)", rng("Dameon Pierce", 0, 20)), ("Xavier Legette near worthless (< $15)", rng("Xavier Legette", 0, 15)),
          ("Rhamondre Stevenson up (> $40)", rng("Rhamondre Stevenson", 40, 99999)), ("Anthony Richardson up a little (> $20)", rng("Anthony Richardson Sr.", 20, 99999)),
          ("Tank Dell up (> $22)", rng("Tank Dell", 22, 99999)), ("Brian Robinson Jr. about a pair of 4ths on IR ($30-$110)", rng("Brian Robinson Jr.", 30, 110))]
    # Oliver 2026-11-24 (top end, loose): older RBs a bit inflated, Kyren Williams ceding to Blake Corum, Malik Nabers too low,
    # Jalen Hurts and Harold Fannin Jr. still too high (the QB order notes, Caleb > Stroud and Lamar > Maye, are "not calls")
    t += [("Jonathan Taylor down (< $2,350)", rng("Jonathan Taylor", 1, 2350)), ("James Cook down (< $2,430)", rng("James Cook III", 1, 2430)),
          ("Christian McCaffrey down (< $2,350)", rng("Christian McCaffrey", 1, 2350)), ("Kyren Williams down (< $2,240)", rng("Kyren Williams", 1, 2240)),
          ("Malik Nabers up (> $2,330)", rng("Malik Nabers", 2330, 99999)), ("Jalen Hurts down (< $1,580)", rng("Jalen Hurts", 1, 1580)),
          ("Harold Fannin Jr. down (< $1,560)", rng("Harold Fannin Jr.", 1, 1560))]
    # Oliver 2026-11-24 (middle tier, loose)
    t += [("Chase Brown a tad lower (< $1,120)", rng("Chase Brown", 1, 1120)), ("Jameson Williams lower (< $960)", rng("Jameson Williams", 1, 960)),
          ("Sam LaPorta lower (< $830)", rng("Sam LaPorta", 1, 830)), ("Rome Odunze lower (< $760)", rng("Rome Odunze", 1, 760)),
          ("Tyler Warren > Sam LaPorta", gt("Tyler Warren", "Sam LaPorta")), ("Tyler Warren > Kyle Pitts", gt("Tyler Warren", "Kyle Pitts Sr.")),
          ("Kenneth Walker > Kyren Williams", gt("Kenneth Walker III", "Kyren Williams")), ("Travis Hunter down a bit (< $490)", rng("Travis Hunter", 1, 490)),
          ("Emmett Johnson lower on a 2-game sample (< $460)", rng("Emmett Johnson", 1, 460)), 
          # Antonio Williams "lower (< $320)" retired 2026-11-24 (Oliver: 22 points on MNF; WR_SHOWN stays, it applied before the breakout)

          ("Chuba Hubbard way up (> $550)", rng("Chuba Hubbard", 550, 99999))]
    # Oliver 2026-11-24 (middle tier, part 2, loose)
    t += [("Jordan Addison down a peg (< $285)", rng("Jordan Addison", 1, 285)), ("Michael Wilson up (> $500)", rng("Michael Wilson", 500, 99999)),
          ("Kyler Murray a low 3rd at most (< $90)", rng("Kyler Murray", 1, 90)), ("Travis Kelce a 3rd at best (< $137)", rng("Travis Kelce", 1, 137)),
          ("Nicholas Singleton down (< $140)", rng("Nicholas Singleton", 1, 140)), ("Jaylen Warren a mid/high 2nd ($280-$600)", rng("Jaylen Warren", 280, 600)),
          ("Jaylen Warren < Chuba Hubbard", gt("Chuba Hubbard", "Jaylen Warren")), ("Baker Mayfield a big boost (> $200)", rng("Baker Mayfield", 200, 99999)),
          ("Jonathon Brooks > Trevor Etienne", gt("Jonathon Brooks", "Trevor Etienne")), ("Corey Kiner down (< $50)", rng("Corey Kiner", 1, 50)),
          ("Jalen Coker a high 3rd / low 2nd ($120-$300)", rng("Jalen Coker", 120, 300)), ("Jalen Milroe below a 3rd (< $58)", rng("Jalen Milroe", 1, 58)),
          ("LeQuint Allen Jr. down (< $40)", rng("LeQuint Allen Jr.", 1, 40)), ("J.J. McCarthy about a low 3rd ($55-$110)", rng("J.J. McCarthy", 55, 110)),
          ("Josh Downs a mid 3rd ($75-$130)", rng("Josh Downs", 75, 130)), ("Kyle Pitts back up to about $550 ($480-$650)", rng("Kyle Pitts Sr.", 480, 650))]
    t += [(f"{n} a low 4th at best (< $40)", rng(n, 1, 40)) for n in ("Mike Gesicki", "Evan Engram", "Brenton Strange")]
    # Oliver 2026-11-24: Fernando Mendoza too high for two career games; about the 1.01 now (drafted 1.02), no more
    t += [("Fernando Mendoza about the 1.01, no more ($1,500-$1,850)", rng("Fernando Mendoza", 1500, 1850))]
    # rating-page votes that count as calls (Oliver 2026-11-10: unanimous with 3+ teams agreeing), on the board they were shown
    for d, kind, a, b in VOTE_CALLS:
        B = on(d)
        if kind == "over": t += [(f"votes {d}: {a} > {b}", gt(a, b, 0.0))]
        else:
            lo, hi = {"right": (b / (1 + VOTE_BAND), b * (1 + VOTE_BAND)), "up": (b, 99999), "down": (1, b)}[kind]
            t += [(f"votes {d}: {a} {dict(right='about', up='above', down='below')[kind]} ${b:,.0f}", rng(a, lo, hi))]
    B = on(CALL_DATES[0])
    if ref is not None:
        for n in MID_TE + ["Brock Purdy", "Jared Goff"]:   # "middle TEs good", "Purdy & Goff fine"
            r = REVIEW_AT.get(n, ref[n] if n in ref.index else None)
            m = resolve(n, B.index)   # renamed since (Harold Fannin -> Harold Fannin Jr.)
            if r is not None: t += [(f"{n} stays near the reviewed ${r:,.0f}", rng(m, 0.75 * r, 1.3 * r))]
    return [(n, min(x, CALL_CAP)) for n, x in t]

BUBBLE = (93, 222)   # Oliver 2026-11-09: the bubble is a mid-late second to an early third (2.05 $222 .. 3.03 $93), was $50-300
def vet_bubble(v, exp):
    """'very few guys between a mid-late second and an early third who are not in their first 1-3 years' (replacement level)"""
    e = exp.reindex(v.index); vets = v[e >= 3]
    frac = float(vets.between(*BUBBLE).mean()) if len(vets) else 0.0
    return (f"few veterans valued ${BUBBLE[0]}-{BUBBLE[1]} (replacement level)", max(0.0, frac - 0.03) * 10)
# calls on one player's row on a past date (the inputs keep every trade side's row): (date, name, lo, hi, label). A row
# dated on or up to 7 days before the date stands in (a trade's row is the day before it). Oliver 2026-11-22: Jefferson
# was at his peak at the 2022-09-27 trade ("Chase is worth like 3800 today ... at least 3500 at the time")
ROW_CALLS = (("2022-09-27", "Justin Jefferson", 3500, 99999, "Jefferson >= $3,500 at the 2022-09-27 trade (Oliver 2026-11-22)"),)


def row_calls(R, V):
    """[(label, loss)] for ROW_CALLS on the inputs rows R (values V, aligned with R)"""
    out = []
    d = pd.to_datetime(R.date)
    names = set(R.name.values)
    for day, name, lo, hi, label in ROW_CALLS:
        name = resolve(name, names)
        if name not in names: MISSING.add(name)
        t = pd.Timestamp(day); m = np.where((R.name.values == name) & (d <= t) & (d >= t - pd.Timedelta(days=7)))[0]
        if not len(m): continue
        x = float(V[m[np.argmax(d.values[m])]])
        out.append((label, max(0.0, np.log(lo) - np.log(x) - RANGE_TOL) + max(0.0, np.log(x) - np.log(hi) - RANGE_TOL)))
    return out


def score(v, ref=None, qbs=(), others_w=0.15, exp=None):
    """sum of call losses + a light pull of everyone else toward the reviewed board ('a lot of the rest looks alright')"""
    t = calls(v, ref, qbs)
    v = v if not isinstance(v, dict) else v[min(v)]      # the first review's board: the bubble and the 'rest looks alright' pull
    if exp is not None: t.append(vet_bubble(v, exp))
    loss = sum(x for _, x in t)
    if ref is not None:
        named = {resolve(n, v.index) for n in LOW_FIRST + UNDER_FIRST + MID_TE + TOP3 + ["Derrick Henry"]}
        o = [n for n in ref.index if n in v.index and n not in named and ref[n] >= 50]
        loss += others_w * float(np.mean(np.abs(np.log(v[o].values) - np.log(ref[o].values))))
    return loss, t
