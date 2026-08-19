"""Phase 15 — the lede: the paragraph at the top of the two weekly emails.

Both emails are walls of one-line facts. The Tuesday digest ran to 65 lines
across four board sections (nine are possible); the Wednesday audit, on a week
with findings, runs to a flag per sheet with a dozen detail lines under each.
Nobody reads a wall, and the one line that matters sits in it with the same
weight as the thirtieth.

This writes the few sentences that go above the list. Both ledes are computed —
no model, no key, no network, nothing to pay for — but neither is a count.
Each reasons about its own kind of email:

  `digest_lede`  scores every board move on PLACE, PROMINENCE and SURPRISE,
                 leads with the winner, and folds the bulk into one clause.
  `audit_lede`   scores every finding on how likely it is to be a REAL BUG:
                 a lost column or a build error outranks rows that moved, and
                 among rows that moved, the size and shape of the number swing
                 is what separates a defect from drift.

An AI version of this was written, tested and shelved; `plan/notes/ai-email-lede.md`
has the prompts, the grounding guard, the code and the setup steps, along with
the cases where a model would beat these heuristics.

**Nothing here can stop an email going out.** Every entry point returns a string
or "", and `build_intro` catches everything: the lede is a nicety on top of mail
that has to send either way.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

# The cap is on SENTENCES, not words — a lede is allowed to be five short
# sentences or one long one, and a word budget quietly punishes the former. The
# word ceiling is only a runaway guard for a model that ignores the sentence cap.
_MAX_SENTENCES = 5
# Two is a paragraph; one is a headline with no context. A week with more than
# one move always gets a second sentence, even if it has to run over budget.
_MIN_SENTENCES = 2
# The lede QUOTES the digest's own sentences instead of writing its own, and a
# quoted line can be 30 words on its own — so the budget is generous, with a hard
# ceiling behind it that only the minimum-sentence rule can push into.
_LEDE_MAX_WORDS = 95
_LEDE_HARD_WORDS = 130
_HEAD_MAX_WORDS = 34
# What we hand the model. A quiet week is a dozen lines; the busiest digest on
# record is under a hundred. The cap is a cost guard, not a filter we expect to
# bind — when it does bind, the prompt says so, so the model doesn't claim to
# have seen every line.



# ---------------------------------------------------------------------------
# The material
# ---------------------------------------------------------------------------
class Line:
    """A plain string dressed as a digest item, for callers (the audit email)
    whose findings aren't dataclasses with a `sentence()`."""

    def __init__(self, text: str):
        self.text = str(text)

    def sentence(self) -> str:
        return self.text


def counted_summary(sections: Sequence[Tuple[str, str, list]]) -> str:
    """The digest's deterministic lede: how much moved, and where.

    Says nothing about which move mattered — it can't know — but it is always
    available and always true, which is the whole point of having it. The audit
    email passes its own equivalent to `build_intro` instead."""
    per = sorted(((title, len(items)) for title, _v, items in sections if items),
                 key=lambda t: -t[1])
    total = sum(n for _t, n in per)
    if not total:
        return ""
    # Four or fewer sections is a readable list; more and it becomes the three
    # biggest plus a count of the rest, which is then always at least two — hence
    # the fixed plural.
    shown, rest = (per, 0) if len(per) <= 4 else (per[:3], len(per) - 3)
    where = ", ".join(f"{n} on {_short(t)}" for t, n in shown)
    tail = f", and {rest} more sections" if rest else ""
    return (f"{total} leaderboard {'move' if total == 1 else 'moves'} this week — "
            f"{where}{tail}.")


def _short(title: str) -> str:
    """Section title as it reads mid-sentence: "All-time leaderboard moves —
    draft picks" is "draft picks"."""
    return title.split("—")[-1].strip().rstrip(")").lower() if "—" in title else title.lower()


