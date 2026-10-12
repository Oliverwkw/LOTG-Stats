"""App-style win % (lotg_support.gametime.app_win_pct) against the Sleeper app.

The 40 matchups of 2026 weeks 5-14 as the lineups stood on 2026-10-07: the two
Sleeper-projected totals and the win % the app showed for the first team, read
off the app by the user (totals confirmed equal to the app's). APP_WIN_EXPONENT
must reproduce every one to the whole percent. LIVE_MATCHUPS: the app mid-week
(points so far in), which APP_TIME_POWER must match too.
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


# The app's LIVE win % during 2026 week 5, read off the app by the user
# [2026-10-10 / 11]: (when, A's projected total, A's points so far, B's
# projected total, B's points so far, the app's win % for A). The app shows
# 1-99% until the matchup is over.
LIVE_MATCHUPS = [
    ("Sat 11:25", 140.57, 0.00, 105.17, 0.00, 75), ("Sat 11:25", 165.25, 0.00, 168.36, 59.50, 48),
    ("Sat 11:25", 156.54, 14.20, 169.22, 13.86, 42), ("Sat 11:25", 140.94, 15.54, 99.71, 0.00, 80),
    ("Sun 11:19", 141.03, 0.00, 100.35, 9.06, 79), ("Sun 11:19", 163.86, 0.00, 168.63, 59.50, 47),
    ("Sun 11:19", 147.88, 31.94, 86.22, 6.60, 91), ("Sun 11:19", 162.38, 14.20, 170.11, 13.86, 45),
    ("Sun 12:59", 142.43, 0.00, 101.13, 19.74, 79), ("Sun 12:59", 163.73, 0.00, 178.87, 59.50, 41),
    ("Sun 12:59", 157.61, 45.94, 91.44, 18.40, 92), ("Sun 12:59", 162.62, 14.20, 169.97, 13.86, 46),
    ("Sun 13:14", 143.56, 8.30, 99.50, 24.44, 82), ("Sun 13:14", 173.90, 17.40, 175.75, 61.92, 49),
    ("Sun 13:14", 155.02, 45.94, 90.13, 20.90, 92), ("Sun 13:14", 157.27, 20.30, 171.10, 17.76, 42),
    ("Sun 19:46", 130.54, 114.76, 87.44, 87.44, 99), ("Sun 19:46", 138.84, 103.54, 208.23, 197.98, 1),
    ("Sun 19:46", 167.46, 127.72, 62.04, 62.04, 99), ("Sun 19:46", 191.05, 170.26, 165.74, 93.06, 77),
]


def _live(r, k=None, power=None):
    """Our app-style % (unrounded, 0-100) for a LIVE_MATCHUPS row; k / power
    override APP_WIN_EXPONENT / APP_TIME_POWER for the fit report."""
    _w, a, sa, b, sb, _app = r
    done = (sa + sb) / (a + b)
    if k is None:
        return 100 * gametime.app_win_pct(a, b, done)
    kk = k / (1 - done) ** power
    return min(max(100 / (1 + (b / a) ** kk), 1), 99)


def _pct(a, b, k):
    return round(100 / (1 + (b / a) ** k))


def exponent_range(rows, lo=2.0, hi=6.0, step=0.001):
    """(lowest, highest) pre-week exponent reproducing every APP_MATCHUPS-style
    row (week, A, B, app %) to the whole percent, or None."""
    ks = [round(lo + i * step, 3) for i in range(int((hi - lo) / step) + 1)]
    ok = [k for k in ks if all(_pct(r[-3], r[-2], k) == r[-1] for r in rows)]
    return (ok[0], ok[-1]) if ok else None


def live_fit(rows=None, ks=None, powers=None):
    """[(misses, k, power)] best first: how many of APP_MATCHUPS + `rows` each
    (k, time power) leaves off the app's whole percent."""
    rows = LIVE_MATCHUPS if rows is None else rows
    ks = ks or [round(3.70 + i * 0.001, 3) for i in range(121)]
    powers = powers or [round(0.3 + i * 0.01, 2) for i in range(61)]
    allr = [(w, a, 0.0, b, 0.0, p) for w, a, b, p in APP_MATCHUPS] + list(rows)
    out = [(sum(round(_live(r, k, pw)) != r[-1] for r in allr), k, pw) for k in ks for pw in powers]
    return sorted(out)


def test_app_win_pct_reproduces_the_app():
    misses = [(w, a, b, app, round(100 * gametime.app_win_pct(a, b))) for w, a, b, app in APP_MATCHUPS
              if round(100 * gametime.app_win_pct(a, b)) != app]
    assert not misses, f"app-style win % off the app's own pre-week numbers (last = ours): {misses}"


def test_app_win_pct_reproduces_the_app_live():
    # Every live reading to the whole percent, but one: Saturday's 80 for
    # AceMatthew, 79.47 here — two hundredths short of rounding up (no (k, power)
    # fits all 60; 59 is the best there is).
    misses = [r + (round(_live(r), 2),) for r in LIVE_MATCHUPS if round(_live(r)) != r[-1]]
    assert len(misses) <= 1, misses
    assert all(abs(m[-1] - m[-2]) < 0.6 for m in misses), misses


def test_the_app_holds_1_to_99_and_grows_surer():
    assert gametime.app_win_pct(200.0, 50.0) == 0.99 and gametime.app_win_pct(50.0, 200.0) == 0.01
    # the same 10% edge reads surer the more of the week is played
    p = [gametime.app_win_pct(110.0, 100.0, f) for f in (0.0, 0.3, 0.6, 0.9)]
    assert p == sorted(p) and p[0] < p[-1]
    assert gametime.app_exponent(0.0) == gametime.APP_WIN_EXPONENT


def test_app_win_pct_is_symmetric():
    for _w, a, b, _app in APP_MATCHUPS:
        assert abs(gametime.app_win_pct(a, b) + gametime.app_win_pct(b, a) - 1.0) < 1e-12
    assert gametime.app_win_pct(120.0, 120.0) == 0.5


def test_exponent_sits_inside_the_fitted_range():
    # Every k in this range reproduces all 40 pre-week readings; with the live
    # ones, (3.751-3.763) x time power (0.60-0.62) leave only the one miss.
    assert 3.751 <= gametime.APP_WIN_EXPONENT <= 3.763
    assert 0.60 <= gametime.APP_TIME_POWER <= 0.62


def test_column_names():
    assert len(gametime.WIN_PCT_COLUMNS) == 21
    assert "Pre-week Win % (Sleeper Projection)" in gametime.WIN_PCT_COLUMNS
    assert "Win % overcome entering last game (Enhanced Projection)" in gametime.WIN_PCT_COLUMNS
    assert gametime.comeback_names("Sleeper")[0] == "Comeback size (Sleeper Projection)"
    assert len(gametime.PROJECTION_COMEBACK_COLUMNS) == 8


if __name__ == "__main__":
    # Fit report first, so a failing row still shows what exponent would fit.
    print("APP_WIN_EXPONENT =", gametime.APP_WIN_EXPONENT)
    print("APP_TIME_POWER =", gametime.APP_TIME_POWER)
    print("pre-week fits k in", exponent_range(APP_MATCHUPS))
    fit = live_fit()
    best = [f for f in fit if f[0] == fit[0][0]]
    print(f"with the {len(LIVE_MATCHUPS)} live readings: best leaves {fit[0][0]} of "
          f"{len(APP_MATCHUPS) + len(LIVE_MATCHUPS)} off, at k {min(f[1] for f in best)}-{max(f[1] for f in best)}, "
          f"time power {min(f[2] for f in best)}-{max(f[2] for f in best)}")
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
