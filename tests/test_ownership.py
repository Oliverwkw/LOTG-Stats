"""The ownership ledger: which rosters held a player, in what order.

`analysis.timeline()` tells the story of one entity; `ownership_ledger()` is the
same story for every player at once, which is what a question of the shape
"across all players, who has property P about their ownership history" needs.

Two guards make it quotable. `check_trade_counts_match_build`: the ledger's
trade rows, counted per player, must equal `player_all_time."Number of trades"`
— a number the build computed independently, from Sleeper pids rather than from
the exported name text, and it reconciles exactly today including 2020, whose
trades have to be recovered by name because that season has no snapshot.
`check_ledger_chains`: every trade must take a player from exactly where the
ledger last had him, which tests the ordering, the sender attribution and the
snapshot/sheet merge at once.

The rest pin the traps that make a hand-rolled version of this wrong: a traded
draft pick is not a traded player ("2021 1.06(T. Etienne)"); Sleeper
occasionally records one exchange twice, as a pick trade and again as the player
swap that executes it; and the sheets' timestamps are on a different clock from
the snapshot's, so ordering them by printed text interleaves them wrongly.

Run: python tests/test_ownership.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import analysis as A  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_week.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Pure logic — no exports needed
# ---------------------------------------------------------------------------
def test_pick_assets_are_not_players():
    """The trap: splitting an asset cell on ';' reads a pick as a player."""
    cell = ("Alvin Kamara; 2021 1.06(T. Etienne); Mike Williams; "
            "2027 4(Oliverwkw); 2022 3.07(Z. White)")
    players, picks = A.split_assets(cell)
    assert players == ["Alvin Kamara", "Mike Williams"], players
    assert len(picks) == 3, picks
    # A pick's parenthetical names the player it became; he was not traded here.
    assert not any("Etienne" in p for p in players)

    empty_players, empty_picks = A.split_assets("")
    assert empty_players == [] and empty_picks == []
    # Placeholder cells (a trade with nothing coming back on that side) and the
    # "nan" a missing cell reads as are both dropped, not counted as a player.
    assert A.split_assets("nan")[0] == []
    assert A.split_assets("Unknown; -")[0] == []


def test_season_labels_parse():
    assert A._season_of_label("2021") == 2021
    assert A._season_of_label("2021 (vet)") == 2021
    assert A._season_of_label("startup") is None


def test_unknown_event_kind_is_rejected():
    """A typo should raise, not silently return a ledger missing a whole kind."""
    try:
        A.ownership_ledger(events=("trade", "waiver"))
    except ValueError as exc:
        assert "waiver" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown event kind")


# ---------------------------------------------------------------------------
# Tied to the build
# ---------------------------------------------------------------------------
def test_trade_counts_match_the_builds_own_column():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    problems = A.check_trade_counts_match_build()
    assert not problems, problems[:10]


def test_the_documented_duplicate_is_the_only_one():
    """Including the known duplicate must break the reconciliation, and only there.

    If this starts failing, Sleeper has recorded another exchange twice and
    `DUPLICATE_TRADE_TRANSACTIONS` needs the new id — or the old one has stopped
    being a duplicate.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    problems = A.check_trade_counts_match_build(include_duplicates=True)
    assert len(problems) == 2, problems
    assert {p.split(":")[0] for p in problems} == {"Michael Carter", "Rhamondre Stevenson"}
    assert all("+1" in p for p in problems), problems


def test_every_trade_hands_off_from_where_the_player_was():
    """Ordering, sender attribution and the cross-source merge, in one assertion."""
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    problems = A.check_ledger_chains()
    assert not problems, problems[:10]


def test_sheet_timestamps_are_read_on_the_export_clock():
    """The sheets print Sleeper's `created` in US Eastern; ordering depends on it."""
    assert A._sheet_epoch_ms("") is None
    assert A._sheet_epoch_ms("not a date") is None
    # 2021-08-29 11:53:08 Eastern is 15:53:08 UTC — the four-hour summer offset.
    stamp = A._sheet_epoch_ms("2021-08-29 11:53:08")
    assert stamp == 1630252388000, stamp
    # ... and five hours in winter, which is why this is a zone and not a constant.
    assert A._sheet_epoch_ms("2021-12-22 10:31:49") == 1640187109000