# ---------------------------------------------------------------------------
# The reasoned lede (deterministic, and the one that actually ships by default)
# ---------------------------------------------------------------------------
# `counted_summary` says how much moved. This says which move mattered, which is
# the question a reader actually has, and it answers it without a network call.
#
# Three things make a line worth leading with, and they are scored independently
# and multiplied, so a line has to be good on more than one axis to win:
#
#   PLACE        1st is not "a bit better" than 5th, it is the only place anyone
#                remembers. The weights fall off a cliff after 2nd.
#   PROMINENCE   "O-Score" and "Points" are stats the league argues about;
#                "Pick-adjusted Difference in KTC 2 years after draft day" is a
#                diagnostic column that happens to be rankable. Both are true;
#                only one is news.
#   SURPRISE     A line is interesting in proportion to how little it resembles
#                the rest of the week. Twenty-three moves on one column are one
#                event reported twenty-three times; the single move on a column
#                nothing else touched, or in the direction nothing else went, is
#                the one a reader could not have guessed.
#
# Everything is a single O(n) pass over the items, at most two are ever named,
# and the composed lede is trimmed sentence-by-sentence to the same caps the AI
# lede is held to — so a 65-line week and a 6,500-line week produce the same
# shape of paragraph, and neither can produce a wall.

# Places fall off a cliff: 1st is the story, 2nd is a footnote, 5th is a rounding
# error. Anything past the board window shares the floor.
_PLACE_WEIGHT = {1: 1.0, 2: 0.42, 3: 0.24, 4: 0.17, 5: 0.13}
_PLACE_FLOOR = 0.10

# What kind of news the section is, independent of the line in it. A record or a
# milestone is a threshold nobody had crossed before; a board move is a
# reshuffle; an on-pace change is a projection, and projections are the softest
# claim in the email.
_SECTION_WEIGHT = (
    ("milestone", 1.35),
    ("single-season record", 1.30),
    ("single-week record", 1.15),
    ("— players", 1.10),
    ("— teams", 1.10),
    ("on pace", 0.55),
    ("season-long results", 0.75),
)

# Stats the league argues about. Matched on the column's family (see
# `_column_family`), so "Points added" and "Avg points added" both land here.
_PROMINENT = {
    "o-score", "pf", "avg pf", "max pf", "pa", "points", "avg points",
    "net points", "points added",
    "points against", "points lost", "differential", "avg differential",
    "win %", "all-play win %", "faab", "total faab bid", "record",
    "trade impact score", "player addition value", "trade addition value",
    "number of trades", "number of transactions",
}
# Deliberately NOT prominent: "KTC". It is real and rankable, but it is also the
# column this pipeline recomputes most often, so a KTC week is the norm rather
# than the news. Leaving it in the set above let the week's own bulk win the
# headline over the one line that wasn't part of it.
# Diagnostic columns: real, rankable, and not what anyone means by a record.
_DERIVED_MARKERS = ("pick-adjusted", "adjusted by position", "quartile",
                    "volatility", "difference of averages", "over same time",
                    "5 games before", "times as", "% of starts", "cuff",
                    "length of tenure", "skill")

_FAMILY_STOP_STRONG = {"at", "after", "value", "values", "adjusted", "vs",
                       "before", "over", "while", "when"}
_FAMILY_STOP_WEAK = {"of", "per", "in", "from", "by", "on"}
_FAMILY_MAX_WORDS = 3


def _column_family(column: str) -> str:
    """The stat a column belongs to, with its qualifiers stripped.

    "KTC at end of rookie year", "KTC 1 year after draft day" and "KTC value of
    player added at end of season" are one stat measured at three moments — the
    lede needs to see them as one story, which is exactly what makes a week of
    KTC churn describable in a clause instead of twenty-three lines."""
    out: List[str] = []
    for tok in str(column).split():
        low = tok.lower().strip(",;:()")
        if tok[:1].isdigit() and out:
            break
        if low in _FAMILY_STOP_STRONG and out:
            break
        if low in _FAMILY_STOP_WEAK and len(out) >= 2:
            break
        out.append(tok)
        if len(out) >= _FAMILY_MAX_WORDS:
            break
    return " ".join(out) if out else str(column)


def stat_relevance(column: str) -> float:
    """How much this stat matters, 0.45 (a diagnostic) to 1.5 (one the league
    argues about). Public because the email ORDERS by it too — the lede and the
    list should agree about which stats are worth reading first, and two tables
    would drift apart."""
    return _prominence(column, _column_family(column))


