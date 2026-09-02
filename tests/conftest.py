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
