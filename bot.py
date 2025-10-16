
import os
import json
from typing import Optional, List

import discord
from discord.ext import commands
from dotenv import load_dotenv

CONFIG_PATH = "config.json"
DATA_PATH = "data.json"


# ------------- Persistence -------------
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


# ------------- Config and per guild data -------------
config = load_json(CONFIG_PATH, {"default_prefix": "!", "owner_ids": []})
data = load_json(DATA_PATH, {})

# data structure per guild id, as string
# {
#   "prefix": "!",
#   "enabled": true,
#   "log_channel_id": 0,
#   "watchlist": [user_id, ...]
# }


def gset(guild: discord.Guild) -> dict:
    gid = str(guild.id)
    if gid not in data:
        data[gid] = {
            "prefix": config.get("default_prefix", "!"),
            "enabled": True,
            "log_channel_id": 0,
            "watchlist": []
        }
    return data[gid]


def save_data():
    save_json(DATA_PATH, data)


# ------------- Intents and prefix -------------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True


def prefix_getter(bot, message):
    if not message.guild:
        return config.get("default_prefix", "!")
    return gset(message.guild).get("prefix", config.get("default_prefix", "!"))


bot = commands.Bot(command_prefix=prefix_getter, intents=intents)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")


# ------------- Permissions helpers -------------
def has_manage_guild():
    async def predicate(ctx: commands.Context):
        if ctx.author.id in config.get("owner_ids", []):
            return True
        return ctx.author.guild_permissions.manage_guild
    return commands.check(predicate)


def role_is_admin(role: discord.Role) -> bool:
    perms = role.permissions
    return perms.administrator


async def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    gs = gset(guild)
    cid = gs.get("log_channel_id") or 0
    return guild.get_channel(cid) if cid else None


async def log(guild: discord.Guild, text: str):
    ch = await get_log_channel(guild)
    if ch:
        try:
            await ch.send(text)
        except Exception:
            pass


async def strip_admin_roles(member: discord.Member, reason: str) -> List[discord.Role]:
    removed = []
    me = member.guild.me
    if me is None:
        return removed
    if not member.guild.me.guild_permissions.manage_roles:
        return removed

    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.is_default():
            continue
        if role_is_admin(role):
            if me.top_role > role:
                try:
                    await member.remove_roles(role, reason=reason)
                    removed.append(role)
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass
    return removed


async def kick_member(member: discord.Member, reason: str) -> bool:
    if not member.guild.me.guild_permissions.kick_members:
        return False
    try:
        await member.kick(reason=reason)
        return True
    except discord.Forbidden:
        return False
    except discord.HTTPException:
        return False


# ------------- Core guard logic -------------
async def enforce_guard(member: discord.Member, join_event: bool = True):
    guild = member.guild
    gs = gset(guild)
    if not gs.get("enabled", True):
        return

    if member.id not in gs.get("watchlist", []):
        return

    reason = f"Guard enforcement, watchlisted join, join_event={join_event}"
    removed = await strip_admin_roles(member, reason)
    kicked = await kick_member(member, reason)

    removed_txt = ", ".join([r.name for r in removed]) if removed else "none"
    action = f"Removed admin roles: {removed_txt}. "
    action += "Kicked." if kicked else "Kick failed or no permission."

    await log(guild, f"⚠️ Guard action on {member.mention} ({member.id}). {action}")


# ------------- Events -------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Guarding your server"))
    for g in bot.guilds:
        gset(g)
    save_data()


@bot.event
async def on_guild_join(guild: discord.Guild):
    gset(guild)
    save_data()


@bot.event
async def on_member_join(member: discord.Member):
    await enforce_guard(member, join_event=True)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    try:
        b_admin = any(role_is_admin(r) for r in before.roles)
        a_admin = any(role_is_admin(r) for r in after.roles)
        if a_admin and not b_admin:
            await enforce_guard(after, join_event=False)
    except Exception:
        pass


# ------------- Converters -------------
async def to_user_id(ctx: commands.Context, token: str) -> Optional[int]:
    token = token.strip()
    if token.startswith("<@") and token.endswith(">"):
        token = token.replace("<@", "").replace("<@!", "").replace(">", "")
    if token.isdigit():
        return int(token)
    member = ctx.guild.get_member_named(token)
    if member:
        return member.id
    try:
        user = await bot.fetch_user(int(token))
        return user.id
    except Exception:
        return None


