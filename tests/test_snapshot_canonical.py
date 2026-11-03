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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