def _prominence(column: str, family: str) -> float:
    low = str(column).lower()
    if any(m in low for m in _DERIVED_MARKERS):
        return 0.45
    if family.lower() in _PROMINENT:
        return 1.5
    # A long, heavily qualified name is its own signal that the column is a
    # measurement rather than a headline.
    return 0.8 if len(low.split()) > 4 else 1.0


class _Cand:
    """One reportable line, with the facts the scoring needs pulled off it.

    Every attribute is read with a default, so an item type this module has never
    seen scores as an ordinary line instead of raising."""

    __slots__ = ("item", "section", "rank", "column", "family", "end",
                 "sheet", "tied", "derived", "who", "score")

    def __init__(self, item, section: str):
        self.item = item
        self.section = section
        self.rank = getattr(item, "rank", None)
        self.column = str(getattr(item, "column", "") or "")
        self.family = _column_family(self.column) if self.column else section
        self.end = str(getattr(item, "end", "") or "")
        self.sheet = str(getattr(item, "sheet", "") or getattr(item, "section", "") or section)
        self.tied = bool(getattr(item, "tied", False))
        self.derived = _prominence(self.column, self.family) < 1.0
        self.who = str(getattr(item, "group", lambda: "")() or "")
        self.score = 0.0

    def sentence(self) -> str:
        return self.item.sentence()


def _section_weight(title: str) -> float:
    low = title.lower()
    for needle, w in _SECTION_WEIGHT:
        if needle in low:
            return w
    return 1.0


