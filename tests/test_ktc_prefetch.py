"""KTC history prefetch: several downloads at once, same cache files and values
as the one-at-a-time loop (user, 2026-09-30 — build runtime).

Runs under pytest and directly as `python tests/test_ktc_prefetch.py`. No network:
the HTTP call is replaced with a stub."""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from lotg_support import ktc  # noqa: E402


def _stub(calls, delay=0.0, fail=()):
    lock = threading.Lock()

    def get(url):
        nm = url.rsplit("/", 1)[-1]
        with lock:
            calls.append(nm)
        time.sleep(delay)
        if nm in fail:
            raise OSError("boom")
        return [{"date": "2026-09-01", "sf_trade_value": len(nm)}]
    return get


def test_prefetch_fetches_only_stale_and_writes_same_files():
    calls = []
    real = ktc._http_get_json
    ktc._http_get_json = _stub(calls)
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            players = ktc._cache_dir(root) / "players"
            (players / "fresh.json").write_text(json.dumps([{"date": "x"}]))
            n = ktc.prefetch_histories(root, ["a", "bb", "fresh", "a", ""], workers=4)
            assert n == 2, n
            assert sorted(calls) == ["a", "bb"], calls           # fresh file not refetched
            assert json.loads((players / "bb.json").read_text()) == \
                [{"date": "2026-09-01", "sf_trade_value": 2}]
            calls.clear()
            assert ktc.load_history(root, "bb")[0]["sf_trade_value"] == 2
            assert calls == []                                    # serial pass reads the cache
    finally:
        ktc._http_get_json = real


def test_prefetch_runs_concurrently():
    calls = []
    real = ktc._http_get_json
    ktc._http_get_json = _stub(calls, delay=0.2)
    try:
        with tempfile.TemporaryDirectory() as d:
            t0 = time.time()
            ktc.prefetch_histories(Path(d), [f"p{i}" for i in range(12)], workers=6)
            took = time.time() - t0
            assert took < 1.5, f"12 x 0.2s fetches took {took:.2f}s — not concurrent"
    finally:
        ktc._http_get_json = real


def test_failed_fetch_keeps_cached_copy():
    calls = []
    real = ktc._http_get_json
    ktc._http_get_json = _stub(calls, fail={"old"})
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            f = ktc._cache_dir(root) / "players" / "old.json"
            f.write_text(json.dumps([{"date": "2020-01-01", "sf_trade_value": 9}]))
            os.utime(f, (0, 0))                                   # make it stale
            ktc.prefetch_histories(root, ["old"], workers=3)
            assert json.loads(f.read_text())[0]["sf_trade_value"] == 9
    finally:
        ktc._http_get_json = real


if __name__ == "__main__":
    test_prefetch_fetches_only_stale_and_writes_same_files()
    test_prefetch_runs_concurrently()
    test_failed_fetch_keeps_cached_copy()
    print("ok")
