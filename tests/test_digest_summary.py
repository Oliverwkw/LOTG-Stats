"""Phase 15: the digest lede — the paragraph above the wall of one-line facts.

Covers the two ways it gets written and, mostly, the guard between them: an AI
draft only ships if every number in it already appeared in the material it was
given. The AI path is exercised against a stub client (no network, no key), so
the request shape and the response handling are tested here rather than
discovered in production. The deterministic path is tested for content, not just
for existing — it is what the league actually reads whenever the key is unset.

Run: PYTHONPATH=src:lib python tests/test_digest_summary.py
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import digest as D              # noqa: E402
from lotg_support import digest_summary as DS     # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


@dataclass
class _Item:
    """Stands in for any digest item; they all expose sentence()/group()/detail()."""
    text: str
    who: str = "Somebody"

    def sentence(self) -> str:
        return self.text

    def group(self) -> str:
        return self.who

    def detail(self) -> str:
        return self.text


def _sections():
    return [
        ("All-time leaderboard moves — draft picks", "moved", [
            _Item("2021 pick 4.07 (Josh Doctson) passes 2021 pick 4.06 for 1st-lowest KTC (0)."),
            _Item("startup pick 19.04 (Larry Fitzgerald) passes 2021 pick 4.07 for 2nd-lowest KTC (65)."),
        ]),
        ("All-time leaderboard moves — trades", "moved", [
            _Item("Oliverwkw's 2023-12-05 trade passes LWebs53's trade for 1st-highest O-Score (103.3)."),
        ]),
    ]


# ---------------------------------------------------------------------------
def check_counted_summary_names_the_sections():
    """No key configured is the DEFAULT state, so this text is what ships until
    a secret exists. It has to stand on its own."""
    text = DS.counted_summary(_sections())
    ok = _ok("counts every move", text.startswith("3 leaderboard moves this week"), text)
    ok &= _ok("names the sections", "2 on draft picks" in text and "1 on trades" in text, text)
    ok &= _ok("one sentence", text.count(".") == 1, text)
    ok &= _ok("nothing moved -> no lede", DS.counted_summary([]) == "")
    return ok


def check_counted_summary_condenses_many_sections():
    """With nine board sections a full list stops being a sentence; the three
    biggest plus a count of the rest is the readable form."""
    secs = [(f"All-time leaderboard moves — sheet {i}", "moved",
             [_Item("x")] * (10 - i)) for i in range(6)]
    text = DS.counted_summary(secs)
    ok = _ok("leads with the biggest", "10 on sheet 0" in text, text)
    ok &= _ok("condenses the tail", "and 3 more sections" in text, text)
    ok &= _ok("no plural typo", "section(s)" not in text, text)
    four = DS.counted_summary(secs[:4])
    ok &= _ok("four sections are all named", "more sections" not in four
              and four.count(" on sheet ") == 4, four)
    return ok


def check_grounding_guard():
    """The reason the guard exists: this is a stats email, and a lede that
    invents a number is worse than no lede at all."""
    src = "passes for 1st-highest O-Score (103.3). 2nd-lowest KTC (65)."
    ok = _ok("faithful numbers pass",
             DS.is_grounded("A trade took 1st-highest O-Score at 103.3.", src))
    ok &= _ok("a promoted rank fails", not DS.is_grounded("took 3rd place", src))
    ok &= _ok("a rounded value fails", not DS.is_grounded("O-Score of 103", src))
    ok &= _ok("a fabricated count fails", not DS.is_grounded("all 42 picks moved", src))
    ok &= _ok("no numbers at all is fine", DS.is_grounded("Trades reshuffled the top.", src))
    ok &= _ok("commas and trailing zeros normalise",
              DS.is_grounded("1,234 and 103.30", "1234 points, 103.3 O-Score"))
    return ok


def check_shape_guard():
    src = DS._prompt(_sections(), "hdr")
    ok = _ok("a clean draft is accepted",
             DS._acceptable("Trades reshuffled the all-time top.", src))
    ok &= _ok("empty is rejected", not DS._acceptable("   ", src))
    ok &= _ok("a preamble is rejected",
              not DS._acceptable("Here is your summary: trades moved.", src))
    ok &= _ok("a bullet list is rejected", not DS._acceptable("- trades moved", src))
    ok &= _ok("a second digest is rejected",
              not DS._acceptable(" ".join(["word"] * (DS._MAX_WORDS + 1)), src))
    return ok


def check_prompt_carries_the_lines_and_admits_truncation():
    src = DS._prompt(_sections(), "LOTG weekly digest — 2026 season, week 7")
    ok = _ok("carries the header", "week 7" in src)
    ok &= _ok("carries the counts", "3 leaderboard moves" in src, )
    ok &= _ok("carries the digest's own sentences", "Josh Doctson" in src and "103.3" in src)
    ok &= _ok("labels each section with its size", "draft picks (2)" in src)

    big = [("All-time leaderboard moves — draft picks", "moved",
            [_Item(f"line {i}") for i in range(DS._MAX_LINES + 25)])]
    trunc = DS._prompt(big, "hdr")
    ok &= _ok("a huge week is capped", trunc.count("\nline ") <= DS._MAX_LINES)
    ok &= _ok("and the model is told it was capped",
              "not shown — do not claim to have seen every move" in trunc)
    return ok


# ---------------------------------------------------------------------------
# The AI path, against a stub client — no key, no network.
# ---------------------------------------------------------------------------
class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Msg:
    def __init__(self, text, stop_reason="end_turn"):
        self.content, self.stop_reason = [_Block(text)], stop_reason


class _Stream:
    def __init__(self, msg):
        self._msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        if isinstance(self._msg, Exception):
            raise self._msg
        return self._msg


def _stub_anthropic(monkey_result, captured: dict):
    """A module object shaped like `anthropic` for the one call we make."""
    mod = types.ModuleType("anthropic")

    class _Messages:
        def stream(self, **kw):
            captured.update(kw)
            return _Stream(monkey_result)

    class _Client:
        def __init__(self, **kw):
            captured["client_kwargs"] = kw
            self.messages = _Messages()

    mod.Anthropic = _Client
    return mod


def _run_ai(result, env_key="sk-test"):
    import os
    captured: dict = {}
    prev_mod, prev_key = sys.modules.get("anthropic"), os.environ.get("ANTHROPIC_API_KEY")
    sys.modules["anthropic"] = _stub_anthropic(result, captured)
    if env_key:
        os.environ["ANTHROPIC_API_KEY"] = env_key
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        return DS.ai_summary(_sections(), "LOTG weekly digest — 2026 season, week 7"), captured
    finally:
        if prev_mod is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = prev_mod
        if prev_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = prev_key


def check_ai_request_shape():
    """Pins the request the build actually sends: a current model, adaptive
    thinking, and streaming (a non-streaming call at this max_tokens is what
    trips SDK HTTP timeouts)."""
    good = "Oliverwkw's trade took 1st-highest O-Score at 103.3; the draft-pick board reshuffled below it."
    text, kw = _run_ai(_Msg(good))
    ok = _ok("a grounded draft ships", text == good, text)
    ok &= _ok("model is a current one", kw.get("model") == "claude-opus-5", kw.get("model"))
    ok &= _ok("adaptive thinking", kw.get("thinking") == {"type": "adaptive"}, kw.get("thinking"))
    ok &= _ok("no budget_tokens (400s on this model)",
              "budget_tokens" not in str(kw.get("thinking")))
    ok &= _ok("no sampling params (400 on this model)",
              not {"temperature", "top_p", "top_k"} & set(kw))
    ok &= _ok("the user turn is the digest's own lines",
              "Josh Doctson" in kw["messages"][0]["content"])
    ok &= _ok("a system prompt is set", bool(kw.get("system")))
    ok &= _ok("a timeout is set", kw.get("client_kwargs", {}).get("timeout"))
    # The lede is the one part of the email we didn't write, and it is
    # interpolated raw into the HTML body.
    esc, _ = _run_ai(_Msg("Trades & picks moved; <b> is not markup."))
    ok &= _ok("model output is HTML-escaped",
              "&amp;" in esc and "&lt;b&gt;" in esc, esc)
    return ok


def check_ai_failures_all_fall_back():
    """Every way the call can go wrong is the same outcome to the caller: no
    lede, use the counts. None of them may raise — this runs inside the build."""
    ok = _ok("an ungrounded draft is dropped",
             _run_ai(_Msg("Trades set a new record of 999 points."))[0] is None)
    ok &= _ok("a refusal is dropped",
              _run_ai(_Msg("...", stop_reason="refusal"))[0] is None)
    ok &= _ok("an API error is dropped",
              _run_ai(RuntimeError("connection reset"))[0] is None)
    ok &= _ok("no key means no call at all",
              _run_ai(_Msg("anything"), env_key=None)[0] is None)
    return ok


def check_build_intro_always_returns_something():
    import os
    prev = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        text = DS.build_intro(_sections(), "hdr")
        ok = _ok("no key -> the counted lede", text.startswith("3 leaderboard moves"), text)
        ok &= _ok("--no-ai-summary -> the counted lede",
                  DS.build_intro(_sections(), "hdr", use_ai=False).startswith("3 leaderboard"))
        ok &= _ok("nothing moved -> no lede", DS.build_intro([], "hdr") == "")
    finally:
        if prev is not None:
            os.environ["ANTHROPIC_API_KEY"] = prev
    return ok


def check_lede_renders_above_the_list():
    """The lede has to reach the email, and it has to sit above the sections —
    a summary below the wall it summarises is worthless."""
    crossing = D.Crossing(section="players", column="PF", end="high", rank=1,
                          mover="A", passed="B", value=10.0)
    html = D.render_digest_html([crossing], [], {"season": 2026, "weeks_completed": 7},
                                intro="Three trades reshuffled the all-time top.")
    ok = _ok("the lede is in the email", "Three trades reshuffled" in html)
    ok &= _ok("above the first section",
              html.index("Three trades") < html.index("<h2"), )
    ok &= _ok("below the header", html.index("<h1") < html.index("Three trades"))
    plain = D.render_digest_html([crossing], [], {"season": 2026, "weeks_completed": 7})
    ok &= _ok("no lede -> no empty paragraph", "<p" not in plain)
    return ok


def check_sections_cover_the_whole_email():
    """digest_sections is the single declaration of the digest's shape — if the
    email grows a section the lede doesn't see, the lede quietly stops being a
    summary. Everything the renderer draws must come from here."""
    body = D.render_digest_html.__code__.co_consts
    ok = _ok("the renderer builds only from digest_sections",
             "digest_sections" in D.render_digest_html.__code__.co_names,
             str(D.render_digest_html.__code__.co_names))
    every = D.digest_sections(
        crossings=[D.Crossing("players", "PF", "high", 1, "A", "B", 10.0),
                   D.Crossing("teams", "PF", "high", 1, "T", "U", 10.0)],
        milestones=[D.Milestone("PF", 50000.0, 50000.0)],
    )
    titles = [t for t, _v, _i in every]
    ok &= _ok("players and teams are separate sections", len(titles) == 3, titles)
    ok &= _ok("milestones render flat (no group())",
              [v for t, v, _ in every if t == "League milestones"] == [""])
    ok &= _ok("empty sections are dropped", D.digest_sections() == [])
    return ok


def run_all() -> bool:
    tests = [
        check_counted_summary_names_the_sections,
        check_counted_summary_condenses_many_sections,
        check_grounding_guard,
        check_shape_guard,
        check_prompt_carries_the_lines_and_admits_truncation,
        check_ai_request_shape,
        check_ai_failures_all_fall_back,
        check_build_intro_always_returns_something,
        check_lede_renders_above_the_list,
        check_sections_cover_the_whole_email,
    ]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_digest_summary():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
