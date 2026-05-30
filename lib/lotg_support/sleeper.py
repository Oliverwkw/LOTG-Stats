from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import HttpConfig, BuildLogger, fetch_json


@dataclass
class SleeperClient:
    league_id: str
    cfg: HttpConfig
    logger: Optional[BuildLogger] = None
    base: str = "https://api.sleeper.app/v1"
    # On-disk JSON cache for immutable Sleeper responses (historical leagues,
    # completed drafts, etc.). When unset, behaves as before — every call hits
    # the API. Caller passes `repo_root / ".cache" / "sleeper"`; the same
    # `.cache/` tree is restored across CI runs by the workflow's actions/cache
    # step (see .github/workflows/build.yml).
    cache_dir: Optional[Path] = None
    # URL substrings that should NEVER be cached — anything tied to the
    # current league (mutable each week: rosters, transactions, matchups)
    # plus /players/nfl (mutable as NFL rosters churn). Populated from
    # `league_id` on first use.
    _no_cache_markers: List[str] = field(default_factory=list)

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base}{path}"

    def _should_cache(self, url: str) -> bool:
        if self.cache_dir is None:
            return False
        if not self._no_cache_markers:
            # Build the skip-list lazily so callers can mutate league_id post-init.
            self._no_cache_markers = [
                f"/league/{self.league_id}",
                "/players/nfl",
            ]
        return not any(m in url for m in self._no_cache_markers)

    def _cache_path(self, url: str) -> Path:
        # sha1 is plenty for path-shortening (not a security boundary).
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        assert self.cache_dir is not None
        return self.cache_dir / f"{h}.json"

    def get(self, path: str) -> Optional[Any]:
        url = self._url(path)
        if self._should_cache(url):
            cp = self._cache_path(url)
            if cp.exists() and cp.stat().st_size > 0:
                try:
                    return json.loads(cp.read_text())
                except Exception:
                    pass  # corrupt cache file — fall through to refetch
            data = fetch_json(url, self.cfg, self.logger)
            if data is not None:
                try:
                    cp.parent.mkdir(parents=True, exist_ok=True)
                    cp.write_text(json.dumps(data))
                except Exception:
                    pass  # cache write failure should never break the build
            return data
        return fetch_json(url, self.cfg, self.logger)

    # Core league endpoints
    def league(self, league_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        lid = league_id or self.league_id
        return self.get(f"/league/{lid}")

    def users(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        lid = league_id or self.league_id
        return self.get(f"/league/{lid}/users") or []

    def rosters(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        lid = league_id or self.league_id
        return self.get(f"/league/{lid}/rosters") or []

    def matchups(self, week: int, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        lid = league_id or self.league_id
        return self.get(f"/league/{lid}/matchups/{week}") or []

    def transactions(self, week: int, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        lid = league_id or self.league_id
        return self.get(f"/league/{lid}/transactions/{week}") or []

    def traded_picks(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        lid = league_id or self.league_id
        return self.get(f"/league/{lid}/traded_picks") or []

    def drafts(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        lid = league_id or self.league_id
        return self.get(f"/league/{lid}/drafts") or []

    def draft_picks(self, draft_id: str) -> List[Dict[str, Any]]:
        return self.get(f"/draft/{draft_id}/picks") or []

    def draft(self, draft_id: str) -> Dict[str, Any]:
        """Full draft object — includes `slot_to_roster_id`, which the
        /league/{id}/drafts list endpoint omits."""
        return self.get(f"/draft/{draft_id}") or {}

    def players_nfl(self) -> Dict[str, Any]:
        return self.get("/players/nfl") or {}

    # Dynasty chain
    def league_chain(self) -> List[str]:
        chain: List[str] = []
        curr = self.league_id
        while curr:
            chain.append(curr)
            info = self.league(curr) or {}
            prev = info.get("previous_league_id")
            if not prev:
                break
            curr = str(prev)
        return chain
