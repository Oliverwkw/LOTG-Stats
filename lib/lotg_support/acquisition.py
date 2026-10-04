"""Points above expectation for a player addition, and the price paid for it.

Two columns on `player_additions`, each "what he produced here minus what a
player bought at the same price would have produced over the same weeks":

* **Points above expectation (total)** — X minus Y, where Y is the sum, over
  the weeks he was rostered here (counted as elapsed weeks since acquisition),
  of what same-price, same-position acquisitions ACTUALLY scored in that elapsed
  week, whether or not their team still held them (assume nobody was ever cut
  or traded: a peer's week off the roster counts what he scored elsewhere —
  another league roster, or the NFL via nflverse — and 0 if he did not play).
  Answers "did this buy produce more than the average player bought at that
  price really did over the same span?".
* **Points above expectation (rate)** — the same, per rostered week: the total
  / weeks rostered.

X is every point he scored for this team during this tenure (started and
benched), position-adjusted with the build's per-season position factor and put
on one scoring scale across seasons (each week x the all-seasons league starter
average / that season's). A tenure with no rostered week is 0 in both columns.

Price, per channel, in that channel's own units (the model never compares one
channel with another):

=========  ==========================================  =====================
channel    model price                                 `Price paid (FAAB)`
=========  ==========================================  =====================
free       0 (free agency, and a $0 waiver claim)      0
waiver     log(1 + winning bid)                        the bid
rookie     log(overall pick)                           the money curve at that class's
                                                       slot value; a 5.0X (a FAAB buy)
                                                       is locked at $20
startup    log(overall pick); 2021 vet picks continue  the money curve at that board
           the startup board (#153+)                   slot's value
trade      log(1 + price in FAAB $)                    sum of what was sent, in FAAB $
=========  ==========================================  =====================

**The money curve** (`MoneyCurve`, user 2026-10-03, "option B"): the league's
currency is draft picks, and FAAB scales roughly logarithmically with player
value — a star is not in the same hemisphere as a margin guy. KTC only places an
asset on the rookie draft board ("which pick is this worth?"): the board is
draft-day KTC per overall rookie pick, pooled over every class and made
non-increasing. Dollars then rise exponentially up the board, from the last
regular pick (4.08, at its KTC / 100) to a mid first (pick 4.5) at $1,000. Below
the 4.08 an asset is worth KTC / 100 — the locked 100 KTC per $ that holds for
depth pieces and add-ons. On each date that board curve is folded into the
day's market (`MarketCurve`): the field's 49th player is $1,000 (a mid first
floats with its class and the market), the top is priced by standing over the
day's top 10 (the best player averages $3,500 — KTC's 9,999 cap hides how far
ahead he is on raw value), and below the anchor half the same market effect is
blended with the board curve. A draft pick is priced at its own
class's slot value, so a strong class's first costs a little more than a weak
one's (pick value moves year to year) — blended, `CLASS_WEIGHT` (25%) from the
class and the rest from all classes pooled, so the swing stays slight. A
TRADED pick is priced on the board too, never by KTC: its slot's price, or the
average over its round's slots when the slot is not yet known, less
`PICK_YEAR_DISCOUNT` (0.95) per draft it sits beyond the next one — a small
discount, as the league applies to future picks in trades.

A trade's price is the dollars of everything SENT (each asset through the money
curve; FAAB sent counts as its dollars), split across what was received by their
dollars. Received picks take their share. Dollars add, so seven depth pieces
stay cheap and one star is expensive — no depth tax (that is `KTC value
difference`'s fairness comparison of two sides, not a price per asset; it priced
Luke's twelve assets for Dalvin Cook at $101), and no flat face value (that
priced stevenb123's seven depth pieces for Cam Skattebo above Luke's four
starters for Justin Jefferson).

Y's weekly rate is a Poisson regression fitted per channel on the whole
dataset (numpy IRLS, ridge 1.0), one row per addition per elapsed week from its
acquisition to the last week played: the elapsed week (log, with bends at
2/4/8/17/34/68 weeks), offseasons crossed, a piecewise-linear price ramp between
price quintiles constrained to move the right way (a better pick / a bigger bid
/ a bigger trade price never predicts less), price x time, and position x time.
Past the 95th percentile of a channel's elapsed weeks the rate is carried
forward ("if more players existed it would extend so").

The model refits every build, so every row moves slightly whenever a new week
lands — the columns are registered in `volatile_columns`.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

RATE_COLUMN = "Points above expectation (rate)"
TOTAL_COLUMN = "Points above expectation (total)"
PRICE_COLUMN = "Price paid (FAAB)"
COLUMNS = (PRICE_COLUMN, RATE_COLUMN, TOTAL_COLUMN)

CHANNELS = ("free", "waiver", "rookie", "startup", "trade")
POSITIONS = ("QB", "RB", "WR", "TE")
DEPTH_FACTOR = 0.6
# A rookie-draft round-5 pick (5.0X) is a FAAB buy, locked at this price (user
# rule 2026-10-03). Not the 2020 startup's round 5, a real pick of a 19-round
# draft, which is priced off the slot curve like the rest of that board.
ROUND5_PICK_FAAB = 20.0
# The money curve's anchor: a mid first (rookie pick 4.5, between 1.04 and
# 1.05) costs this much FAAB (user, 2026-10-03).
MID_FIRST_SLOT = 4.5
MID_FIRST_FAAB = 1000.0
# A rookie pick's board value: this share from its own class's draft-day values,
# the rest from all classes pooled. Pick value moves "slightly" year to year
# (user, 2026-10-03); the class alone swung a 1.04 from $476 (2022) to $1,528
# (2024) because the money curve magnifies a class's KTC level, 25% keeps the
# swing near +/-10%.
CLASS_WEIGHT = 0.25
# The market curve (MarketCurve, user 2026-10-03). On each date:
#   * the field's FIELD_ANCHOR_RANK-th player costs MID_FIRST_FAAB ($1,000) —
#     where a mid first sits on average (rank 49, range 30-77 over 65
#     month-ends), so a real mid first floats with its class and the market;
#   * above it, $1,000 x FIELD_GROWTH ^ (standing over the day's top-10 average),
#     G fixed so the best player averages TOP_PLAYER_FAAB ($3,500, "3-4 firsts",
#     more on a day he stands far above a thin top, less when it is bunched);
#   * below it, HALF the same market effect: the geometric blend (weight
#     LOW_STRENGTH) of $1,000 x FIELD_GROWTH_LOW ^ (standing against the day's
#     100th player) — G fixed so a 2,000-KTC piece averages $20 — and the money
#     curve rescaled to $1,000 at the anchor.
# Fitted on 73 month-ends 2020-09 to 2026-09; fixed, not refit per build: a
# price is locked at the move.
TOP_PLAYER_FAAB = 3500.0
FIELD_ANCHOR_RANK = 49
FIELD_GROWTH = 2.619
FIELD_GROWTH_LOW = 8.26
LOW_STRENGTH = 0.5
# A PLAYER is priced above replacement (user, 2026-10-03): a guy the league
# could pick up for free costs no FAAB. The replacement line is the field's
# player at the league's last rostered spot — roster spots (taxi and IR not
# counted) x teams, less one per team from SUPERTAXI_FROM, when a third taxi slot
# for long shots (<50% rostered) arrived, assumed to hold a zero-value player:
# 168 in 2020, 184 in 2021-23, 208 in 2024, 200 in 2025-26. The deduction is
# faded, not a hard floor (league opinion and KTC don't always agree): a softplus
# with scale (line price / REPLACEMENT_FADE), so a player well above the line
# loses about the line's price and one below it shrinks smoothly toward $0
# (Cooper Kupp, 2026-10-03: $17 -> ~$3.50). Picks keep their board price — the
# league pays $20 FAAB for a 5.0X — and FAAB is its dollars.
SUPERTAXI_FROM = 2025
REPLACEMENT_FADE = 2.5
# A traded pick's slot is priced on what was knowable at the trade, never on
# where it eventually landed (user, 2026-10-03). For a pick whose deciding
# season (draft year - 1) is in progress or next up, each team's chance of each
# slot comes from a projection of the final order: the original owner's roster
# strength (its best ROSTER_TOP players' KTC that day — the 2 weakest rosters on
# Sept 1 drew a bottom-4 pick 80% of the time, 2021-25) blended with the stat
# that sets the order, as the season is played. The blend (roster_weight) and
# the spread of the odds (SLOT_SIGMA) were fitted on the 2021-25 seasons: in-
# season results overtake roster strength by week 2, the two combined beat
# either alone through week ~6, and roster adds nothing from week 8-9. The stat
# follows the draft's order rule (draft_capital.order_rule): record (wins, then
# points) for reverse placement, drafts through 2025; under ascending Max PF
# (2026 on) record still decides who makes the playoffs, so a team is placed in
# a block by record and the bottom block ordered by Max PF to date. Once the
# order is set the pick is its slot; the 2.09 only exists then. A pick two or
# more drafts out is its round's average.
ROSTER_TOP = 15
# After the regular season (user, 2026-10-03) the order is mostly mechanical:
# the bottom four go by the rule — Max PF (2026 on) and the 2025 draft's
# regular-season record are known outright; through the 2024 draft placement
# still counted the toilet bowl, so a spread of TOILET_BOWL_SIGMA remains until
# it is played — and the playoff block is revealed by the bracket: four teams
# over 5-8 before the semifinals, winners over 7-8 and losers over 5-6 after.
TOILET_BOWL_SIGMA = 0.75
PLACEMENT_COUNTS_TOILET_BOWL_THROUGH = 2024     # draft year
SLOT_SIGMA = (2.75, 2.35, 2.00, 1.90, 1.65, 1.55, 1.55, 1.55, 1.55, 1.40, 1.35, 1.35, 1.25, 1.00)
FIELD_STALE_DAYS = 30
FIELD_STALE_DAYS_PRE_DAILY = 365
KTC_DAILY_FLOOR = date(2021, 4, 16)    # the dynasty-daddy mirror's first daily quote
# A traded pick loses this factor per draft between the trade and its own draft
# (the next rookie draft = no discount). Set by the user, 2026-10-03: a small
# discount, 0.95. The league's pick-for-pick trades fit 0.80, but on only 14
# cross-year deals (bootstrap 80% range 0.59-1.00), mostly draft-day swaps
# carrying a pick-now premium — "WAY too big". Fixed, not refit per build: a
# price is locked at the move.
PICK_YEAR_DISCOUNT = 0.95
RIDGE = 1.0
PRICE_QUANTILES = (0, .2, .4, .6, .8, 1.0)
TAIL_QUANTILE = 0.95
MIN_KMAX = 8
# The expectation's tenure curve (2026-10-04; plan/notes/POINTS_ABOVE_EXPECTATION.md).
# Elapsed-week knots double past 68 as the data grows, and only those inside the
# observed range (TAIL_QUANTILE of the rows) are used; the offseason curve is
# piecewise linear with a hinge at every offseason at least MIN_TENURE_ADDITIONS
# additions have reached, its last slope carrying on. Nothing names a season or
# a horizon, so in 2036 the curve has ten seasons of shape where today it has six.
BASE_KNOT_WEEKS = (2, 4, 8, 17, 34, 68)
MIN_TENURE_ADDITIONS = 40
EXPECTATION_RIDGE = 30.0
PAID_CHANNELS = ("waiver", "rookie", "startup", "trade")
# A better price moves the expectation this way: down the pick number, up the
# bid / trade price.
_PRICE_SIGN = {"rookie": -1, "startup": -1, "waiver": 1, "trade": 1}


# ---------------------------------------------------------------------------
# channel / price
# ---------------------------------------------------------------------------
def channel(addition_type: str, faab: Optional[float] = None,
            draft_kind: Optional[str] = None) -> Optional[str]:
    """Model channel of one addition, or None (a commissioner move has no
    price). `draft_kind` is "rookie" / "startup" / "vet" for a Draft row."""
    t = str(addition_type or "").strip().lower()
    if t == "commissioner":
        return None
    if t == "draft":
        return "rookie" if str(draft_kind or "").lower() == "rookie" else "startup"
    if t == "trade":
        return "trade"
    if t == "waiver" and (faab or 0) > 0:
        return "waiver"
    return "free"


def price_feature(ch: str, *, faab: Optional[float] = None, overall: Optional[float] = None,
                  trade_faab: Optional[float] = None) -> Optional[float]:
    """The model's price for one addition (None = unpriceable)."""
    if ch == "free":
        return 0.0
    if ch == "waiver":
        return math.log1p(max(float(faab or 0.0), 0.0))
    if ch in ("rookie", "startup"):
        return math.log(max(float(overall), 1.0)) if overall is not None else None
    if ch == "trade":
        return math.log1p(max(float(trade_faab), 0.0)) if trade_faab is not None else None
    return None


