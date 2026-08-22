"""Phase 15: the digest lede — the paragraph above the wall of one-line facts.

The lede is computed, so it is tested for CONTENT: that it leads with the line a
reader would pick, folds the week's bulk into one clause, reports what is
surprising rather than what is merely numerous, and accounts for every move it
doesn't name. Also for the two properties that make it safe to run inside a
build — it cannot produce a wall (bounded on a 6,000-line week with pathological
labels), and it cannot stop an email.

The audit email's lede is tested in tests/test_send_audit_email.py, next to the
findings it reasons about.

Run: PYTHONPATH=src:lib python tests/test_email_summary.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import digest as D              # noqa: E402
from lotg_support import email_summary as DS      # noqa: E402


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
            _Item("2021 pick 4.07 (Josh Doctson) passes 2021 pick 4.06 for lowest KTC (0)."),
            _Item("startup pick 19.04 (Larry Fitzgerald) passes 2021 pick 4.07 for 2nd-lowest KTC (65)."),
        ]),
        ("All-time leaderboard moves — trades", "moved", [
            _Item("Oliverwkw's 2023-12-05 trade passes LWebs53's trade for highest O-Score (103.3)."),
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


def check_sentence_cap():
    """The cap is on sentences, not words — a lede may be five short ones or a
    couple of long ones, and length should track how much happened."""
    ok = _ok("five sentences is the limit",
             DS.sentence_count("One. Two. Three. Four. Five.") == 5)
    ok &= _ok("two is the floor", DS._MIN_SENTENCES == 2)
    # The whole reason for the lookahead in _SENT_END: these emails are full of
    # decimals and dotted pick numbers.
    ok &= _ok("decimals are not sentence ends",
              DS.sentence_count("Pick 2.04 took 1st at 103.3 all-time.") == 1)
    ok &= _ok("an unterminated fragment still counts",
              DS.sentence_count("no full stop here") == 1)
    ok &= _ok("nothing is zero sentences", DS.sentence_count("  ") == 0)
    return ok


def check_build_intro_always_returns_something():
    """The lede leads with a line rather than a count; `counted_summary` is the
    floor beneath it, not what ships. And it cannot raise — it runs inside a
    build that has to finish."""
    text = DS.build_intro(_sections(), "hdr")
    ok = _ok("a lede that leads with a line",
             text.startswith("Oliverwkw's 2023-12-05 trade"), text)
    ok &= _ok("an explicit fallback wins (the audit email's route)",
              DS.build_intro(_sections(), "hdr", fallback="mine.") == "mine.")
    ok &= _ok("nothing moved -> no lede", DS.build_intro([], "hdr") == "")
    ok &= _ok("inside the budget", len(text.split()) <= DS._LEDE_HARD_WORDS)
    ok &= _ok("a lede that blows up costs the lede and nothing else",
              DS.build_intro([object()], "hdr") == "")
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
    ok &= _ok("milestones render flat (no entity to group by)",
              [g for t, g, _ in every if t == "League milestones"] == [False])
    ok &= _ok("empty sections are dropped", D.digest_sections() == [])
    return ok


# ---------------------------------------------------------------------------
# The reasoned lede
# ---------------------------------------------------------------------------
class _Move:
    """Shaped like an EventCrossing — the attributes the scorer reads."""

    def __init__(self, label, column, rank, end="low", sheet="picks", tied=False):
        self.label, self.column, self.rank = label, column, rank
        self.end, self.sheet, self.tied = end, sheet, tied

    def sentence(self):
        w = "ties" if self.tied else "passes"
        return f"{self.label} {w} someone for {self.rank}-{self.end}est {self.column} (1)."

    def group(self):
        return self.label


def _week(n_ktc=20, extras=()):
    """A week that is mostly one stat family, plus whatever else is passed."""
    bulk = [_Move(f"pick {i}", "KTC at end of rookie year", 3, sheet="picks")
            for i in range(n_ktc)]
    return [("All-time leaderboard moves — draft picks", "moved", bulk + list(extras))]


def check_reasoned_leads_with_place_and_prominence():
    """First place and a stat the league argues about beat a 5th-place move on a
    diagnostic column, even when the diagnostic one is rarer. The diagnostic is
    still worth a mention, though — an all-time worst is an all-time worst."""
    secs = _week(extras=[_Move("A", "O-Score", 1),
                         _Move("B", "Pick-adjusted Difference in KTC", 1),
                         _Move("C", "O-Score", 5)])
    out = DS.reasoned_summary(secs)
    ok = _ok("leads with the prominent 1st-place line", out.startswith("A passes"), out)
    ok &= _ok("not the diagnostic column", not out.startswith("B "), out)
    ok &= _ok("not the 5th-place line", not out.startswith("C "), out)
    ok &= _ok("the diagnostic 1st place still gets named", "B passes" in out, out)
    return ok


def check_reasoned_numbers_close():
    """Every move is either named or counted. "59 KTC moves" under "16 of the 65"
    left six unaccounted for, which reads as an arithmetic mistake even when
    every figure in it is right."""
    import re
    secs = _week(n_ktc=20, extras=[_Move("A", "O-Score", 1),
                                   _Move("B", "Total FAAB bid", 1),
                                   _Move("C", "Points", 4),
                                   _Move("D", "Points", 5)])
    out = DS.reasoned_summary(secs)
    named = sum(1 for who in "ABCD" if f"{who} passes" in out)
    block = int(re.search(r"(\d+) KTC moves", out).group(1))
    spare = re.search(r"plus (\d+) other", out)
    spare_n = int(spare.group(1)) if spare else 0
    ok = _ok("the counts add up to every move",
             named + block + spare_n == 24, f"{named}+{block}+{spare_n} vs 24")
    ok &= _ok("and the leftover is stated, not implied", spare is not None, out)
    return ok


def check_reasoned_is_two_to_five_sentences():
    """One sentence reads as an accident rather than a summary; six is a wall."""
    ok = True
    for n, extras in ((6, [_Move("A", "O-Score", 1)]),
                      (40, [_Move("A", "O-Score", 1), _Move("B", "Points", 1)]),
                      (0, [_Move("A", "O-Score", 1), _Move("B", "Points", 2)])):
        out = DS.reasoned_summary(_week(n_ktc=n, extras=extras))
        c = DS.sentence_count(out)
        ok &= _ok(f"{n} bulk + {len(extras)} others -> {c} sentences",
                  DS._MIN_SENTENCES <= c <= DS._MAX_SENTENCES, out)
    single = DS.reasoned_summary(_week(n_ktc=0, extras=[_Move("A", "O-Score", 1)]))
    ok &= _ok("one move is allowed one sentence", DS.sentence_count(single) == 1, single)
    return ok


def check_runner_up_is_a_different_entity():
    """Two lines about the same trade is one line, printed twice."""
    secs = _week(n_ktc=6, extras=[_Move("SAME", "O-Score", 1),
                                  _Move("SAME", "Points", 1),
                                  _Move("OTHER", "Total FAAB bid", 1)])
    out = DS.reasoned_summary(secs)
    return _ok("the second line is someone else", out.count("SAME passes") == 1, out)


def check_reasoned_folds_the_bulk_into_one_clause():
    """The point of the whole thing: 20 lines that are one event get one clause,
    not 20 mentions — and the clause merges the sheets that event landed on."""
    secs = _week(extras=[_Move("A", "O-Score", 1)])
    secs.append(("All-time leaderboard moves — trades", "moved",
                 [_Move(f"t{i}", "KTC value of player added at end of season", 3,
                        sheet="trades") for i in range(9)]))
    out = DS.reasoned_summary(secs)
    ok = _ok("names the family once", out.count("KTC") == 1, out)
    ok &= _ok("counts the whole family across sheets", "29 KTC moves" in out, out)
    ok &= _ok("names the sheets it spans",
              "draft picks" in out and "trades" in out, out)
    ok &= _ok("no individual bulk line is quoted", "pick 0 " not in out, out)
    return ok


def check_reasoned_reports_surprise():
    """A lone move in the direction nothing else went is the one a reader could
    not have guessed, and it should outrank a same-place move in the crowd."""
    bulk = [_Move(f"p{i}", "Points", 2, end="low", sheet="picks") for i in range(12)]
    odd = _Move("ODD", "Points", 2, end="high", sheet="picks")
    out = DS.reasoned_summary([("All-time leaderboard moves — draft picks", "moved",
                               bulk + [odd])])
    return _ok("the against-the-grain move leads", out.startswith("ODD "), out)


def check_reasoned_flags_ties():
    secs = _week(n_ktc=6, extras=[_Move("A", "O-Score", 1),
                                  _Move("T1", "Points", 2, tied=True),
                                  _Move("T2", "Points", 2, tied=True),
                                  _Move("T3", "Points", 3, tied=True)])
    out = DS.reasoned_summary(secs)
    ok = _ok("a week with several ties says so", "3 of the 10 were ties" in out, out)
    quiet = DS.reasoned_summary(_week(n_ktc=6, extras=[_Move("A", "O-Score", 1)]))
    ok &= _ok("a week with none doesn't", "ties" not in quiet, quiet)
    return ok


def check_reasoned_survives_a_huge_week():
    """The whole design constraint: a 6,000-line week with pathological labels
    must still produce a paragraph, not a wall — and must not take a coffee
    break doing it."""
    import time
    label = "Oliverwkw's 2024-08-06 trade for " + ", ".join(f"Player {i}" for i in range(8))
    items = [_Move(label, ["KTC at end of rookie year", "O-Score", "Points"][i % 3],
                   (i % 5) + 1, end="high" if i % 2 else "low",
                   sheet=["picks", "trades", "add_drops"][i % 3], tied=i % 7 == 0)
             for i in range(6000)]
    secs = [("All-time leaderboard moves — trades", "moved", items)]
    t0 = time.time()
    out = DS.reasoned_summary(secs)
    elapsed = time.time() - t0
    ok = _ok("still a paragraph", 0 < DS.sentence_count(out) <= DS._MAX_SENTENCES,
             f"{DS.sentence_count(out)} sentences")
    ok &= _ok("inside the word budget", len(out.split()) <= DS._LEDE_MAX_WORDS,
              f"{len(out.split())} words")
    ok &= _ok("fast enough to sit in a build", elapsed < 2.0, f"{elapsed*1000:.0f} ms")
    return ok


def check_reasoned_never_returns_a_wall():
    """A line too long to quote can't be the lede. It yields to one that fits,
    and if nothing fits the counted line ships instead."""
    long_label = " ".join(["word"] * 200)
    secs = [("All-time leaderboard moves — trades", "moved",
             [_Move(long_label, "O-Score", 1), _Move("short", "Points", 2)])]
    out = DS.reasoned_summary(secs)
    ok = _ok("the unquotable line yields", out.startswith("short "), out[:80])
    only = [("All-time leaderboard moves — trades", "moved",
             [_Move(long_label, "O-Score", 1), _Move(long_label, "Points", 2)])]
    fell_back = DS.reasoned_summary(only)
    ok &= _ok("nothing quotable -> the counted line",
              fell_back.startswith("2 leaderboard moves"), fell_back[:80])
    ok &= _ok("and it is still short", len(fell_back.split()) <= DS._LEDE_MAX_WORDS)
    return ok


def check_reasoned_is_the_default_fallback():
    import os
    prev = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        secs = _week(extras=[_Move("A", "O-Score", 1)])
        out = DS.build_intro(secs, "hdr")
        ok = _ok("build_intro ships the reasoned lede, not the counts",
                 out.startswith("A passes"), out)
        ok &= _ok("an explicit fallback still wins (the audit email's)",
                  DS.build_intro(secs, "hdr", fallback="mine.") == "mine.")
    finally:
        if prev is not None:
            os.environ["ANTHROPIC_API_KEY"] = prev
    return ok


def check_column_family():
    """Qualifiers are what make one stat look like five."""
    cases = {
        "KTC at end of rookie year": "KTC",
        "KTC 1 year after draft day": "KTC",
        "KTC value of player added at end of season": "KTC",
        "O-Score": "O-Score",
        "Number of trades": "Number of trades",
        "Avg points added adjusted by position": "Avg points added",
        "Win % vs Oliverwkw": "Win %",
    }
    ok = True
    for col, want in cases.items():
        ok &= _ok(f"{col!r} -> {want!r}", DS._column_family(col) == want,
                  DS._column_family(col))
    return ok


def check_a_single_finding_lede_does_not_echo_it():
    """The lede RANKS findings. With one finding there is nothing to rank.

    Opening by restating the top finding says "read this one first", which earns
    a sentence when there are ten. With exactly one it is a verbatim echo of the
    bullet immediately below it — and when that finding is the NFLverse drift
    line, the same sentence appears a third time under the NFLverse header. It
    never showed while a bad week carried ten findings; the week the noise was
    cleared, it was the whole email.
    """
    drift_text = ("NFLverse made 27571 value(s) across 15476 row(s). "
                  "Significant: a completed season's production changed")
    one = [{"section": "NFLverse upstream drift", "text": drift_text, "details": []}]
    lede = DS.audit_lede(one, {}, None, 0)
    ok = _ok("a single finding is not echoed back",
             drift_text not in lede, repr(lede))
    ok &= _ok("and with nothing else to add there is no lede at all",
              lede == "", repr(lede))

    # Two findings: naming the one to open first is the lede doing its job.
    two = one + [{"section": "Part 1", "text": "player_year: 40 changed row(s)",
                  "details": ["    - columns that moved: Points (40)"]}]
    lede2 = DS.audit_lede(two, {}, None, 0)
    ok &= _ok("with two findings the ranking sentence returns", bool(lede2), repr(lede2))
    ok &= _ok("and names one of them",
              "player_year" in lede2 or "NFLverse" in lede2, repr(lede2))
    return ok


def check_a_single_finding_still_gets_what_it_does_not_say():
    """Dropping the echo must not drop the ANALYSIS. Breadth and swing shape are
    computed from the audit's detail lines, not restated from them, so a lone
    finding that hides a blank value still says so."""
    one = [{"section": "Part 1", "text": "player_year: 40 changed row(s) moved",
            "details": ["    - columns that moved: Points (40)",
                        "    - changed: Player=X | Year=2024 — Points: 120.4 → "]}]
    lede = DS.audit_lede(one, {}, None, 0)
    ok = _ok("the lone finding's own text is not echoed",
             "40 changed row(s) moved" not in lede, repr(lede))
    ok &= _ok("but the lede still reports what it found",
              bool(lede) and ("blank" in lede or "column" in lede), repr(lede))
    return ok


def run_all() -> bool:
    tests = [
        check_counted_summary_names_the_sections,
        check_counted_summary_condenses_many_sections,
        check_sentence_cap,
        check_column_family,
        check_reasoned_leads_with_place_and_prominence,
        check_reasoned_numbers_close,
        check_reasoned_is_two_to_five_sentences,
        check_runner_up_is_a_different_entity,
        check_reasoned_folds_the_bulk_into_one_clause,
        check_reasoned_reports_surprise,
        check_reasoned_flags_ties,
        check_reasoned_survives_a_huge_week,
        check_reasoned_never_returns_a_wall,
        check_reasoned_is_the_default_fallback,
        check_build_intro_always_returns_something,
        check_lede_renders_above_the_list,
        check_sections_cover_the_whole_email,
        check_a_single_finding_lede_does_not_echo_it,
        check_a_single_finding_still_gets_what_it_does_not_say,
    ]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_email_summary():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
