from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests


@dataclass
class HttpConfig:
    timeout_seconds: int = 30
    max_retries: int = 8
    backoff_base_seconds: float = 0.7
    user_agent: str = "LOTG-Stats/1.0 (+https://sleeper.app)"


def _sleep_backoff(base: float, attempt: int) -> None:
    # exponential backoff with jitter, capped
    delay = base * (2 ** attempt) * (0.6 + random.random() * 0.8)
    time.sleep(min(delay, 25))


class BuildLogger:
    """Small logger that prints and also writes JSONL for CI debugging."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def _write(self, level: str, msg: str, fields: Dict[str, Any]) -> None:
        rec = {"ts": time.time(), "level": level, "msg": msg, **(fields or {})}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        print(f"{level}: {msg} {fields if fields else ''}")
        self._fh.write(line + "\n")
        self._fh.flush()

    def info(self, msg: str, **fields: Any) -> None:
        self._write("INFO", msg, fields)

    def warn(self, msg: str, **fields: Any) -> None:
        self._write("WARN", msg, fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._write("ERROR", msg, fields)


def get_logger(path: Path) -> BuildLogger:
    return BuildLogger(path)


def fetch_json(url: str, cfg: HttpConfig, logger: Optional[BuildLogger] = None) -> Optional[Any]:
    """GET JSON with retries. Returns parsed object or None."""
    headers = {"User-Agent": cfg.user_agent, "Accept": "application/json"}
    last_status = None
    for attempt in range(cfg.max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=cfg.timeout_seconds)
            last_status = resp.status_code
            if resp.status_code == 200:
                # Sleeper sometimes returns empty string; guard.
                if not resp.text:
                    return None
                return resp.json()
            # retryable statuses
            if resp.status_code in (429, 500, 502, 503, 504):
                if logger:
                    logger.warn("fetch_json retryable status", url=url, status=resp.status_code, attempt=attempt)
                _sleep_backoff(cfg.backoff_base_seconds, attempt)
                continue
            if logger:
                logger.error("fetch_json non-200", url=url, status=resp.status_code, body=resp.text[:2000])
            return None
        except requests.RequestException as e:
            if logger:
                logger.warn("fetch_json request exception", url=url, err=str(e), attempt=attempt)
            _sleep_backoff(cfg.backoff_base_seconds, attempt)
    if logger:
        logger.error("fetch_json exhausted retries", url=url, last_status=last_status)
    return None


def normalize_player_id(pid: Any) -> str:
    """Sleeper player_id keys are strings; normalize."""
    if pid is None:
        return ""
    return str(pid).strip()


def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


_slug_re = re.compile(r"[^a-zA-Z0-9_]+")


def slug(s: str) -> str:
    return _slug_re.sub("_", (s or "").strip())


def safe_float(x: Any, default: float = 0.0) -> float:
    """Convert a value to float; return default if conversion fails."""
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def safe_div(a: Any, b: Any, default: float = 0.0) -> float:
    """Safely divide a by b.

    Many rollups use ratios (efficiency, win%, etc.). In production we prefer
    deterministic defaults over aborting the entire build.
    """
    aa = safe_float(a, default=None)
    bb = safe_float(b, default=None)
    if aa is None or bb is None or bb == 0.0:
        return default
    return aa / bb


def safe_bool(x: Any, default: bool = False) -> bool:
    """Best-effort conversion to bool for mixed Sleeper/pandas values."""
    if x is None:
        return default
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(int(x))
    s = str(x).strip().lower()
    if s in ("true", "t", "yes", "y", "1"):
        return True
    if s in ("false", "f", "no", "n", "0", ""):
        return False
    return default


def clamp01(x: Any, default: float = 0.0) -> float:
    """Clamp numeric value into [0,1]."""
    v = safe_float(x, default=default)
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def clean_name(s: Any) -> str:
    """Normalize a display/name string for stable comparisons and keys."""
    if s is None:
        return ""
    out = str(s).strip()
    # collapse internal whitespace
    out = re.sub(r"\s+", " ", out)
    return out

