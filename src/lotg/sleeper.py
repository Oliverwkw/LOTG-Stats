from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
import requests

from .utils import HttpConfig, get_json

BASE = "https://api.sleeper.app/v1"

Json = Union[Dict[str, Any], List[Any]]

class SleeperClient:
    """Thin wrapper around Sleeper v1 endpoints used by LOTG.

    Keep methods small and explicit so missing endpoints fail loudly in CI.
    """

    def __init__(self, http: HttpConfig):
        self.http = http
        self.s = requests.Session()

    # -----------------
    # League endpoints
    # -----------------
    def league(self, league_id: str) -> Dict[str, Any]:
        return get_json(f"{BASE}/league/{league_id}", self.http, self.s)

    def users(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/users", self.http, self.s)

    def rosters(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/rosters", self.http, self.s)

    def matchups(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/matchups/{int(week)}", self.http, self.s)

    def transactions(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/transactions/{int(week)}", self.http, self.s)

    def traded_picks(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/traded_picks", self.http, self.s)

    # Draft
    def drafts(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/drafts", self.http, self.s)

    def draft_picks(self, draft_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/draft/{draft_id}/picks", self.http, self.s)

    # Brackets
    def winners_bracket(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/winners_bracket", self.http, self.s)

    def losers_bracket(self, league_id: str) -> List[Dict[str, Any]]:
        return get_json(f"{BASE}/league/{league_id}/losers_bracket", self.http, self.s)

    # Players
    def players_nfl(self) -> Dict[str, Any]:
        return get_json(f"{BASE}/players/nfl", self.http, self.s)

    # NFL stats
    def nfl_stats_week(self, season: int, week: int, season_type: str = "regular") -> Dict[str, Any]:
        season = int(season)
        week = int(week)
        st = str(season_type or "regular").lower()
        return get_json(f"{BASE}/stats/nfl/{st}/{season}/{week}", self.http, self.s)
