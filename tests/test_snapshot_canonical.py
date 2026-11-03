"""The committed player dictionary is written in a canonical field order.

`snapshot.canonical_players` sorts the fields inside each Sleeper player record so
consecutive snapshots delta in git (each refresh used to store a fresh ~2 MB blob).
These pin that it changes ORDER only: same players in Sleeper's order, same values.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import snapshot  # noqa: E402


def _blob():
    return {
        "6462": {"team": None, "age": 26, "metadata": {"z": 1, "channel_id": "x"},
                 "fantasy_positions": ["TE", "RB"], "player_id": "6462"},
        "11255": {"player_id": "11255", "injury_status": "Out", "age": 23},
        "17": {"b": [{"y": 1, "x": 2}], "a": 0},
    }


def test_only_the_order_inside_a_record_changes():
    raw = _blob()
    out = snapshot.canonical_players(raw)
    assert out == raw                                  # every value equal, deep
    assert list(out) == list(raw)                      # Sleeper's player order kept
    assert list(out["6462"]) == sorted(raw["6462"])    # fields sorted
    assert list(out["6462"]["metadata"]) == ["channel_id", "z"]
    assert out["6462"]["fantasy_positions"] == ["TE", "RB"]   # list order kept
    assert list(out["17"]["b"][0]) == ["x", "y"]


def test_two_shuffled_fetches_write_the_same_bytes():
    a = _blob()
    b = {pid: dict(reversed(list(rec.items()))) for pid, rec in a.items()}
    assert json.dumps(a, indent=2) != json.dumps(b, indent=2)
    ca, cb = snapshot.canonical_players(a), snapshot.canonical_players(b)
    assert json.dumps(ca, indent=2) == json.dumps(cb, indent=2)


def test_not_a_dict_passes_through():
    assert snapshot.canonical_players({}) == {}
    assert snapshot.canonical_players([]) == []


def test_committed_dictionary_parses_to_the_same_values_canonicalised():
    """The committed file re-written canonically holds exactly what it held."""
    p = _ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json"
    if not p.exists():
        return
    raw = json.loads(p.read_text())
    out = snapshot.canonical_players(raw)
    assert out == raw and list(out) == list(raw)


def test_every_snapshot_json_is_written_key_sorted():
    """Nested dicts sorted at every depth, lists in Sleeper's order, values equal."""
    import tempfile
    tx = [{"type": "waiver", "adds": {"9": 3, "1": 3}, "metadata": {"z": 1, "a": None},
           "roster_ids": [3, 1], "status": "complete"}]
    shuffled = [{"status": "complete", "roster_ids": [3, 1], "metadata": {"a": None, "z": 1},
                 "adds": {"1": 3, "9": 3}, "type": "waiver"}]
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.json", Path(d) / "b.json"
        snapshot._safe_write_json(a, tx)
        snapshot._safe_write_json(b, shuffled)
        assert a.read_bytes() == b.read_bytes()           # same data, same bytes
        got = json.loads(a.read_text())
        assert got == tx and list(got[0]) == sorted(tx[0]) and list(got[0]["adds"]) == ["1", "9"]
        assert got[0]["roster_ids"] == [3, 1]             # list order kept


def test_the_players_file_keeps_sleeper_player_order():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "p.json"
        snapshot._safe_write_json(p, snapshot.canonical_players(_blob()), sort_keys=False)
        assert list(json.loads(p.read_text())) == list(_blob())


def test_committed_weekly_files_hold_the_same_values_canonicalised():
    snap = _ROOT / "exports" / "snapshot"
    files = sorted(snap.glob("season_*/weeks/week_*/transactions.json"))[:40]
    for f in files:
        raw = json.loads(f.read_text())
        assert snapshot._sorted_keys(raw) == raw


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
