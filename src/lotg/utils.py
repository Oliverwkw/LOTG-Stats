from __future__ import annotations
import time, random, re, json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Iterable

import requests

@dataclass
class HttpConfig:
    timeout_seconds: int = 30
    max_retries: int = 8
    backoff_base_seconds: float = 0.7

def _sleep_backoff(base: float, attempt: int) -> None:
    delay = base * (2 ** attempt) * (0.6 + random.random() * 0.8)
    time.sleep(min(delay, 25))

def get_json(url: str, cfg: HttpConfig, session: Optional[requests.Session] = None) -> Any:
    s = session or requests.Session()
    last_err: Optional[Exception] = None
    for attempt in range(cfg.max_retries):
        try:
            r = s.get(url, timeout=cfg.timeout_seconds, headers={"Accept":"application/json"})
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                _sleep_backoff(cfg.backoff_base_seconds, attempt)
                continue
            raise RuntimeError(f"HTTP {r.status_code} {url} :: {r.text[:250]}")
        except Exception as e:
            last_err = e
            _sleep_backoff(cfg.backoff_base_seconds, attempt)
    raise RuntimeError(f"Failed after retries: {url} :: {last_err}")

def clean_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def safe_div(a: float, b: float) -> float | None:
    try:
        if b == 0:
            return None
        return a / b
    except Exception:
        return None

def percentile_rank(values: Iterable[float], x: float) -> float:
    arr = sorted([float(v) for v in values])
    if not arr:
        return 0.0
    lt = sum(1 for v in arr if v < x)
    eq = sum(1 for v in arr if v == x)
    return (lt + 0.5*eq) / len(arr)


# --------------------------
# Simple build logger
# --------------------------

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict as _Dict, Optional as _Optional

@dataclass
class _BuildLogger:
    path: Path

    def _write(self, level: str, msg: str, fields: _Optional[_Dict[str, Any]] = None) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rec = {
                "ts": time.time(),
                "level": level,
                "msg": msg,
                "fields": fields or {},
            }
            line = json.dumps(rec, ensure_ascii=False)
            print(f"[{level}] {msg} | {rec['fields']}")
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # last resort: never crash the build because logging failed
            try:
                print(f"[{level}] {msg}")
            except Exception:
                pass

    def info(self, msg: str, **fields: Any) -> None:
        self._write("INFO", msg, fields)

    def warn(self, msg: str, **fields: Any) -> None:
        self._write("WARN", msg, fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._write("ERROR", msg, fields)

def get_logger(path: Path) -> _BuildLogger:
    """Create a logger that prints and also writes JSONL to the given file path."""
    return _BuildLogger(path=path)
