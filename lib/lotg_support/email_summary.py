"""Phase 15 — the lede: the paragraph at the top of the two weekly emails.

Both emails are walls of one-line facts. The Tuesday digest ran to 65 lines
across four board sections (nine are possible); the Wednesday audit, on a week
with findings, runs to a flag per sheet with a dozen detail lines under each.
Nobody reads a wall, and the one line that matters sits in it with the same
weight as the thirtieth.

This writes the few sentences that go above the list. Two ways, tried in order:

  1. **Claude** (`ANTHROPIC_API_KEY` set). The model is handed the email's own
     already-rendered sentences — never a frame, never a rank map, never a number
     it has to work out — and asked which of them matter. That is the judgment a
     count can't make: one 1st-place overtake outweighs thirty 5th-place
     shuffles, and one schema break outweighs a thousand re-valued cells.
  2. **`reasoned_summary`**, otherwise — a deterministic lede that scores every
     line on place, prominence and surprise, leads with the winner, and folds the
     bulk into one clause. Offline, always true, and good enough that the AI path
     is an upgrade rather than a requirement. (The audit email passes its own
     counted line instead.)

Every AI draft passes `is_grounded` before it ships: every number in it must
already appear in the material it was given. These are stats emails — a lede that
invents a number is worse than no lede, and the fallback is one line away. A
draft that trips the guard is dropped silently in favour of (2).

**Nothing here can stop an email going out.** Every entry point returns a string
or "" — no key, no `anthropic` package, an API error, a timeout, a refusal, an
over-long answer, or an unexpected exception anywhere in this module all end the
same way: the counted lede, or no lede at all, and the email sends exactly as it
did before this file existed.

Env:
  ANTHROPIC_API_KEY     enables the AI lede; absent (and no ANTHROPIC_AUTH_TOKEN)
                        means the counted lede and no network call at all.
  LOTG_SUMMARY_MODEL    override the model (default: claude-opus-5).

TURNING THE AI LEDE ON (one repo secret, no other setup):

  1. Create an API key at https://platform.claude.com/settings/keys and copy it
     (it is shown once). Any workspace works; spend is a few cents a month —
     two emails a week, a page of text each.
  2. In GitHub: the repo -> Settings -> Secrets and variables -> Actions ->
     "New repository secret". Name it exactly ANTHROPIC_API_KEY, paste the key,
     click "Add secret".
  3. Nothing else. `.github/workflows/build.yml` (digest) and
     `weekly_health_email.yml` (audit) already pass the secret through; with no
     secret present they pass an empty string and this module never dials out.

  To check it took: after the next run, `exports/raw/digest.log` /
  `exports/raw/audit_email.log` print the lede that shipped and, when the AI one
  was rejected, exactly why. To turn it back off, delete the secret.
"""
from __future__ import annotations

import html
import os
import re
from typing import List, Optional, Sequence, Tuple

# The cap is on SENTENCES, not words — a lede is allowed to be five short
# sentences or one long one, and a word budget quietly punishes the former. The
# word ceiling is only a runaway guard for a model that ignores the sentence cap.
_MAX_SENTENCES = 5
_MAX_WORDS = 150
# The deterministic lede quotes the digest's own sentences instead of writing
# its own, so it gets a tighter budget: a quoted line can be 30 words on its own.
_LEDE_MAX_WORDS = 70
_HEAD_MAX_WORDS = 32
# What we hand the model. A quiet week is a dozen lines; the busiest digest on
# record is under a hundred. The cap is a cost guard, not a filter we expect to
# bind — when it does bind, the prompt says so, so the model doesn't claim to
# have seen every line.
_MAX_LINES = 150
_MODEL = os.environ.get("LOTG_SUMMARY_MODEL", "claude-opus-5")
_TIMEOUT_S = 90.0

_LENGTH_RULE = f"""\
- At most {_MAX_SENTENCES} sentences, and fewer whenever fewer will do — one \
sentence is the right length for a quiet week. Length should track how much \
actually happened, not fill the allowance.
- Plain prose, no bullets, no heading, no markdown, no preamble like "Here is". \
Output only the paragraph itself."""

_GROUNDING_RULE = """\
- Every fact must come from the lines you are given. Do not use any number that \
does not appear there, do not compute new numbers, and do not name anything that \
is not named there."""

SYSTEM_DIGEST = f"""\
You write the opening paragraph of a fantasy-football league's weekly stats \
email. Below it sits the full list of every leaderboard move, which the reader \
can already see. Your job is to tell them which of those moves is worth caring \
about, so they know whether to read on.

Rules:
{_LENGTH_RULE}
{_GROUNDING_RULE}
- Lead with the single most notable item, then the shape of the rest. A 1st- or \
2nd-place move outranks a 5th-place one; a record or a milestone outranks a \
board shuffle; a stat people care about (points, O-Score, trades) outranks an \
obscure one.
- When a whole section moved for one obvious reason — dozens of draft-pick KTC \
values, say — say that as one clause rather than listing them.
- Write for the league members, not for an analyst. Name teams and players the \
way the lines do. No hype, no exclamation marks, no second-guessing the data."""

