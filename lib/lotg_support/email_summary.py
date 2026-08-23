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
# quoted line can be 30 words on its own. On a rich week it now carries up to
# three of those PLUS a two-sentence read of what kind of week it was, so the
# budget is generous — a hard ceiling behind it that only the minimum-sentence
# rule can push into. Still bounded: the sentence cap is the real guard, and a
# quiet week stays short because it has fewer sentences, not fewer words each.
_LEDE_MAX_WORDS = 105
_LEDE_HARD_WORDS = 135
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
# Everything is a single O(n) pass over the items, up to four are ever named,
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
    "number of trades", "number of add/drops", "total transactions",
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
                 "sheet", "tied", "joined", "is_new", "derived", "who", "score")

    def __init__(self, item, section: str):
        self.item = item
        self.section = section
        self.rank = getattr(item, "rank", None)
        self.column = str(getattr(item, "column", "") or "")
        self.family = _column_family(self.column) if self.column else section
        self.end = str(getattr(item, "end", "") or "")
        self.sheet = str(getattr(item, "sheet", "") or getattr(item, "section", "") or section)
        self.tied = bool(getattr(item, "tied", False))
        # A brand-new row (the diff found its key in no prior board) — a just-made
        # trade/add, a freshly recorded pick. New data, whatever its column.
        self.is_new = bool(getattr(item, "is_new", False))
        # A crossing that JOINED a place (arrived at a value someone still holds)
        # is a tie in every sense the reader cares about; the event boards phrase
        # it as `joined` where the player/team crossings use `tied`. The ties
        # tally below counts both — `_score` keeps using `tied` alone, so surfacing
        # joins in the count doesn't quietly re-rank which line leads.
        self.joined = self.tied or bool(getattr(item, "joined", False))
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


# Below this a week is a handful of odds and ends, not a "broad" one worth a
# where-it-landed sentence — the plain leftover clause says it in fewer words.
_BROAD_MIN = 6
# The lede may call out up to FOUR standout lines — a rich week has a record, a
# trade, a team move and more that are separate stories, and collapsing them
# loses most. The first leads its own sentence; the rest are packed into one
# semicolon-joined REEL, so four headlines cost two sentences, not four. A line
# still has to earn it: score within `_RUNNERUP_FRAC` of the headline, a DIFFERENT
# stat family and a different entity from everything named, and short enough.
_MAX_NAMED = 4
_RUNNERUP_FRAC = 0.4
# Words held back from the named lines so the cause sentence and the texture
# sentence survive the final trim — the shape of the week is worth more than one
# extra quoted line.
_STORY_RESERVE = 50

# ---------------------------------------------------------------------------
# Provenance — telling a re-valuation apart from real results
# ---------------------------------------------------------------------------
# The single most useful thing a lede can say about a busy week is WHY it is
# busy, and there are three different reasons, which read as three different
# weeks:
#
#   RE-VALUED HISTORY  a settled season's rows moved. A completed season's picks,
#                      trades and weeks cannot change because of new games — they
#                      are done — so when they move it is the pipeline recomputing
#                      them: a formula, a key or an attribution changed. This is
#                      the fingerprint of a code change (or an upstream data
#                      correction), NOT of the league playing football.
#   MARKET DRIFT       KTC and age move on their own, every single run, forever.
#                      A week that is mostly KTC churn is the quietest kind there
#                      is, however many rows it touches.
#   NEW RESULTS        the in-progress season's game production moved.
#
# The first two ARE new data — market prices and the calendar are real inputs —
# and only re-valued history is the pipeline talking to itself. So a headline can
# come from any of the three; only recompute is barred from it.
#
# A special case of re-valued history is worth calling out by name: a row that
# now "passes" an earlier-numbered version of ITSELF. That only happens when a
# key the boards rank on was renumbered — the unmistakable signature of a
# structural change — so the lede says so in as many words.
#
# Things that move on their own, without a game being played, are still NEW DATA:
#   Length of tenure — the wall clock advancing a still-rostered player's tenure.
#   Current KTC       — the live market re-pricing a player TODAY.
# But a DATED KTC checkpoint ("KTC on draft day", "… 3 years after draft day",
# "… at end of rookie year") is settled history: that value belonged to a past
# date and is fixed, so when it moves it is a backfill correction or a renumber —
# a recompute, not the market. And "Pick-adjusted Difference in KTC …" is a
# recompute diagnostic (family "Pick-adjusted Difference"), never drift.
_KTC_CHECKPOINT = re.compile(r"after|at end|on draft|rookie|year")


