from __future__ import annotations
from typing import Any, Dict, List
import requests
from .utils import HttpConfig, get_json

BASE = "https://api.sleeper.app/v1"

class SleeperClient:
    def __init__(self, http: HttpConfig):
        self.http = http
        self.s = requests.Session()

    def league(self, league_id: str) -> Dict[str, Any]:
        return get_json(f"{BASE}/league/{league_id}", self.http, self.s)

    def users(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/users", self.http, self.s)

    def rosters(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/rosters", self.http, self.s)

    def matchups(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/matchups/{week}", self.http, self.s)

    def transactions(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/transactions/{week}", self.http, self.s)

    def traded_picks(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/traded_picks", self.http, self.s)

    def drafts(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/drafts", self.http, self.s)

    def draft_picks(self, draft_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/draft/{draft_id}/picks", self.http, self.s)

    def players_nfl(self) -> Dict[str, Any]:
        return get_json(f"{BASE}/players/nfl", self.http, self.s)
def winners_bracket(self, league_id: str):
    return self._get(f"/league/{league_id}/winners_bracket")

def losers_bracket(self, league_id: str):
    return self._get(f"/league/{league_id}/losers_bracket")
