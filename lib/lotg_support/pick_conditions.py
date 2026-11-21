"""Pick swaps and protections: a PORTION of a draft pick changing hands.

Some trades move less than a whole pick: a pick handed over "top-4 protected"
(the original owner keeps it if it lands in slots 1-4), a later payment to lift
that protection, or a swap right ("you get the better of my 4th and yours").
`data/pick_conditions.csv` records each one; this module values them.

The value system ("portion of a pick")
--------------------------------------
Until a pick's slot is set it is equally likely to be any of the league's
`TEAMS` slots, and two different teams' picks never share a slot. Each
condition is a function of the slots of the picks it names, so its value on a
date is the EXPECTED value over every assignment of distinct slots, each slot
priced at the pick's round-average price that day (KTC, or the FAAB board)
shaped by the league's draft-day slot curve (see "the slot curve" below). Once a pick has been drafted its slot is known and the condition
resolves to what actually happened (a protection on a pick that landed 2.08 is
worth 0; the pick itself is worth all of it).

  protected_pick      the receiver gets the pick EXCEPT in the protected slots,
                      where he gets the rollover pick (the same owner's
                      same-round pick a later year) or nothing:
                      E[v(slot) * 1{not protected} + v(rollover) * 1{protected}]
  protection_removal  the receiver (who already holds the protected pick) gets
                      the protected part: E[(v(slot) - v(rollover)) * 1{protected}]
                      — so protected_pick + protection_removal = the whole pick.
  better_of           the receiver gets ONE pick, the better (earlier slot) of
                      two named picks: E[v(better)]
  swap                the receiver gets the better (earlier slot) of his own
                      pick `orig` and the giver's pick `other`, giving up the
                      worse: E[v(better) - v(own)] >= 0. `after` names a swap
                      that runs first and stands in for whichever of the two is
                      blank: what that swap left the side (its receiver the
                      better of its two, its giver the worse).

The "portion" printed in the trades sheet is that value over the value of one
whole pick of the same round on the same date (for a swap: over the receiver's
own pick), at the deal.

Owners are Sleeper display handles (like data/commissioner_pick_trades.csv);
`trade_completed_utc` is the target trade's completion time, UTC, the same key
the commissioner overlay matches on.
"""
from __future__ import annotations

import csv
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "pick_conditions.csv"
TEAMS = 8
KINDS = ("protected_pick", "protection_removal", "swap", "better_of")
_ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}

# (orig owner, slot, draft year) -> value of that pick at that slot on the date in question
PickValue = Callable[[str, int, int], Optional[float]]
# (orig owner, draft year) -> its slot when already settled (drafted) on that date, else None
KnownSlot = Callable[[str, int], Optional[int]]


@dataclass(frozen=True)
class Condition:
    cid: str
    kind: str
    year: int
    rnd: int
    orig: str                  # protected pick's / swap receiver's own pick's original owner
    other: str                 # swap: the giver's pick's original owner ('' when `after` is set)
    slots: FrozenSet[int]      # protection: the protected slots
    after: str                 # swap: cid of a swap that runs first
    frm: str                   # owner giving this up
    to: str                    # owner getting it
    ts: str                    # target trade's completion, UTC "YYYY-MM-DD HH:MM:SS"
    deal: str = ""
    notes: str = ""
    rollover: Optional[int] = None   # protection: the year of the same owner's same-round pick conveyed instead

    @property
    def has_asset(self) -> bool:
        """a separate asset on the trade (a protected pick rides on its own pick leg)"""
        return self.kind != "protected_pick"


def _slots(s: str) -> FrozenSet[int]:
    out = set()
    for part in str(s or "").replace(" ", "").split("|"):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return frozenset(out)


