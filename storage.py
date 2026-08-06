import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


class GuildStorage:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.path = DATA_DIR / f"{guild_id}.json"
        self._lock = asyncio.Lock()
        self.data = self._load()

    def _load(self) -> Dict:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "notification_channel": None,
            "followed_teams": {},      # id -> name
            "followed_leagues": {},    # id -> name  (covers competitions too)
            "last_scores": {},         # match_id -> {"home": x, "away": y, "events": [...]}
            "settings": {"poll_enabled": True},
        }

    async def save(self):
        async with self._lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get_channel(self) -> Optional[int]:
        return self.data.get("notification_channel")

    async def set_channel(self, channel_id: int):
        self.data["notification_channel"] = channel_id
        await self.save()

    async def follow_team(self, team_id: int | str, name: str):
        self.data["followed_teams"][str(team_id)] = name
        await self.save()

    async def unfollow_team(self, team_id: int | str):
        self.data["followed_teams"].pop(str(team_id), None)
        await self.save()

    async def follow_league(self, league_id: int | str, name: str):
        self.data["followed_leagues"][str(league_id)] = name
        await self.save()

    async def unfollow_league(self, league_id: int | str):
        self.data["followed_leagues"].pop(str(league_id), None)
        await self.save()

    def get_followed_teams(self) -> Dict[str, str]:
        return self.data.get("followed_teams", {})

    def get_followed_leagues(self) -> Dict[str, str]:
        return self.data.get("followed_leagues", {})

    def get_last_score(self, match_id: str) -> Optional[Dict]:
        return self.data.get("last_scores", {}).get(str(match_id))

    async def update_last_score(self, match_id: str, home: Any, away: Any, events: List = None):
        self.data.setdefault("last_scores", {})[str(match_id)] = {
            "home": home,
            "away": away,
            "events": events or [],
        }
        # Keep last_scores from growing forever – prune old finished ones periodically if needed
        await self.save()
