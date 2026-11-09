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

CALLS_DATE = "2026-10-24"                                  # the reviewed board (reviewed_board_<date>.csv)
CALL_DATES = ("2026-10-24", "2026-10-25", "2026-10-26")   # first review, second review, league chat consensus
# Oliver 2026-11-09: McConkey cut to a low first / top-2 second, Coker to at least a mid second (his breakout call folded
# in), Henderson's low-first call dropped (it was Oliver's, not the league's); prices are the 2026 pick board's slots.
LOW_FIRST = ["Dak Prescott", "Justin Herbert", "Jordan Love", "Omarion Hampton", "Derrick Henry", "Denzel Boston",
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
RANGE_TOL = float(np.log(1.05))
PAIR_TOL = float(np.log(1.01))
CALL_CAP = 0.5

def calls(v, ref=None, qbs=()):
    """v: Series name -> value (one board for every call), or {call date: Series} (each group on the board of the
    day it was made; a date with no board uses the latest earlier one). ref: Series of the board Oliver reviewed
    (for 'looks alright'). Returns list of (call, loss)."""
    on = lambda d: v if not isinstance(v, dict) else v[max([k for k in v if k <= d] or [min(v)])]
    B = on(CALL_DATES[0])
    g = lambda n: float(B.get(n, np.nan))
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
    t += [("Tuten about a 2.01-2.03 ($395-615)", rng("Bhayshul Tuten", 395, 615)), ("Monangai a mid-low second ($180-340)", rng("Kyle Monangai", 180, 340)),
          ("Hampton >= Bucky", gt("Omarion Hampton", "Bucky Irving", 0.0)), ("Henderson at least a high second (>= $615)", rng("TreVeyon Henderson", 615, 99999))]
    B = on(CALL_DATES[0])
    if ref is not None:
        for n in MID_TE + ["Brock Purdy", "Jared Goff"]:   # "middle TEs good", "Purdy & Goff fine"
            r = REVIEW_AT.get(n, ref[n] if n in ref.index else None)
            if r is not None: t += [(f"{n} stays near the reviewed ${r:,.0f}", rng(n, 0.75 * r, 1.3 * r))]
    return [(n, min(x, CALL_CAP)) for n, x in t]

BUBBLE = (93, 222)   # Oliver 2026-11-09: the bubble is a mid-late second to an early third (2.05 $222 .. 3.03 $93), was $50-300
def vet_bubble(v, exp):
    """'very few guys between a mid-late second and an early third who are not in their first 1-3 years' (replacement level)"""
    e = exp.reindex(v.index); vets = v[e >= 3]
    frac = float(vets.between(*BUBBLE).mean()) if len(vets) else 0.0
    return (f"few veterans valued ${BUBBLE[0]}-{BUBBLE[1]} (replacement level)", max(0.0, frac - 0.03) * 10)
def score(v, ref=None, qbs=(), others_w=0.15, exp=None):
    """sum of call losses + a light pull of everyone else toward the reviewed board ('a lot of the rest looks alright')"""
    t = calls(v, ref, qbs)
    v = v if not isinstance(v, dict) else v[min(v)]      # the first review's board: the bubble and the 'rest looks alright' pull
    if exp is not None: t.append(vet_bubble(v, exp))
    loss = sum(x for _, x in t)
    if ref is not None:
        named = set(LOW_FIRST + UNDER_FIRST + MID_TE + TOP3)
        o = [n for n in ref.index if n in v.index and n not in named and ref[n] >= 50]
        loss += others_w * float(np.mean(np.abs(np.log(v[o].values) - np.log(ref[o].values))))
    return loss, t