SYSTEM_AUDIT = f"""\
You write the opening paragraph of a weekly dataset-health email for the one \
person who maintains a fantasy-football stats pipeline. Below it sits the full \
audit: every finding, its detail lines, what upstream revised, and which weeks \
are missing injury captures. Your job is to tell the maintainer what needs a \
decision, so they know whether to open it now or after coffee.

Rules:
{_LENGTH_RULE}
{_GROUNDING_RULE}
- Lead with the thing most likely to be a real defect. A lost or renamed column, \
a build error, or a failing test outranks rows that moved; rows that moved for no \
stated reason outrank rows explained by an upstream revision or a merged code \
change; a missed injury week is the least urgent thing here.
- Say what moved and roughly how much, not every sheet by name. If many sheets \
moved for one stated reason, say the reason once.
- Do not diagnose, do not speculate about a cause the lines don't state, and do \
not recommend a fix. Do not reassure — if the findings are all explained, say \
so plainly and stop.
- Write to a peer who knows this pipeline. No hedging, no exclamation marks."""


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


def section_lines(sections: Sequence[Tuple[str, str, list]]) -> List[Tuple[str, List[str]]]:
    """(title, [sentence, ...]) per section — the email's own phrasing.

    Deliberately the rendered sentences and nothing else. The model never sees a
    frame, a rank map, or a raw value it would have to interpret, so the worst it
    can do is choose badly among true statements."""
    out = []
    for title, _verb, items in sections:
        lines = [i.sentence() for i in items if hasattr(i, "sentence")]
        if lines:
            out.append((title, lines))
    return out


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
    "o-score", "points", "avg points", "net points", "points added",
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
                 "sheet", "tied", "derived", "score")

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

    # A second line earns its place only by being about a different STAT, by not
    # already being covered by a block, and by being a stat rather than a
    # diagnostic — another KTC line above the sentence that says "59 KTC moves"
    # is the same fact told twice, and no lede should open on a column called
    # "Pick-adjusted Difference in KTC 4 years after draft day".
    for c in ranked[1:8]:
        if (c.score >= 0.4 * head.score and c.family != head.family
                and c.family not in block_fams
                and (not c.derived or head.derived)
                and len(c.sentence().split()) <= _HEAD_MAX_WORDS):
            parts.append(c.sentence())
            named.add(id(c))
            rest = [x for x in rest if id(x) != id(c)]
            break
    if len(big) == 1:
        fam, n, secs = big[0]
        lead = ("The rest of the week is one story: " if covered >= 0.7 * len(rest)
                else "Most of the rest is one story: ")
        parts.append(f"{lead}{n} {fam} moves across {_join(secs[:3])}.")
    elif big:
        parts.append("Most of the rest is "
                     + _join([f"{n} {fam} moves" for fam, n, _s in big]) + ".")

    leftover = len(rest) - covered
    if leftover and (not big or leftover >= max(3, int(0.1 * total))):
        where = _join(sorted({_short(c.section) for c in rest})[:3])
        parts.append(f"{leftover} other {'move' if leftover == 1 else 'moves'} "
                     f"across {where}.")

    # Ties are easy to miss in a list of near-identical lines, and a week that is
    # a third ties is a different week from one that is none.
    ties = sum(1 for c in cands if c.tied)
    if ties >= 3:
        parts.append(f"{ties} of the {total} were ties rather than overtakes.")

    return _fit(parts) or counted_summary(sections)


def _fit(parts: List[str]) -> str:
    """Join what fits, dropping whole sentences from the end — never cutting one
    mid-way, which would leave a half-stated fact in the email.

    Held to a tighter word budget than the AI lede: this one QUOTES the digest's
    own sentences rather than writing its own, and quoted sentences are long."""
    out: List[str] = []
    for p in parts:
        trial = out + [p]
        if len(trial) > _MAX_SENTENCES or len(" ".join(trial).split()) > _LEDE_MAX_WORDS:
            break
        out = trial
    return " ".join(out)


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A sentence ends at .!? followed by whitespace or the end of the text. "103.3"
# and "pick 2.04" don't match (the dot is followed by a digit), which is the
# whole reason for the lookahead.
_SENT_END = re.compile(r"[.!?][\"')\]]*(?:\s|$)")


def _numbers(text: str) -> set:
    """Numeric tokens, comma- and trailing-zero-normalised so "1,234" and "1234"
    and "1234.0" are the same number."""
    out = set()
    for raw in _NUM.findall(text or ""):
        v = raw.replace(",", "")
        if "." in v:
            v = v.rstrip("0").rstrip(".")
        out.add(v or "0")
    return out


