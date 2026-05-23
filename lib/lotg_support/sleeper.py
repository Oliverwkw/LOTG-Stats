from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .utils import HttpConfig, BuildLogger, fetch_json


@dataclass
class SleeperClient:
    league_id: str
    cfg: HttpConfig
    logger: Optional[BuildLogger] = None
    base: str = "https://api.sleeper.app/v1"

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base}{path}"

    def get(self, path: str) -> Optional[Any]:
        return fetch_json(self._url(path), self.cfg, self.logger)

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