def _is_new_data_family(column: str, family: str) -> bool:
    """A column whose movement is real new data rather than a recompute — the
    wall clock (tenure) or the live market (a CURRENT KTC, not a dated checkpoint)."""
    fam, col = str(family).lower(), str(column).lower()
    if fam.startswith("length of tenure"):
        return True
    if "ktc" in col and fam.startswith("ktc") and not _KTC_CHECKPOINT.search(col):
        return True
    return False
_PAREN = re.compile(r"\(([^()]*)\)\s*$")
_YEAR = re.compile(r"\b(20\d\d)\b")


def _paren(label: str) -> str:
    """The entity in a board label's trailing parentheses — the player in
    "startup pick 10.07 (Tom Brady)", "" when there is none."""
    m = _PAREN.search(str(label))
    return m.group(1).strip() if m else ""


def _self_reference(cand: "_Cand") -> bool:
    """True when the mover passed or joined a DIFFERENT row of the same entity —
    "Tom Brady 10.07 passes Tom Brady 10.02". The only thing that produces this
    is a renumbered key, so it is a structural-change tell, not real movement."""
    item = cand.item
    mover = getattr(item, "label", None) or getattr(item, "mover", "") or ""
    me = _paren(mover)
    if not me:
        return False
    passed = list(getattr(item, "passed", ()) or ()) + \
        list(getattr(item, "others", ()) or ())
    return any(_paren(p) == me and str(p) != str(mover) for p in passed)


def _row_season(label: str) -> Optional[int]:
    """The season a board row belongs to, for the history-vs-live split. The 2020
    startup carries no year in its label but is the oldest season there is."""
    low = str(label).lower()
    if "startup" in low:
        return 2020
    m = _YEAR.search(str(label))
    return int(m.group(1)) if m else None


def _provenance(cand: "_Cand", season: Optional[int],
                in_season: bool = True) -> str:
    """"drift" | "live" | "recompute" — why this row moved. `recompute` is the
    catch-all: a settled-history row, a self-reference (renumbered key), or one
    whose season can't be read (an all-time total, which only moves by
    recomputation anyway).

    `live` — a genuinely new result — covers two cases: a BRAND-NEW row dated in
    the current period (a trade or add just made, a pick freshly recorded — new
    data whatever the time of year), and current-season game production once the
    season is UNDERWAY. In the preseason a current-season row that is not new
    cannot have moved on results — a 2026 rookie pick's valuation shifts only
    because the board around it was recomputed — so it reads as the recompute it
    is."""
    # A row overtaking a renumbered version of itself didn't move — a key
    # changed. That is structural, whatever column it lands on, so it is judged
    # before the family check (an "Age when drafted" self-pass is not drift).
    if _self_reference(cand):
        return "recompute"
    if _is_new_data_family(cand.column, cand.family):
        return "drift"
    yr = _row_season(getattr(cand.item, "label", "") or
                     getattr(cand.item, "mover", "") or cand.section)
    # A brand-new row in the current period is a real new transaction/pick — new
    # data even in the offseason, when no week has been played. An OLD-dated new
    # row is a historical event the pipeline only just started recording (e.g. a
    # backfilled startup slot-swap): that is a recompute, so it is not live.
    if cand.is_new and season and yr and yr >= season:
        return "live"
    if in_season and season and yr and yr >= season:
        return "live"
    return "recompute"


