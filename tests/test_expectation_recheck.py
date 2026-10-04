"""Guards for `lotg_support.expectation_recheck` — the points-above-expectation
model's replay of the build as of past seasons (plan/MASTER_TODO.md, "Yearly
re-check of the expectation model").

Synthetic checks pin the plumbing (inputs round-trip, a season cut, the
verdict). The data check is the weekly early warning: on the inputs this build
just wrote (exports/raw/pae_additions.json.gz, artifact only) the latest
season's replay must stay inside the re-tune limits; it skips when the file is
absent (a local checkout).

Run: python tests/test_expectation_recheck.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "tests"))

from lotg_support import acquisition as ACQ  # noqa: E402
from lotg_support import expectation_recheck as RC  # noqa: E402

_DUMP = _ROOT / "exports" / "raw" / RC.DUMP_NAME


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _league(seasons: int = 8):
    """test_acquisition's synthetic league, its seasons numbered from 2020."""
    from test_acquisition import _league as league
    adds = league(seasons)
    for a in adds:
        a.s0 = 2020 + seasons - 1 - a.noff[-1]
    return adds


def test_inputs_round_trip():
    adds = _league(4)
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / RC.DUMP_NAME)
        RC.dump_additions(adds, path)
        back = RC.load_additions(path)
    assert [(a.key, a.ch, a.p, a.pos, a.s0, a.held, a.cf, a.noff) for a in back] == \
           [(a.key, a.ch, a.p, a.pos, a.s0, a.held, a.cf, a.noff) for a in adds]
    assert ACQ.points_above_expectation(back) == ACQ.points_above_expectation(adds)


def test_as_of_keeps_only_what_was_known():
    adds = _league(5)                                    # seasons 2020-24
    cut = RC.as_of(adds, 2022)
    assert {a.s0 for a in cut} == {2020, 2021, 2022}
    for a in cut:
        assert all(a.s0 + n <= 2022 for n in a.noff)
        assert len(a.cf) == len(a.noff) == 17 * (2022 - a.s0 + 1)
        assert all(k <= len(a.cf) for k, _x in a.held)


def test_replay_is_calibrated_on_a_league_the_model_fits():
    checks = RC.replay(_league(8), seasons=[2024, 2027])
    assert [c.season for c in checks] == [2024, 2027]
    assert all(c.calibration is not None and c.calibration < RC.MAX_CALIBRATION for c in checks), checks
    assert all(c.edge is not None and c.edge < RC.MAX_EDGE_ERROR for c in checks), checks
    assert RC.verdict(checks) == "ok"


def test_verdict_names_what_to_retune():
    C = RC.SeasonCheck
    assert RC.verdict([C(2026, 100, 0.03, 0.04, 0.038)]) == "ok"
    assert RC.verdict([C(2026, 100, 0.08, 0.04, 0.038)]).startswith("RE-TUNE: 2026: calibration 0.080")
    assert "oldest-tenure error 0.150" in RC.verdict([C(2026, 100, 0.03, 0.15, None)])
    rising = [C(2026, 1, 0.030, 0.02, None), C(2027, 1, 0.035, 0.02, None), C(2028, 1, 0.040, 0.02, None)]
    assert "rising two seasons running" in RC.verdict(rising)


# --- against this build's inputs -------------------------------------------
def test_latest_season_inside_the_retune_limits():
    """The weekly early warning: the expectation as fitted now, replayed out of
    fold on the latest season, is inside the limits. A failure means re-run
    scripts/pae_recheck.py and re-tune (plan/MASTER_TODO.md)."""
    if not _DUMP.exists():
        return _skip("no points-above-expectation inputs (written by the build, artifact only)")
    adds = RC.load_additions(str(_DUMP))
    priced = [a for a in adds if a.ch in ACQ.CHANNELS and a.p is not None]
    assert len(priced) > 1000, len(priced)
    latest = max(a.s0 for a in adds if a.s0 is not None)
    (check,) = RC.replay(adds, seasons=[latest])
    print(f"  {check}")
    assert check.ok(), RC.verdict([check])


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            print(_n)
            _f()
    print("ok")
