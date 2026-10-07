"""App-style win % (lotg_support.gametime.app_win_pct) against the Sleeper app.

The 40 matchups of 2026 weeks 5-14 as the lineups stood on 2026-10-07: the two
Sleeper-projected totals and the win % the app showed for the first team, read
off the app by the user (totals confirmed equal to the app's). APP_WIN_EXPONENT
must reproduce every one to the whole percent.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from lotg_support import gametime  # noqa: E402

# (week, projected total A, projected total B, app win % for A)
APP_MATCHUPS = [
    (5, 143.89, 104.76, 77), (5, 165.98, 147.83, 61), (5, 165.76, 157.70, 55), (5, 167.03, 93.65, 90),
    (6, 112.92, 98.88, 62), (6, 154.85, 144.85, 56), (6, 112.84, 109.48, 53), (6, 132.33, 110.62, 66),
    (7, 147.25, 137.90, 56), (7, 176.25, 44.18, 99), (7, 126.71, 72.80, 89), (7, 140.37, 136.46, 53),
    (8, 142.85, 108.16, 74), (8, 165.55, 111.86, 81), (8, 123.81, 111.81, 59), (8, 99.34, 92.72, 56),
    (9, 151.82, 133.67, 62), (9, 169.26, 159.51, 56), (9, 150.21, 101.02, 82), (9, 160.11, 99.58, 86),
    (10, 149.51, 143.63, 54), (10, 161.47, 157.10, 53), (10, 147.97, 113.40, 73), (10, 102.67, 85.88, 66),
    (11, 110.37, 94.30, 64), (11, 152.15, 76.71, 93), (11, 157.17, 104.10, 82), (11, 122.70, 98.39, 70),
    (12, 142.67, 113.38, 70), (12, 180.21, 141.96, 71), (12, 155.67, 150.60, 53), (12, 153.02, 101.58, 82),
    (13, 131.25, 92.61, 79), (13, 150.66, 118.24, 71), (13, 151.13, 126.99, 66), (13, 138.83, 106.06, 73),
    (14, 154.03, 146.66, 55), (14, 147.56, 89.93, 87), (14, 150.84, 113.91, 74), (14, 135.80, 117.75, 63),
]


# The app's LIVE win % during a week, read off the app mid-week: (when, the two
# projected totals the app shows then — points so far + the remaining
# starters' projections — and the app's win % for the first team). Add rows as
# you read them; see "Tweaking the app-style win %" in plan/MASTER_TODO.md.
LIVE_MATCHUPS = []   # e.g. ("2026 wk5 entering MNF", 118.4, 131.0, 31)


def _pct(a, b, k):
    return round(100 / (1 + (b / a) ** k))


def exponent_range(rows, lo=2.0, hi=6.0, step=0.001):
    """(lowest, highest) exponent reproducing every row's app % to the whole
    percent, or None when no single exponent does (the formula's shape is off)."""
    ks = [round(lo + i * step, 3) for i in range(int((hi - lo) / step) + 1)]
    ok = [k for k in ks if all(_pct(r[-3], r[-2], k) == r[-1] for r in rows)]
    return (ok[0], ok[-1]) if ok else None


def _misses(rows):
    return [r + (round(100 * gametime.app_win_pct(r[-3], r[-2])),) for r in rows
            if round(100 * gametime.app_win_pct(r[-3], r[-2])) != r[-1]]


def test_app_win_pct_reproduces_the_app():
    misses = _misses(APP_MATCHUPS)
    assert not misses, f"app-style win % off the app's own pre-week numbers (last = ours): {misses}"


def test_app_win_pct_reproduces_the_app_live():
    misses = _misses(LIVE_MATCHUPS)
    assert not misses, f"app-style win % off the app's own live numbers (last = ours): {misses}"


def test_app_win_pct_is_symmetric():
    for _w, a, b, _app in APP_MATCHUPS:
        assert abs(gametime.app_win_pct(a, b) + gametime.app_win_pct(b, a) - 1.0) < 1e-12
    assert gametime.app_win_pct(120.0, 120.0) == 0.5


def test_exponent_sits_inside_the_fitted_range():
    # Every k in this range reproduces all 40; nudging past either edge breaks one.
    assert 3.751 <= gametime.APP_WIN_EXPONENT <= 3.764


def test_column_names():
    assert len(gametime.WIN_PCT_COLUMNS) == 21
    assert "Pre-week Win % (Sleeper Projection)" in gametime.WIN_PCT_COLUMNS
    assert "Win % overcome entering last game (Enhanced Projection)" in gametime.WIN_PCT_COLUMNS
    assert gametime.comeback_names("Sleeper")[0] == "Comeback size (Sleeper Projection)"
    assert len(gametime.PROJECTION_COMEBACK_COLUMNS) == 8


if __name__ == "__main__":
    # Fit report first, so a failing row still shows what exponent would fit.
    print("APP_WIN_EXPONENT =", gametime.APP_WIN_EXPONENT)
    print("pre-week fits k in", exponent_range(APP_MATCHUPS))
    if LIVE_MATCHUPS:
        print("live fits k in", exponent_range(LIVE_MATCHUPS))
        print("both fit k in", exponent_range(APP_MATCHUPS + LIVE_MATCHUPS))
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