# ------------- Commands -------------
@bot.group(name="guard", invoke_without_command=True)
@has_manage_guild()
async def guard_group(ctx: commands.Context):
    gid = str(ctx.guild.id)
    gs = gset(ctx.guild)
    await ctx.send(
        f"Guard is {'enabled' if gs.get('enabled', True) else 'disabled'}. "
        f"Prefix: `{gs.get('prefix')}`. "
        f"Watchlist count: {len(gs.get('watchlist', []))}. "
        f"Log channel: {gs.get('log_channel_id') or 'not set'}."
    )


@guard_group.command(name="enable")
@has_manage_guild()
async def guard_enable(ctx: commands.Context):
    gs = gset(ctx.guild)
    gs["enabled"] = True
    save_data()
    await ctx.send("Guard enabled.")


@guard_group.command(name="disable")
@has_manage_guild()
async def guard_disable(ctx: commands.Context):
    gs = gset(ctx.guild)
    gs["enabled"] = False
    save_data()
    await ctx.send("Guard disabled.")


@guard_group.command(name="setlog")
@has_manage_guild()
async def guard_setlog(ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
    gs = gset(ctx.guild)
    if channel is None:
        gs["log_channel_id"] = 0
        await ctx.send("Log channel cleared.")
    else:
        gs["log_channel_id"] = channel.id
        await ctx.send(f"Log channel set to {channel.mention}.")
    save_data()


@guard_group.command(name="add")
@has_manage_guild()
async def guard_add(ctx: commands.Context, *, who: str):
    uid = await to_user_id(ctx, who)
    if not uid:
        await ctx.send("Could not parse that user or bot.")
        return
    gs = gset(ctx.guild)
    if uid in gs["watchlist"]:
        await ctx.send(f"{uid} is already on the watchlist.")
        return
    gs["watchlist"].append(uid)
    save_data()
    await ctx.send(f"Added `{uid}` to the watchlist.")
    await log(ctx.guild, f"➕ Watchlist add by {ctx.author.mention}: `{uid}`")


@guard_group.command(name="remove")
@has_manage_guild()
async def guard_remove(ctx: commands.Context, *, who: str):
    uid = await to_user_id(ctx, who)
    if not uid:
        await ctx.send("Could not parse that user or bot.")
        return
    gs = gset(ctx.guild)
    if uid not in gs["watchlist"]:
        await ctx.send(f"{uid} is not on the watchlist.")
        return
    gs["watchlist"].remove(uid)
    save_data()
    await ctx.send(f"Removed `{uid}` from the watchlist.")
    await log(ctx.guild, f"➖ Watchlist remove by {ctx.author.mention}: `{uid}`")


@guard_group.command(name="list")
@has_manage_guild()
async def guard_list(ctx: commands.Context):
    gs = gset(ctx.guild)
    wl = gs.get("watchlist", [])
    if not wl:
        await ctx.send("Watchlist is empty.")
        return
    lines = []
    for uid in wl[:50]:
        display = str(uid)
        user = ctx.guild.get_member(uid) or bot.get_user(uid)
        if user:
            display = f"{user} ({uid})"
        lines.append(display)
    more = "" if len(wl) <= 50 else f"\n... and {len(wl) - 50} more"
    await ctx.send("Watchlist:\n" + "\n".join(lines) + more)


@commands.guild_only()
@bot.command(name="setprefix")
@has_manage_guild()
async def setprefix(ctx: commands.Context, prefix: str):
    if not prefix or len(prefix) > 5:
        await ctx.send("Provide a prefix 1 to 5 characters.")
        return
    gs = gset(ctx.guild)
    gs["prefix"] = prefix
    save_data()
    await ctx.send(f"Prefix updated to `{prefix}`")


@commands.guild_only()
@bot.command(name="status")
async def status_cmd(ctx: commands.Context):
    gs = gset(ctx.guild)
    await ctx.send(
        f"Enabled: {gs.get('enabled', True)}\n"
        f"Prefix: `{gs.get('prefix')}`\n"
        f"Watchlist size: {len(gs.get('watchlist', []))}\n"
        f"Log channel id: {gs.get('log_channel_id') or 'not set'}"
    )


@commands.guild_only()
@bot.command(name="testkick")
@has_manage_guild()
async def testkick(ctx: commands.Context, member: discord.Member):
    if member == ctx.guild.me:
        await ctx.send("I will not kick myself.")
        return
    await enforce_guard(member, join_event=False)
    await ctx.send("Enforcement attempted. Check the log channel for details.")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Add it to a .env file or your environment.")
    bot.run(TOKEN)
