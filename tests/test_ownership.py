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

import pandas as pd

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
def test_an_asset_cell_holds_three_kinds_of_thing():
    """The trap: an asset cell mixes players, picks and cash. Only one is a player."""
    cell = ("Alvin Kamara; 2021 1.06(T. Etienne); Mike Williams; "
            "2027 4(Oliverwkw); $15 FAAB; 2022 3.07(Z. White)")
    players, picks, faab = A.split_assets(cell)
    assert players == ["Alvin Kamara", "Mike Williams"], players
    assert len(picks) == 3, picks
    assert faab == ["$15 FAAB"], faab
    # A pick's parenthetical names the player it became; he was not traded here.
    assert not any("Etienne" in p for p in players)
    # Cash is neither a pick nor a placeholder, so a two-way test lets it through
    # as a player — 166 tokens across the sheet would have become acquisitions.
    assert not any("FAAB" in p for p in players)

    assert A.split_assets("") == ([], [], [])
    # Placeholder cells (a trade with nothing coming back on that side) and the
    # "nan" a missing cell reads as are both dropped, not counted as a player.
    assert A.split_assets("nan")[0] == []
    assert A.split_assets("Unknown; -")[0] == []


def test_no_asset_cell_holds_anything_but_those_three():
    """Over-inclusive: sweep the whole sheet rather than trusting the two regexes.

    Anything classified as a player that no player dictionary can resolve is
    either a new asset kind or a name problem, and should be looked at.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    sheet = Q.load_sheet("trades")
    strays = set()
    for _, row in sheet.iterrows():
        for column in ("Assets received", "Assets sent"):
            for name in A.split_assets(row[column])[0]:
                if not A._resolve_quietly(name):
                    strays.add(name)
    # "David Johnson" is ambiguous in Sleeper's dictionary (two of them), so it
    # resolves to nothing and keeps the sheet's spelling — that is the designed
    # fallback, not a stray asset kind. Anything else here is a real finding.
    assert strays <= {"David Johnson"}, sorted(strays)


def test_season_labels_parse():
    assert A._season_of_label("2021") == 2021
    assert A._season_of_label("2021 (vet)") == 2021
    assert A._season_of_label("nonsense") is None


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


def test_the_count_guard_catches_a_phantom_player():
    """The guard must look both ways, or it cannot see a non-player asset.

    Comparing only the names `player_all_time` knows about is blind to an asset
    the ledger mistook for a player: it has no row to be compared against, so it
    passes silently. Feeding the guard a ledger containing cash proves the
    second direction fires.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    real = A.ownership_ledger

    def with_a_phantom(*args, **kwargs):
        df = real(*args, **kwargs)
        phantom = df.iloc[[0]].copy()
        phantom["player"] = "$15 FAAB"
        phantom["event"] = "trade"
        return pd.concat([df, phantom], ignore_index=True)

    A.ownership_ledger = with_a_phantom
    try:
        problems = A.check_trade_counts_match_build()
    finally:
        A.ownership_ledger = real
    assert any("FAAB" in p for p in problems), problems
    assert any("not a player" in p for p in problems), problems


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


def test_the_startup_draft_belongs_to_the_inaugural_season():
    """`startup` is a season, not the absence of one.

    It is the 19-round ESPN inception draft of 2020-09-10 (152 rows, numbered
    through 19.08). Leaving it unlabelled drops every original roster's origin
    out of a season-filtered view, so `--season 2020` returned no drafts at all
    and a filtered `path` began at a player's first trade instead of his draft.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    inaugural = min(Q.export_seasons())
    assert A._season_of_label("startup") == inaugural

    drafts = A.ownership_ledger(season=inaugural, events=("draft",))
    assert len(drafts) == 152, len(drafts)
    # And the origin still precedes every move that season.
    kamara = A.ownership_ledger(player="Alvin Kamara")
    assert kamara.iloc[0]["event"] == "draft"
    assert int(kamara.iloc[0]["season"]) == inaugural


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
    """Kamara is the ping-pong case: drafted once, then traded back and forth.

    Everything asserted here is derived from the exports rather than written
    down, because this is a LIVE league — Kamara was traded again on the morning
    of 2026-08-19 and a pinned "three trades, path shmuel > steven > shmuel >
    steven" turned into two red tests about nothing. What actually has to hold
    is the SHAPE: the startup draft comes first, every later row is a trade, and
    each one hands him on from wherever the ledger last had him.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    df = A.ownership_ledger(player="Alvin Kamara")
    assert {"player", "player_id", "season", "date", "event", "team",
            "from_team", "source"} == set(df.columns)
    # He entered in the startup draft and has changed hands by trade ever since.
    assert len(df) >= 4, f"expected the startup draft + his trades, got {len(df)}"
    assert list(df["event"]) == ["draft"] + ["trade"] * (len(df) - 1)
    # The undated startup draft sorts to the front, not to the end.
    assert df.iloc[0]["event"] == "draft"
    trades = df[df["event"] == "trade"]
    # Both ends of every trade are named, and nobody trades with themselves.
    assert all(t for t in trades["from_team"]), "a trade must record its sender"
    assert not any(r.team == r.from_team for r in trades.itertuples())
    # Each trade takes him from exactly where the ledger last had him.
    held = list(df["team"])
    assert list(trades["from_team"]) == held[:-1], (
        f"chain breaks: {held} vs senders {list(trades['from_team'])}")


def test_summary_separates_spells_from_teams():
    """spells counts ACQUISITIONS, teams counts distinct rosters — the two come
    apart exactly when a player returns to a roster he has already been on.

    Kamara is the worked example, reconciled against his own ledger rather than
    against numbers written down here: he keeps getting traded (see the note on
    the previous test), so his counts are not constants.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    summary = A.ownership_summary()
    kamara = summary[summary["player"] == "Alvin Kamara"].iloc[0]
    ledger = A.ownership_ledger(player="Alvin Kamara")
    path = list(ledger["team"])
    assert kamara["trades"] == int((ledger["event"] == "trade").sum())
    assert kamara["spells"] == len(path), "the startup draft is an acquisition too"
    assert kamara["teams"] == len(set(path))
    assert kamara["boomerangs"] == len(path) - len(set(path))
    assert kamara["path"] == " > ".join(path)
    # He is the ping-pong case: fewer rosters than acquisitions, i.e. he has
    # been re-acquired by a roster that already had him.
    assert kamara["teams"] < kamara["spells"], "Kamara should be a boomerang case"
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
    test_an_asset_cell_holds_three_kinds_of_thing,
    test_no_asset_cell_holds_anything_but_those_three,
    test_season_labels_parse,
    test_unknown_event_kind_is_rejected,
    test_trade_counts_match_the_builds_own_column,
    test_the_count_guard_catches_a_phantom_player,
    test_every_trade_hands_off_from_where_the_player_was,
    test_sheet_timestamps_are_read_on_the_export_clock,
    test_the_documented_duplicate_is_the_only_one,
    test_the_startup_draft_belongs_to_the_inaugural_season,
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