def _score(cands: List[_Cand]) -> None:
    """Score every candidate in place. One pass to count, one to score."""
    fam_n: dict = {}
    end_n: dict = {}
    for c in cands:
        fam_n[(c.sheet, c.family)] = fam_n.get((c.sheet, c.family), 0) + 1
        end_n[(c.sheet, c.end)] = end_n.get((c.sheet, c.end), 0) + 1
    for c in cands:
        place = _PLACE_WEIGHT.get(c.rank, _PLACE_FLOOR) if c.rank else 0.5
        weight = place * _section_weight(c.section) * _prominence(c.column, c.family)
        # Surprise, part one: how alone this line is. One move on a column
        # nothing else touched is news; the twenty-third move on one column is
        # the same news, restated.
        n = fam_n[(c.sheet, c.family)]
        weight *= 1.6 if n == 1 else (1.15 if n == 2 else (0.7 if n >= 8 else 1.0))
        # Surprise, part two: direction. When a sheet moved almost entirely at
        # one end, the lone move at the other end is the one nobody predicted.
        same, other = end_n.get((c.sheet, c.end), 0), end_n.get(
            (c.sheet, "low" if c.end == "high" else "high"), 0)
        if c.end and other >= 4 and same <= max(1, other // 4):
            weight *= 1.4
        # A record equalled is a different event from a record broken, and at the
        # sharp end of a board it is the rarer of the two.
        if c.tied and (c.rank or 99) <= 2:
            weight *= 1.2
        c.score = weight


def _blocks(cands: List[_Cand], min_size: int = 4):
    """(family, count, [section, ...]) for the stat families big enough to be one
    story, biggest first.

    Merged across SHEETS on purpose. A KTC re-valuation lands on picks, trades
    and transactions at once; reporting it as three blocks describes the sheets
    it touched rather than the single thing that happened."""
    counts: dict = {}
    where: dict = {}
    for c in cands:
        counts[c.family] = counts.get(c.family, 0) + 1
        where.setdefault(c.family, []).append(_short(c.section))
    out = []
    for fam, n in counts.items():
        if n < min_size:
            continue
        seen, secs = set(), []
        for w in where[fam]:                       # first-seen order, deduped
            if w not in seen:
                seen.add(w)
                secs.append(w)
        out.append((fam, n, secs))
    return sorted(out, key=lambda t: -t[1])


def _join(words: Sequence[str]) -> str:
    """"a", "a and b", "a, b and c" — the list reads as prose, not as output."""
    ws = list(words)
    if len(ws) <= 1:
        return ws[0] if ws else ""
    return ", ".join(ws[:-1]) + " and " + ws[-1]


def reasoned_summary(sections: Sequence[Tuple[str, str, list]]) -> str:
    """The deterministic lede that leads with the most notable line.

    Falls back to `counted_summary` if it can't do better — an empty week, or a
    headline sentence so long that quoting it would defeat the purpose."""
    cands = [_Cand(i, title) for title, _v, items in sections for i in items
             if hasattr(i, "sentence")]
    if not cands:
        return ""
    if len(cands) == 1:
        return _fit([cands[0].sentence()]) or counted_summary(sections)
    _score(cands)
    ranked = sorted(cands, key=lambda c: -c.score)
    total = len(cands)

    # The headline is quoted verbatim, so it has to be quotable. Some labels run
    # very long (a four-asset trade names all four), and a 40-word opening
    # sentence defeats the point of having a lede at all — so a line that can't
    # be said briefly yields to the next-best one that can.
    head = next((c for c in ranked[:6]
                 if len(c.sentence().split()) <= _HEAD_MAX_WORDS), ranked[0])
    parts = [head.sentence()]
    named = {id(head)}

    # The bulk, worked out BEFORE the second line is chosen. One stat family
    # carrying most of the week IS the week, and saying that once is worth more
    # than any of the lines inside it.
    rest = [c for c in cands if id(c) not in named]
    big = [b for b in _blocks(rest) if b[1] >= max(4, int(0.2 * total))][:2]
    covered = sum(n for _f, n, _s in big)
    block_fams = {f for f, _n, _s in big}

    # A second line earns its place by being about a different STAT and by not
    # already being covered by a block — another KTC line above the sentence that
    # says "59 KTC moves" is the same fact told twice, and so is a second line
    # about the same trade. A diagnostic column is NOT excluded: `_prominence`
    # already discounts it in the score, and an all-time worst on one is still an
    # all-time worst.
    for c in ranked[1:8]:
        if (c.score >= 0.4 * head.score and c.family != head.family
                and c.family not in block_fams
                and (c.who != head.who or not c.who)
                and len(c.sentence().split()) <= _HEAD_MAX_WORDS):
            parts.append(c.sentence())
            named.add(id(c))
            rest = [x for x in rest if id(x) != id(c)]
            break
    # The leftover rides on the block clause rather than taking a sentence of its
    # own, because the two are one thought — and because the counts have to
    # CLOSE. "59 KTC moves" under "16 of the 65" left six moves unaccounted for,
    # which reads as an arithmetic mistake even when every figure is right.
    leftover = len(rest) - covered
    spare = (f", plus {leftover} other{'' if leftover == 1 else 's'}"
             if leftover else "")
    if len(big) == 1:
        fam, n, secs = big[0]
        lead = ("The rest of the week is one story: " if covered >= 0.7 * len(rest)
                else "Most of the rest is one story: ")
        parts.append(f"{lead}{n} {fam} moves across {_join(secs[:3])}{spare}.")
    elif big:
        parts.append("Most of the rest is "
                     + _join([f"{n} {fam} moves" for fam, n, _s in big])
                     + f"{spare}.")
    elif leftover:
        where = _join(sorted({_short(c.section) for c in rest})[:3])
        parts.append(f"{leftover} other {'move' if leftover == 1 else 'moves'} "
                     f"across {where}.")

    # Ties are easy to miss in a list of near-identical lines, and a week that is
    # a third ties is a different week from one that is none.
    ties = sum(1 for c in cands if c.tied)
    if ties >= 3:
        parts.append(f"{ties} of the {total} were ties rather than overtakes.")

    # Two sentences minimum when there is more than one move: if the composition
    # above produced only a headline, the shape of the week is the missing half.
    if len(parts) == 1 and total > 1:
        parts.append(counted_summary(sections))
    return _fit(parts) or counted_summary(sections)


def _fit(parts: List[str]) -> str:
    """Join what fits, dropping whole sentences from the end — never cutting one
    mid-way, which would leave a half-stated fact in the email.

    Two sentences are guaranteed when two exist: a lone headline reads as an
    accident rather than a summary. That guarantee can push past the normal word
    budget, but never past the hard ceiling — a lede longer than the list it
    summarises has failed at its one job."""
    out: List[str] = []
    for p in parts:
        trial = out + [p]
        if len(trial) > _MAX_SENTENCES:
            break
        words = len(" ".join(trial).split())
        required = len(trial) <= _MIN_SENTENCES
        if words > (_LEDE_HARD_WORDS if required else _LEDE_MAX_WORDS):
            break
        out = trial
    return " ".join(out)


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------
# A sentence ends at .!? followed by whitespace or the end of the text. "103.3"
# and "pick 2.04" don't match (the dot is followed by a digit), which is the
# whole reason for the lookahead.
_SENT_END = re.compile(r"[.!?][\"')\]]*(?:\s|$)")


def sentence_count(text: str) -> int:
    """Sentences in `text`, counting a trailing fragment with no terminator."""
    s = (text or "").strip()
    if not s:
        return 0
    ends = list(_SENT_END.finditer(s))
    trailing = 1 if (not ends or ends[-1].end() < len(s)) else 0
    return len(ends) + trailing



# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_intro(sections: Sequence[Tuple[str, str, list]], title: str = "",
                fallback: Optional[str] = None) -> str:
    """The digest's lede: the reasoned read of the board moves, the counts as a
    floor beneath it, "" when there is nothing to summarise.

    `fallback` lets a caller supply its own lede instead — the audit email does,
    via `audit_lede`, because its findings need a different kind of reasoning.

    Cannot raise. An unexpected failure anywhere in here costs the lede and
    nothing else."""
    try:
        if not sections and fallback is None:
            return ""
        if fallback is not None:
            return fallback
        return reasoned_summary(sections) or counted_summary(sections)
    except Exception as exc:                      # noqa: BLE001 — never fail the email
        print(f"[lede] summary skipped ({type(exc).__name__}: {exc}).")
        return ""


