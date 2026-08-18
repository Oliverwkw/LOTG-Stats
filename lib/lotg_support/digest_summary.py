"""Phase 15 — the one-paragraph lede at the top of the weekly digest.

The digest is a wall of one-line facts: 68 of them in a recent week, spread over
nine board sections. Nobody reads a wall. This writes the two or three sentences
that go above it — what actually happened this week, before the list.

Two ways to write it, tried in order:

  1. **Claude** (`ANTHROPIC_API_KEY` set). The model is handed the digest's own
     already-computed sentences — never the raw frames, never a number it has to
     work out — and asked which of them matter. That is the judgment the counts
     can't make: one 1st-place overtake outweighs thirty 5th-place shuffles, and
     only a reader can tell which is which.
  2. **The counts** (`counted_summary`). Deterministic, offline, always right,
     never interesting. Used whenever (1) is unavailable or unconvincing.

Every AI draft passes `is_grounded` before it ships: every number in it must
already appear in the material it was given. This is a stats email — a lede that
invents a number is worse than no lede, and the fallback is one line away. A
draft that trips the guard is dropped silently in favour of (2).

The whole module is a safe no-op, matching `send_digest.py` / `send_audit_email.py`:
no key, no `anthropic` package, an API error, a timeout, a refusal, a too-long
answer — all return the counted lede and the digest builds exactly as before.
Nothing here can fail the build.

Env:
  ANTHROPIC_API_KEY     enables the AI lede; absent (and no ANTHROPIC_AUTH_TOKEN)
                        means the counted lede and no network call at all.
  LOTG_SUMMARY_MODEL    override the model (default: claude-opus-5).
"""
from __future__ import annotations

import html
import os
import re
from typing import List, Optional, Sequence, Tuple

# A lede, not a second digest. Longer than this and it stops being the thing you
# read instead of the list.
_MAX_WORDS = 80
# What we hand the model. A quiet week is a dozen lines; the busiest on record is
# under a hundred. The cap is a cost guard, not a filter we expect to bind — when
# it does bind, the prompt says so, so the model doesn't claim to have seen all.
_MAX_LINES = 150
_MODEL = os.environ.get("LOTG_SUMMARY_MODEL", "claude-opus-5")
_TIMEOUT_S = 90.0

_SYSTEM = """\
You write the opening paragraph of a fantasy-football league's weekly stats \
email. Below it sits the full list of every leaderboard move, which the reader \
can already see. Your job is to tell them which of those moves is worth caring \
about, so they know whether to read on.

Rules:
- 2-3 sentences, under 60 words. Plain prose, no bullets, no heading, no \
markdown, no preamble like "Here is". Output only the paragraph itself.
- Every fact must come from the lines you are given. Do not use any number that \
does not appear there, do not compute new numbers, and do not name anyone who is \
not named there.
- Lead with the single most notable item, then the shape of the rest. A 1st- or \
2nd-place move outranks a 5th-place one; a record or a milestone outranks a \
board shuffle; a stat people care about (points, O-Score, trades) outranks an \
obscure one.
- When a whole section moved for one obvious reason — dozens of draft-pick KTC \
values, say — say that as one clause rather than listing them.
- Write for the league members, not for an analyst. Name teams and players the \
way the lines do. No hype, no exclamation marks, no second-guessing the data."""


# ---------------------------------------------------------------------------
# The material
# ---------------------------------------------------------------------------
def section_lines(sections: Sequence[Tuple[str, str, list]]) -> List[Tuple[str, List[str]]]:
    """(title, [sentence, ...]) per section — the digest's own phrasing.

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
    """The deterministic lede: how much moved, and where.

    Says nothing about which move mattered — it can't know — but it is always
    available and always true, which is the whole point of having it."""
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
# The grounding guard
# ---------------------------------------------------------------------------
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


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


def is_grounded(summary: str, source: str) -> bool:
    """Every number in `summary` also appears in `source`.

    Ordinals ("2nd") and values ("103.3") both fall out of the same regex, so a
    draft that promotes a 5th-place move to "1st", or rounds a value, fails here
    rather than in someone's inbox. Section counts are stated in `source` for the
    same reason — the model is never asked to add anything up."""
    return _numbers(summary).issubset(_numbers(source))


def _acceptable(summary: str, source: str) -> bool:
    s = (summary or "").strip()
    if not s or len(s.split()) > _MAX_WORDS:
        return False
    # A model that answered with a list, a heading, or a preamble did not follow
    # the brief; the counted lede is better than a half-followed one.
    if s.startswith(("#", "-", "*", "Here", "Summary")) or "\n\n" in s:
        return False
    return is_grounded(s, source)


# ---------------------------------------------------------------------------
# The AI lede
# ---------------------------------------------------------------------------
def _prompt(sections: Sequence[Tuple[str, str, list]], title: str) -> str:
    blocks = [f"Email header: {title}", f"Totals: {counted_summary(sections)}", ""]
    budget = _MAX_LINES
    for name, lines in section_lines(sections):
        shown = lines[:budget]
        blocks.append(f"## {name} ({len(lines)})")
        blocks += shown
        if len(shown) < len(lines):
            blocks.append(f"(+{len(lines) - len(shown)} more lines in this section, "
                          f"not shown — do not claim to have seen every move)")
        blocks.append("")
        budget -= len(shown)
        if budget <= 0:
            break
    return "\n".join(blocks)


def ai_summary(sections: Sequence[Tuple[str, str, list]], title: str,
               model: Optional[str] = None) -> Optional[str]:
    """Claude's lede, or None if it isn't available or isn't usable.

    Never raises: a missing package, a missing key, a network failure, a refusal
    and an ungrounded draft are all the same outcome to the caller — no lede,
    use the counted one."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    source = _prompt(sections, title)
    try:
        client = anthropic.Anthropic(timeout=_TIMEOUT_S)
        with client.messages.stream(
            model=model or _MODEL,
            max_tokens=2000,
            system=_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": source}],
        ) as stream:
            message = stream.get_final_message()
    except Exception as exc:                      # noqa: BLE001 — never fail the build
        print(f"[digest] AI summary unavailable ({type(exc).__name__}: {exc}) "
              f"— using the counted lede.")
        return None
    if getattr(message, "stop_reason", None) == "refusal":
        print("[digest] AI summary declined — using the counted lede.")
        return None
    text = " ".join(b.text for b in message.content
                    if getattr(b, "type", None) == "text").strip()
    if not _acceptable(text, source):
        print(f"[digest] AI summary rejected by the grounding guard "
              f"({len(text.split())} words) — using the counted lede.")
        return None
    # This string is interpolated straight into the email body. It is the only
    # part of the digest we didn't write, so it gets escaped; an `&` or a `<` in
    # a model-written sentence would otherwise render as broken markup.
    return html.escape(text, quote=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_intro(sections: Sequence[Tuple[str, str, list]], title: str,
                use_ai: bool = True, model: Optional[str] = None) -> str:
    """The lede for this week's digest: Claude's if it's available and grounded,
    the counts otherwise, "" when nothing moved (the digest is empty and won't
    be sent anyway)."""
    if not sections:
        return ""
    if use_ai:
        text = ai_summary(sections, title, model=model)
        if text:
            return text
    return counted_summary(sections)