def _prov_phrase(recomp: int, drift: int, live: int) -> str:
    """The non-zero buckets, as "X re-valued, Y live, Z drift" — the split reads
    as the week's cause at a glance."""
    bits = []
    if recomp:
        bits.append(f"{recomp} re-valued history")
    if live:
        bits.append(f"{live} from new results")
    if drift:
        bits.append(f"{drift} KTC/tenure drift")
    return _join(bits)


def _bulk_story(rest: List["_Cand"], season: Optional[int],
                have_named: bool = True, in_season: bool = True) -> List[str]:
    """The heart of the lede: one or two sentences that say what KIND of week
    this was, framed by the dominant provenance of everything not already named.

    Every branch closes the count — the numbers it quotes account for every
    move in `rest` — because a summary whose figures don't add reads as a bug.
    `have_named` is whether a headline was quoted above; when it wasn't (a pure
    recompute week has no new-data line to lead with), the count is "of the N
    moves", not "of the N OTHER moves"."""
    n = len(rest)
    if n == 0:
        return []
    others_word = "other moves" if have_named else "moves"
    prov = {"recompute": 0, "drift": 0, "live": 0}
    for c in rest:
        prov[_provenance(c, season, in_season)] += 1
    recomp, drift, live = prov["recompute"], prov["drift"], prov["live"]
    sheets: dict = {}
    for c in rest:
        s = _short(c.section)
        sheets[s] = sheets.get(s, 0) + 1
    top = sorted(sheets.items(), key=lambda kv: (-kv[1], kv[0]))
    span = _join([f"{cnt} on {s}" for s, cnt in top[:2]])

    # The biggest stat family and the sheet spread are read off the REMAINDER,
    # not the whole week — a family line that got quoted as a headline is gone
    # from `rest`, and counting the full board here would overshoot it (the bug
    # that once produced "plus -1 others").
    rest_big = [b for b in _blocks(rest) if b[1] >= max(4, int(0.2 * n))][:2]
    block_fam = rest_big[0][0] if rest_big else None
    block_n = rest_big[0][1] if rest_big else 0
    block_secs = _join(rest_big[0][2][:3]) if rest_big else span
    others = n - block_n
    plus = f", plus {others} other{'' if others == 1 else 's'}" if others else ""

    def _besides(*, exclude: str) -> str:
        """The provenance buckets OTHER than the dominant one, so even a lopsided
        week accounts for all three causes — a rich summary names what else moved,
        not just the biggest pile."""
        r = 0 if exclude == "recompute" else recomp
        d = 0 if exclude == "drift" else drift
        li = 0 if exclude == "live" else live
        phrase = _prov_phrase(r, d, li)
        return f"; {phrase} besides" if phrase else ""

    # A handful of odds and ends: one plain clause, no story to tell.
    if n < _BROAD_MIN and not block_fam:
        where = _join(sorted(sheets)[:3])
        lead = f"{n} more" if have_named else f"{n}"
        return [f"{lead} {'move' if n == 1 else 'moves'} across {where}."]

    # DRIFT dominates: KTC / tenure moving on their own — real new data, but the
    # quietest kind, so it is summarised rather than dressed up as an event. (Only
    # tenure or a current KTC can reach here as drift; dated KTC checkpoints are
    # already counted as recompute, so a KTC-checkpoint block never triggers it.)
    if drift >= 0.6 * n and block_fam and \
            block_fam.lower().startswith(("length of tenure", "ktc")):
        lead = "The rest is" if have_named else "The week was"
        return [f"{lead} routine drift — {block_n} {block_fam} moves across "
                f"{block_secs}{plus}{_besides(exclude='drift')}."]

    # RE-VALUED HISTORY dominates: the settled past moved, which means the
    # pipeline changed, not the standings. This is the sentence that separates a
    # code/data-shape week from a football week — two short sentences, cause then
    # detail, rather than one that runs to forty words.
    if recomp >= 0.6 * n:
        lead = ("This is a recompute, not a results week" if recomp >= 0.85 * n
                else "This is mostly a recompute")
        newdata = live + drift
        nd = f", and only {newdata} reflect new data" if newdata else ""
        return [f"{lead}: {recomp} of the {n} {others_word} re-value settled "
                f"history ({span}){nd}."]

    # NEW RESULTS dominate: the in-progress season actually moved. On a big
    # in-season week this is the common case — so it still names the other causes,
    # to stay a complete account rather than only the headline pile.
    if live >= 0.6 * n:
        return [f"It was an active week — {live} of the {n} {others_word} are new "
                f"results ({span}){_besides(exclude='live')}."]

    # GENUINELY MIXED: no single cause owns it. Say how big, where it landed, and
    # the cause split — three facts that together are the week.
    opener = ("It was a big, broad week —" if n >= 60 else
              "It was a broad week —" if n >= 20 else
              "The week was spread out —")
    tail = sum(cnt for _s, cnt in top[3:])
    where = span + (f", and {tail} elsewhere" if tail else "")
    split = _prov_phrase(recomp, drift, live)
    return [f"{opener} {n} moves across {where} ({split})."]


