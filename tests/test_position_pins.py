"""Fantasy-position pins: one label per player, and no pool of one.

NFLverse labels a player by the position he PLAYS. For a two-way player that is
a defensible label upstream and a broken one here, because every league-relative
stat we compute pools a score with whoever shares its position label.

Travis Hunter is the case. In August 2026 NFLverse relabelled his 2025 weeks 1-7
from WR/WR to CB/DB. Our league drafted, rostered and started him as a WR, so
that put him alone in a 2025 "CB" pool: his weekly positional scoring percentile
became his rank among his own seven games (week 5, 9.4 pts -> 100.0; week 3, 3.1
pts -> 0.0, where the WR pool had them at 32.4 and 6.6), and weeks 8-17 — which
have no NFLverse row and fall back to Sleeper's dictionary — stayed WR, so one
player sat in two pools inside one season.

Two guards here:
  * the pin itself rewrites the label on read, keyed by gsis_id, touching
    nobody else (the 2000-odd genuine CB rows upstream are left alone);
  * `check_no_position_pool_of_one` is the general net. It does not know
    Hunter's name: it asserts that no (season, position) pool in the shipped
    player_week has exactly one player in it, which is the property that made
    his percentiles meaningless and which the next relabel would break again.

Run: PYTHONPATH=src:lib python tests/test_position_pins.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import external as E  # noqa: E402

_EXPORTS = Path(__import__("os").environ.get("LOTG_EXPORTS", _ROOT / "exports"))
_HAVE_EXPORTS = (_EXPORTS / "player_week.csv").exists()


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond or not detail else f" — {detail}"))
    return bool(cond)


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# The pin itself — pure, no exports needed
# ---------------------------------------------------------------------------
def check_pin_rewrites_only_the_pinned_player() -> bool:
    """Hunter's rows become WR; the genuine cornerbacks beside him do not."""
    df = pd.DataFrame({
        "player_id": ["00-0040718", "00-0040718", "00-0011111", "00-0022222"],
        "player_display_name": ["Travis Hunter", "Travis Hunter", "Some Corner", "A Receiver"],
        "week": [1, 2, 1, 1],
        "position": ["CB", "CB", "CB", "WR"],
        "position_group": ["DB", "DB", "DB", "WR"],
    })
    out = E.apply_position_pins(df.copy())
    ok = _ok("pinned player's position is rewritten",
             list(out.loc[out.player_id == "00-0040718", "position"]) == ["WR", "WR"])
    ok &= _ok("every position column moves together, not just `position`",
              list(out.loc[out.player_id == "00-0040718", "position_group"]) == ["WR", "WR"])
    ok &= _ok("a real cornerback is untouched",
              out.loc[out.player_id == "00-0011111", "position"].iat[0] == "CB")
    ok &= _ok("an unrelated receiver is untouched",
              out.loc[out.player_id == "00-0022222", "position"].iat[0] == "WR")
    return ok


def check_pin_matches_on_gsis_id_not_name() -> bool:
    """Upstream re-spells names and names collide; the id is the stable key."""
    df = pd.DataFrame({
        "player_id": ["00-0040718", "00-0099999"],
        "player_display_name": ["T. Hunter", "Travis Hunter"],   # impostor by name
        "position": ["CB", "CB"],
    })
    out = E.apply_position_pins(df.copy())
    return (_ok("the id matches even when the name is spelled differently",
                out.loc[out.player_id == "00-0040718", "position"].iat[0] == "WR")
            and _ok("a same-NAME different-id player is not pinned",
                    out.loc[out.player_id == "00-0099999", "position"].iat[0] == "CB"))


def check_pin_accepts_either_id_column() -> bool:
    """stats files key on `player_id`, roster files on `gsis_id`."""
    df = pd.DataFrame({"gsis_id": ["00-0040718"], "position": ["CB"]})
    return _ok("gsis_id-keyed files are pinned too",
               E.apply_position_pins(df.copy())["position"].iat[0] == "WR")


def check_pin_is_a_noop_on_unrelated_frames() -> bool:
    """A frame with no id column, no position column, or no pinned player is
    returned untouched rather than raising."""
    ok = _ok("no position column -> unchanged",
             list(E.apply_position_pins(
                 pd.DataFrame({"player_id": ["00-0040718"], "x": [1]})).columns) == ["player_id", "x"])
    ok &= _ok("no id column -> unchanged",
              E.apply_position_pins(pd.DataFrame({"position": ["CB"]}))["position"].iat[0] == "CB")
    ok &= _ok("empty frame -> unchanged", E.apply_position_pins(pd.DataFrame()).empty)
    nobody = pd.DataFrame({"player_id": ["00-0000001"], "position": ["CB"]})
    ok &= _ok("frame naming no pinned player -> unchanged",
              E.apply_position_pins(nobody)["position"].iat[0] == "CB")
    return ok


# ---------------------------------------------------------------------------
# The general net — against the shipped exports
# ---------------------------------------------------------------------------
def check_no_position_pool_of_one() -> bool:
    """No (season, position) pool may hold exactly one player.

    This is the property the relabel broke, stated without naming anybody: a
    pool of one ranks a player against himself, so his positional percentile is
    0 or 100 by construction and every "adjusted by position" factor is his own
    average divided by itself.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    pw = pd.read_csv(_EXPORTS / "player_week.csv", low_memory=False)
    if not {"Player", "Year", "Position"}.issubset(pw.columns):
        return _skip("player_week has no Position column")
    pools = (pw.dropna(subset=["Position"])
               .groupby([pw["Year"].astype(str), pw["Position"].astype(str)])["Player"]
               .nunique())
    lonely = pools[pools == 1]
    return _ok("no season/position pool has a single player",
               lonely.empty, f"pools of one: {dict(lonely)}")


def check_a_player_keeps_one_position_per_season() -> bool:
    """A player must not straddle two position pools inside one season.

    Hunter did: weeks 1-7 came from NFLverse (relabelled CB) and weeks 8-17,
    which NFLverse has no row for, fell back to Sleeper and stayed WR.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    pw = pd.read_csv(_EXPORTS / "player_week.csv", low_memory=False)
    if not {"Player", "Year", "Position"}.issubset(pw.columns):
        return _skip("player_week has no Position column")
    seen = (pw.dropna(subset=["Position"])
              .groupby([pw["Player"].astype(str), pw["Year"].astype(str)])["Position"]
              .nunique())
    split = seen[seen > 1]
    return _ok("each player has one position per season",
               split.empty, f"split across pools: {dict(split)}")


def run_all() -> bool:
    ok = True
    for t in (check_pin_rewrites_only_the_pinned_player,
              check_pin_matches_on_gsis_id_not_name,
              check_pin_accepts_either_id_column,
              check_pin_is_a_noop_on_unrelated_frames,
              check_no_position_pool_of_one,
              check_a_player_keeps_one_position_per_season):
        print(f"\n{t.__name__}:")
        ok &= bool(t())
    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return ok


def test_position_pins():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