# `digest_lede` is the name the callers should use; `reasoned_summary` stays as
# the implementation it delegates to.
digest_lede = build_intro


# ---------------------------------------------------------------------------
# The audit lede — which finding is most likely to be a real bug
# ---------------------------------------------------------------------------
# The digest lede asks "which move is most interesting?". The audit asks a
# harder and more useful question: "which of these is a DEFECT, and which is the
# pipeline working?" Most weeks the answer is "none of them" — upstream revised
# some data and our exports followed — so the lede's job is to say, in one
# sentence, whether this is one of those weeks.
#
# Three things separate a defect from drift, in order:
#
#   STRUCTURE    A pinned column that vanished or was renamed, a build error, a
#                failing test. These are not judgement calls: the pipeline said
#                it would produce something and didn't.
#   SWING SHAPE  Among rows that merely moved, the SHAPE of the number change is
#                the signal. A value that went blank, dropped to zero, or flipped
#                sign is a different event from one that moved 2%. This is the
#                bug class this repo keeps hitting — a present-day feed deciding
#                a historical value, which shows up as a wall of `1613 → 0`.
#   BREADTH      One column moving across a thousand rows is one cause reported a
#                thousand times. Many columns moving in one sheet is broader and
#                worse. Counting rows conflates the two; counting distinct
#                columns doesn't.
#
# Everything is parsed out of the audit's own already-rendered detail lines, so
# the lede cannot contradict the list underneath it.

# Blanks are half of most drift pairs, and audit_weekly renders them as "∅".
_BLANKS = {"", "∅", "n/a", "na", "nan", "none", "null", "in progress", "-"}
# "changed: Team=A | Year=2024 — PF: 100 → 999; O-Score: 41.2 → 39.8"
_DELTA_SPLIT = " — "
_ARROW = " → "
# How a finding's own section places it before any of its details are read.
_AUDIT_SECTION_WEIGHT = (
    ("part 2", 1.00),      # schema: a pinned column lost or renamed
    ("schema", 1.00),
    ("part 3", 0.92),      # build errors, failing tests
    ("part 1", 0.45),      # rows moved — the swing shape decides how much it matters
)
# Matched against the finding's SECTION only. Matching its text too looked
# harmless and wasn't: every Part 1 finding ends "since the committed build",
# so a substring test for "build" promoted routine row movement to the weight of
# a build error, and the real build error stopped leading the email.
# These phrases are unambiguous enough to raise a finding on their own.
_STRUCTURAL_MARKERS = ("missing pinned column", "renamed", "no longer present",
                       "build error", "failing test", "test failed",
                       "lost column", "unreadable", "could not be read")
