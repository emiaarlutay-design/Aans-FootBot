"""
Simple async FotMob client using unofficial endpoints.
Endpoints can change – monitor and update as needed.
"""
import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("fotmob")

BASE = "https://www.fotmob.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.fotmob.com/",
    "Origin": "https://www.fotmob.com",
}


class FotMobClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=HEADERS)
        return self

    async def __aexit__(self, *args):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        if not self.session:
            self.session = aiohttp.ClientSession(headers=HEADERS)
        url = f"{BASE}{path}"
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"FotMob {resp.status} for {url}")
                return None
        except Exception as e:
            logger.error(f"Request failed {url}: {e}")
            return None

    async def get_matches_by_date(self, date_str: Optional[str] = None, timezone: str = "UTC") -> Dict:
        """date_str = YYYYMMDD. Returns leagues with matches (live scores, status, etc.)."""
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        return await self._get("/data/matches", {"date": date_str, "timezone": timezone, "ccode3": "GBR"}) or {}

    async def get_match_details(self, match_id: int | str) -> Dict:
        return await self._get("/data/matchDetails", {"matchId": match_id}) or {}

    async def search(self, term: str, hits: int = 20) -> List[Dict]:
        """Search teams, leagues, players, etc."""
        # Common working search path (may vary)
        data = await self._get("/data/search", {"term": term, "lang": "en"}) 
        if not data:
            # Fallback / alternative
            data = await self._get("/searchapi/suggest", {"term": term, "lang": "en"})
        if isinstance(data, list) and data:
            return data[0].get("suggestions", data) if isinstance(data[0], dict) else data
        if isinstance(data, dict):
            return data.get("suggestions", data.get("results", []))
        return []

    async def search_teams(self, term: str) -> List[Dict]:
        results = await self.search(term)
        return [r for r in results if r.get("type") == "team" or "team" in str(r.get("type", "")).lower()]

    async def search_leagues(self, term: str) -> List[Dict]:
        results = await self.search(term)
        return [r for r in results if r.get("type") in ("league", "competition") or "league" in str(r.get("type", "")).lower()]

    def parse_match_summary(self, match: Dict) -> Dict:
        """Normalize a match object from /matches endpoint."""
        status = match.get("status") or {}
        home = match.get("home") or {}
        away = match.get("away") or {}
        return {
            "id": match.get("id"),
            "home_id": home.get("id"),
            "away_id": away.get("id"),
            "home_name": home.get("name") or home.get("longName"),
            "away_name": away.get("name") or away.get("longName"),
            "home_score": home.get("score"),
            "away_score": away.get("score"),
            "score_str": status.get("scoreStr") or f"{home.get('score', '-')} - {away.get('score', '-')}",
            "status": status,
            "started": status.get("started", False),
            "finished": status.get("finished", False),
            "utc": status.get("utcTime"),
            "league_id": match.get("leagueId"),
            "time_str": match.get("time"),
            "raw": match,
        }

    async def get_live_and_today(self) -> List[Dict]:
        """Convenience: today's matches that are live or recent."""
        data = await self.get_matches_by_date()
        matches = []
        for league in data.get("leagues", []):
            lid = league.get("id") or league.get("primaryId")
            lname = league.get("name")
            for m in league.get("matches", []):
                parsed = self.parse_match_summary(m)
                parsed["league_name"] = lname
                parsed["league_id"] = lid
                matches.append(parsed)
        return matches
