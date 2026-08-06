import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from fotmob_client import FotMobClient
from storage import GuildStorage

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))  # seconds – aim for 10-30s latency
DEV_GUILD_ID = os.getenv("GUILD_ID")  # optional, for instant command sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AansFootBot")

intents = discord.Intents.default()
intents.message_content = False  # not required for pure slash
bot = commands.Bot(command_prefix="!", intents=intents)

# Cache of GuildStorage
storages: Dict[int, GuildStorage] = {}


def get_storage(guild_id: int) -> GuildStorage:
    if guild_id not in storages:
        storages[guild_id] = GuildStorage(guild_id)
    return storages[guild_id]


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (Aans FootBot)")
    try:
        if DEV_GUILD_ID:
            guild = discord.Object(id=int(DEV_GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            logger.info(f"Synced commands to guild {DEV_GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} global commands")
    except Exception as e:
        logger.error(f"Command sync failed: {e}")

    if not score_poller.is_running():
        score_poller.start()


# ========== SLASH COMMANDS ==========

@bot.tree.command(name="setchannel", description="Set the channel where FootBot sends score updates")
@app_commands.describe(channel="The text channel for notifications")
@app_commands.checks.has_permissions(manage_guild=True)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    storage = get_storage(interaction.guild_id)
    await storage.set_channel(channel.id)
    await interaction.response.send_message(
        f"✅ Notification channel set to {channel.mention}. I will post live scores & goals here.",
        ephemeral=True,
    )


@bot.tree.command(name="follow_team", description="Follow a team for live score updates")
@app_commands.describe(query="Team name (e.g. Arsenal, Real Madrid)")
async def follow_team(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    async with FotMobClient() as fm:
        results = await fm.search_teams(query)
    if not results:
        # Fallback: try broader search and filter
        async with FotMobClient() as fm:
            all_res = await fm.search(query)
        results = [r for r in all_res if "team" in str(r.get("type", "")).lower() or r.get("id")]

    if not results:
        await interaction.followup.send(f"No teams found for `{query}`. Try a more precise name.", ephemeral=True)
        return

    # Take best match (first)
    team = results[0]
    team_id = team.get("id") or team.get("payload", {}).get("id") or team.get("entityId")
    name = team.get("name") or team.get("title") or team.get("payload", {}).get("name") or query

    if not team_id:
        await interaction.followup.send("Could not extract team ID. Try again or use a different query.", ephemeral=True)
        return

    storage = get_storage(interaction.guild_id)
    await storage.follow_team(team_id, name)
    await interaction.followup.send(f"✅ Now following **{name}** (ID: {team_id}).", ephemeral=True)


@bot.tree.command(name="unfollow_team", description="Stop following a team")
@app_commands.describe(team_id="The team ID (see /list)")
async def unfollow_team(interaction: discord.Interaction, team_id: str):
    storage = get_storage(interaction.guild_id)
    await storage.unfollow_team(team_id)
    await interaction.response.send_message(f"Unfollowed team `{team_id}`.", ephemeral=True)


@bot.tree.command(name="follow_league", description="Follow a league or competition")
@app_commands.describe(query="League/competition name (e.g. Premier League, Champions League)")
async def follow_league(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    async with FotMobClient() as fm:
        results = await fm.search_leagues(query)
    if not results:
        async with FotMobClient() as fm:
            all_res = await fm.search(query)
        results = [r for r in all_res if any(k in str(r.get("type", "")).lower() for k in ("league", "competition", "cup"))]

    if not results:
        await interaction.followup.send(f"No leagues/competitions found for `{query}`.", ephemeral=True)
        return

    item = results[0]
    lid = item.get("id") or item.get("payload", {}).get("id") or item.get("entityId")
    name = item.get("name") or item.get("title") or item.get("payload", {}).get("name") or query

    if not lid:
        await interaction.followup.send("Could not extract ID.", ephemeral=True)
        return

    storage = get_storage(interaction.guild_id)
    await storage.follow_league(lid, name)
    await interaction.followup.send(f"✅ Now following **{name}** (ID: {lid}).", ephemeral=True)


@bot.tree.command(name="unfollow_league", description="Stop following a league/competition")
@app_commands.describe(league_id="The league/competition ID (see /list)")
async def unfollow_league(interaction: discord.Interaction, league_id: str):
    storage = get_storage(interaction.guild_id)
    await storage.unfollow_league(league_id)
    await interaction.response.send_message(f"Unfollowed `{league_id}`.", ephemeral=True)


@bot.tree.command(name="list", description="Show currently followed teams and leagues")
async def list_followed(interaction: discord.Interaction):
    storage = get_storage(interaction.guild_id)
    teams = storage.get_followed_teams()
    leagues = storage.get_followed_leagues()
    ch = storage.get_channel()

    embed = discord.Embed(title="Aans FootBot – Followed", color=0x00A86B)
    embed.add_field(
        name="Notification Channel",
        value=f"<#{ch}>" if ch else "Not set (use `/setchannel`)",
        inline=False,
    )
    embed.add_field(
        name="Teams",
        value="\n".join(f"• **{n}** (`{i}`)" for i, n in teams.items()) or "None",
        inline=False,
    )
    embed.add_field(
        name="Leagues / Competitions",
        value="\n".join(f"• **{n}** (`{i}`)" for i, n in leagues.items()) or "None",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="live", description="Show current live scores for followed teams/leagues")
async def live(interaction: discord.Interaction):
    await interaction.response.defer()
    storage = get_storage(interaction.guild_id)
    teams = set(storage.get_followed_teams().keys())
    leagues = set(storage.get_followed_leagues().keys())

    async with FotMobClient() as fm:
        all_matches = await fm.get_live_and_today()

    relevant = []
    for m in all_matches:
        if not (m.get("started") and not m.get("finished")):
            continue
        mid_home = str(m.get("home_id"))
        mid_away = str(m.get("away_id"))
        lid = str(m.get("league_id"))
        if mid_home in teams or mid_away in teams or lid in leagues:
            relevant.append(m)

    if not relevant:
        await interaction.followup.send("No live matches right now for your followed teams/leagues.")
        return

    embed = discord.Embed(
        title="🔴 Live Scores – Aans FootBot",
        description=f"Updated near real-time (poll ~{POLL_INTERVAL}s)",
        color=0xE74C3C,
        timestamp=datetime.now(timezone.utc),
    )
    for m in relevant[:15]:  # limit
        status = m.get("status") or {}
        minute = ""
        # Try to extract live minute if present
        if status.get("liveTime"):
            minute = f" ({status['liveTime'].get('short', '')})"
        elif not m.get("finished"):
            minute = " (LIVE)"

        embed.add_field(
            name=f"{m.get('league_name', 'League')}",
            value=f"**{m['home_name']}** {m['score_str']} **{m['away_name']}**{minute}",
            inline=False,
        )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="fixtures", description="Today's fixtures for followed items")
async def fixtures(interaction: discord.Interaction):
    await interaction.response.defer()
    storage = get_storage(interaction.guild_id)
    teams = set(storage.get_followed_teams().keys())
    leagues = set(storage.get_followed_leagues().keys())

    async with FotMobClient() as fm:
        all_matches = await fm.get_live_and_today()

    relevant = []
    for m in all_matches:
        mid_home = str(m.get("home_id"))
        mid_away = str(m.get("away_id"))
        lid = str(m.get("league_id"))
        if mid_home in teams or mid_away in teams or lid in leagues:
            relevant.append(m)

    if not relevant:
        await interaction.followup.send("No fixtures today for your followed teams/leagues.")
        return

    embed = discord.Embed(title="📅 Today's Fixtures – Aans FootBot", color=0x3498DB)
    for m in sorted(relevant, key=lambda x: x.get("utc") or "")[:20]:
        status_txt = "FT" if m.get("finished") else ("LIVE" if m.get("started") else m.get("time_str", "Scheduled"))
        embed.add_field(
            name=f"{m.get('league_name')}",
            value=f"{m['home_name']} vs {m['away_name']} — **{m['score_str']}** ({status_txt})",
            inline=False,
        )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="help_footbot", description="How to use Aans FootBot")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Aans FootBot Help",
        description="Football live scores powered by FotMob (unofficial).",
        color=0x00A86B,
    )
    embed.add_field(
        name="Setup",
        value="1. `/setchannel #your-channel`\n2. `/follow_team Arsenal`\n3. `/follow_league Premier League`",
        inline=False,
    )
    embed.add_field(
        name="Commands",
        value=(
            "`/setchannel` – where I post updates\n"
            "`/follow_team` / `/unfollow_team`\n"
            "`/follow_league` / `/unfollow_league` (also competitions)\n"
            "`/list` – see what you follow\n"
            "`/live` – current live scores\n"
            "`/fixtures` – today’s matches\n"
            "`/help_footbot` – this message"
        ),
        inline=False,
    )
    embed.add_field(
        name="Accuracy",
        value=f"I poll every **{POLL_INTERVAL} seconds** when relevant matches are live. Expect 10–30s delay typically. Goals and score changes are detected and posted automatically.",
        inline=False,
    )
    embed.set_footer(text="Unofficial FotMob data • May break if API changes")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ========== BACKGROUND POLLER (near real-time) ==========

@tasks.loop(seconds=POLL_INTERVAL)
async def score_poller():
    """Poll FotMob frequently and push goal/score updates to configured channels."""
    if not bot.is_ready():
        return

    try:
        async with FotMobClient() as fm:
            all_matches = await fm.get_live_and_today()
    except Exception as e:
        logger.error(f"Poll fetch failed: {e}")
        return

    # Build quick lookup
    live_or_recent = [m for m in all_matches if m.get("started")]

    for guild in bot.guilds:
        storage = get_storage(guild.id)
        channel_id = storage.get_channel()
        if not channel_id:
            continue

        channel = bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            continue

        teams = set(storage.get_followed_teams().keys())
        leagues = set(storage.get_followed_leagues().keys())
        if not teams and not leagues:
            continue

        for m in live_or_recent:
            mid = str(m.get("id"))
            home_id = str(m.get("home_id"))
            away_id = str(m.get("away_id"))
            lid = str(m.get("league_id"))

            if not (home_id in teams or away_id in teams or lid in leagues):
                continue

            home_score = m.get("home_score")
            away_score = m.get("away_score")
            prev = storage.get_last_score(mid)

            # First time seeing it
            if prev is None:
                await storage.update_last_score(mid, home_score, away_score)
                if m.get("started") and not m.get("finished"):
                    # Optional: announce kickoff
                    try:
                        embed = discord.Embed(
                            title="Kick-off!",
                            description=f"**{m['home_name']}** vs **{m['away_name']}**\n{m.get('league_name')}",
                            color=0x2ECC71,
                        )
                        await channel.send(embed=embed)
                    except Exception:
                        pass
                continue

            # Score changed?
            if prev.get("home") != home_score or prev.get("away") != away_score:
                # Fetch details for goal scorer if possible
                goal_info = ""
                try:
                    details = await fm.get_match_details(mid)
                    events = (
                        details.get("content", {})
                        .get("matchFacts", {})
                        .get("events", {})
                        .get("events", [])
                    )
                    # Find newest Goal
                    for ev in reversed(events or []):
                        if ev.get("type") == "Goal":
                            player = ev.get("nameStr") or ev.get("player", {}).get("name") or "Unknown"
                            minute = ev.get("timeStr") or ev.get("time")
                            is_home = ev.get("isHome")
                            team_name = m["home_name"] if is_home else m["away_name"]
                            goal_info = f"⚽ **GOAL!** {player} ({minute}') – {team_name}"
                            break
                except Exception as e:
                    logger.debug(f"Details fetch failed: {e}")

                color = 0xE74C3C if m.get("started") and not m.get("finished") else 0x95A5A6
                embed = discord.Embed(
                    title="Score Update" if not goal_info else "GOAL!",
                    description=goal_info or "Score changed",
                    color=color,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(
                    name=m.get("league_name", "Match"),
                    value=f"**{m['home_name']}** {home_score} - {away_score} **{m['away_name']}**",
                    inline=False,
                )
                if m.get("finished"):
                    embed.set_footer(text="Full Time")
                else:
                    embed.set_footer(text=f"Live • polled every {POLL_INTERVAL}s")

                try:
                    await channel.send(embed=embed)
                except discord.HTTPException as e:
                    logger.warning(f"Could not send to {channel_id}: {e}")

                await storage.update_last_score(mid, home_score, away_score)

            # Clean finished matches from tracking after a while (optional)
            if m.get("finished") and prev:
                # Keep for a bit then you can prune
                pass


@score_poller.before_loop
async def before_poller():
    await bot.wait_until_ready()
    logger.info(f"Score poller started (interval={POLL_INTERVAL}s)")


# Error handler for commands
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need Manage Server permission for that.", ephemeral=True)
    else:
        logger.error(f"Command error: {error}")
        try:
            await interaction.response.send_message("Something went wrong. Try again later.", ephemeral=True)
        except Exception:
            pass


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set DISCORD_TOKEN in .env")
    bot.run(TOKEN)