def sentence_count(text: str) -> int:
    """Sentences in `text`, counting a trailing fragment with no terminator."""
    s = (text or "").strip()
    if not s:
        return 0
    ends = list(_SENT_END.finditer(s))
    trailing = 1 if (not ends or ends[-1].end() < len(s)) else 0
    return len(ends) + trailing


def is_grounded(summary: str, source: str) -> bool:
    """Every number in `summary` also appears in `source`.

    Ordinals ("2nd") and values ("103.3") both fall out of the same regex, so a
    draft that promotes a 5th-place move to "1st", or rounds a value, fails here
    rather than in someone's inbox. The counted line is stated in `source` for
    the same reason — the model is never asked to add anything up."""
    return _numbers(summary).issubset(_numbers(source))


def _acceptable(summary: str, source: str) -> bool:
    s = (summary or "").strip()
    if not s or sentence_count(s) > _MAX_SENTENCES or len(s.split()) > _MAX_WORDS:
        return False
    # A model that answered with a list, a heading, or a preamble did not follow
    # the brief; the counted lede is better than a half-followed one.
    if s.startswith(("#", "-", "*", "Here", "Summary")) or "\n\n" in s:
        return False
    return is_grounded(s, source)


# ---------------------------------------------------------------------------
# The AI lede
# ---------------------------------------------------------------------------
def _prompt(sections: Sequence[Tuple[str, str, list]], title: str,
            totals: str = "") -> str:
    blocks = [f"Email header: {title}", f"Totals: {totals}", ""]
    budget = _MAX_LINES
    for name, lines in section_lines(sections):
        shown = lines[:budget]
        blocks.append(f"## {name} ({len(lines)})")
        blocks += shown
        if len(shown) < len(lines):
            blocks.append(f"(+{len(lines) - len(shown)} more lines in this section, "
                          f"not shown — do not claim to have seen every line)")
        blocks.append("")
        budget -= len(shown)
        if budget <= 0:
            break
    return "\n".join(blocks)


def ai_summary(sections: Sequence[Tuple[str, str, list]], title: str,
               totals: str = "", system: str = SYSTEM_DIGEST,
               model: Optional[str] = None) -> Optional[str]:
    """Claude's lede, or None if it isn't available or isn't usable.

    Never raises: a missing package, a missing key, a network failure, a refusal
    and an ungrounded draft are all the same outcome to the caller — no lede,
    use the counted one."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
    except Exception:                             # noqa: BLE001 — absent or broken install
        return None
    source = _prompt(sections, title, totals)
    try:
        client = anthropic.Anthropic(timeout=_TIMEOUT_S)
        with client.messages.stream(
            model=model or _MODEL,
            max_tokens=2000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": source}],
        ) as stream:
            message = stream.get_final_message()
    except Exception as exc:                      # noqa: BLE001 — never fail the email
        print(f"[lede] AI summary unavailable ({type(exc).__name__}: {exc}) "
              f"— using the counted lede.")
        return None
    if getattr(message, "stop_reason", None) == "refusal":
        print("[lede] AI summary declined — using the counted lede.")
        return None
    text = " ".join(b.text for b in message.content
                    if getattr(b, "type", None) == "text").strip()
    if not _acceptable(text, source):
        print(f"[lede] AI summary rejected by the guards "
              f"({sentence_count(text)} sentence(s), {len(text.split())} words) "
              f"— using the counted lede.")
        return None
    # This string is interpolated straight into the email body. It is the only
    # part of either email we didn't write, so it gets escaped; an `&` or a `<`
    # in a model-written sentence would otherwise render as broken markup.
    return html.escape(text, quote=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_intro(sections: Sequence[Tuple[str, str, list]], title: str,
                fallback: Optional[str] = None, system: str = SYSTEM_DIGEST,
                use_ai: bool = True, model: Optional[str] = None) -> str:
    """The lede for this email: Claude's if it's available and grounded, the
    caller's counted line otherwise, "" when there is nothing to summarise.

    Cannot raise. The lede is a nicety on top of an email that has to go out
    either way, so an unexpected failure anywhere in here costs the lede and
    nothing else."""
    try:
        if not sections:
            return ""
        # The digest's own fallback reasons about the lines (see
        # `reasoned_summary`); the audit email passes its own counted line in.
        counted = (reasoned_summary(sections) or counted_summary(sections)
                   if fallback is None else fallback)
        if use_ai:
            # The deterministic read goes into the prompt as well as being the
            # fallback: its aggregates ("59 KTC moves", "16 of the 65") are
            # computed truths the model would otherwise have to work out, and
            # `is_grounded` refuses numbers that aren't in front of it.
            totals = counted_summary(sections)
            if counted and counted != totals:
                totals = f"{totals}\nA deterministic read of the same lines: {counted}"
            text = ai_summary(sections, title, totals, system=system, model=model)
            if text:
                return text
        return counted
    except Exception as exc:                      # noqa: BLE001 — never fail the email
        print(f"[lede] summary skipped ({type(exc).__name__}: {exc}).")
        return ""