def _reel(lines: Sequence[str]) -> str:
    """The standouts after the headline, packed into ONE sentence — each still
    quoted verbatim (so still grounded), joined by semicolons. Four headlines in
    the space of one, instead of four separate sentences."""
    clauses = [str(l).strip().rstrip(".") for l in lines if str(l).strip()]
    return "; ".join(clauses) + "." if clauses else ""


def _texture(cands: Sequence["_Cand"], rest: Sequence["_Cand"], total: int) -> List[str]:
    """One dense closing sentence: the biggest one or two stat families still
    moving, the renumber-artifact tell, and how much of the week was ties rather
    than overtakes — three kinds of texture a reader would otherwise have to count
    off the list themselves, folded together and dropped as a unit if the budget
    is tight."""
    bits: List[str] = []
    blocks = [b for b in _blocks(list(rest)) if b[1] >= max(4, int(0.15 * total))][:2]
    if len(blocks) == 1:
        fam, cnt, _s = blocks[0]
        bits.append(f"the biggest single thread is {cnt} {fam} moves")
    elif blocks:
        bits.append("the biggest threads are "
                    + _join([f"{cnt} {fam}" for fam, cnt, _s in blocks]) + " moves")
    arts = sum(1 for x in rest if _self_reference(x))
    if arts >= 3:
        bits.append(f"{arts} picks pass earlier-numbered versions of themselves")
    ties = sum(1 for x in cands if x.joined)
    if ties >= 3:
        bits.append(f"{ties} of the {total} were ties rather than overtakes")
    if not bits:
        return []
    s = "; ".join(bits)
    return [s[0].upper() + s[1:] + "."]