def test_ledger_covers_every_season_including_the_snapshotless_one():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    df = A.ownership_ledger(events=("trade",))
    seasons = {int(s) for s in df["season"].dropna()}
    # 2020 came from the ESPN backfill and has no snapshot, so its trades can
    # only come from the sheet; every later season should come from the raw
    # record instead.
    assert 2020 in seasons, "the ESPN-backfilled season is missing its trades"
    assert set(df[df["season"] == 2020]["source"]) == {"sheet"}
    for year in Q.snapshot_seasons():
        rows = df[df["season"] == year]
        if not rows.empty:
            assert set(rows["source"]) == {"snapshot"}, year


# ---------------------------------------------------------------------------
# Shape and semantics
# ---------------------------------------------------------------------------
def test_ledger_is_one_row_per_acquisition_in_order():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    df = A.ownership_ledger(player="Alvin Kamara")
    assert {"player", "player_id", "season", "date", "event", "team",
            "from_team", "source"} == set(df.columns)
    assert list(df["event"]) == ["draft", "trade", "trade", "trade"]
    # The undated startup draft sorts to the front, not to the end.
    assert df.iloc[0]["team"] == "shmuel256"
    assert list(df["team"]) == ["shmuel256", "stevenb123", "shmuel256", "stevenb123"]
    # Both ends of every trade are named.
    trades = df[df["event"] == "trade"]
    assert all(t for t in trades["from_team"]), "a trade must record its sender"
    assert not any(r.team == r.from_team for r in trades.itertuples())


def test_summary_separates_spells_from_teams():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    summary = A.ownership_summary()
    kamara = summary[summary["player"] == "Alvin Kamara"].iloc[0]
    assert kamara["trades"] == 3
    assert kamara["teams"] == 2, "two rosters, three trades — the ping-pong case"
    assert kamara["spells"] == 4, "the startup draft is an acquisition too"
    assert kamara["boomerangs"] == 2
    assert kamara["path"] == ("shmuel256 > stevenb123 > shmuel256 > stevenb123")
    # spells >= teams always: you cannot be on more rosters than times acquired.
    assert (summary["spells"] >= summary["teams"]).all()
    # boomerangs is exactly the excess.
    assert (summary["spells"] - summary["teams"] >= summary["boomerangs"]).all()


def test_summary_totals_agree_with_the_ledger():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    ledger = A.ownership_ledger()
    summary = A.ownership_summary(ledger)
    assert summary["spells"].sum() == len(ledger)
    assert summary["trades"].sum() == int((ledger["event"] == "trade").sum())
    assert summary["adds"].sum() == int((ledger["event"] == "add").sum())
    assert len(summary) == ledger["player"].nunique()


def test_reads_are_pure():
    """An inquiry helper must not write anything."""
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    exports = _ROOT / "exports"
    before = {p: p.stat().st_mtime for p in exports.rglob("*") if p.is_file()}
    A.ownership_summary()
    after = {p: p.stat().st_mtime for p in exports.rglob("*") if p.is_file()}
    assert before == after, "ownership helpers must not touch exports/"


TESTS = [
    test_pick_assets_are_not_players,
    test_season_labels_parse,
    test_unknown_event_kind_is_rejected,
    test_trade_counts_match_the_builds_own_column,
    test_every_trade_hands_off_from_where_the_player_was,
    test_sheet_timestamps_are_read_on_the_export_clock,
    test_the_documented_duplicate_is_the_only_one,
    test_ledger_covers_every_season_including_the_snapshotless_one,
    test_ledger_is_one_row_per_acquisition_in_order,
    test_summary_separates_spells_from_teams,
    test_summary_totals_agree_with_the_ledger,
    test_reads_are_pure,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall ownership checks passed")
