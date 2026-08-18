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
  2. **The caller's own counted line**, otherwise. Deterministic, offline, always
     true, never interesting.

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
        counted = counted_summary(sections) if fallback is None else fallback
        if use_ai:
            text = ai_summary(sections, title, counted, system=system, model=model)
            if text:
                return text
        return counted
    except Exception as exc:                      # noqa: BLE001 — never fail the email
        print(f"[lede] summary skipped ({type(exc).__name__}: {exc}).")
        return ""
