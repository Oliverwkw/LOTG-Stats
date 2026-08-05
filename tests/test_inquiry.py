"""Inquiry layer: sheet loading, column search, filters, snapshot access.

Guards the primitives that ad-hoc league questions are answered from, including
the traps they exist to absorb: the +5 semifinal bonus baked into `team_week.PF`
but not into Sleeper's raw points, the current-only player dictionary (positions
drift), the 2020 exports that have no snapshot behind them, and team names whose
case differs between Sleeper and the built sheets.

Pure-logic checks run anywhere; the ones that need the committed data SKIP
cleanly when `exports/` is absent.

Run: python tests/test_inquiry.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "team_week.csv").exists()
_HAVE_SNAPSHOT = (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_sheet_name_aliases():
    assert Q.sheet_name("player_week") == "player_week"
    assert Q.sheet_name("Player-Week") == "player_week"
    assert Q.sheet_name("PW") == "player_week"
    assert Q.sheet_name(" team all time ") == "team_all_time"
    try:
        Q.sheet_name("nope")
    except KeyError as exc:
        assert "unknown sheet" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown sheet should raise")


def test_to_number_handles_build_cells():
    assert Q.to_number("75%") == 75.0
    assert Q.to_number("1,234.5") == 1234.5
    assert Q.to_number("") is None
    assert Q.to_number("34-20") is None  # a record, not a number
    assert Q.to_number("12.5") == 12.5


def test_predicate_parsing_and_matching():
    pred = Q.parse_predicate("Points>200")
    assert (pred.column, pred.op, pred.value) == ("Points", ">", "200")
    assert pred.matches("250.4") and not pred.matches("199")
    # A blank or non-numeric cell never satisfies an ordering comparison.
    assert not pred.matches("") and not pred.matches("n/a")

    assert Q.parse_predicate("Year = 2025").matches("2025")
    assert Q.parse_predicate("Team=shmuel256").matches("SHMUEL256")  # case-insensitive
    assert Q.parse_predicate("Win?=true").matches("TRUE")
    assert Q.parse_predicate("Win?=true").matches("1")
    assert Q.parse_predicate("Player~^lamar").matches("Lamar Jackson")
    assert not Q.parse_predicate("Player~^lamar").matches("Josh Allen")


def test_filter_rows_is_conjunctive_and_names_near_misses():
    df = pd.DataFrame({"Year": ["2024", "2025", "2025"],
                       "Team": ["a", "b", "c"], "PF": ["100", "250", "80"]})
    got = Q.filter_rows(df, "Year=2025", "PF>90")
    assert list(got["Team"]) == ["b"]
    assert len(Q.filter_rows(df)) == 3
    try:
        Q.filter_rows(df, "Yer=2025")
    except KeyError as exc:
        assert "Year" in str(exc)  # suggests the near miss
    else:  # pragma: no cover
        raise AssertionError("unknown column should raise")


def test_season_meta_shape_is_read_not_hardcoded():
    if not _HAVE_SNAPSHOT:
        return _skip("no snapshot")
    m2021, m2024, m2026 = Q.season_meta(2021), Q.season_meta(2024), Q.season_meta(2026)
    # One flex in 2021, two from 2024 — the reason a hardcoded template is wrong.
    assert m2021.lineup_size == 9 and m2024.lineup_size == 10
    assert sum(1 for s in m2021.starting_slots if s == ("RB", "WR", "TE")) == 1
    assert sum(1 for s in m2024.starting_slots if s == ("RB", "WR", "TE")) == 2
    # Playoffs moved in 2026, and its final is a two-week round.
    assert m2024.playoff_week_start == 16 and m2024.regular_season_weeks == 15
    assert m2026.playoff_week_start == 15 and m2026.regular_season_weeks == 14
    assert m2024.finals_weeks == (17,) and m2026.finals_weeks == (16, 17)
    # 2020 predates the Sleeper snapshot: exports exist, replay data does not.
    assert Q.season_meta(2020).has_snapshot is False
    assert 2020 not in Q.snapshot_seasons()


# ---------------------------------------------------------------------------
# Against the committed data
# ---------------------------------------------------------------------------
def test_sheets_load_and_carry_expected_keys():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    sheets = Q.all_sheets()
    assert set(sheets) >= {"player_week", "team_week", "team_year", "trades"}
    for name, df in sheets.items():
        entity = Q.ENTITY_COL.get(name)
        assert not df.empty, name
        if entity:
            assert entity in df.columns, f"{name} missing {entity}"


def test_find_columns_searches_names_and_notes():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    hits = Q.find_columns("efficiency")
    assert {h.sheet for h in hits} >= {"team_week", "league_week"}
    # Notes are searched too, so a concept can be found under a column that
    # does not spell it — that is the whole point of the search.
    named_only = Q.find_columns("one-man army", search_notes=False)
    with_notes = Q.find_columns("one-man army", search_notes=True)
    assert len(with_notes) > len(named_only)
    assert Q.find_columns("zzz-no-such-stat") == []


def test_top_ranks_numerically_not_lexically():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    board = Q.top("team_week", "PF", "Year=2025", n=5)
    values = [Q.to_number(v) for v in board["PF"]]
    assert values == sorted(values, reverse=True)
    assert values[0] > 200  # a lexical sort would put "99.9" on top
    low = Q.top("team_week", "PF", "Year=2025", n=3, ascending=True)
    assert Q.to_number(low["PF"].iloc[0]) < values[-1]


def test_describe_column_reports_extremes():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    info = Q.describe_column("player_all_time", "Points")
    assert info["numeric_values"] > 100
    assert info["max"] > info["min"]
    assert info["argmax"]


def test_team_names_are_canonicalised_to_the_exports():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    exported = set(Q.load_sheet("team_week")["Team"])
    for name in Q.teams(2025).values():
        assert name in exported, f"{name} is not spelled the way the sheets spell it"
    assert Q.canonical_team("SHMUEL256") in exported


def test_player_resolution_prefers_the_fantasy_relevant_match():
    if not _HAVE_SNAPSHOT:
        return _skip("no snapshot")
    pl = Q.players()
    # "Lamar Jackson" is also a cornerback; the startable QB must win.
    assert pl.position(pl.resolve("Lamar Jackson")) == "QB"
    assert pl.resolve("6797") == "6797"
    assert pl.name(pl.resolve("Justin Herbert")) == "Justin Herbert"
    try:
        pl.resolve("zzzz not a player")
    except KeyError as exc:
        assert "no player matches" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown player should raise")


def test_season_eligibility_absorbs_position_drift():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    # Cordarrelle Patterson is listed RB today but filled a strict WR slot in
    # 2021. Eligibility must carry both, or three real lineups look illegal.
    pid = Q.players().resolve("Cordarrelle Patterson")
    elig_2021 = Q.season_eligibility(2021).get(pid, frozenset())
    assert {"RB", "WR"} <= elig_2021, elig_2021
    assert Q.players().position(pid) == "RB"  # the dictionary itself is untouched


def test_week_and_pairings_match_the_league_shape():
    if not _HAVE_SNAPSHOT:
        return _skip("no snapshot")
    rows = Q.week(2025, 6)
    assert len(rows) == 8
    assert all(len(r.starters) == Q.season_meta(2025).lineup_size for r in rows.values())
    pairs = Q.pairings(2025, 6)
    assert len(pairs) == 4
    assert sorted(rid for pair in pairs for rid in pair) == sorted(rows)
    assert Q.played_weeks(2025)[-1] == 17


def test_semifinal_bonus_explains_every_pf_mismatch():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    # The documented trap: PF != raw Sleeper points, in exactly one week, by
    # exactly +5, for exactly the higher seed in each semifinal.
    tw = Q.load_sheet("team_week")
    mismatches = []
    for year in (y for y in Q.snapshot_seasons() if y in set(Q.export_seasons())):
        table = Q.teams(year)
        rows = Q.rows("team_week", f"Year={year}")
        for _, r in rows.iterrows():
            wk = int(float(r["Week"]))
            rid = next((i for i, t in table.items() if t == str(r["Team"])), None)
            if rid is None:
                continue
            raw = Q.week(year, wk).get(rid)
            if raw is None:
                continue
            delta = round(Q.to_number(r["PF"]) - raw.points, 2)
            if abs(delta) > 0.02:
                mismatches.append((year, wk, str(r["Team"]), delta))
    assert mismatches, "expected the known +5 rows"
    assert all(d == Q.SEMIFINAL_HOME_BONUS for *_, d in mismatches), mismatches
    assert all(wk == Q.season_meta(y).semifinal_week for y, wk, *_ in mismatches), mismatches
    assert len(tw) > 0


def test_trades_resolve_both_sides():
    if not _HAVE_SNAPSHOT:
        return _skip("no snapshot")
    deals = Q.trades(season=2025, player="Justin Herbert")
    assert len(deals) == 1
    trade = deals[0]
    assert trade.date == "2025-08-07"
    names = {Q.players().name(p) for side in trade.received.values() for p in side}
    assert {"Justin Herbert", "Lamar Jackson", "Chris Godwin"} <= names
    assert set(trade.faab.values()) == {35.0, -35.0}
    assert len(trade.picks) == 4
    assert "gets" in trade.describe()


def test_unavailable_flags_come_from_the_build():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    out = Q.unavailable(2025)
    assert out, "2025 should have bye/injury/suspension flags"
    lamar = Q.players().resolve("Lamar Jackson")
    # He missed weeks 5-8 in 2025 — the fact the anchored lineup model leans on.
    assert any((lamar, wk) in out for wk in (5, 6, 7, 8))


def test_reads_are_pure():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    before = {p: p.stat().st_mtime for p in (_ROOT / "exports").glob("*.csv")}
    Q.rows("team_week", "Year=2025")
    Q.top("player_year", "Points", n=3)
    Q.player_dossier("Josh Allen")
    after = {p: p.stat().st_mtime for p in (_ROOT / "exports").glob("*.csv")}
    assert before == after, "inquiry must never write to exports/"


TESTS = [
    test_sheet_name_aliases,
    test_to_number_handles_build_cells,
    test_predicate_parsing_and_matching,
    test_filter_rows_is_conjunctive_and_names_near_misses,
    test_season_meta_shape_is_read_not_hardcoded,
    test_sheets_load_and_carry_expected_keys,
    test_find_columns_searches_names_and_notes,
    test_top_ranks_numerically_not_lexically,
    test_describe_column_reports_extremes,
    test_team_names_are_canonicalised_to_the_exports,
    test_player_resolution_prefers_the_fantasy_relevant_match,
    test_season_eligibility_absorbs_position_drift,
    test_week_and_pairings_match_the_league_shape,
    test_semifinal_bonus_explains_every_pf_mismatch,
    test_trades_resolve_both_sides,
    test_unavailable_flags_come_from_the_build,
    test_reads_are_pure,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall inquiry checks passed")