def load(path: Path = DATA) -> List[Condition]:
    path = Path(path)
    if not path.exists():
        return []
    rows: List[Condition] = []
    with path.open(newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    for r in csv.DictReader(lines):
        kind = (r.get("kind") or "").strip()
        if kind not in KINDS:
            raise ValueError(f"pick_conditions: unknown kind {kind!r} ({r})")
        rows.append(Condition(
            cid=r["condition_id"].strip(), kind=kind, year=int(r["pick_year"]), rnd=int(r["round"]),
            orig=r["orig_owner"].strip(), other=(r.get("other_orig_owner") or "").strip(),
            slots=_slots(r.get("protected_slots") or ""), after=(r.get("after") or "").strip(),
            frm=r["from_owner"].strip(), to=r["to_owner"].strip(), ts=r["trade_completed_utc"].strip(),
            deal=(r.get("deal") or "").strip(), notes=(r.get("notes") or "").strip(),
            rollover=int(r["rollover_year"]) if (r.get("rollover_year") or "").strip() else None))
    validate(rows)
    return rows


def validate(conds: Sequence[Condition]) -> None:
    ids = {c.cid for c in conds}
    for c in conds:
        if c.kind in ("protected_pick", "protection_removal"):
            if not c.slots or not all(1 <= s <= TEAMS for s in c.slots):
                raise ValueError(f"pick_conditions: {c.cid} needs protected slots 1..{TEAMS}")
        if c.kind == "better_of" and (not c.other or c.after):
            raise ValueError(f"pick_conditions: better_of {c.cid} needs other_orig_owner (and no after)")
        if c.kind == "swap":
            if [bool(c.orig), bool(c.other), bool(c.after)].count(True) != 2:
                raise ValueError(f"pick_conditions: swap {c.cid} needs two of orig_owner (the receiver's pick) / "
                                 f"other_orig_owner (the giver's) / after (an earlier swap supplies the missing one)")
            if c.after and c.after not in ids:
                raise ValueError(f"pick_conditions: swap {c.cid} runs after unknown {c.after}")
        if c.frm == c.to:
            raise ValueError(f"pick_conditions: {c.cid} from == to")


def by_trade(conds: Iterable[Condition]) -> Dict[str, List[Condition]]:
    out: Dict[str, List[Condition]] = {}
    for c in conds:
        out.setdefault(c.ts, []).append(c)
    return out


def _round(c: Condition) -> str:
    return _ORD.get(c.rnd, f"{c.rnd}th")


def label(c: Condition) -> Optional[str]:
    """the asset as it reads in 'Assets received' / 'Assets sent'. Starts with a word, never a year, so the
    pick-label parsers (which key on a leading 'YYYY') never take it for a pick leg."""
    if c.kind == "protection_removal":
        return f"Pick protection removed: {c.year} {_round(c)}({c.orig}) top {_slot_text(c.slots)}"
    if c.kind == "swap":
        return f"Pick swap: {c.year} {_round(c)}s, {c.to} gets the better ({c.deal or c.cid})"
    if c.kind == "better_of":
        return f"Pick better of: {c.year} {_round(c)}({c.orig}) or {c.year} {_round(c)}({c.other})"
    return None


def _slot_text(s: FrozenSet[int]) -> str:
    s = sorted(s)
    if s == list(range(1, len(s) + 1)):
        return str(len(s))
    return "/".join(str(x) for x in s)


LABEL_RE = re.compile(r"^Pick (?:protection removed|swap|better of): ")


def is_label(text) -> bool:
    return bool(LABEL_RE.match(str(text or "").strip()))


def from_label(text, conds: Sequence[Condition]) -> Optional[Condition]:
    t = str(text or "").strip()
    for c in conds:
        if label(c) == t:
            return c
    return None


# ------------------------------------------------------------------------------------------- the slot curve
# KTC quotes picks only by 12-team quarter (an 8-team round spans two: 4.01-4.04 all read "Early 3rd") and the
# FAAB board prices a future pick at its round average, so neither tells one slot from the next within a quarter.
# The SHAPE across a round's slots comes from the league's own draft-day slot prices
# (data/faab_value/pick_schedule_base.csv: the median price of each slot over every rookie draft held); the LEVEL
# from the unit being priced. An unsettled pick at slot s is worth  whole(unit, date) * w(s) / mean(w over the round),
# where whole is the round-average price of that pick in KTC or FAAB on the date — so the expectation of a single
# pick over its slots is exactly its round-average price, and a portion is the same fraction of a pick in both units.

SLOT_CURVE_CSV = ROOT / "data" / "faab_value" / "pick_schedule_base.csv"
_CURVE: Dict[int, Dict[int, float]] = {}


def slot_curve(rnd: int) -> Dict[int, float]:
    """slot -> the round's draft-day price at that slot (rounds 1-4; 2.09 and the 5.0X buys are not swapped)"""
    if not _CURVE:
        with Path(SLOT_CURVE_CSV).open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                m = re.match(r"^(\d)\.(\d\d)$", r["slot"].strip())
                if m and 1 <= int(m.group(2)) <= TEAMS:
                    _CURVE.setdefault(int(m.group(1)), {})[int(m.group(2))] = float(r["price"])
    return _CURVE.get(int(rnd), {})


def slot_share(rnd: int, slot: int) -> float:
    """w(slot) / mean(w) over the round: 1.0 for every slot when the curve is missing"""
    c = slot_curve(rnd)
    if len(c) < TEAMS or int(slot) not in c:
        return 1.0
    return c[int(slot)] / (sum(c.values()) / len(c))


def unit_pick_value(rnd: int, whole: Callable[[str, int], Optional[float]],
                    settled: Callable[[str, int, int], Optional[float]], known: KnownSlot) -> PickValue:
    """the PickValue used for one unit: a settled (drafted) pick at its own slot is priced exactly (`settled`);
    otherwise the round-average price (`whole(orig, year)`) shaped by the slot curve"""
    def _pv(o, slot, y):
        if known(o, y) == slot:
            return settled(o, slot, y)
        w = whole(o, y)
        return None if w is None else float(w) * slot_share(rnd, slot)
    return _pv


# ------------------------------------------------------------------------------------------- the value system

def _by_id(conds: Sequence[Condition]) -> Dict[str, Condition]:
    return {c.cid: c for c in conds}


def picks_of(c: Condition, conds: Sequence[Condition]) -> List[str]:
    """every original owner whose pick's slot this condition depends on"""
    out = [x for x in (c.orig, c.other) if x]
    if c.kind == "swap" and c.after:
        out += [x for x in picks_of(_by_id(conds)[c.after], conds) if x not in out]
    return out


def _held(c: Condition, conds, slot: Dict[str, int], who: str) -> str:
    """the pick (original owner) `who` holds when swap `c` runs: the named one, or — with `after` — what the
    earlier swap left him (its receiver the better slot, its giver the worse)"""
    fixed = c.orig if who == c.to else c.other
    if fixed:
        return fixed
    prev = _by_id(conds)[c.after]
    a, b = _held(prev, conds, slot, prev.to), _held(prev, conds, slot, prev.frm)
    better, worse = (a, b) if slot[a] < slot[b] else (b, a)
    if who == prev.to:
        return better
    if who == prev.frm:
        return worse
    raise ValueError(f"pick_conditions: {c.cid} runs after {prev.cid}, which {who} is not part of")


def own_pick(c: Condition) -> str:
    """the original owner of the pick a portion is measured against (a swap's named pick when the receiver's
    own comes from an earlier swap)"""
    return c.orig or c.other


def _outcome(c: Condition, conds, slot: Dict[str, int], v: Dict[str, float], roll: float = 0.0) -> float:
    """value to the receiver for one assignment of slots (roll = the rollover pick's value, 0 if none)"""
    if c.kind == "protected_pick":
        return roll if slot[c.orig] in c.slots else v[c.orig]
    if c.kind == "protection_removal":
        return v[c.orig] - roll if slot[c.orig] in c.slots else 0.0
    if c.kind == "better_of":
        return v[c.orig] if slot[c.orig] < slot[c.other] else v[c.other]
    own, other = _held(c, conds, slot, c.to), _held(c, conds, slot, c.frm)
    better = own if slot[own] < slot[other] else other
    return v[better] - v[own]


def _rollover_value(c: Condition, pick_value: PickValue, known_slot: KnownSlot, teams: int) -> Optional[float]:
    if c.kind not in ("protected_pick", "protection_removal") or not c.rollover:
        return 0.0
    s = known_slot(c.orig, c.rollover)
    vals = [pick_value(c.orig, x, c.rollover) for x in ([s] if s is not None else range(1, teams + 1))]
    if any(x is None for x in vals):
        return None
    return sum(vals) / len(vals)


def value(c: Condition, conds: Sequence[Condition], pick_value: PickValue,
          known_slot: KnownSlot = lambda _o, _y: None, teams: int = TEAMS) -> Optional[float]:
    """value to the receiver (c.to) on one date: the expectation over every assignment of distinct slots to the
    picks whose slot is not yet known. None if a needed slot price is unavailable."""
    roll = _rollover_value(c, pick_value, known_slot, teams)
    if roll is None:
        return None
    owners = picks_of(c, conds)
    fixed = {o: known_slot(o, c.year) for o in owners}
    fixed = {o: s for o, s in fixed.items() if s is not None}
    free = [o for o in owners if o not in fixed]
    open_slots = [s for s in range(1, teams + 1) if s not in fixed.values()]
    price: Dict[Tuple[str, int], Optional[float]] = {}

    def _p(o, s):
        if (o, s) not in price:
            price[(o, s)] = pick_value(o, s, c.year)
        return price[(o, s)]

    total, n = 0.0, 0
    for perm in itertools.permutations(open_slots, len(free)):
        slot = dict(fixed)
        slot.update(zip(free, perm))
        v = {}
        for o in owners:
            x = _p(o, slot[o])
            if x is None:
                return None
            v[o] = float(x)
        total += _outcome(c, conds, slot, v, roll)
        n += 1
    return total / n if n else None


def whole_pick(c: Condition, pick_value: PickValue, known_slot: KnownSlot = lambda _o, _y: None,
               teams: int = TEAMS) -> Optional[float]:
    """the expected value of the whole pick the portion is measured against (the receiver's own for a swap)"""
    o = own_pick(c)
    s = known_slot(o, c.year)
    vals = [pick_value(o, x, c.year) for x in ([s] if s is not None else range(1, teams + 1))]
    if any(x is None for x in vals):
        return None
    return sum(vals) / len(vals)


def portion(c: Condition, conds: Sequence[Condition], pick_value: PickValue,
            known_slot: KnownSlot = lambda _o, _y: None, teams: int = TEAMS) -> Optional[float]:
    v = value(c, conds, pick_value, known_slot, teams)
    w = whole_pick(c, pick_value, known_slot, teams)
    if v is None or not w:
        return None
    return v / w


def describe(c: Condition, frac: Optional[float], ktc: Optional[float] = None, faab: Optional[float] = None) -> str:
    """one line for the trades sheet's 'Pick swaps and protections' column: what moved, its portion of a pick and
    its KTC / FAAB price at the deal"""
    price = ", ".join(x for x in (f"{ktc:,.0f} KTC" if ktc is not None else "",
                                  f"${faab:,.1f} FAAB" if faab is not None else "") if x)
    p = (f" — {frac:.2f} of a pick at the deal" if frac is not None else "") + (f" ({price})" if price else "")
    top = _slot_text(c.slots)
    alt = (f"{c.to} gets {c.orig}'s {c.rollover} {_round(c)} instead" if c.rollover
           else f"{c.orig} keeps it")
    if c.kind == "protected_pick":
        return (f"{c.year} {_round(c)}({c.orig}) is top-{top} protected: if it lands in slots 1-{top} {alt}"
                f"{p.replace('of a pick', 'of the pick')}" + (f". {c.notes}" if c.notes else ""))
    if c.kind == "protection_removal":
        return (f"Removes the top-{top} protection on the {c.year} {_round(c)}({c.orig}) {c.to} already held "
                f"(it was: {alt} if it landed in slots 1-{top}){p}" + (f". {c.notes}" if c.notes else ""))
    if c.kind == "better_of":
        return (f"{c.to} gets the better (earlier slot) of the {c.year} {_round(c)}s of {c.orig} and {c.other}{p}"
                + (f". {c.notes}" if c.notes else ""))
    mine = (f"the {c.orig} pick he holds" if c.orig
            else f"the one he keeps after the earlier swap ({c.after})")
    giver = (f"the {c.other} pick {c.frm} holds" if c.other
             else f"the one {c.frm} keeps after the earlier swap ({c.after})")
    return (f"Pick swap: {c.to} takes the better of two {c.year} {_round(c)}s — {mine} or {giver} — "
            f"and {c.frm} the worse{p}" + (f". {c.notes}" if c.notes else ""))


def chain_note(c: Condition, conds: Sequence[Condition]) -> str:
    """which other trade a condition's partner lives on (protection granted / removed)"""
    for o in conds:
        if o is c or o.orig != c.orig or o.year != c.year or o.rnd != c.rnd:
            continue
        if {c.kind, o.kind} == {"protected_pick", "protection_removal"}:
            return o.ts
    return ""


# ------------------------------------------------------------------------------------------- FAAB values
# The FAAB Value columns carry each condition inside a side's pick list as "YYYY cond:<id>"
# (faab_history.pick_value hands such a label here), so every consumer of those lists — the build's
# FAAB pass and lotg_support.faab_derived's recompute — values it the same way.

COND_RE = re.compile(r"^(\d{4}) cond:(\S+)$")
_FAAB_CTX: Dict[str, object] = {}


def norm(name) -> str:
    """the build's _norm_team_name: case- and space-insensitive"""
    return re.sub(r"\s+", "", str(name or "").strip().lower())


def spec_label(c: Condition) -> str:
    return f"{c.year} cond:{c.cid}"


def set_faab_context(fidx, conds: Sequence[Condition], slots: Dict[Tuple[int, int, str], Tuple[int, Optional[tuple]]],
                     draft_start: Callable[[int], object]) -> None:
    """slots: (year, round, norm(orig)) -> (slot it was drafted at, (drafted player id, date he stands in from))"""
    _FAAB_CTX.clear()
    _FAAB_CTX.update(fidx=fidx, conds=list(conds), slots=dict(slots), draft_start=draft_start)


def faab_value(label, target, price: Optional[Callable] = None) -> Optional[float]:
    """a "YYYY cond:<id>" entry's FAAB value on `target` (None when unknown / no context).
    price(label, drafted, target) prices one pick at one slot (default faab_history.pick_value on the context)"""
    m = COND_RE.match(str(label).strip())
    if not m or not _FAAB_CTX:
        return None
    conds = _FAAB_CTX["conds"]
    c = _by_id(conds).get(m.group(2))
    if c is None:
        return None
    if price is None:
        from . import faab_history as FH
        fidx = _FAAB_CTX["fidx"]

        def price(lbl, dk, d):
            return FH.pick_value(fidx, lbl, dk, d)
    slots = _FAAB_CTX["slots"]
    import datetime as _dt
    t = target if isinstance(target, _dt.date) else _dt.date.fromisoformat(str(target)[:10])

    def _known(o, y):
        if t < _FAAB_CTX["draft_start"](y):
            return None
        got = slots.get((int(y), int(c.rnd), norm(o)))
        return got[0] if got else None

    def _settled(o, slot, y):
        got = slots.get((int(y), int(c.rnd), norm(o)))
        return price(f"{int(y)} {int(c.rnd)}.{int(slot):02d}", got[1] if got else None, t)

    def _whole(o, y):
        return price(f"{int(y)} {int(c.rnd)}.??", None, t)

    return value(c, conds, unit_pick_value(c.rnd, _whole, _settled, _known), _known)
