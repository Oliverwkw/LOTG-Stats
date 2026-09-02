"""Top team ranks on FULL-FY tenure until the player has actually PLAYED a week.

The build keeps two tenure ledgers per (player, fantasy year): full-FY, spanning
championship Monday to championship Monday, and in-season, `[Sept 1 FY, Feb 1
FY+1]`. Top team ranks on the in-season one — correctly, once there is a season
to rank on. The switch between them used to be a bare `or` on two dicts, with no
floor on the in-season side, so the instant that window opened on Sept 1 with ANY
time in it the full-FY ledger was discarded whole:

  * on 2026-09-02, the team that had held Mason Taylor for 1.8 of 248 days
    became his 2026 "Top Team" on ~42 hours of in-season tenure;
  * 25 player_year rows flipped in a single day, every one of them a 2026 row —
    a season with no games played yet — and every one "earlier owner -> current
    owner";
  * four all-time races that were within ONE DAY of each other (Tyreek Hill 306
    vs 307 in-season days, Jaylen Waddle 306/307, Adonai Mitchell and Ben
    Sinnott 153/154) were settled by the window opening.

So the in-season ledger is used only for a (player, year) with a played week:
rostered, and not out for injury, suspension or a bye — the build's own
`_played` predicate. A player rostered through August and dropped before kickoff
never has one, and full-FY ownership is the only fact about his year that exists.

Run: PYTHONPATH=src:lib python tests/test_top_team_played_week.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

_SRC = (_ROOT / "src" / "lotg.py").read_text()


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond or not detail else f" — {detail}"))
    return bool(cond)


def _rank(inseason, full_fy, has_played):
    """The build's choice, as the three call sites express it."""
    ledger = inseason
    if inseason and not has_played:
        ledger = full_fy or inseason
    if not ledger:
        return None
    return max(ledger.items(), key=lambda kv: kv[1])[0]


DAY = 86400.0


def check_the_september_case():
    """Mason Taylor, 2026, as the 09-02 rebuild had him."""
    full = {"shmuel256": 125.0 * DAY, "Oliverwkw": 121.0 * DAY, "plehv79": 1.8 * DAY}
    ins = {"plehv79": 42.4 * 3600}
    ok = _ok("no played week -> ranks on full FY", _rank(ins, full, False) == "shmuel256",
             _rank(ins, full, False))
    ok &= _ok("...and NOT on 42 hours of in-season time", _rank(ins, full, False) != "plehv79")
    ok &= _ok("once he plays -> ranks on the season", _rank(ins, full, True) == "plehv79",
              _rank(ins, full, True))
    return ok


def check_completed_season_is_untouched():
    """A real season: in-season time is what Top team has always meant, and a
    player who played must still rank on it even when full-FY disagrees."""
    full = {"A": 300 * DAY, "B": 65 * DAY}      # B acquired late in the offseason
    ins = {"A": 20 * DAY, "B": 130 * DAY}       # ...and held him all season
    return _ok("played season ranks on in-season, not full FY",
               _rank(ins, full, True) == "B", _rank(ins, full, True))


def check_rostered_but_dropped_before_kickoff():
    """No played week, so the whole fantasy year is the only evidence."""
    full = {"A": 200 * DAY, "B": 20 * DAY}
    ins = {"B": 6 * DAY}                        # B held him into September, then cut him
    return _ok("dropped before he played -> full-FY owner wins",
               _rank(ins, full, False) == "A", _rank(ins, full, False))


def check_single_team_year_cannot_move():
    """52 of the 70 historical rows this rule reaches are one-team years."""
    full, ins = {"A": 200 * DAY}, {"A": 10 * DAY}
    return _ok("one team -> same answer either way",
               _rank(ins, full, False) == _rank(ins, full, True) == "A")


def check_no_in_season_tenure_still_falls_through():
    """Preserving the old key set matters: a (pid, fy) with no in-season tenure
    got no entry and fell back to the player_week-derived top team. The rule
    must not start inventing entries for those."""
    return _ok("empty in-season ledger -> no ranking at all", _rank({}, {"A": 5 * DAY}, False) is None)


def check_the_rule_is_applied_at_every_site():
    """Three consumers read the ledgers: the per-FY map (pw-derived rows), the
    pad path (the live season's ONLY path), and the all-time accumulation."""
    ok = _ok("predicate exists", "def _has_played_week(" in _SRC)
    ok &= _ok("built from the rostered/injury/suspension/bye flags",
              all(f in _SRC.split("_played_pid_years")[1][:900]
                  for f in ('"Injury?"', '"Suspension?"', '"Bye?"')))
    ok &= _ok("unknown -> falls back to the previous behaviour",
              re.search(r"if _played_pid_years is None:\s*\n\s*return True", _SRC) is not None)
    n = _SRC.count("_has_played_week(")
    ok &= _ok("applied at all three call sites (+1 def)", n == 4, f"count={n}")
    ok &= _ok("the bare `or` no longer decides it alone",
              "if not _has_played_week(str(sid), int(yr)):" in _SRC)
    ok &= _ok("all-time in-season ledger is gated too",
              re.search(r"if _has_played_week\(_pid, _fy\):\s*\n\s*tenure_inseason_time_team_all",
                        _SRC) is not None)
    return ok


def check_last_team_is_left_alone():
    """`Last team` reads the latest in-season ownership EVENT, so "current
    owner" is its right answer and it is not part of this change."""
    ok = _ok("last-event map still keyed off the in-season window only",
             "tenure_last_event_fy[(_pid, _fy)] = (_is_ovl_e, str(tm))" in _SRC)
    ok &= _ok("no played-week gate was added to it",
              "_has_played_week" not in _SRC.split("tenure_last_event_fy[(_pid, _fy)]")[1][:400])
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_the_september_case,
              check_completed_season_is_untouched,
              check_rostered_but_dropped_before_kickoff,
              check_single_team_year_cannot_move,
              check_no_in_season_tenure_still_falls_through,
              check_the_rule_is_applied_at_every_site,
              check_last_team_is_left_alone):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_top_team_played_week():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
