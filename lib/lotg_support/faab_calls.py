"""The league's calls about player value (the 2026-10 league chat and Oliver's reviews), as TESTS on a board.

Nothing here sets a value. The general rules in `faab_value` are fitted so the board passes these, and the same
list is the regression test afterwards: if a later season's data breaks one, it shows up as a failed check,
never as a hand edit. Each test returns a hinge loss in log units (0 = passes). A call names the board it was
made about (2026-10-24); it is a test of that date's board only.
"""
from __future__ import annotations

import numpy as np

CALLS_DATE = "2026-10-24"
LOW_FIRST = ["Dak Prescott", "Justin Herbert", "Jordan Love", "Omarion Hampton", "Derrick Henry", "Denzel Boston", "Ladd McConkey",
             "A.J. Brown", "Bo Nix", "Bucky Irving", "TreVeyon Henderson", "Jalen Coker", "Luther Burden", "Emeka Egbuka",
             "Parker Washington", "Bryce Young"]
UNDER_FIRST = ["George Kittle", "Matthew Stafford", "Baker Mayfield", "Jadarian Price"]   # Etienne: left to the system (2026-10-25)
MID_TE = ["Sam LaPorta", "Colston Loveland", "Isaiah Likely", "George Kittle", "Tyler Warren", "Kenyon Sadiq", "Tucker Kraft", "Harold Fannin"]
TOP3 = ["Josh Allen", "Jahmyr Gibbs", "Bijan Robinson"]