def slot_price_curve(picks: Iterable[Tuple[float, float]]) -> Dict[int, float]:
    """{overall pick: price} from (overall pick, draft-day KTC of whoever went
    there) pairs: the mean per slot, made non-increasing in the pick number by
    isotonic regression (pool-adjacent-violators, weighted by picks per slot),
    so an earlier pick never costs less than a later one. Each pick's own value
    is in (unlike the leave-one-out pick-adjustment baseline, which priced
    1.04 above 1.01 in the 2020 startup). Slots with no value read off the
    curve by linear interpolation, held flat beyond its ends."""
    by: Dict[int, List[float]] = {}
    for s, v in picks:
        if s is None or v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        by.setdefault(int(s), []).append(float(v))
    if not by:
        return {}
    slots = sorted(by)
    # PAVA for a non-increasing fit: blocks of (sum, weight, first slot index).
    blocks: List[List[float]] = []
    for s in slots:
        blocks.append([sum(by[s]), float(len(by[s])), 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]:
            t = blocks.pop()
            blocks[-1][0] += t[0]
            blocks[-1][1] += t[1]
            blocks[-1][2] += t[2]
    fitted: List[float] = []
    for tot, w, n in blocks:
        fitted.extend([tot / w] * int(n))
    out = dict(zip(slots, fitted))
    for s in range(slots[0], slots[-1] + 1):
        if s not in out:
            out[s] = float(np.interp(s, slots, fitted))
    return out


def slot_price(curve: Dict[int, float], overall: Optional[float]) -> Optional[float]:
    """The curve's price for one pick (flat beyond the curve's ends)."""
    if not curve or overall is None:
        return None
    s = int(overall)
    if s in curve:
        return curve[s]
    return curve[min(curve)] if s < min(curve) else curve[max(curve)]


@dataclass
class MoneyCurve:
    """KTC -> FAAB $ through the rookie draft board (see the module docstring).
    `board` is {overall rookie pick: draft-day KTC}, non-increasing."""
    board: Dict[int, float]
    last_slot: int
    ktc_per_faab: float = 100.0
    mid_slot: float = MID_FIRST_SLOT
    mid_faab: float = MID_FIRST_FAAB

    def __post_init__(self):
        slots = sorted(s for s in self.board if s <= self.last_slot)
        if not slots:
            raise ValueError("empty draft board")
        self._slots = np.array(slots, float)
        self._ktc = np.array([self.board[s] for s in slots], float)
        self.k_last = float(self._ktc[-1])
        self.k_top = float(self._ktc[0])
        self.k_mid = float(np.interp(self.mid_slot, self._slots, self._ktc))
        # Above the 1.01 the board continues at its first step (1.01 -> 1.02),
        # the slope the user signed off on (2026-10-03: Jefferson ~$2,150, the
        # startup 1.01 ~$2,300 with a mid first at $1,000).
        k_second = float(self._ktc[1]) if len(self._ktc) > 1 else self.k_top
        self.top_slope = max(self.k_top - k_second, 1.0)
        base = self.k_last / self.ktc_per_faab
        self.r = (self.mid_faab / base) ** (1.0 / (self.last_slot - self.mid_slot))

    def slot_of(self, ktc: float) -> float:
        """The rookie pick an asset of this KTC is worth (continuous; < 1 above
        the 1.01, = last_slot at or below the 4.08)."""
        k = float(ktc)
        if k >= self.k_top:
            return float(self._slots[0]) - (k - self.k_top) / self.top_slope
        if k <= self.k_last:
            return float(self.last_slot)
        # the board falls with the slot; np.interp needs rising x
        return float(np.interp(k, self._ktc[::-1], self._slots[::-1]))

    def faab(self, ktc: Optional[float]) -> Optional[float]:
        if ktc is None or (isinstance(ktc, float) and math.isnan(ktc)):
            return None
        k = max(float(ktc), 0.0)
        if k <= self.k_last:
            return k / self.ktc_per_faab
        return (self.k_last / self.ktc_per_faab) * self.r ** (self.last_slot - self.slot_of(k))


def roster_weight(weeks_played: int) -> float:
    """Weight of roster strength (vs in-season results) in the projected
    order: all of it before week 1, half through week 3, none from week 8."""
    k = int(weeks_played)
    if k <= 0:
        return 1.0
    if k <= 3:
        return 0.5
    return max(0.0, 0.5 * (8 - k) / 5)


def slot_sigma(weeks_played: int) -> float:
    k = max(int(weeks_played), 0)
    return SLOT_SIGMA[min(k, len(SLOT_SIGMA) - 1)]


def inseason_score(record: Dict[str, float], max_pf: Dict[str, float], rule: str,
                   playoff_teams: int = 4) -> Dict[str, float]:
    """Higher = projected later pick. `record` is wins (ties broken by points,
    e.g. wins + PF / 1e5). Under "max_pf" a team is placed in a block by record
    and the bottom block is ordered by Max PF to date."""
    if rule != "max_pf":
        return dict(record)
    order = sorted(record, key=lambda t: record[t])
    bottom = set(order[:max(len(order) - int(playoff_teams), 0)])
    top = 1.0 + max(max_pf.values(), default=0.0)
    return {t: (max_pf.get(t, 0.0) if t in bottom else top + record[t]) for t in record}


def _normal_odds(rank: int, n: int, sigma: float, slots: Sequence[int]) -> List[float]:
    out = [0.0] * n
    if sigma <= 0:
        out[rank - 1] = 1.0
        return out
    w = {s: math.exp(-((s - rank) ** 2) / (2 * sigma * sigma)) for s in slots}
    tot = sum(w.values())
    for s, v in w.items():
        out[s - 1] = v / tot
    return out


def post_season_slot_odds(record: Dict[str, float], max_pf: Dict[str, float], draft_year: int, rule: str,
                          playoff_teams: int = 4, semifinal_winners: Optional[Sequence[str]] = None) -> Dict[str, List[float]]:
    """{team: [P(slot)]} once the regular season is over and before the order
    is final (see TOILET_BOWL_SIGMA)."""
    teams = sorted(record, key=lambda t: record[t])               # worst record first
    n = len(teams)
    nb = max(n - int(playoff_teams), 0)
    bottom, playoff = teams[:nb], teams[nb:]
    out: Dict[str, List[float]] = {}
    if rule == "max_pf":
        order, sig = sorted(bottom, key=lambda t: max_pf.get(t, 0.0)), 0.0
    else:
        order = bottom
        sig = TOILET_BOWL_SIGMA if int(draft_year) <= PLACEMENT_COUNTS_TOILET_BOWL_THROUGH else 0.0
    for i, t in enumerate(order):
        out[t] = _normal_odds(i + 1, n, sig, range(1, nb + 1))
    if semifinal_winners:
        win = [t for t in playoff if t in set(semifinal_winners)]
        lose = [t for t in playoff if t not in set(semifinal_winners)]
        groups = [(lose, range(nb + 1, nb + 1 + len(lose))), (win, range(nb + 1 + len(lose), n + 1))]
    else:
        groups = [(playoff, range(nb + 1, n + 1))]
    for grp, slots in groups:
        slots = list(slots)
        for t in grp:
            out[t] = [(1.0 / len(slots) if (s + 1) in slots else 0.0) for s in range(n)]
    return out


def _rank_z(values: Dict[str, float]) -> Dict[str, float]:
    teams = sorted(values, key=lambda t: values[t])
    r = np.arange(1, len(teams) + 1, dtype=float)
    z = (r - r.mean()) / (r.std() or 1.0)
    return {t: float(z[i]) for i, t in enumerate(teams)}


def project_slot_odds(roster_strength: Dict[str, float], weeks_played: int,
                      record: Optional[Dict[str, float]] = None, max_pf: Optional[Dict[str, float]] = None,
                      rule: str = "placement", playoff_teams: int = 4) -> Dict[str, List[float]]:
    """{team: [P(slot 1), ..., P(slot n)]} for a draft whose deciding season
    has `weeks_played` regular-season weeks done. Teams are ranked by a blend
    of roster strength and the in-season stat (rank z-scores, roster_weight),
    1 = projected worst, and each rank spreads over the slots as a discrete
    normal with slot_sigma."""
    teams = list(roster_strength)
    n = len(teams)
    a = roster_weight(weeks_played)
    score = _rank_z(roster_strength)
    if a < 1.0 and record:
        ins = _rank_z(inseason_score(record, max_pf or {}, rule, playoff_teams))
        score = {t: a * score[t] + (1 - a) * ins.get(t, 0.0) for t in teams}
    ranked = sorted(teams, key=lambda t: (score[t], t))
    sig = slot_sigma(weeks_played)
    out = {}
    for i, t in enumerate(ranked):
        r = i + 1
        w = np.array([math.exp(-((s - r) ** 2) / (2 * sig * sig)) for s in range(1, n + 1)])
        out[t] = list(w / w.sum())
    return out


def replacement_rank(roster_spots: int, teams: int, season: int) -> int:
    """The league's last rostered spot in a season (taxi and IR not counted),
    less the supertaxi long shot from SUPERTAXI_FROM."""
    return int(roster_spots) * int(teams) - (int(teams) if int(season) >= SUPERTAXI_FROM else 0)


def above_replacement(price: float, line_price: float) -> float:
    """A player's price above the replacement line, faded (softplus)."""
    if line_price <= 0:
        return max(float(price), 0.0)
    s = line_price / REPLACEMENT_FADE
    e = (float(price) - line_price) / s
    return s * (math.log1p(math.exp(e)) if e < 30 else e)


@dataclass
class MarketCurve:
    """KTC -> FAAB $ on one date, relative to that day's field (see the
    constants above). `player_values` is every league-relevant player's KTC that
    day; `money` is the board curve used, at half strength, below the anchor.

    Market-relative (user 2026-10-03): the board was measured on draft days
    whose anchor averaged `board_anchor`; KTC's level drifts (the anchor ran
    ~5,900 in 2020, ~4,700 in 2022-23, ~5,300 in 2025-26), so the board half
    reads an asset at its standing relative to the day's anchor, and a pick is
    priced at its draft-day ratio x the day's anchor (`pick_ktc`).
    `line_ratio` overrides the replacement line (as a fraction of the anchor)
    when the day's field is thinner than the replacement rank."""
    player_values: Sequence[float]
    money: "MoneyCurve"
    anchor_faab: float = MID_FIRST_FAAB
    replacement_rank: Optional[int] = None
    board_anchor: Optional[float] = None
    line_ratio: Optional[float] = None

    def __post_init__(self):
        vals = sorted((float(v) for v in self.player_values if v is not None), reverse=True)
        if not vals:
            raise ValueError("empty field")
        self.size = len(vals)
        self.k0 = vals[min(FIELD_ANCHOR_RANK, len(vals)) - 1]
        self.top10 = float(np.mean(vals[:10]))
        self.k100 = vals[min(100, len(vals)) - 1]
        self.spread_top = max(self.top10 - self.k0, 1.0)
        self.spread_low = max(self.k0 - self.k100, 1.0)
        self._scale = (self.board_anchor / self.k0) if self.board_anchor else 1.0
        self._m0 = self.money.faab(self.k0 * self._scale) or self.anchor_faab
        self.line_faab = None
        self.line_ktc = None
        if self.line_ratio is not None:
            self.line_ktc = self.line_ratio * self.k0
        elif self.replacement_rank and len(vals) >= int(self.replacement_rank):
            self.line_ktc = vals[int(self.replacement_rank) - 1]
        if self.line_ktc is not None:
            self.line_faab = self.faab(self.line_ktc)

    def covers(self, rank: Optional[int]) -> bool:
        """True when the field is deep enough to read rank `rank` off it."""
        return rank is None or self.size >= int(rank)

    def pick_ktc(self, ratio: Optional[float]) -> Optional[float]:
        """A pick's value on this date from its draft-day ratio to the anchor."""
        return None if ratio is None else float(ratio) * self.k0

    def player_faab(self, ktc: float) -> float:
        """A PLAYER's price: the market price above the replacement line."""
        p = self.faab(ktc)
        return above_replacement(p, self.line_faab) if self.line_faab is not None else p

    def faab(self, ktc: float) -> float:
        k = float(ktc)
        if k >= self.k0:
            return self.anchor_faab * FIELD_GROWTH ** ((k - self.k0) / self.spread_top)
        market = self.anchor_faab * FIELD_GROWTH_LOW ** ((k - self.k0) / self.spread_low)
        board = self.money.faab(max(k, 0.0) * self._scale) * self.anchor_faab / self._m0
        return market ** LOW_STRENGTH * board ** (1.0 - LOW_STRENGTH)


def field_values(histories: Dict[str, Tuple[List[str], List[float]]], on: date) -> List[float]:
    """Every player's KTC on `on` from {id: (sorted dates, values)}, skipping a
    stale last quote (FIELD_STALE_DAYS; FIELD_STALE_DAYS_PRE_DAILY before KTC's
    daily history) and zeros."""
    iso = on.isoformat()
    win = FIELD_STALE_DAYS if on >= KTC_DAILY_FLOOR else FIELD_STALE_DAYS_PRE_DAILY
    cut = (on - timedelta(days=win)).isoformat()
    out = []
    for ds, vs in histories.values():
        i = bisect.bisect_right(ds, iso) - 1
        if i >= 0 and ds[i] >= cut and vs[i] > 0:
            out.append(vs[i])
    return out


def asset_faab(ktc: Optional[float], money: "MoneyCurve", market: Optional[MarketCurve] = None,
               player: bool = False) -> Optional[float]:
    """An asset worth `ktc` in FAAB $ on the day's market curve (a player above
    replacement), or on the money curve alone when there is no field."""
    if ktc is None or (isinstance(ktc, float) and math.isnan(ktc)):
        return None
    if market is not None:
        return market.player_faab(float(ktc)) if player else market.faab(float(ktc))
    return money.faab(float(ktc))


def depth_value(values: Iterable[float], factor: float = DEPTH_FACTOR) -> float:
    """The build's package value (`KTC value difference`'s depth tax): best
    asset in full, each next x factor^i. A fairness comparison of two sides —
    NOT a price; used here only to check the per-asset values against the
    exported margin."""
    return sum(v * factor ** i for i, v in enumerate(sorted((float(x) for x in values), reverse=True)))


def value_shares(values: Sequence[Optional[float]]) -> Optional[List[float]]:
    """Each received asset's share of a trade's price: its KTC over the side's
    total (no depth tax — a price is per asset, user 2026-10-03). Shares sum to
    1. None when any asset is unvalued (the split would be a guess); an
    all-zero side splits equally."""
    if not values or any(v is None for v in values):
        return None
    vals = [max(float(v), 0.0) for v in values]
    tot = sum(vals)
    if tot <= 0:
        return [1.0 / len(vals)] * len(vals)
    return [v / tot for v in vals]


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------
def _poisson(X: np.ndarray, y: np.ndarray, lam: float = RIDGE, it: int = 60) -> np.ndarray:
    b = np.zeros(X.shape[1])
    b[0] = math.log(max(float(np.mean(y)), 1e-6))
    for _ in range(it):
        eta = np.clip(X @ b, -20, 10)
        mu = np.exp(eta)
        z = eta + (y - mu) / mu
        nb = np.linalg.solve(X.T @ (X * mu[:, None]) + lam * np.eye(X.shape[1]), X.T @ (mu * z))
        if np.max(np.abs(nb - b)) < 1e-8:
            return nb
        b = nb
    return b


def _monotone_poisson(X: np.ndarray, y: np.ndarray, ramp_cols: Sequence[int], sign: int,
                      lam: float = RIDGE) -> np.ndarray:
    """Poisson fit whose price-ramp coefficients all point `sign`'s way: the
    most wrong-signed ramp is pinned at 0 and the fit repeated until none is."""
    keep = np.ones(X.shape[1], bool)
    b = np.zeros(X.shape[1])
    for _ in range(len(ramp_cols) + 1):
        b = np.zeros(X.shape[1])
        b[keep] = _poisson(X[:, keep], y, lam)
        bad = [i for i in ramp_cols if keep[i] and sign * b[i] < 0]
        if not bad:
            break
        keep[min(bad, key=lambda i: sign * b[i])] = False
    return b


def _edges(p: np.ndarray) -> np.ndarray:
    return np.unique(np.quantile(p, PRICE_QUANTILES)) if len(p) else np.array([0.0])


def _ramps(p: np.ndarray, edges: np.ndarray) -> List[np.ndarray]:
    return [np.clip(p - lo, 0, hi - lo) for lo, hi in zip(edges[:-1], edges[1:])]


def _knots(kmax: float) -> np.ndarray:
    """Log elapsed-week knots inside the observed range: the base set, then
    doubling past 68 (136, 272, ...) as tenures that long appear."""
    weeks = list(BASE_KNOT_WEEKS) + [BASE_KNOT_WEEKS[-1] * 2 ** i for i in range(1, 12)]
    return np.log([w for w in weeks if w < kmax])


def _horizon(no: np.ndarray, aid: np.ndarray) -> int:
    """The longest tenure, in offseasons, that MIN_TENURE_ADDITIONS additions
    have reached — where the offseason curve may still bend."""
    reach = pd.Series(aid).groupby(no).nunique()
    ok = reach[reach >= MIN_TENURE_ADDITIONS]
    return max(1, int(ok.index.max()) if len(ok) else 1)


_POS3 = POSITIONS[1:]      # RB, WR, TE against a QB baseline


def _design(r: Dict[str, np.ndarray], chans: Sequence[str], st: dict) -> Tuple[np.ndarray, List[int]]:
    """The expectation's design over rows `r` (k, no, p, pos, ch, q).

    Per channel, as before: a level, an elapsed-week curve (capped at the
    channel's own TAIL_QUANTILE), a piecewise-linear offseason curve, price
    ramps (signed so a better price never expects less) with price x tenure, and
    a level and slope per position. Shared by the channels in the fit: each
    position's own elapsed-week curve (uncapped), a per-position slope per
    offseason, and — paid channels — position x price-percentile x tenure, so a
    cheap QB and a dear RB each age as their own peers did."""
    k, no, p, pos, ch, q = r["k"], r["no"], r["p"], r["pos"], r["ch"], r["q"]
    S = st["S"]
    hinges = [np.maximum(no - h, 0) for h in range(1, S)]
    cols: List[np.ndarray] = []
    ramp: List[int] = []
    for c in chans:
        m = (ch == c).astype(float)
        lk = np.minimum(np.log(k), math.log(st["kmax"][c]))
        cols += [m, m * lk] + [m * np.maximum(lk - x, 0) for x in st["knots"][c]]
        cols += [m * no] + [m * h for h in hinges]
        if c != "free":
            rr = _ramps(p, st["edges"][c])
            ramp += list(range(len(cols), len(cols) + len(rr)))
            cols += [m * _PRICE_SIGN[c] * x for x in rr] + [m * p * lk, m * p * no]
        pc = [(pos == P).astype(float) for P in _POS3]
        cols += [m * x for x in pc] + [m * x * lk for x in pc]
    lk = np.log(k)
    pc = [(pos == P).astype(float) for P in _POS3]
    pc4 = [(pos == P).astype(float) for P in POSITIONS]
    cols += [x * np.maximum(lk - kn, 0) for x in pc for kn in st["knots_all"]]
    if tuple(chans) == ("free",):
        cols += [x * h for x in pc for h in hinges]
    cols += [x * no for x in pc4]
    if tuple(chans) != ("free",):
        cols += [x * q * no for x in pc4] + [x * q * lk for x in pc4]
    return np.column_stack(cols), ramp


def _rows(group: Sequence["Addition"], q: Dict[object, float]) -> Dict[str, np.ndarray]:
    out: Dict[str, list] = {c: [] for c in ("k", "no", "p", "pos", "ch", "q", "y", "aid")}
    for i, a in enumerate(group):
        n = len(a.cf)
        out["k"] += range(1, n + 1)
        out["no"] += list(a.noff[:n])
        out["p"] += [a.p] * n
        out["pos"] += [_norm_pos(a.pos)] * n
        out["ch"] += [a.ch] * n
        out["q"] += [q.get(a.key, 0.5)] * n
        out["y"] += list(a.cf)
        out["aid"] += [i] * n
    return {c: np.array(v, dtype=object if c in ("pos", "ch") else float) for c, v in out.items()}


def _price_percentile(usable: Sequence["Addition"]) -> Dict[object, float]:
    """Each addition's price as a percentile within its channel (1 = dearest),
    the common scale the paid channels share their tenure terms on."""
    s = pd.Series([a.p * _PRICE_SIGN.get(a.ch, 1) for a in usable])
    pct = s.groupby(pd.Series([a.ch for a in usable])).rank(pct=True)
    return {a.key: float(v) for a, v in zip(usable, pct)}


def _fit_expectation(group: Sequence["Addition"], q: Dict[object, float]):
    """Fit one group (free, or the paid channels pooled); a predictor of the
    expected points for rows, or None when the group is empty."""
    r = _rows(group, q)
    if not len(r["k"]):
        return None
    chans = tuple(c for c in CHANNELS if (r["ch"] == c).any())
    st = {"kmax": {}, "edges": {}, "knots": {}}
    for c in chans:
        kc, pcn = r["k"][r["ch"] == c], r["p"][r["ch"] == c]
        st["kmax"][c] = max(MIN_KMAX, int(np.quantile(kc, TAIL_QUANTILE)))
        st["edges"][c] = _edges(pcn)
        st["knots"][c] = _knots(st["kmax"][c])
    st["knots_all"] = _knots(max(MIN_KMAX, int(np.quantile(r["k"], TAIL_QUANTILE))))
    st["S"] = _horizon(r["no"], r["aid"])
    X, ramp = _design(r, chans, st)
    b = _monotone_poisson(X, r["y"], ramp, 1, EXPECTATION_RIDGE)

    def predict(rr: Dict[str, np.ndarray]) -> np.ndarray:
        return np.exp(np.clip(_design(rr, chans, st)[0] @ b, -20, 10))
    return predict


@dataclass
class Addition:
    """One priced addition and its weeks. `held` = [(elapsed week, X points)]
    for every rostered week of the tenure (elapsed week 1 = the first league
    week that ended on/after the pickup); `cf` = the counterfactual
    ("never cut") points for elapsed weeks 1..len(cf), the held weeks included;
    `noff` = offseasons crossed by each of those weeks (same length as cf).
    Held weeks lie within 1..len(cf)."""
    key: object
    ch: Optional[str]
    p: Optional[float]
    pos: str
    held: List[Tuple[int, float]] = field(default_factory=list)
    cf: List[float] = field(default_factory=list)
    noff: List[int] = field(default_factory=list)


def _norm_pos(pos: object) -> str:
    p = str(pos or "").upper()
    if p in POSITIONS:
        return p
    return "RB" if p == "FB" else "WR"


def points_above_expectation(additions: Sequence[Addition]) -> Dict[object, Dict[str, Optional[float]]]:
    """{key: {RATE_COLUMN, TOTAL_COLUMN}} for every addition. Both None when it
    has no channel or no price; both 0.0 with no rostered week.

    Y is fit on every never-cut week of every priced addition: free agency on
    its own, the paid channels (waiver, rookie, startup, trade) pooled with
    their own price curves and shared position x tenure terms (`_design`)."""
    out: Dict[object, Dict[str, Optional[float]]] = {}
    usable = [a for a in additions if a.ch in CHANNELS and a.p is not None]
    for a in additions:
        if a.ch not in CHANNELS or a.p is None:
            out[a.key] = {RATE_COLUMN: None, TOTAL_COLUMN: None}
        elif not a.held:
            out[a.key] = {RATE_COLUMN: 0.0, TOTAL_COLUMN: 0.0}
    q = _price_percentile(usable)
    for chans in (("free",), PAID_CHANNELS):
        group = [a for a in usable if a.ch in chans]
        predict = _fit_expectation(group, q) if group else None
        for a in group:
            if not a.held:
                continue
            x = sum(pts for _k, pts in a.held)
            total = None
            if predict is not None:
                ks = [int(k) for k, _ in a.held]
                n = len(ks)
                rr = {"k": np.array(ks, float),
                      "no": np.array([a.noff[k - 1] if k - 1 < len(a.noff) else a.noff[-1] for k in ks], float),
                      "p": np.full(n, float(a.p)), "pos": np.array([_norm_pos(a.pos)] * n, dtype=object),
                      "ch": np.array([a.ch] * n, dtype=object), "q": np.full(n, q.get(a.key, 0.5))}
                total = x - float(predict(rr).sum())
            rate = round(total / len(a.held), 2) if total is not None else None
            total = round(total, 2) if total is not None else None
            out[a.key] = {RATE_COLUMN: rate, TOTAL_COLUMN: total}
    return out


# ---------------------------------------------------------------------------
# scale helpers shared by the build and recomputes
# ---------------------------------------------------------------------------
def season_scale(starter_avg_by_season: Dict[int, float], source_by_season: Dict[int, int]) -> Dict[int, float]:
    """{season: all-seasons league starter average / that season's}, so a point
    in any season is worth the same. The all-seasons average is over seasons on
    their own baseline (a season still borrowing the previous one's is left
    out of it)."""
    own = [v for y, v in starter_avg_by_season.items() if source_by_season.get(y, y) == y and v]
    overall = float(np.mean(own)) if own else 1.0
    return {int(y): (overall / v if v else 1.0) for y, v in starter_avg_by_season.items()}


def elapsed_calendar(weeks: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """League weeks in order — the clock 'elapsed week' counts on (offseason
    days are not weeks)."""
    return sorted({(int(y), int(w)) for y, w in weeks})


def first_elapsed_index(calendar: Sequence[Tuple[int, int]], week_end_day: Dict[Tuple[int, int], str],
                        pickup_day: str) -> int:
    """Index into `calendar` of the first week that ended on/after the pickup
    day (the tenure rule: a week counts once its last game is on/after the
    pickup). len(calendar) when none has yet."""
    for i, yw in enumerate(calendar):
        if str(week_end_day.get(yw, "")) >= str(pickup_day)[:10]:
            return i
    return len(calendar)
