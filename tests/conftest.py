"""Suite-wide fixtures. Chiefly: the tests do not touch the network.

`lotg_support.external` re-downloads any cache file past
`CACHE_MAX_AGE_DAYS`, which is what keeps the Tuesday build's data under a week
old. The committed `.cache` is months older than that by design — it is a
cold-start seed, not a live copy — so a test that reaches a loader against the
repo's own `.cache` would now pull ~156MB before asserting anything, on every
run, in CI included. `tests/test_contracts.py` re-scores league points straight
out of `.cache/nflverse_stats_player_week_*.csv` and does exactly that.

Hermeticism belongs to the suite, not the loaders, so it is pinned here rather
than by weakening the horizon: the tests replay the committed cache as-is.
`tests/test_refresh_external.py` is the one place the horizon itself is under
test, and it sets the variable per case around this default.
"""
from __future__ import annotations

import functools
import json
import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _offline_cache_horizon():
    prior = os.environ.get("LOTG_CACHE_MAX_AGE_DAYS")
    os.environ["LOTG_CACHE_MAX_AGE_DAYS"] = "36500"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("LOTG_CACHE_MAX_AGE_DAYS", None)
        else:
            os.environ["LOTG_CACHE_MAX_AGE_DAYS"] = prior


@pytest.fixture(autouse=True)
def _skips_are_skips(request, monkeypatch):
    """Make each module's `_skip(reason)` a real pytest skip.

    The helper prints and returns True so the files also run as plain scripts
    (`python tests/test_x.py`). Under pytest that return was a PASS: on the
    2026-09-23 health run six `test_contracts.py` data tests had never run in
    CI (no contracts file cached) and reported PASSED, visible only as
    PytestReturnNotNoneWarning noise. A skip has to say so, with its reason, so
    the health email can list it.
    """
    mod = request.module
    if callable(getattr(mod, "_skip", None)):
        def _skip(reason: str) -> bool:
            print(f"  SKIP — {reason}")
            pytest.skip(reason)
        monkeypatch.setattr(mod, "_skip", _skip)


@pytest.hookimpl(wrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """Fail a test that RETURNS a value instead of letting it pass.

    A returned value is almost always a skip helper that returned rather than
    skipped (see `_skips_are_skips`), and pytest counts it as a pass with only a
    warning. Done here rather than as a `filterwarnings = error::…` entry,
    because that entry names a pytest-internal warning class: were a pytest
    upgrade to rename it, the filter would abort the whole run at startup and
    the weekly health email would lose its test section."""
    fn = pyfuncitem.obj

    @functools.wraps(fn)
    def _checked(*args, **kwargs):
        result = fn(*args, **kwargs)
        if result is not None:
            pytest.fail(f"{pyfuncitem.name} returned {result!r} instead of "
                        "asserting or skipping — pytest would have counted it "
                        "as a pass", pytrace=False)

    pyfuncitem.obj = _checked
    try:
        return (yield)
    finally:
        pyfuncitem.obj = fn


# ---------------------------------------------------------------------------
# Machine-readable results for the weekly health email
# ---------------------------------------------------------------------------
# scripts/audit_weekly.py (Part 3) needs every test's outcome and every skip's
# REASON. pytest's console format is not a contract — pytest 8's `-v` lines
# carry no skip reason, and its `-rs` summary files every one of ours under
# conftest.py, where `_skip` raises — so the suite writes its own record when
# LOTG_TEST_RESULTS names a path. `complete` is written only at session end: a
# file without it is a suite that crashed.
_RESULTS: list = []


def pytest_runtest_logreport(report):
    if report.when == "call" or report.outcome != "passed":
        reason = ""
        if report.skipped and isinstance(report.longrepr, tuple):
            reason = str(report.longrepr[2])
            if reason.startswith("Skipped: "):
                reason = reason[len("Skipped: "):]
        outcome = report.outcome
        if report.failed and report.when != "call":
            outcome = "error"          # a fixture blew up, not an assertion
        _RESULTS.append({"test": report.nodeid, "outcome": outcome, "reason": reason})


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("LOTG_TEST_RESULTS")
    if not out:
        return
    try:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w") as fh:
            json.dump({"complete": True, "exitstatus": int(exitstatus),
                       "results": _RESULTS}, fh, indent=1)
    except OSError:
        pass