def calls(v, ref=None, qbs=()):
    """v: Series name -> value (today's board). ref: Series of the board Oliver reviewed (for 'looks alright').
    Returns list of (call, loss)."""
    g = lambda n: float(v.get(n, np.nan))
    def gt(a, b, m=0.03): return max(0.0, np.log(g(b)) - np.log(g(a)) + m) if not (np.isnan(g(a)) or np.isnan(g(b))) else 0.0
    def rng(n, lo, hi): x = g(n); return 0.0 if np.isnan(x) else max(0.0, np.log(lo) - np.log(x)) + max(0.0, np.log(x) - np.log(hi))
    t = []
    rest = v.drop([n for n in TOP3 if n in v.index]).max()
    t += [(f"{n} above everyone outside the top 3", max(0.0, np.log(rest) - np.log(g(n)) + 0.02)) for n in TOP3]
    hi_, lo_ = max(g(n) for n in TOP3), min(g(n) for n in TOP3)
    t += [("top 3 within 15%", max(0.0, np.log(hi_ / lo_) - np.log(1.15))), ("top 3 at most about $4,300 (5 firsts is an overpay; top end lower than the reviewed board)", rng("Josh Allen", 3700, 4300) + rng("Jahmyr Gibbs", 3700, 4300))]
    q = v[[n for n in v.index if n in set(qbs)]].sort_values(ascending=False)
    if len(q) > 10:
        t += [("Allen QB1", max(0.0, np.log(q.drop("Josh Allen").max()) - np.log(g("Josh Allen")) + 0.02)),
              ("Lamar QB2", max(0.0, np.log(q.drop(["Josh Allen", "Lamar Jackson"]).max()) - np.log(g("Lamar Jackson")) + 0.02)),
              ("Hurts QB4 (out for the year)", max(0.0, np.log(g("Jalen Hurts")) - np.log(q.drop("Jalen Hurts").iloc[2]))),
              ("Daniels outside the top 10 QBs", max(0.0, np.log(g("Jayden Daniels")) - np.log(q.drop("Jayden Daniels").iloc[9])))]
    t += [("Burrow > Mendoza", gt("Joe Burrow", "Fernando Mendoza")), ("Burrow > Tyson", gt("Joe Burrow", "Jordyn Tyson")),
          ("Lamar - Burrow < Tet", max(0.0, (g("Lamar Jackson") - g("Joe Burrow")) / g("Tetairoa McMillan") - 1.0)),
          ("Herbert > Stafford", gt("Justin Herbert", "Matthew Stafford"))]
    for a in ["Puka Nacua", "Ja'Marr Chase", "Amon-Ra St. Brown"]:
        t += [(f"{a} > CeeDee", gt(a, "CeeDee Lamb")), (f"{a} > Nabers", gt(a, "Malik Nabers"))]
    jj = v.drop("Justin Jefferson").nlargest(12).iloc[-1]
    t += [("Jefferson top 12", max(0.0, np.log(jj) - np.log(g("Justin Jefferson"))))]
    t += [("Walker >= Tet", gt("Kenneth Walker", "Tetairoa McMillan", 0.0)), ("Bijan > Tet", gt("Bijan Robinson", "Tetairoa McMillan")),
          ("Bijan > Jeanty", gt("Bijan Robinson", "Ashton Jeanty")), ("Tate > Tyson", gt("Carnell Tate", "Jordyn Tyson")),
          ("Tate > LaPorta", gt("Carnell Tate", "Sam LaPorta")), ("AJ Brown > Ladd", gt("A.J. Brown", "Ladd McConkey")),
          ("Egbuka > Singleton", gt("Emeka Egbuka", "Nicholas Singleton")), ("Likely > Stowers", gt("Isaiah Likely", "Eli Stowers")),
          ("Loveland > 1.4x Kittle", max(0.0, np.log(1.4 * g("George Kittle")) - np.log(g("Colston Loveland")))),
          ("Jamo > Hunter", gt("Jameson Williams", "Travis Hunter")), ("Hunter > Addison", gt("Travis Hunter", "Jordan Addison"))]
    t += [("Odunze near Addison", max(0.0, np.log(0.8 * g("Jordan Addison")) - np.log(g("Rome Odunze")))),
          ("BTJ below Addison (fell off)", gt("Jordan Addison", "Brian Thomas", 0.0)), ("MHJ below Addison (fell off)", gt("Jordan Addison", "Marvin Harrison", 0.0))]
    t += [("Henry about a first", rng("Derrick Henry", 850, 1250)), ("Golden about $1,000", rng("Matthew Golden", 850, 1250)),
          ("KC about $1,000", rng("KC Concepcion", 850, 1250)),
          ("Lemon below the 1.05", rng("Makai Lemon", 600, 1250)), ("Mixon (no team) cheap", rng("Joe Mixon", 1, 120))]
    t += [(f"{n} a low first", rng(n, 750, 1200)) for n in LOW_FIRST]
    t += [(f"{n} just under a first", rng(n, 600, 1050)) for n in UNDER_FIRST]
    t += [("McBride below ARSB", gt("Amon-Ra St. Brown", "Trey McBride")), ("Bowers below Jefferson", gt("Justin Jefferson", "Brock Bowers")),
          ("McBride <= $2,700", rng("Trey McBride", 1, 2700)), ("Bowers <= $2,700", rng("Brock Bowers", 1, 2700)),
          ("Stowers <= $300", rng("Eli Stowers", 1, 300)), ("Strange <= $300", rng("Brenton Strange", 1, 300))]
    for n, was in [("Chuba Hubbard", 1500), ("Isaiah Likely", 1252), ("Sam LaPorta", 1286), ("C.J. Stroud", 1252), ("Jordyn Tyson", 1377)]:
        t += [(f"{n} below the ${was:,} flagged as too high", rng(n, 1, 0.85 * was))]
    # second review (2026-10-25)
    t += [("Walker > CMC", gt("Kenneth Walker", "Christian McCaffrey")), ("Kyren > Tet", gt("Kyren Williams", "Tetairoa McMillan")),
          ("Nabers > Tet", gt("Malik Nabers", "Tetairoa McMillan")), ("London > Olave", gt("Drake London", "Chris Olave")),
          ("London > Golden", gt("Drake London", "Matthew Golden")), ("London > Tate", gt("Drake London", "Carnell Tate", 0.0)),
          ("Jeremiyah Love > Egbuka", gt("Jeremiyah Love", "Emeka Egbuka")), ("Jeremiyah Love > Golden", gt("Jeremiyah Love", "Matthew Golden")),
          ("Zay > AJ Brown", gt("Zay Flowers", "A.J. Brown")), ("Zay > Golden", gt("Zay Flowers", "Matthew Golden")),
          ("Nico up (>= $1,300)", rng("Nico Collins", 1300, 99999)), ("Zay up (>= $1,300)", rng("Zay Flowers", 1300, 99999)),
          ("Jefferson up (>= $2,500)", rng("Justin Jefferson", 2500, 99999)), ("Hurts down (<= $1,800)", rng("Jalen Hurts", 1, 1800)),
          ("Rice up (>= $900)", rng("Rashee Rice", 900, 99999)), ("Michael Wilson up (>= $500)", rng("Michael Wilson", 500, 99999)),
          ("Ollie Gordon down (<= $350)", rng("Ollie Gordon", 1, 350)), ("Etienne down (<= $450)", rng("Travis Etienne", 1, 450)),
          ("Antonio Williams down (<= $300)", rng("Antonio Williams", 1, 300)),
          ("CeeDee > Kyren", gt("CeeDee Lamb", "Kyren Williams")), ("Nabers > London", gt("Malik Nabers", "Drake London")),
          ("Jacobs about a first (>= $900)", rng("Josh Jacobs", 900, 99999)), ("Bucky about a first (>= $900)", rng("Bucky Irving", 900, 99999)),
          ("Addison at best a second (<= $350)", rng("Jordan Addison", 1, 350)), ("Bucky > Tuten", gt("Bucky Irving", "Bhayshul Tuten")),
          ("Jamo down (<= $1,200)", rng("Jameson Williams", 1, 1200)),
          ("Rice down (<= $1,250)", rng("Rashee Rice", 1, 1250)), ("Nico > Rice", gt("Nico Collins", "Rashee Rice")), ("Zay > Rice", gt("Zay Flowers", "Rashee Rice")),
          ("Mahomes > Goff", gt("Patrick Mahomes", "Jared Goff")), ("Mahomes near Lamar (>= 90%)", max(0.0, np.log(0.9 * g("Lamar Jackson")) - np.log(g("Patrick Mahomes")))),
          ("Hurts < Mahomes", gt("Patrick Mahomes", "Jalen Hurts")), ("Hurts < Maye", gt("Drake Maye", "Jalen Hurts")), ("Hurts < Caleb", gt("Caleb Williams", "Jalen Hurts")),
          ("Coker like a breakout (>= $700)", rng("Jalen Coker", 700, 99999)), ("Parker Washington like a breakout (>= $700)", rng("Parker Washington", 700, 99999))]
    # league chat consensus (2026-10-25/26, the Bucky/Tuten thread): Tuten ~2.01-2.03, Monangai a mid-low second,
    # Hampton at least Bucky, Henderson at least a high second
    t += [("Tuten about a 2.01-2.03 ($395-615)", rng("Bhayshul Tuten", 395, 615)), ("Monangai a mid-low second ($180-340)", rng("Kyle Monangai", 180, 340)),
          ("Hampton >= Bucky", gt("Omarion Hampton", "Bucky Irving", 0.0)), ("Henderson at least a high second (>= $615)", rng("TreVeyon Henderson", 615, 99999))]
    if ref is not None:
        for n in MID_TE + ["Brock Purdy", "Jared Goff"]:   # "middle TEs good", "Purdy & Goff fine"
            if n in ref.index: t += [(f"{n} stays near the reviewed ${ref[n]:,.0f}", rng(n, 0.75 * ref[n], 1.3 * ref[n]))]
    return t

def vet_bubble(v, exp):
    """'very few guys between $50 and $300 who are not in their first 1-3 years' (replacement level)"""
    e = exp.reindex(v.index); vets = v[e >= 3]
    frac = float(vets.between(50, 300).mean()) if len(vets) else 0.0
    return ("few veterans valued $50-300 (replacement level)", max(0.0, frac - 0.03) * 10)
def score(v, ref=None, qbs=(), others_w=0.15, exp=None):
    """sum of call losses + a light pull of everyone else toward the reviewed board ('a lot of the rest looks alright')"""
    t = calls(v, ref, qbs)
    if exp is not None: t.append(vet_bubble(v, exp))
    loss = sum(x for _, x in t)
    if ref is not None:
        named = set(LOW_FIRST + UNDER_FIRST + MID_TE + TOP3)
        o = [n for n in ref.index if n in v.index and n not in named and ref[n] >= 50]
        loss += others_w * float(np.mean(np.abs(np.log(v[o].values) - np.log(ref[o].values))))
    return loss, t
