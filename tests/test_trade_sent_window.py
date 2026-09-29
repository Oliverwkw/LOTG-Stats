"""Trades' "Avg PPG of sent players over same time" window cap.

The sent side is measured from the trade until the last received player (or
player drafted with a received pick) leaves, to today when one is still here or
nothing but picks / FAAB came back. `_sent_window_end` stops every window
_SENT_WINDOW_YEARS calendar years after the trade.

Run: PYTHONPATH=src:lib python tests/test_trade_sent_window.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

import lotg  # noqa: E402


def check_cap_applies_four_calendar_years_on():
    # Lazard to shmuel256 for picks + FAAB: runs to today, capped 2028-10-07.
    got = lotg._sent_window_end("2024-10-07", "2099-01-01")
    ok = lotg._SENT_WINDOW_YEARS == 4 and got == "2028-10-07"
    print(f"  2024-10-07 -> today(2099) capped at {got}: {'ok' if ok else 'FAIL'}")
    return ok


def check_earlier_end_is_kept():
    cases = [("2023-10-05", "2025-08-17", "2025-08-17"),   # a received player left first
             ("2026-07-10", "2026-09-29", "2026-09-29"),   # today, inside the cap
             ("2020-09-09", "2024-09-09", "2024-09-09")]   # exactly at the cap
    ok = True
    for trade, end, want in cases:
        got = lotg._sent_window_end(trade, end)
        good = got == want
        ok &= good
        print(f"  {trade} -> {end}: {got} {'ok' if good else f'FAIL (want {want})'}")
    return ok


def check_leap_day_and_timestamps():
    cases = [("2024-02-29", "2099-01-01", "2028-02-29"),   # leap year to leap year
             ("2020-02-29", "2099-01-01", "2024-02-29"),
             ("2023-02-28", "2099-01-01", "2027-02-28"),
             ("2022-09-22 02:10:27", "2099-01-01", "2026-09-22")]
    ok = True
    for trade, end, want in cases:
        got = lotg._sent_window_end(trade, end)
        good = got == want
        ok &= good
        print(f"  {trade}: {got} {'ok' if good else f'FAIL (want {want})'}")
    # Feb 29 onto a non-leap year falls back to Feb 28.
    saved = lotg._SENT_WINDOW_YEARS
    try:
        lotg._SENT_WINDOW_YEARS = 3
        got = lotg._sent_window_end("2024-02-29", "2099-01-01")
    finally:
        lotg._SENT_WINDOW_YEARS = saved
    good = got == "2027-02-28"
    print(f"  2024-02-29 +3y: {got} {'ok' if good else 'FAIL (want 2027-02-28)'}")
    return ok and good


def check_unparseable_trade_day_leaves_end_alone():
    got = lotg._sent_window_end("", "2026-09-29")
    ok = got == "2026-09-29"
    print(f"  blank trade day: {got} {'ok' if ok else 'FAIL'}")
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_cap_applies_four_calendar_years_on,
              check_earlier_end_is_kept,
              check_leap_day_and_timestamps,
              check_unparseable_trade_day_leaves_end_alone):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_trade_sent_window():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