_SWING_WEIGHT = 0.5        # how much the worst swing can lift a Part 1 finding
# A swing of this factor or more is reported as a defect shape rather than a
# correction. Two-and-a-half times is deliberately low: on these sheets a value
# that merely doubled is already the wrong value, not a revised one.
_FOLD_MIN = 2.5
# The shapes that read as a defect rather than a correction, and how to count
# them in prose. Everything not in here is ordinary movement.
_SEVERE_KINDS = {
    "blank": "went blank",
    "zero": "dropped to zero",
    "sign": "flipped sign",
    "fold": "swung several-fold",
}


def _num(text: str) -> Optional[float]:
    try:
        return float(str(text).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _swing(old: str, new: str) -> Tuple[float, str, str]:
    """(severity 0-1, kind key, how to say it).

    Ordered by how hard the change is to explain as ordinary drift. A number that
    became nothing, or became zero, or moved by a factor, is the shape of a bug;
    a number that moved a couple of percent is the shape of an upstream
    correction. The fold case reports the actual multiple, because "a 10x swing"
    and "a 1000x swing" are not the same news."""
    o_raw, n_raw = str(old).strip(), str(new).strip()
    o_blank, n_blank = o_raw.lower() in _BLANKS, n_raw.lower() in _BLANKS
    if o_blank and n_blank:
        return 0.0, "", ""
    if n_blank:
        return 1.00, "blank", "a value that went blank"
    if o_blank:
        # A window maturing looks exactly like this and is expected; the audit
        # already suppresses the clean cases, so what reaches here is mild.
        return 0.15, "filled", "a blank that filled in"
    o, n = _num(o_raw), _num(n_raw)
    if o is None or n is None:
        return 0.40, "text", "a text value that changed"
    if o == n:
        return 0.0, "", ""
    if n == 0:
        return 0.90, "zero", "a value that dropped to zero"
    if o == 0:
        return 0.50, "offzero", "a value that came off zero"
    if o * n < 0:
        return 0.80, "sign", "a value that flipped sign"
    big, small = max(abs(o), abs(n)), min(abs(o), abs(n))
    ratio = big / small if small else float("inf")
    if ratio >= _FOLD_MIN:
        sev = 0.62 + min(0.10, (ratio - _FOLD_MIN) / 100.0)
        return sev, "fold", f"a {_mult(ratio)} swing"
    rel = abs(n - o) / max(abs(o), 1e-9)
    return min(0.55, rel), ("move" if rel >= 0.25 else ""), \
        ("a large move" if rel >= 0.25 else "")


def _mult(ratio: float) -> str:
    """"10×", "1,000×" — rounded, because the exact factor of a bug is noise."""
    if ratio == float("inf") or ratio >= 1000:
        return "1,000×+"
    # 9.99 rounds to "10.0×", which reads as a typo; hand it to the integer form.
    return f"{ratio:.0f}×" if ratio >= 9.5 else f"{ratio:.1f}×"


_ROLLUP = "columns that moved: "
_ROLLUP_ITEM = re.compile(r"^(?P<col>.+?)\s*\((?P<n>\d+)\)$")


class _Finding:
    """One audit flag: the worst swing under it, and the columns it moved."""

    __slots__ = ("text", "section", "sheet", "score", "worst", "kind",
                 "column", "columns", "swings", "shown", "sampled")

    def __init__(self, flag: dict):
        self.text = str(flag.get("text") or "").replace("**", "")
        self.section = str(flag.get("section") or "")
        self.sheet = self.text.split(":")[0].strip() if ":" in self.text else ""
        self.worst, self.kind, self.column = 0.0, "", ""
        details = list(flag.get("details") or ())
        # Per-column row counts for the WHOLE finding, from the audit's own
        # roll-up. The `changed:` lines under it are a sample the audit chose to
        # show, so counting those would describe the sample, not the week.
        self.columns = _rollup(details)
        self.sampled = not self.columns
        self.swings: dict = {}
        self.shown = 0
        seen: dict = {}
        for col, old, new in _deltas(details):
            self.shown += 1
            seen[col] = seen.get(col, 0) + 1
            sev, key, label = _swing(old, new)
            if key:
                self.swings[key] = self.swings.get(key, 0) + 1
            if sev > self.worst:
                self.worst, self.kind, self.column = sev, label, col
        # Without a roll-up the only breadth evidence is the lines the audit
        # chose to show — usable, but it describes the sample, and `sampled`
        # makes the lede say so rather than passing it off as the whole week.
        if self.sampled:
            self.columns = seen
        base = 0.60
        sec = self.section.lower()
        for needle, w in _AUDIT_SECTION_WEIGHT:
            if needle in sec:
                base = w
                break
        low = self.text.lower()
        if any(m in low for m in _STRUCTURAL_MARKERS):
            base = max(base, 0.92)
        self.score = min(1.0, base + _SWING_WEIGHT * self.worst)


def _rollup(details: Sequence[str]) -> dict:
    """{column: rows} from the audit's "columns that moved:" line, if present."""
    out: dict = {}
    for line in details:
        i = str(line).find(_ROLLUP)
        if i < 0:
            continue
        tail = str(line)[i + len(_ROLLUP):].split(" … ")[0]
        for item in tail.split(", "):
            m = _ROLLUP_ITEM.match(item.strip())
            if m:
                out[m.group("col")] = int(m.group("n"))
    return out


def _deltas(details: Sequence[str]):
    """(column, old, new) for every `COL: old → new` pair in the detail lines.

    Reads the audit's own rendering rather than re-deriving anything, so the
    lede is incapable of describing a change the list below it doesn't show."""
    for line in details:
        if _ROLLUP in str(line):
            continue
        _, sep, tail = str(line).partition(_DELTA_SPLIT)
        if not sep:
            continue
        for piece in tail.split("; "):
            col, sep2, rest = piece.partition(": ")
            if not sep2 or _ARROW not in rest:
                continue
            old, _, new = rest.partition(_ARROW)
            yield col.strip(), old.strip(), new.strip()


def audit_lede(flags: Sequence[dict], gaps: Optional[dict] = None,
               drift=None, attributed: int = 0) -> str:
    """The dataset-health lede: what most needs a look, and whether it is a bug.

    Cannot raise — `render_email` calls it while assembling an email that has to
    go out regardless."""
    try:
        return _audit_lede(flags, gaps or {}, drift, attributed)
    except Exception as exc:                      # noqa: BLE001
        print(f"[lede] audit summary skipped ({type(exc).__name__}: {exc}).")
        return _counted_audit(flags, gaps or {})


def _counted_audit(flags: Sequence[dict], gaps: dict) -> str:
    n_break, n_gap = len(flags), sum(len(v) for v in gaps.values())
    bits = []
    if n_break:
        sections = len({f.get("section") or f.get("text") for f in flags})
        bits.append(f"{n_break} finding{'s' if n_break != 1 else ''} across "
                    f"{sections} audit section{'s' if sections != 1 else ''}")
    if n_gap:
        bits.append(f"{n_gap} missed injury week{'s' if n_gap != 1 else ''}")
    return (" and ".join(bits) + ".") if bits else ""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _audit_lede(flags: Sequence[dict], gaps: dict, drift, attributed: int) -> str:
    found = [_Finding(f) for f in flags]
    n_gap = sum(len(v) for v in gaps.values())
    if not found:
        return (f"No findings; {_plural(n_gap, 'missed injury week')}."
                if n_gap else "")
    found.sort(key=lambda f: -f.score)
    top = found[0]
    parts: List[str] = []

    # 1. The alarm. A structural break speaks for itself; a row that merely moved
    #    needs its swing quoted, because the swing IS the question.
    #
    #    Opening by restating the top finding is RANKING — it says which of
    #    several to read first. With exactly one finding there is nothing to
    #    rank, and the sentence becomes a verbatim echo of the bullet directly
    #    beneath it. That never showed while a bad week carried ten findings;
    #    the week the noise was cleared, the whole email was one drift line
    #    printed three times (lede, breakage, NFLverse section). So on a
    #    single-finding week the echo is dropped and the lede keeps only what
    #    the finding does not already say — its breadth and its swing profile,
    #    which are computed, not restated. If that leaves nothing, there is no
    #    lede, exactly as on a clean week.
    if top.worst >= 0.60 and top.kind:
        where = f" on {top.sheet}" if top.sheet else ""
        parts.append(f"Worth opening first{where}: {top.kind} in {top.column}.")
    elif len(found) > 1:
        parts.append(_sentence(top.text))

    # 2. Breadth, from the audit's own per-column roll-up. One column across a
    #    thousand rows is one cause reported a thousand times; several columns in
    #    one sheet is wider and worse — and a row count cannot tell them apart.
    cols: dict = {}
    for f in found:
        for c, n in f.columns.items():
            cols[c] = cols.get(c, 0) + n
    total = sum(cols.values())
    sampled = all(f.sampled for f in found)

    def _unit(n: int) -> str:
        noun = "changed value" if sampled else "changed row"
        return f"{n} {noun}{'' if n == 1 else 's'}" + (" shown" if sampled else "")

    if len(cols) == 1 and total:
        only = top.column if top.column in cols else next(iter(cols))
        parts.append(f"All of it is one column, {only} ({_unit(total)}).")
    elif total and max(cols.values()) >= 0.6 * total:
        col, n = max(cols.items(), key=lambda kv: kv[1])
        # Don't name the column twice — the first sentence already did.
        named = "that column" if col == top.column else f"one column, {col}"
        parts.append(f"{n} of the {_unit(total)} are {named}; "
                     f"{_plural(len(cols) - 1, 'other')} moved too.")
    elif len(cols) > 1:
        parts.append(f"{_plural(len(cols), 'column')} moved.")

    # 3. The swing profile — the sentence that says "bug" or "drift". Counted
    #    over the changes the audit chose to SHOW, so it is described that way.
    shapes: dict = {}
    for f in found:
        for kind, n in f.swings.items():
            shapes[kind] = shapes.get(kind, 0) + n
    severe = sorted(((k, n) for k, n in shapes.items() if k in _SEVERE_KINDS),
                    key=lambda kv: -kv[1])
    shown = sum(f.shown for f in found)
    if severe:
        parts.append("Of the changes shown, "
                     + _join([f"{n} {_SEVERE_KINDS[k]}" for k, n in severe[:3]]) + ".")
    elif shapes.get("move"):
        parts.append(f"{shapes['move']} of the changes shown are large moves, but "
                     "none are blanks, zeroes or sign flips.")
    elif shown:
        parts.append("None of the changes shown are blanks, zeroes or sign flips.")

    # 4. What is already accounted for, and what is merely missing. Separate
    #    sentences: joined they read as a garden path, and `_fit` can drop the
    #    least important one on its own when the budget is tight.
    if drift is not None and getattr(drift, "compared", False) \
            and getattr(drift, "any_change", False):
        parts.append(f"NFLverse changed {drift.changed_cells} values"
                     + (f", explaining {_plural(attributed, 'row')} of ours."
                        if attributed else "."))
    if n_gap:
        parts.append(f"{_plural(n_gap, 'injury week')} have no capture.")

    # `_counted_audit` is the floor for a week that HAS something to summarise
    # and whose sentences all got trimmed. A single finding with nothing
    # computed to add is a different case: "1 finding across 1 audit section"
    # sits above one bullet saying the same thing in more words. No lede, the
    # same as a clean week.
    fitted = _fit(parts)
    if fitted:
        return fitted
    return "" if len(found) == 1 else _counted_audit(flags, gaps)


def _sentence(text: str) -> str:
    """A finding's own text as a sentence — it is written as a fragment.

    Left uncapitalised when it opens with a sheet name ("picks: missing pinned
    column …"). Those are identifiers, and "Player_year" is not a word."""
    t = str(text).strip().rstrip(".")
    if not t:
        return ""
    first = t.split(" ", 1)[0]
    lead = t if first.endswith(":") or "_" in first else t[:1].upper() + t[1:]
    return lead + "."