def reasoned_summary(sections: Sequence[Tuple[str, str, list]],
                     season: Optional[int] = None,
                     weeks_completed: Optional[int] = None) -> str:
    """The deterministic lede: up to three standout lines, then one or two
    sentences that say what KIND of week it was.

    `weeks_completed` gates what can count as new results: with no week played
    yet (the preseason), nothing is live and the whole week is a recompute. When
    it is not given the season is assumed underway, so a caller that only knows
    the year still gets the year-based read.

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
    in_season = weeks_completed is None or weeks_completed > 0

    # The blocks are worked out first: one stat family carrying a chunk of the
    # week is the biggest thread, and a line already covered by a block should
    # not also be quoted (that is the same fact told twice).
    big = [b for b in _blocks(ranked) if b[1] >= max(4, int(0.2 * total))][:2]
    block_fams = {f for f, _n, _s in big}

    # The standout lines, quoted verbatim so they can't drift from the facts —
    # but ONLY new-data lines are eligible to be one. New data is any of: new
    # results, a market move (KTC), or the clock advancing a tenure — anything but
    # a RECOMPUTE, which is the pipeline recomputing a settled value, not news
    # about the league. Spotlighting a recompute as the headline while the summary
    # below calls the week a recompute contradicts itself; recompute lines still
    # feed that summary, they just never take the headline. (With no season to
    # judge by, provenance is unknowable, so every line stays eligible and the old
    # behaviour holds — but the digest always supplies one.)
    eligible = [c for c in ranked
                if season is None or _provenance(c, season, in_season) != "recompute"]
    named_lines: List[str] = []
    words = 0
    named: set = set()
    named_fams: set = set()
    named_who: set = set()
    if eligible:
        head = next((c for c in eligible
                     if len(c.sentence().split()) <= _HEAD_MAX_WORDS), eligible[0])
        named_lines.append(head.sentence())
        words = len(named_lines[0].split())
        named = {id(head)}
        named_fams = {head.family}
        named_who = {head.who} if head.who else set()
        # Up to three more standouts join it if they clear the bar and add
        # something new — a different stat AND a different entity. A word budget is
        # held in reserve for the story and texture so a run of long trade labels
        # can't crowd them out; the extras are packed into one reel sentence below.
        for c in eligible:
            if len(named_lines) >= _MAX_NAMED:
                break
            if id(c) in named:
                continue
            if c.score < _RUNNERUP_FRAC * head.score:
                break                          # ranked desc — nothing better left
            s = c.sentence()
            w = len(s.split())
            if (c.family in named_fams or c.family in block_fams
                    or (c.who and c.who in named_who) or w > _HEAD_MAX_WORDS
                    or words + w > _LEDE_MAX_WORDS - _STORY_RESERVE):
                continue
            named_lines.append(s)
            words += w
            named.add(id(c))
            named_fams.add(c.family)
            if c.who:
                named_who.add(c.who)

    rest = [c for c in cands if id(c) not in named]

    # Compose, in priority order so `_fit` keeps the most valuable prefix: the
    # marquee highlight, then the cause/scale story, then a REEL of the remaining
    # standouts packed into one sentence, then a TEXTURE sentence folding the
    # biggest threads, the renumber artifacts and the ties count together. A rich
    # week thus packs four highlights plus the full analysis into five sentences;
    # a quiet one is short because it has fewer of these, not thinner ones.
    parts: List[str] = []
    if named_lines:
        parts.append(named_lines[0])
    parts += _bulk_story(rest, season, bool(named), in_season)
    if len(named_lines) > 1:
        reel = _reel(named_lines[1:])
        if reel:
            parts.append(reel)
    parts += _texture(cands, rest, total)

    # Two sentences minimum when a lone HEADLINE is all there is: a single quoted
    # line reads as an accident, so the shape of the week is the missing half. A
    # lone STORY sentence (a pure drift or recompute week with no headline) is
    # already a summary and stands on its own — padding it with the counts just
    # says the same thing twice.
    if named and len(parts) == 1 and total > 1:
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
                fallback: Optional[str] = None,
                weeks_completed: Optional[int] = None) -> str:
    """The digest's lede: the reasoned read of the board moves, the counts as a
    floor beneath it, "" when there is nothing to summarise.

    `fallback` lets a caller supply its own lede instead — the audit email does,
    via `audit_lede`, because its findings need a different kind of reasoning.
    `weeks_completed` gates "new results": in the preseason (zero) nothing is
    live, so a current-season row that moved is the recompute it actually is.

    Cannot raise. An unexpected failure anywhere in here costs the lede and
    nothing else."""
    try:
        if not sections and fallback is None:
            return ""
        if fallback is not None:
            return fallback
        # The current season, read off the title ("… — 2026 season, …"), is what
        # tells a re-valued 2020 row apart from a live 2026 one. Absent or
        # unparseable, provenance leans "recompute" — the neutral read.
        m = _YEAR.search(title or "")
        season = int(m.group(1)) if m else None
        return (reasoned_summary(sections, season, weeks_completed)
                or counted_summary(sections))
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
