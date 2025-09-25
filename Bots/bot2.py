# ===============
# bot2.py  (Bot 2)
# ===============
# - This file runs ONLY Bot 2.
# - Command prefix: ?

import discord
from discord.ext import commands, tasks
from discord.ui import View, button, Button
import asyncio
import re
import aiohttp
import os
import json
import random
import sqlite3
import io
import time
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
from collections import deque
from typing import Optional, Tuple


# -------- Intents --------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

# ===== WARNINGS CONFIG =====
WARN_TIMEOUT_AT_3_DAYS = 2  # 2 days at 3 warnings
WARN_TIMEOUT_AT_5_DAYS = 3  # 3 days at 5 warnings
WARN_RESET_AT_5 = True      # reset to 0 after applying the 5-warning timeout
WARN_LOG_CHANNEL_ID = 1411283522131591178  # <- your log channel


# === Configure which commands are "warnings commands" ===
# 🔁 Update these names to match your actual warning commands.
WARNING_COMMAND_NAMES = {"warn", "warnings", "clearwarnings"}

# -------- Create bot2 --------
bot2 = commands.Bot(command_prefix=commands.when_mentioned_or("?", "!"), intents=intents)


# =========================
# CORE EVENTS
# =========================

# Quick health check command
@bot2.command()
async def ping(ctx):
    await ctx.reply("Pong from Bot 2!")

# =========================
# ALL THE BOT 2 LOGIC BELOW

def warning_only():
    """Allow this command only when called with the '!' prefix."""
    async def predicate(ctx: commands.Context):
        return ctx.prefix == "!"
    return commands.check(predicate)

@bot2.check
async def prefix_gate(ctx: commands.Context) -> bool:
    """
    Enforce prefix rules:
      - If the command is a warnings command -> must use '!'
      - Otherwise -> must use '?'
    """
    if ctx.command is None:
        return False  # no command resolved
    cmd_name = ctx.command.qualified_name  # includes group name if any
    if cmd_name in WARNING_COMMAND_NAMES:
        return ctx.prefix == "!"
    return ctx.prefix == "?"

@bot2.event
async def on_command_error(ctx: commands.Context, error):
    # Give a helpful hint if user used the wrong prefix
    from discord.ext.commands import CheckFailure, CommandNotFound
    if isinstance(error, CheckFailure):
        cmd = ctx.invoked_with or (ctx.command.qualified_name if ctx.command else "that")
        if cmd in WARNING_COMMAND_NAMES:
            return await ctx.reply(f"`!{cmd}` must be used with the `!` prefix.")
        else:
            return await ctx.reply(f"`?{cmd}` must be used with the `?` prefix.")
    if isinstance(error, CommandNotFound):
        # Optional: stay quiet or give a soft hint
        return
    # Optionally re-raise or log others
    raise error



# ===== WARNINGS HELPERS =====



async def _apply_timeout(member: discord.Member, days: int, reason: str | None = None):
    try:
        until = datetime.now(timezone.utc) + timedelta(days=days)
        # Pass `until` as a positional arg—no `until=`
        await member.timeout(until, reason=reason or "Automated timeout triggered by warnings")
        return True, until
    except Exception as e:
        return False, str(e)

async def _remove_timeout(member: discord.Member, reason: str | None = None):
    try:
        # Remove timeout: pass None as a positional arg, not `until=None`
        await member.timeout(None, reason=reason or "Warnings reset")
        return True, None
    except Exception as e:
        return False, str(e)



def _get_warn_log_channel(guild: discord.Guild):
    # Only valid inside the guild that actually has the channel
    ch = guild.get_channel(WARN_LOG_CHANNEL_ID)
    return ch

async def _send_warn_log(guild: discord.Guild, embed: discord.Embed | None = None, text: str | None = None):
    ch = _get_warn_log_channel(guild)
    if not ch:
        print(f"[WARNINGS] Log channel {WARN_LOG_CHANNEL_ID} not found in guild {guild.id}")
        return
    try:
        if embed:
            await ch.send(embed=embed)
        elif text:
            await ch.send(text)
    except Exception as e:
        print(f"[WARNINGS] Failed to send log to {WARN_LOG_CHANNEL_ID} in guild {guild.id}: {e}")

async def cancel_match(guild: discord.Guild, admin_msg_id: int, reason: str = "Cancelled by admin", actor: discord.Member | None = None):
    """
    Cancels an in-progress 1v1 without recording a result.
    - Marks the match as resolved
    - Cleans up temp text/voice/category channels if present
    - Updates the admin results message to reflect cancellation
    - Notifies players in the private text room
    - Edits the public announce card to show 'CANCELLED'
    """
    match = MATCHES.get(admin_msg_id)
    if not match or match.get("resolved"):
        return False

    a_id = match.get("a")
    b_id = match.get("b")
    a_member = guild.get_member(a_id) if a_id else None
    b_member = guild.get_member(b_id) if b_id else None

    # Mark resolved to stop any later processing
    match["resolved"] = True

    # 1) Admin results message → mark CANCELLED
    try:
        admin_chan = guild.get_channel(WIN_REPORT_CHANNEL_ID)
        if isinstance(admin_chan, (discord.TextChannel, discord.Thread)):
            admin_msg = await admin_chan.fetch_message(admin_msg_id)
            new_content = f"~~{admin_msg.content}~~\n**⛔ Match CANCELLED.** {reason}"
            if admin_msg.embeds:
                from copy import deepcopy
                emb = deepcopy(admin_msg.embeds[0])
                emb.title = (emb.title or "Match") + " — CANCELLED"
                await admin_msg.edit(content=new_content, embed=emb)
            else:
                await admin_msg.edit(content=new_content)
            try:
                await admin_msg.clear_reactions()
            except Exception:
                pass
    except Exception:
        pass

    # 2) Notify in the private text room (if it exists)
    try:
        text_id = match.get("text_chan_id") or match.get("text_channel_id") or match.get("channel_id")
        if text_id:
            room = guild.get_channel(text_id)
            if isinstance(room, (discord.TextChannel, discord.Thread)):
                tag_a = a_member.mention if a_member else f"<@{a_id}>"
                tag_b = b_member.mention if b_member else f"<@{b_id}>"
                admin_tag = actor.mention if actor else "an admin"
                await room.send(f"{tag_a} {tag_b} — **This 1v1 has been cancelled by {admin_tag}.** Reason: {reason}")
    except Exception:
        pass

    # 3) Public announce card → edit to CANCELLED if present
    try:
        ann_id = match.get("announce_msg_id")
        ann_ch_id = match.get("announce_ch_id")
        if ann_id and ann_ch_id:
            ann_ch = guild.get_channel(ann_ch_id) or await guild.fetch_channel(ann_ch_id)
            if isinstance(ann_ch, (discord.TextChannel, discord.Thread)):
                ann_msg = await ann_ch.fetch_message(ann_id)
                # prefer editing the embed if any
                if ann_msg.embeds:
                    from copy import deepcopy
                    pub = deepcopy(ann_msg.embeds[0])
                    pub.title = (pub.title or "1v1") + " — CANCELLED"
                    pub.set_footer(text=f"Cancelled by {actor.display_name if actor else 'admin'}")
                    await ann_msg.edit(content="**⛔ This match was CANCELLED by admin.**", embed=pub)
                else:
                    await ann_msg.edit(content="**⛔ This match was CANCELLED by admin.**")
    except Exception:
        pass

    # 4) Clean up private text/voice/category if any
    for key in ("text_chan_id", "text_channel_id", "private_text_channel_id", "match_text_channel_id", "channel_id"):
        try:
            ch_id = match.get(key)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    await ch.delete(reason="1v1 cancelled")
        except Exception:
            pass

    for key in ("voice_chan_id", "voice_channel_id", "temp_voice_channel_id", "voice_id"):
        try:
            vc_id = match.get(key)
            if vc_id:
                vc = guild.get_channel(vc_id)
                if isinstance(vc, discord.VoiceChannel):
                    await vc.delete(reason="1v1 cancelled")
        except Exception:
            pass

    try:
        cat_id = match.get("category_id")
        if cat_id:
            cat = guild.get_channel(cat_id)
            if isinstance(cat, discord.CategoryChannel):
                await cat.delete(reason="1v1 cancelled")
    except Exception:
        pass

    # 5) Remove from registry
    try:
        MATCHES.pop(admin_msg_id, None)
    except Exception:
        pass

    return True



async def create_1v1_rooms(
    guild: discord.Guild,
    player1: discord.Member,
    player2: discord.Member,
    base_channel: discord.abc.GuildChannel
) -> Tuple[Optional[int], Optional[int]]:
    """Create a private text + voice channel visible only to p1, p2, bot, and admins."""
    try:
        category = guild.get_channel(ONEVONE_CATEGORY_ID) if ONEVONE_CATEGORY_ID else None
        if category is None and hasattr(base_channel, "category"):
            category = base_channel.category

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),

            player1: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True
            ),
            player2: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True
            ),

            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, manage_messages=True, connect=True, speak=True
            ),
        }

        # Optional admin role visibility
        admin_role = guild.get_role(ADMIN_ROLE_ID) if 'ADMIN_ROLE_ID' in globals() else None
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=True, connect=True, speak=True
            )

        safe_name = f"{player1.display_name}-vs-{player2.display_name}".replace(" ", "-")[:90]

        text_chan = await guild.create_text_channel(
            name=safe_name,
            overwrites=overwrites,
            category=category,
            reason="1v1 match room (text)"
        )
        voice_chan = await guild.create_voice_channel(
            name=f"VC-{safe_name}",
            overwrites=overwrites,
            category=category,
            reason="1v1 match room (voice)"
        )

        return text_chan.id, voice_chan.id

    except discord.Forbidden:
        print("[1v1] Missing permissions to create channels.")
    except discord.HTTPException as e:
        print(f"[1v1] Failed to create channels: {e}")

    return None, None


async def cleanup_1v1_rooms(guild: discord.Guild, text_id: Optional[int], voice_id: Optional[int], delay_seconds: int = 180):
    """Delete the given text/voice channels after a delay."""
    await asyncio.sleep(delay_seconds)
    for chan_id in (text_id, voice_id):
        if chan_id:
            chan = guild.get_channel(chan_id)
            if chan:
                try:
                    await chan.delete(reason="1v1 match finished (auto-cleanup)")
                except discord.HTTPException:
                    pass


async def arm_match_timeout(guild: discord.Guild, match_id: int, timeout_min: int = 90):
    """Safety net: remove 1v1 rooms if the match never gets confirmed."""
    await asyncio.sleep(timeout_min * 60)
    match = MATCHES.get(match_id)
    if match and not match.get("resolved"):
        await cleanup_1v1_rooms(guild, match.get("text_chan_id"), match.get("voice_chan_id"), delay_seconds=0)
        match["timed_out"] = True


def load_color_message_id_from_db(guild_id: int):
    global MESSAGE_ID
    saved = get_setting(guild_id, COLOR_MSG_KEY)
    MESSAGE_ID = int(saved) if saved and saved.isdigit() else None


async def save_leaderboard_message_id(msg_id: int, guild_id: int):
    global LEADERBOARD_MESSAGE_ID
    LEADERBOARD_MESSAGE_ID = msg_id
    set_setting(guild_id, LB_KEY, str(int(msg_id)))

async def _fetch_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.read()

# DROP-IN REPLACEMENT (same signature)
async def render_leaderboard_image(rows, guild) -> io.BytesIO:
    """
    rows: [{'user_id': int, 'points': int, 'wins': int, 'losses': int, 'streak': int}, ...]
    guild: discord.Guild
    """
    # Layout
    pad_x = 32
    pad_y = 24
    row_h = 92
    avatar_size = 72
    col_rank_w = 80
    col_name_w = 480
    col_points_w = 160
    col_wins_w = 140
    col_losses_w = 160
    col_streak_w = 160
    col_rankname_w = 200  # width for Rank (Elite/Pro/Master/Grand Master/Legendary)

    width = (
        pad_x*2
        + col_rank_w + col_name_w + col_points_w + col_wins_w
        + col_losses_w + col_streak_w + col_rankname_w
    )
    height = pad_y*2 + row_h*(len(rows)+1)  # + header row

    bg = Image.new("RGBA", (width, height), (18, 18, 20, 255))
    draw = ImageDraw.Draw(bg)
    font_header = _load_font(30)
    font = _load_font(26)
    font_small = _load_font(22)

    # Header bar
    header_y = pad_y
    draw.rounded_rectangle(
        (pad_x, header_y, width - pad_x, header_y + row_h),
        radius=18, fill=(35, 35, 40, 255)
    )

    # Column titles
    def col_title(x_start, label):
        draw.text((x_start+12, header_y + row_h/2), label, font=font_header,
                  fill=(235, 235, 240, 255), anchor="lm")

    col_x = {
        "rank":     pad_x,
        "name":     pad_x + col_rank_w,
        "points":   pad_x + col_rank_w + col_name_w,
        "wins":     pad_x + col_rank_w + col_name_w + col_points_w,
        "losses":   pad_x + col_rank_w + col_name_w + col_points_w + col_wins_w,
        "streak":   pad_x + col_rank_w + col_name_w + col_points_w + col_wins_w + col_losses_w,
        "rankname": pad_x + col_rank_w + col_name_w + col_points_w + col_wins_w + col_losses_w + col_streak_w,
    }
    col_title(col_x["rank"],   "#")
    col_title(col_x["name"],   "Player")
    col_title(col_x["points"], "Points")
    col_title(col_x["wins"],   "Wins")
    col_title(col_x["losses"], "Losses")
    col_title(col_x["streak"], "Streak")
    col_title(col_x["rankname"], "Rank")

    # Rows
    y = header_y + row_h
    for i, r in enumerate(rows, start=1):
        # zebra
        if i % 2 == 0:
            draw.rounded_rectangle((pad_x, y, width - pad_x, y + row_h),
                                   radius=16, fill=(28, 28, 32, 255))

        # rank #
        draw.text((col_x["rank"] + 22, y + row_h/2), str(i), font=font,
                  fill=(220, 220, 230, 255), anchor="lm")

        # --- SAFE MEMBER LOOKUP (no crashes if user left) ---
        member = guild.get_member(r["user_id"])
        if member is None:
            try:
                member = await guild.fetch_member(r["user_id"])
            except Exception:
                member = None  # covers discord.NotFound (10007) and HTTP issues

        display_name = (member.display_name if member else f"Left server ({r['user_id']})")

        # avatar (best-effort; ignore failures)
        avatar_img = None
        try:
            if member:
                avatar_url = str(member.display_avatar.replace(size=128).url)
                avatar_bytes = await _fetch_bytes(avatar_url)
                if avatar_bytes:
                    avatar_img = Image.open(io.BytesIO(avatar_bytes))
                    avatar_img = _circle_crop(avatar_img, avatar_size)
        except Exception:
            avatar_img = None

        name_x   = col_x["name"] + avatar_size + 18
        avatar_x = col_x["name"] + 8
        avatar_y = int(y + (row_h - avatar_size)/2)
        if avatar_img:
            bg.paste(avatar_img, (avatar_x, avatar_y), avatar_img)

        # primary name line
        draw.text((name_x, y + row_h/2 - 12), display_name, font=font,
                  fill=(240, 240, 245, 255), anchor="lm")

        # secondary tag
        if member and getattr(member, "global_name", None):
            draw.text((name_x, y + row_h/2 + 18), f"@{member.global_name}", font=font_small,
                      fill=(170, 170, 180, 255), anchor="lm")

        # numeric columns helper
        def col_num(x_start, value, width_guess):
            draw.text((x_start + width_guess/2, y + row_h/2), str(value), font=font,
                      fill=(230, 230, 235, 255), anchor="mm")

        col_num(col_x["points"], r.get("points", 0), col_points_w)
        col_num(col_x["wins"],   r.get("wins",   0), col_wins_w)
        col_num(col_x["losses"], r.get("losses", 0), col_losses_w)
        col_num(col_x["streak"], r.get("streak", 0), col_streak_w)

        # Rank name column
        tier_name = rank_for_points(r.get("points", 0))
        draw.text((col_x["rankname"] + col_rankname_w/2, y + row_h/2),
                  tier_name, font=font, fill=(230, 230, 235, 255), anchor="mm")

        y += row_h

    buf = io.BytesIO()
    bg.save(buf, "PNG")
    buf.seek(0)
    return buf

# --- ADD: safe member fetch everywhere ---
async def get_member_safe(guild: discord.Guild, user_id: int) -> discord.Member | None:
    m = guild.get_member(user_id)
    if m:
        return m
    try:
        return await guild.fetch_member(user_id)
    except Exception:
        return None  # covers NotFound (10007) + HTTP issues


# put near your other helpers
async def build_leaderboard_embed_and_file(guild, limit: int = 10):
    rows = get_top_rows(limit)
    if not rows:
        return None, None

    img_buf = await render_leaderboard_image(rows, guild)
    file = discord.File(img_buf, filename="leaderboard.png")

    em = discord.Embed(title="🏆 1v1 Leaderboard", color=discord.Color.blurple())
    em.set_image(url="attachment://leaderboard.png")
    em.set_footer(text="Auto-updates after results are confirmed")

    return em, file


async def refresh_leaderboard_message(guild: discord.Guild):
    # Use stored channel if set; fall back to constant
    ch_id = meta_get("leaderboard_channel_id")
    channel_id = int(ch_id) if ch_id and ch_id.isdigit() else LEADERBOARD_CHANNEL_ID

    channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
    em, file = await build_leaderboard_embed_and_file(guild, limit=10)
    if not em:
        return

    # Try to delete old message: use in‑memory ID if set, else read from SQLite
    old_id = LEADERBOARD_MESSAGE_ID
    if not old_id:
        saved = get_setting(guild.id, LB_KEY)
        old_id = int(saved) if saved and saved.isdigit() else None

    try:
        if old_id:
            old = await channel.fetch_message(old_id)
            await old.delete()
    except Exception:
        pass

    new_msg = await channel.send(embed=em, file=file)
    await save_leaderboard_message_id(new_msg.id, guild.id)

async def _notify_timeout(member: discord.Member):
    try:
        await member.send(f"⏲️ Your 1v1 queue request expired after **{_timeout_human()}** with no opponent found.")
    except Exception:
        # Fallback to guild channel if DMs are closed
        try:
            await member.guild.system_channel.send(f"⏲️ {member.mention} your 1v1 queue request expired.")
        except Exception:
            pass


async def _try_matchmake(guild: discord.Guild):
    """If at least two users are in queue, pair the first two distinct users and start the SAME flow as challenges."""
    q = _ensure_queue(guild.id)

    while len(q) >= 2:
        uid1, t1 = q.popleft()
        # ensure uid1 still queued in this guild
        if MM_INDEX.get(uid1, (None, None))[0] != guild.id:
            continue

        uid2, t2 = None, None
        while q:
            cand_uid, cand_t = q.popleft()
            if cand_uid != uid1 and MM_INDEX.get(cand_uid, (None, None))[0] == guild.id:
                uid2, t2 = cand_uid, cand_t
                break

        if uid2 is None:
            # put uid1 back; not enough distinct players
            q.appendleft((uid1, t1))
            break

        # dequeue both
        MM_INDEX.pop(uid1, None)
        MM_INDEX.pop(uid2, None)

        # 🔔 Use the SAME function used after challenge acceptance
        await start_match_from_challenge(guild, uid1, uid2)
        # loop continues to try pairing more players if available

def _now_mono() -> float:
    return time.monotonic()

def _ensure_queue(gid: int) -> deque[tuple[int, float]]:
    if gid not in MM_QUEUES:
        MM_QUEUES[gid] = deque()
    return MM_QUEUES[gid]

def _remove_from_queue(gid: int, uid: int) -> bool:
    """Remove a user from a guild queue; returns True if removed."""
    q = _ensure_queue(gid)
    removed = False
    if uid in MM_INDEX:
        # rebuild the queue without this user
        newq = deque((u, t) for (u, t) in q if u != uid)
        if len(newq) != len(q):
            MM_QUEUES[gid] = newq
            removed = True
    MM_INDEX.pop(uid, None)
    return removed



# Try to load a nicer font; fallback to default
def _load_font(size=28):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                 "/System/Library/Fonts/SFNS.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _circle_crop(im: Image.Image, size: int) -> Image.Image:
    im = im.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(im, (0, 0), mask)
    return out



def load_leaderboard_message_id_from_db(guild_id: int):
    global LEADERBOARD_MESSAGE_ID
    saved = get_setting(guild_id, LB_KEY)
    LEADERBOARD_MESSAGE_ID = int(saved) if saved and saved.isdigit() else None


async def resolve_user_display(
    bot: discord.Client,
    guild: discord.Guild,
    user_id: int
) -> Tuple[str, str]:
    """
    Return (display_name, mention) for user_id without raising.
    Handles users who left the server & API failures.
    """
    # 1) Try cache
    m = guild.get_member(user_id)
    if m:
        return (m.display_name, m.mention)

    # 2) Try API fetch (may raise 10007 if user left)
    try:
        m = await guild.fetch_member(user_id)
        return (m.display_name, m.mention)
    except discord.NotFound:
        pass
    except discord.HTTPException:
        pass

    # 3) Try global user
    u = bot.get_user(user_id)
    if not u:
        try:
            u = await bot.fetch_user(user_id)
        except discord.NotFound:
            u = None
        except discord.HTTPException:
            u = None

    # 4) Fallback strings
    if u:
        return (u.name, f"<@{user_id}>")
    return (f"Left server ({user_id})", f"<@{user_id}>")


def channel_is(*allowed_ids: int):
    def predicate(ctx: commands.Context):
        ch = ctx.channel
        ch_id = ch.id if hasattr(ch, "id") else None

        # Allow if the command is used in the exact channel
        if ch_id in allowed_ids:
            return True

        # (Optional) Allow threads whose parent is the allowed channel
        parent = getattr(ch, "parent", None)
        parent_id = getattr(parent, "id", None)
        if parent_id in allowed_ids:
            return True

        return False
    return commands.check(predicate)


def resolve_member(ctx, query: str) -> discord.Member | None:
    if not query:
        return ctx.author

    # mention or raw ID
    m = re.match(r'<@!?(\d+)>$', query) or re.match(r'^(\d{15,20})$', query)
    if m:
        return ctx.guild.get_member(int(m.group(1)))

    # exact match on username or nickname (case-insensitive)
    q = query.lower()
    for member in ctx.guild.members:
        if member.name.lower() == q or (member.nick and member.nick.lower() == q):
            return member

    # fallback: partial match
    for member in ctx.guild.members:
        if q in member.name.lower() or (member.nick and q in member.nick.lower()):
            return member

    return None


# ---------- RANKING / POINTS LOGIC ----------
def rank_for_points(points: int) -> str:
    # Veteran starts at 0 as requested; realistic jumps after that.
    if points >= 800:
        return "Legendary"
    if points >= 500:
        return "Grand Master"
    if points >= 250:
        return "Master"
    if points >= 100:
        return "Pro"
    return "Elite"

WIN_POINTS = 10
LOSS_POINTS = -10
STREAK_BONUS = 5  # applied for every win after the first (i.e., streak >= 2)


# ------- Bot 2: Color-role helpers -------
def _color_roles_in_guild(guild: discord.Guild) -> list[discord.Role]:
    """Return all colour Role objects that exist in this guild."""
    roles = []
    for rid in COLOR_ROLE_MAP.values():
        r = guild.get_role(rid)
        if r:
            roles.append(r)
    return roles

async def _ensure_single_color(member: discord.Member, new_role: discord.Role | None):
    """
    Remove any existing color roles from this member, then (optionally) add new_role.
    """
    color_roles = set(_color_roles_in_guild(member.guild))
    # Remove any color roles the user already has
    to_remove = [r for r in member.roles if r in color_roles and (new_role is None or r.id != new_role.id)]
    if to_remove:
        try:
            await member.remove_roles(*to_remove, reason="Enforcing single colour role")
        except Exception as e:
            print(f"[Bot2] Failed removing old color roles from {member.id}: {e}")
    # Add the new one if specified
    if new_role:
        try:
            await member.add_roles(new_role, reason="Selected new colour role")
        except Exception as e:
            print(f"[Bot2] Failed adding color role {new_role.id} to {member.id}: {e}")

async def _sweep_fix_duplicate_colors(guild: discord.Guild):
    color_roles = set(_color_roles_in_guild(guild))
    if not color_roles:
        return
    for member in guild.members:
        # Find all colour roles this member has
        theirs = [r for r in member.roles if r in color_roles]
        if len(theirs) > 1:
            # Keep the highest-position role (Discord typically treats higher position as “dominant”)
            keep = max(theirs, key=lambda r: r.position)
            try:
                to_remove = [r for r in theirs if r.id != keep.id]
                if to_remove:
                    await member.remove_roles(*to_remove, reason="Startup sweep: duplicate color roles")
            except Exception as e:
                print(f"[Bot2] Sweep failed for {member.id}: {e}")



# ---------- DB ----------
WARN_DB_PATH = "warnings.db"

def _warn_db():
    conn = sqlite3.connect(WARN_DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS warnings (
        guild_id INTEGER NOT NULL,
        user_id  INTEGER NOT NULL,
        count    INTEGER NOT NULL DEFAULT 0,
        last_at  TEXT,
        PRIMARY KEY (guild_id, user_id)
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS warnings_log (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id  INTEGER NOT NULL,
        mod_id   INTEGER NOT NULL,
        reason   TEXT,
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    return conn


def _init_settings():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (guild_id, key)
            )
        """)


# --- ADD ONCE (near your SQLite connection setup) ---
def clamp_points(conn, user_id: int, delta: int):
    """
    Apply a points change (+/-) but never let points drop below 0.
    Creates the player row if it doesn't exist.
    """
    cur = conn.cursor()
    cur.execute(
        "UPDATE players SET points = MAX(points + ?, 0) WHERE user_id = ?",
        (delta, user_id),
    )
    if cur.rowcount == 0:
        start_points = max(0, delta)
        cur.execute(
            "INSERT INTO players (user_id, points, wins, losses, streak) VALUES (?, ?, 0, 0, 0)",
            (user_id, start_points),
        )
    conn.commit()


def set_setting(guild_id: int, key: str, value: str):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "REPLACE INTO settings (guild_id, key, value) VALUES (?, ?, ?)",
            (guild_id, key, value)
        )

def get_setting(guild_id: int, key: str) -> str | None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "SELECT value FROM settings WHERE guild_id=? AND key=?",
            (guild_id, key)
        )
        row = cur.fetchone()
        return row[0] if row else None


def init_db():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()

        # --- Core tables ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wins (
                user_id INTEGER PRIMARY KEY,
                wins    INTEGER NOT NULL DEFAULT 0,
                points  INTEGER NOT NULL DEFAULT 0,
                streak  INTEGER NOT NULL DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                winner_id  INTEGER NOT NULL,
                loser_id   INTEGER NOT NULL,
                match_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      INTEGER NOT NULL,
                challenger_id INTEGER NOT NULL,
                opponent_id   INTEGER NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',  -- pending/accepted/declined/cancelled/expired
                created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- Meta (for persistent bot settings like leaderboard channel/message ids) ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # --- Migrations / safety (ensure columns exist if table pre-dated points/streak) ---
        cols = {r[1] for r in cur.execute("PRAGMA table_info(wins)").fetchall()}
        if "points" not in cols:
            cur.execute("ALTER TABLE wins ADD COLUMN points INTEGER NOT NULL DEFAULT 0")
        if "streak" not in cols:
            cur.execute("ALTER TABLE wins ADD COLUMN streak INTEGER NOT NULL DEFAULT 0")

        # --- Helpful indexes ---
        cur.execute("CREATE INDEX IF NOT EXISTS idx_matches_winner  ON matches(winner_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_matches_loser   ON matches(loser_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_challenges_user ON challenges(guild_id, status, challenger_id, opponent_id)")

        con.commit()


def _ensure_user_rows(con, *user_ids: int):
    for uid in user_ids:
        con.execute("INSERT OR IGNORE INTO wins (user_id) VALUES (?)", (uid,))

def record_match_and_points(winner_id: int, loser_id: int):
    """
    Applies:
    - winner: +10 points, +1 win, streak +=1, and if streak_after >=2 → +5 bonus
    - loser:  -10 points, streak = 0
    - inserts match row
    """
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        _ensure_user_rows(con, winner_id, loser_id)

        # Get current states
        cur.execute("SELECT wins, points, streak FROM wins WHERE user_id=?", (winner_id,))
        w_wins, w_pts, w_str = cur.fetchone()
        cur.execute("SELECT wins, points, streak FROM wins WHERE user_id=?", (loser_id,))
        l_wins, l_pts, l_str = cur.fetchone()

        # Winner updates
        new_wins = w_wins + 1
        new_streak = w_str + 1
        delta = WIN_POINTS + (STREAK_BONUS if new_streak >= 2 else 0)
        new_points = w_pts + delta

        # Loser updates
        l_new_points = l_pts + LOSS_POINTS
        l_new_streak = 0  # reset on loss

        # Persist
        cur.execute("UPDATE wins SET wins=?, points=?, streak=? WHERE user_id=?",
                    (new_wins, new_points, new_streak, winner_id))
        cur.execute("UPDATE wins SET points=?, streak=? WHERE user_id=?",
                    (l_new_points, l_new_streak, loser_id))
        cur.execute("INSERT INTO matches (winner_id, loser_id) VALUES (?, ?)", (winner_id, loser_id))
        con.commit()

        return {
            "winner_after": {"wins": new_wins, "points": new_points, "streak": new_streak, "delta": delta},
            "loser_after": {"wins": l_wins, "points": l_new_points, "streak": l_new_streak, "delta": LOSS_POINTS},
        }

def update_points(guild: discord.Guild, winner_id: int, loser_id: int):
    """
    Wrapper used by the reaction handler. Uses your SQLite-backed logic and
    returns the shape the handler expects, including rank labels.
    """
    res = record_match_and_points(winner_id, loser_id)
    # Attach ranks based on the NEW points
    w_pts = res["winner_after"]["points"]
    l_pts = res["loser_after"]["points"]
    res["winner_after"]["rank"] = rank_for_points(w_pts)
    res["loser_after"]["rank"]  = rank_for_points(l_pts)
    return res


def get_top_rows(limit: int = 10):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("""
            SELECT user_id, wins, points, streak
            FROM wins
            ORDER BY points DESC, wins DESC, user_id ASC
            LIMIT ?
        """, (limit,))
        rows = []
        for uid, wins, points, streak in cur.fetchall():
            cur2 = con.execute("SELECT COUNT(*) FROM matches WHERE loser_id=?", (uid,))
            losses = cur2.fetchone()[0]
            rows.append({
                "user_id": uid,
                "wins": wins,
                "points": points,
                "losses": losses,
                "streak": streak
            })
        return rows


def get_user_row(user_id: int):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT wins, points, streak FROM wins WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return (0,0,0) if not r else r

def get_leaderboard_position(user_id: int):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("""
            SELECT user_id
            FROM wins
            ORDER BY points DESC, wins DESC, user_id ASC
        """)
        pos = 1
        for (uid,) in cur.fetchall():
            if uid == user_id:
                return pos
            pos += 1
        return None

def _now(): return datetime.utcnow()

def _expired(created_at_str: str) -> bool:
    try:
        created = datetime.fromisoformat(created_at_str.replace("Z",""))
    except:
        created = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
    return _now() - created > timedelta(hours=CHALLENGE_TTL_HOURS)

def create_challenge(guild_id: int, challenger_id: int, opponent_id: int):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("""
            SELECT id, created_at FROM challenges
            WHERE guild_id=? AND status='pending'
              AND ((challenger_id=? AND opponent_id=?) OR (challenger_id=? AND opponent_id=?))
            ORDER BY id DESC LIMIT 1
        """, (guild_id, challenger_id, opponent_id, opponent_id, challenger_id))
        row = cur.fetchone()
        if row:
            cid, created_at = row
            if not _expired(created_at):
                return ("exists", cid)

        con.execute("INSERT INTO challenges (guild_id, challenger_id, opponent_id) VALUES (?, ?, ?)",
                    (guild_id, challenger_id, opponent_id))
        cur = con.execute("SELECT last_insert_rowid()")
        return ("ok", cur.fetchone()[0])

def get_latest_incoming(guild_id: int, opponent_id: int):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("""
            SELECT id, challenger_id, opponent_id, created_at
            FROM challenges
            WHERE guild_id=? AND status='pending' AND opponent_id=?
            ORDER BY id DESC LIMIT 1
        """, (guild_id, opponent_id))
        return cur.fetchone()

def get_pending_for_user(guild_id: int, user_id: int):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("""
            SELECT id, challenger_id, opponent_id, created_at
            FROM challenges
            WHERE guild_id=? AND status='pending' AND (challenger_id=? OR opponent_id=?)
            ORDER BY id DESC
        """, (guild_id, user_id, user_id))
        return cur.fetchall()

def mark_challenge_status(challenge_id: int, status: str):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE challenges SET status=? WHERE id=?", (status, challenge_id))

def meta_get(key: str) -> str | None:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

def meta_set(key: str, value: str):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

def _format_result_line(w_member, l_member, winner_id, loser_id, res=None, score:str|None=None):
    if res:
        w_pts = res["winner_after"]["points"]
        l_pts = res["loser_after"]["points"]
        w_delta = res["winner_after"]["delta"]
        l_delta = res["loser_after"]["delta"]
        w_rank = res["winner_after"].get("rank", "—")
        l_rank = res["loser_after"].get("rank", "—")
        w_strk = res["winner_after"].get("streak", None)
        score_text = f" | **Score:** {score}" if score else ""
        return (
            f"🏆 **Winner:** {w_member.mention if w_member else f'<@{winner_id}>'} "
            f"(+{w_delta} → **{w_pts}**, Tier **{w_rank}**"
            f"{' | Streak **'+str(w_strk)+'**' if w_strk is not None else ''}){score_text}\n"
            f"❌ **Loser:** {l_member.mention if l_member else f'<@{loser_id}>'} "
            f"({l_delta} → **{l_pts}**, Tier **{l_rank}**)"
        )
    else:
        score_text = f" | **Score:** {score}" if score else ""
        return (
            f"🏆 **Winner:** {w_member.mention if w_member else f'<@{winner_id}>'}{score_text}\n"
            f"❌ **Loser:** {l_member.mention if l_member else f'<@{loser_id}>'}"
        )



# ------- Bot 2: Self-role embed helpers ( -------
async def rebuild_embed(guild):
    global MESSAGE_ID
    channel = guild.get_channel(CHANNEL_ID)
    if not channel:
        return

    # If we have a saved message id, try to use it
    if MESSAGE_ID:
        try:
            msg = await channel.fetch_message(MESSAGE_ID)
            if msg and msg.author == bot2.user and msg.embeds:
                return  # panel already exists
        except Exception:
            pass

    # Try to find an existing panel in recent history
    try:
        async for message in channel.history(limit=50):
            if message.author == bot2.user and message.embeds:
                MESSAGE_ID = message.id
                # persist if key is available
                try:
                    set_setting(guild.id, COLOR_MSG_KEY, str(MESSAGE_ID))
                except Exception:
                    pass
                return
    except Exception:
        pass

    # Build a fresh panel
    embed = discord.Embed(title="🎨 Choose Your Color", color=discord.Color.blurple())
    embed.set_image(url="https://cdn.discordapp.com/attachments/1095053356478771202/1399960727661445170/image.png")

    lines = []
    for emoji_name, role_id in COLOR_ROLE_MAP.items():
        emoji = discord.utils.get(guild.emojis, name=emoji_name)
        lines.append(f"{(emoji or emoji_name)} | <@&{role_id}>")  # show name if emoji missing
    embed.description = "\n".join(lines)

    new_msg = await channel.send(embed=embed)

    # Add reactions only for emojis that exist
    for emoji_name in COLOR_ROLE_MAP:
        emoji = discord.utils.get(guild.emojis, name=emoji_name)
        if emoji:
            try:
                await new_msg.add_reaction(emoji)
            except Exception:
                pass
        else:
            print(f"[Bot2] Warning: emoji '{emoji_name}' not found; reaction skipped.")

    MESSAGE_ID = new_msg.id
    try:
        set_setting(guild.id, COLOR_MSG_KEY, str(MESSAGE_ID))  # persist for future restarts
    except Exception:
        pass


# ------- Bot 2: 1v1 flow with ADMIN CONFIRMATION -------

def build_vs_embed(guild: discord.Guild, a: discord.Member, b: discord.Member, status: str = "Pending"):
    embed = discord.Embed(
        title="⚔️ 1v1 Match",
        description=f"**{a.display_name}** vs **{b.display_name}**",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Player A", value=f"{a.mention}\n`{a.id}`", inline=True)
    embed.add_field(name="Player B", value=f"{b.mention}\n`{b.id}`", inline=True)
    embed.add_field(name="Status", value=status, inline=False)
    embed.set_footer(text="Admins: React 🅰️ if A won, 🅱️ if B won.")
    embed.set_image(url="https://media.discordapp.net/attachments/1095053356478771202/1404403393555861505/Screenshot_2025-08-11_at_10.58.38.png?format=webp&quality=lossless&width=3280&height=804")
    return embed

async def update_public_announce_embed(
    guild: discord.Guild,
    ann_ch_id: int,
    ann_msg_id: int,
    winner_id: int,
    loser_id: int,
    a_id: int,
    b_id: int,
    res: dict | None,
    reactor_name: str,
    results_image_url: str,
    score_text: str | None = None
):
    ann_ch = guild.get_channel(ann_ch_id) or await guild.fetch_channel(ann_ch_id)
    ann_msg = await ann_ch.fetch_message(ann_msg_id)

    # --- REPLACE these four lines inside update_public_announce_embed ---
    a_member = await get_member_safe(guild, a_id)
    b_member = await get_member_safe(guild, b_id)
    w_member = await get_member_safe(guild, winner_id)
    l_member = await get_member_safe(guild, loser_id)

    # Build a fresh public embed showing final result
    pub = discord.Embed(
        title="⚔️ 1v1 Result",
        description=f"**{a_member.display_name if a_member else a_id}** vs **{b_member.display_name if b_member else b_id}**",
        color=discord.Color.green()
    )

    pub.add_field(name="Player A", value=(a_member.mention if a_member else f"<@{a_id}>"), inline=True)
    pub.add_field(name="Player B", value=(b_member.mention if b_member else f"<@{b_id}>"), inline=True)

    if res:
        w_pts = res['winner_after']['points']
        l_pts = res['loser_after']['points']
        w_delta = res['winner_after']['delta']
        l_delta = res['loser_after']['delta']
        w_rank = res['winner_after'].get('rank', '—')
        l_rank = res['loser_after'].get('rank', '—')
        w_strk = res['winner_after'].get('streak', None)

        score_line = f"\n**Score:** {score_text}" if score_text else ""
        pub.add_field(
            name="Winner",
            value=f"{w_member.mention if w_member else f'<@{winner_id}>'} "
                  f"(+{w_delta} → **{w_pts}** | Tier **{w_rank}**"
                  f"{' | Streak **'+str(w_strk)+'**' if w_strk is not None else ''}){score_line}",
            inline=False
        )
        pub.add_field(
            name="Loser",
            value=f"{l_member.mention if l_member else f'<@{loser_id}>'} "
                  f"({l_delta} → **{l_pts}** | Tier **{l_rank}**)",
            inline=False
        )
    else:
        # Fallback if points update failed
        score_line = f"\n**Score:** {score_text}" if score_text else ""
        pub.add_field(name="Winner", value=(w_member.mention if w_member else f"<@{winner_id}>") + score_line, inline=False)
        pub.add_field(name="Loser", value=(l_member.mention if l_member else f"<@{loser_id}>"), inline=False)

    pub.set_footer(text=f"Result confirmed by {reactor_name}")
    pub.set_image(url=results_image_url)

    await ann_msg.edit(embed=pub)


async def start_match_from_challenge(guild: discord.Guild, a_id: int, b_id: int):
    # --- REPLACE the first two lines in start_match_from_challenge ---
    a = await get_member_safe(guild, a_id)
    b = await get_member_safe(guild, b_id)
    if not a or not b:
        return

    # Build the announce embed ONCE so we can reuse it (public + private room)
    announce = discord.Embed(
        title="⚔️ 1v1 Confirmed",
        description=(
            f"**{a.display_name}** vs **{b.display_name}**\n\n"
            "**Players:** Tag this embed and upload a clear screenshot as evidence."
        ),
        color=discord.Color.blurple()
    )
    announce.add_field(name="Player A", value=a.mention, inline=True)
    announce.add_field(name="Player B", value=b.mention, inline=True)
    announce.add_field(name="Status", value="Waiting for admin confirmation…", inline=False)
    announce.set_footer(text="Good luck, have fun!")
    announce.set_image(url="https://media.discordapp.net/attachments/1095053356478771202/1404403392981368923/Screenshot_2025-08-11_at_10.57.38.png?format=webp&quality=lossless&width=3280&height=804")

    # 1) Public announce in the 1v1 channel (if configured)
    announce_msg = None
    announce_ch = guild.get_channel(ANNOUNCE_CHANNEL_ID)
    if announce_ch:
        try:
            announce_msg = await announce_ch.send(embed=announce)
        except Exception as e:
            print(f"[Bot2] Could not post public announce: {e}")

    # 2) Admin card in the results/confirmation channel
    admin_ch = guild.get_channel(WIN_REPORT_CHANNEL_ID)
    if not admin_ch:
        print("[Bot2] WIN_REPORT_CHANNEL_ID not found; cannot create admin confirmation card.")
        return

    try:
        admin_embed = build_vs_embed(guild, a, b, status="Pending admin confirmation")
        admin_msg = await admin_ch.send(embed=admin_embed)

        # Prepare storage (we'll fill text/voice ids right after room creation)
        MATCHES[admin_msg.id] = {
            "a": a.id,
            "b": b.id,
            "resolved": False,
            "announce_msg_id": (announce_msg.id if announce_msg else None),
            "announce_ch_id": (announce_ch.id if announce_ch else None),
            "score": None,
            "text_chan_id": None,
            "voice_chan_id": None,
        }

        # Add reaction buttons for admins
        await admin_msg.add_reaction("🅰️")
        await admin_msg.add_reaction("🅱️")
        await admin_msg.add_reaction("❌")

        # 3) Create the private text + voice rooms visible only to the two players (and admins)
        try:
            text_id, voice_id = await create_1v1_rooms(
                guild=guild,
                player1=a,
                player2=b,
                base_channel=announce_ch or admin_ch  # fallback if announce channel missing
            )
            MATCHES[admin_msg.id]["text_chan_id"] = text_id
            MATCHES[admin_msg.id]["voice_chan_id"] = voice_id

            # Post the SAME embed in the private text room, pinging both players
            if text_id:
                room = guild.get_channel(text_id)
                if room:
                    # Copy the public embed so we can tweak the title for the room
                    room_embed = announce.copy()
                    room_embed.title = "⚔️ 1v1 Confirmed — Private Room"
                    # Optional: small hint that this is the place to upload
                    room_embed.set_footer(text="Upload your result screenshot in this private room. Admins will confirm shortly.")

                    # Ping both players in the room so they get notified
                    content_ping = f"{a.mention} {b.mention} your 1v1 room is ready!{f' 🎙️ VC: <#{voice_id}>' if voice_id else ''}"
                    await room.send(content=content_ping, embed=room_embed)
                    # You can pin it if you want:
                    # sent = await room.send(content=content_ping, embed=room_embed)
                    # try: await sent.pin()
                    # except: pass

                    # And a compact helper message:
                    if voice_id:
                        await room.send(f"🎙️ Temporary voice channel: <#{voice_id}> — GLHF!")

        except Exception as e:
            print(f"[Bot2] Failed to create 1v1 private rooms: {e}")

        # 4) Safety timeout: if no admin confirmation happens, auto-clean the rooms
        asyncio.create_task(arm_match_timeout(guild, admin_msg.id, timeout_min=90))

    except Exception as e:
        print(f"[Bot2] Could not create admin confirmation card: {e}")




class ChallengeView(View):
    def __init__(self, challenge_id: int, challenger_id: int, opponent_id: int, timeout: int = 2*60*60):
        super().__init__(timeout=timeout)
        self.challenge_id = challenge_id
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("Only the challenged user can respond to this.", ephemeral=True)
            return False
        return True

    @button(label="Accept", style=discord.ButtonStyle.success)
    async def accept_btn(self, interaction: discord.Interaction, btn: Button):
        if not await self._guard(interaction): return

        row = get_latest_incoming(interaction.guild.id, self.opponent_id)
        if not row:
            await interaction.response.send_message("No pending challenge to accept.", ephemeral=True)
            return
        cid, challenger_id, opponent_id, created_at = row
        if cid != self.challenge_id:
            await interaction.response.send_message("This challenge has been superseded.", ephemeral=True)
            return
        if _expired(created_at):
            mark_challenge_status(cid, "expired")
            await interaction.response.send_message("This challenge expired. Ask for a new one.", ephemeral=True)
            for c in self.children: c.disabled = True
            await interaction.message.edit(view=self)
            return

        mark_challenge_status(cid, "accepted")
        for c in self.children: c.disabled = True
        await interaction.message.edit(content=f"✅ Challenge accepted by {interaction.user.mention}. Posting match for admin confirmation…", view=self)
        await start_match_from_challenge(interaction.guild, challenger_id, opponent_id)


    @button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline_btn(self, interaction: discord.Interaction, btn: Button):
        if not await self._guard(interaction): return

        row = get_latest_incoming(interaction.guild.id, self.opponent_id)
        if not row:
            await interaction.response.send_message("No pending challenge to decline.", ephemeral=True)
            return
        cid, challenger_id, opponent_id, created_at = row
        if cid != self.challenge_id:
            await interaction.response.send_message("This challenge has been superseded.", ephemeral=True)
            return
        if _expired(created_at):
            mark_challenge_status(cid, "expired")
            await interaction.response.send_message("This challenge already expired.", ephemeral=True)
            for c in self.children: c.disabled = True
            await interaction.message.edit(view=self)
            return

        mark_challenge_status(cid, "declined")
        for c in self.children: c.disabled = True
        await interaction.message.edit(content=f"❌ Challenge declined by {interaction.user.mention}.", view=self)

# Put this helper anywhere above on_ready (top of file is fine)
def _has_perms(g: discord.Guild) -> bool:
    """Minimum perms the bot needs to run its setup tasks in a guild."""
    me = g.me
    if not me:
        return False
    p = me.guild_permissions
    # adjust if you need more/less:
    required = [
        p.view_channel,
        p.send_messages,
        p.read_message_history,
        p.add_reactions,
        p.manage_channels,   # for creating 1v1 rooms
        p.manage_roles,      # for color roles
    ]
    return all(required)


# --- WARNINGS DB BOOTSTRAP ---
def warn_init_db():
    conn = _ensure_warn_conn()
    cur = conn.cursor()

    # Core tables using your original names/columns
    cur.execute("""
    CREATE TABLE IF NOT EXISTS warnings (
        guild_id    INTEGER NOT NULL,
        user_id     INTEGER NOT NULL,
        count       INTEGER NOT NULL DEFAULT 0,
        last_at     TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (guild_id, user_id)
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS warnings_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id    INTEGER NOT NULL,
        user_id     INTEGER NOT NULL,
        mod_id      INTEGER,
        reason      TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    # Helpful indexes (noop if already exist)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_warn_guild_user ON warnings(guild_id, user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_warnlog_guild_user ON warnings_log(guild_id, user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_warnlog_guild_created ON warnings_log(guild_id, created_at);")

    conn.commit()

def _get_warn_count(guild_id: int, user_id: int) -> int:
    conn = _ensure_warn_conn()
    cur = conn.execute(
        "SELECT count FROM warnings WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0

def _set_warn_count(guild_id: int, user_id: int, count: int):
    conn = _ensure_warn_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO warnings(guild_id, user_id, count, last_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET count=excluded.count, last_at=excluded.last_at;
    """, (guild_id, user_id, int(count), now))
    conn.commit()

def _log_warning(guild_id: int, user_id: int, mod_id: int, reason: str | None):
    conn = _ensure_warn_conn()
    conn.execute("""
        INSERT INTO warnings_log(guild_id, user_id, mod_id, reason, created_at)
        VALUES(?, ?, ?, ?, ?);
    """, (guild_id, user_id, mod_id, reason or "", datetime.now(timezone.utc).isoformat()))
    conn.commit()

def _get_warning_history(guild_id: int, user_id: int, limit: int = 10):
    conn = _ensure_warn_conn()
    cur = conn.execute("""
        SELECT mod_id, reason, created_at
        FROM warnings_log
        WHERE guild_id=? AND user_id=?
        ORDER BY id DESC
        LIMIT ?;
    """, (guild_id, user_id, int(limit)))
    return cur.fetchall()

# --- NEW: CLEAR FUNCTIONS (counts + history) ---
def _reset_user_warnings(guild_id: int, user_id: int):
    """
    Zero the user's warning count AND delete all rows from warnings_log for this user.
    """
    conn = _ensure_warn_conn()
    now = datetime.now(timezone.utc).isoformat()

    # Upsert a zeroed count (preserves row existence & last_at)
    conn.execute("""
        INSERT INTO warnings(guild_id, user_id, count, last_at)
        VALUES(?, ?, 0, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET count=0, last_at=excluded.last_at;
    """, (guild_id, user_id, now))

    # Purge history
    conn.execute("DELETE FROM warnings_log WHERE guild_id=? AND user_id=?;", (guild_id, user_id))
    conn.commit()

def _reset_guild_warnings(guild_id: int) -> int:
    """
    Zero ALL counts in this guild and delete ALL history entries for this guild.
    Returns number of member rows whose counts were touched (approximate).
    """
    conn = _ensure_warn_conn()
    cur = conn.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=?;", (guild_id,))
    touched = int(cur.fetchone()[0] or 0)

    conn.execute("""
        UPDATE warnings
        SET count=0, last_at=datetime('now')
        WHERE guild_id=?;
    """, (guild_id,))
    conn.execute("DELETE FROM warnings_log WHERE guild_id=?;", (guild_id,))
    conn.commit()
    return touched

def warn_add(guild_id: int, user_id: int, moderator_id: int | None, reason: str | None):
    current = _get_warn_count(guild_id, user_id)
    _set_warn_count(guild_id, user_id, current + 1)
    _log_warning(guild_id, user_id, moderator_id or 0, reason or "")



# =========================

# === BEGINNING OF BOT 2 SECTIONS ===

# ---- Global state / config ----
# ===== Admin cancel support =====
CANCEL_EMOJIS = ("❌", "🛑")  # either works for cancel


# ===== MATCHMAKING QUEUE (BOT 2) =====
MM_TIMEOUT_S = 120  # 2 minutes

def _timeout_human() -> str:
    m = int(MM_TIMEOUT_S // 60)
    return f"{m} minute{'s' if m != 1 else ''}" if m else f"{MM_TIMEOUT_S} seconds"

# Per-guild FIFO queue: guild_id -> deque of (user_id, joined_at_monotonic)
MM_QUEUES: dict[int, deque[tuple[int, float]]] = {}
# Quick lookup to see if user is queued and where: user_id -> (guild_id, joined_at_monotonic)
MM_INDEX: dict[int, tuple[int, float]] = {}


# ===== Leaderboard auto-post =====
LEADERBOARD_UPDATE_MINUTES = 15


ADMIN_ROLE_ID = 1125786680121626704

# ===== Bot 2: 1v1 Rooms Config =====
ONEVONE_CATEGORY_ID = 1404418906382401546  # fixed category for 1v1 text/voice rooms


# Booster cleanup
BOT2_BOOSTER_ROLE_IDS = [1126898690284601396]
BOT2_CUSTOM_ROLE_IDS = [
    1395942660501405799, 1395942745725603911, 1395942820669292575,
    1395942890311647352, 1395943249868488734, 1395943312783048815,
    1395943372052758718, 1395943437861392395, 1395943497084702926
]

# Color roles
COLOR_ROLE_MAP = {
    "MediumSeaGreen": 1342259618109325367,
    "MediumOrchid": 1342259240974422037,
    "LightPink": 1358564983063052318,
    "LemonChiffon": 1342259031691231337,
    "DimGrey": 1342258850018889831,
    "DarkRed": 1342238188944621578,
    "MediumBlue": 1342258604584996894,
    "DodgerBlue": 1342260006325719141,
    "DarkCyan": 1342260273855205517,
    "Cyan": 1342251057647980777
}

# Self-role embed
CHANNEL_ID = 1342150057306095616
MESSAGE_ID = None  # Set after embed creation

# ===== 1v1 reporting channels =====
WIN_REPORT_CHANNEL_ID = 1404071956571226253  # (already there) results/admin confirm channel
ANNOUNCE_CHANNEL_ID = 1404071820155555860  # ← NEW: public announce channel

# ---- Channel locks (Bot 2) ----
MATCH_CHANNEL_ID = 1404071820155555860   # ?challenge, ?queue, ?cancelchallenge
STATS_CHANNEL_ID = 1404420564772454482   # ?leaderboard, ?mywins


DB_PATH = "leaderboard.db"
CHALLENGE_TTL_HOURS = 2  # challenge validity window

# message_id (admin-report message) -> match data
MATCHES = {}  # {admin_msg_id: {"a": int, "b": int, "resolved": bool, "announce_msg_id": Optional[int], "announce_ch_id": Optional[int]}}

RESULTS_IMAGE_URL = "https://media.discordapp.net/attachments/1095053356478771202/1404403393555861505/Screenshot_2025-08-11_at_10.58.38.png?format=webp&quality=lossless&width=3280&height=804"

LEADERBOARD_CHANNEL_ID = 1404390200192401499
LEADERBOARD_MESSAGE_ID = None  # load from your json/sql at startup

LB_KEY = "leaderboard_message_id"
COLOR_MSG_KEY = "color_message_id"


# ---- Listeners ----
@bot2.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        if ctx.command and ctx.command.name in {"challenge", "queue", "cancelchallenge"}:
            await ctx.reply(
                f"Use this command in <#{MATCH_CHANNEL_ID}>.",
                mention_author=False,
                delete_after=8
            )
            return
        if ctx.command and ctx.command.name in {"leaderboard", "mywins"}:
            await ctx.reply(
                f"Use this command in <#{STATS_CHANNEL_ID}>.",
                mention_author=False,
                delete_after=8
            )
            return
    # fall back to your existing handler if any
    # raise error  # (uncomment if you want default behavior after our messages)

# ===== BOOSTER CHECK LOOP =====
@tasks.loop(minutes=10)
async def booster_check_bot2():
    print(f"[Bot2] Booster check @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    for guild in bot2.guilds:
        booster_roles = [guild.get_role(rid) for rid in BOT2_BOOSTER_ROLE_IDS if guild.get_role(rid)]
        for member in guild.members:
            if not any(r in member.roles for r in booster_roles):
                roles_to_remove = [r for r in member.roles if r.id in BOT2_CUSTOM_ROLE_IDS]
                if roles_to_remove:
                    try:
                        await member.remove_roles(*roles_to_remove, reason="Lost All Booster Roles (Bot2)")
                    except Exception as e:
                        print(f"[Bot2] Error on {member.display_name}: {e}")

@tasks.loop(minutes=LEADERBOARD_UPDATE_MINUTES)
async def leaderboard_updater():
    for guild in bot2.guilds:
        try:
            await refresh_leaderboard_message(guild)
        except Exception as e:
            print(f"[Bot2] Failed to update leaderboard: {e}")

@tasks.loop(seconds=10)
async def mm_queue_sweeper():
    now = _now_mono()
    to_timeout: list[tuple[int, int]] = []  # (guild_id, user_id)

    # collect timeouts
    for gid, q in list(MM_QUEUES.items()):
        newq = deque()
        for uid, joined in q:
            if now - joined >= MM_TIMEOUT_S:
                to_timeout.append((gid, uid))
            else:
                newq.append((uid, joined))
        MM_QUEUES[gid] = newq

    # apply timeouts + notify
    for gid, uid in to_timeout:
        MM_INDEX.pop(uid, None)
        guild = bot2.get_guild(gid)
        if guild:
            member = guild.get_member(uid)
            if member is None:
                try:
                    member = await guild.fetch_member(uid)
                except Exception:
                    member = None
            if member:
                await _notify_timeout(member)

    # after pruning, try to match in each guild
    for gid in list(MM_QUEUES.keys()):
        guild = bot2.get_guild(gid)
        if guild:
            await _try_matchmake(guild)

@mm_queue_sweeper.before_loop
async def _mm_wait_ready():
    await bot2.wait_until_ready()

@bot2.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    try:
        if payload.guild_id is None:
            return

        # Only for your colour panel message
        if payload.channel_id != CHANNEL_ID or payload.message_id != MESSAGE_ID:
            return

        guild = bot2.get_guild(payload.guild_id) or await bot2.fetch_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)  # may be None if not cached
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                return

        emoji_name = payload.emoji.name
        role_id = COLOR_ROLE_MAP.get(emoji_name)
        if not role_id:
            return
        role = guild.get_role(role_id)
        if not role:
            return

        # If user removed the emoji that corresponds to their current colour, drop the role
        if role in member.roles:
            try:
                await member.remove_roles(role, reason="Reaction removed from colour panel")
            except Exception as e:
                print(f"[Bot2] Failed to remove role on reaction_remove: {e}")

    except Exception as e:
        print(f"[Bot2] on_raw_reaction_remove error: {e}")

# Admin-only result confirmation via reactions in the results channel
@bot2.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    try:
        # 0) Ignore DMs and the bot's own reactions
        if payload.guild_id is None:
            return
        if bot2.user and payload.user_id == bot2.user.id:
            return

        # 1) Ensure we have the guild
        guild = bot2.get_guild(payload.guild_id)
        if guild is None:
            try:
                guild = await bot2.fetch_guild(payload.guild_id)
            except Exception:
                return

        # ==========================================================
        # 1) COLOR PANEL: enforce single colour role
        # ==========================================================
        try:
            if 'CHANNEL_ID' in globals() and 'MESSAGE_ID' in globals() and 'COLOR_ROLE_MAP' in globals():
                if payload.channel_id == CHANNEL_ID and payload.message_id == MESSAGE_ID:
                    member = await get_member_safe(guild, payload.user_id)
                    if member is None:
                        return

                    emoji_name = payload.emoji.name
                    role_id = COLOR_ROLE_MAP.get(emoji_name)
                    if not role_id:
                        return

                    role = guild.get_role(role_id)
                    if not role:
                        return

                    # Collect all colour roles present in this guild
                    color_roles = [r for rid in COLOR_ROLE_MAP.values() if (r := guild.get_role(rid))]

                    # Remove any existing colour roles first (other than the chosen one)
                    to_remove = [r for r in member.roles if r in color_roles and r.id != role.id]
                    if to_remove:
                        try:
                            await member.remove_roles(*to_remove, reason="Enforcing single colour role")
                        except Exception as e:
                            print(f"[Bot2] Failed removing old color roles from {member.id}: {e}")

                    # Add the chosen role if they don't already have it
                    if role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Selected new colour role")
                        except Exception as e:
                            print(f"[Bot2] Failed adding color role {role.id} to {member.id}: {e}")

                    # Tidy up other colour reactions from this user on the same message
                    try:
                        channel = guild.get_channel(CHANNEL_ID) or await bot2.fetch_channel(CHANNEL_ID)
                        msg = await channel.fetch_message(MESSAGE_ID)
                        for react in msg.reactions:
                            same = False
                            if isinstance(react.emoji, str):
                                same = (react.emoji == emoji_name)
                            else:
                                same = (getattr(react.emoji, "name", None) == emoji_name)

                            if not same:
                                async for u in react.users():
                                    if u.id == member.id:
                                        try:
                                            await msg.remove_reaction(react.emoji, member)
                                        except Exception:
                                            pass
                                        break
                    except Exception as e:
                        print(f"[Bot2] Could not tidy up old reactions: {e}")

                    return  # handled colour panel; do not fall through to admin logic
        except Exception as e:
            print(f"[Bot2] Color panel block error: {e}")
            # fall through (but do nothing else for color panel)

        # ==========================================================
        # 2) ADMIN RESULTS / CANCEL
        # ==========================================================
        if payload.channel_id != WIN_REPORT_CHANNEL_ID:
            return

        emoji_str = str(payload.emoji)

        # Admin permission check
        reactor = await get_member_safe(guild, payload.user_id)
        if reactor is None:
            return
        if ADMIN_ROLE_ID not in [r.id for r in reactor.roles]:
            return

        admin_msg_id = payload.message_id
        match = MATCHES.get(admin_msg_id)
        if not match or match.get("resolved"):
            return

        # --- Cancel flow (❌ / 🛑) ---
        try:
            cancel_emojis = globals().get("CANCEL_EMOJIS", ("❌", "🛑"))
            if emoji_str in cancel_emojis:
                if "cancel_match" not in globals():
                    print("[Bot2] cancel_match helper missing; cannot cancel.")
                    return
                reason = f"Cancelled via {emoji_str} by {reactor.display_name}"
                ok = await cancel_match(guild, admin_msg_id, reason=reason, actor=reactor)

                # Clean up this admin's cancel reaction to avoid stacking
                try:
                    admin_chan = guild.get_channel(WIN_REPORT_CHANNEL_ID)
                    if isinstance(admin_chan, (discord.TextChannel, discord.Thread)):
                        admin_msg = await admin_chan.fetch_message(admin_msg_id)
                        await admin_msg.remove_reaction(payload.emoji, reactor)
                except Exception:
                    pass

                return  # stop; do not run A/B winner logic
        except Exception as e:
            print(f"[Bot2] Cancel flow error: {e}")
            return

        # --- Winner confirm flow (A / B) ---
        if emoji_str not in ("🅰️", "🅱️"):
            return

        # Resolve players
        a_id = match["a"]
        b_id = match["b"]

        # Fetch the admin message (for editing)
        ch = guild.get_channel(payload.channel_id) or await bot2.fetch_channel(payload.channel_id)
        if ch is None:
            return
        try:
            admin_msg = await ch.fetch_message(admin_msg_id)
        except Exception:
            return

        # Determine winner/loser from reaction
        winner_id = a_id if emoji_str == "🅰️" else b_id
        loser_id  = b_id if winner_id == a_id else a_id

        # Resolve members (safe)
        a_member = await get_member_safe(guild, a_id)
        b_member = await get_member_safe(guild, b_id)
        w_member = await get_member_safe(guild, winner_id)
        l_member = await get_member_safe(guild, loser_id)

        # Points/ranks update
        res = None
        try:
            if "update_points" in globals():
                maybe = update_points(guild, winner_id, loser_id)
                res = await maybe if asyncio.iscoroutine(maybe) else maybe
        except Exception as e:
            print(f"[Bot2] update_points failed: {e}")
            res = None

        RESULTS_IMAGE_URL = globals().get(
            "RESULTS_IMAGE_URL",
            "https://media.discordapp.net/attachments/1095053356478771202/1404403393555861505/Screenshot_2025-08-11_at_10.58.38.png?format=webp&quality=lossless&width=3280&height=804"
        )

        # Build UPDATED ADMIN EMBED
        admin_embed = discord.Embed(
            title="⚔️ 1v1 Result Confirmed",
            color=discord.Color.green()
        )
        admin_embed.add_field(name="Player A", value=(a_member.mention if a_member else f"<@{a_id}>"), inline=True)
        admin_embed.add_field(name="Player B", value=(b_member.mention if b_member else f"<@{b_id}>"), inline=True)

        if res:
            w_pts   = res["winner_after"]["points"]
            l_pts   = res["loser_after"]["points"]
            w_delta = res["winner_after"]["delta"]
            l_delta = res["loser_after"]["delta"]
            w_rank  = res["winner_after"].get("rank", "—")
            l_rank  = res["loser_after"].get("rank", "—")
            w_strk  = res["winner_after"].get("streak", None)

            admin_embed.add_field(
                name="Winner",
                value=f"{w_member.mention if w_member else f'<@{winner_id}>'} "
                      f"(+{w_delta} → **{w_pts}** | Tier **{w_rank}**"
                      f"{' | Streak **'+str(w_strk)+'**' if w_strk is not None else ''})",
                inline=False
            )
            admin_embed.add_field(
                name="Loser",
                value=f"{l_member.mention if l_member else f'<@{loser_id}>'} "
                      f"({l_delta} → **{l_pts}** | Tier **{l_rank}**)",
                inline=False
            )
        else:
            admin_embed.add_field(name="Winner", value=(w_member.mention if w_member else f"<@{winner_id}>"), inline=False)
            admin_embed.add_field(name="Loser",  value=(l_member.mention if l_member else f"<@{loser_id}>"), inline=False)

        admin_embed.set_footer(text=f"Result confirmed by {reactor.display_name}")
        admin_embed.set_image(url=RESULTS_IMAGE_URL)
        await admin_msg.edit(embed=admin_embed)

        # Mark resolved
        match["resolved"] = True
        MATCHES[admin_msg_id] = match

        # Update PUBLIC announce embed if we have its reference
        ann_id = match.get("announce_msg_id")
        ann_ch_id = match.get("announce_ch_id")
        score_text = match.get("score")
        if ann_id and ann_ch_id:
            try:
                await update_public_announce_embed(
                    guild=guild,
                    ann_ch_id=ann_ch_id,
                    ann_msg_id=ann_id,
                    winner_id=winner_id,
                    loser_id=loser_id,
                    a_id=a_id,
                    b_id=b_id,
                    res=res,
                    reactor_name=reactor.display_name,
                    results_image_url=RESULTS_IMAGE_URL,
                    score_text=score_text
                )
            except Exception as e:
                print(f"[Bot2] Could not update public announce embed: {e}")

        # --- Announce result inside the private match room & schedule cleanup ---
        text_id = match.get("text_chan_id")
        voice_id = match.get("voice_chan_id")

        if text_id:
            try:
                room = guild.get_channel(text_id) or await bot2.fetch_channel(text_id)
                if room:
                    priv_desc = (
                        f"**Winner:** {w_member.mention if w_member else f'<@{winner_id}>'}\n"
                        f"**Loser:** {l_member.mention if l_member else f'<@{loser_id}>'}\n\n"
                        "This room will be removed in a few minutes."
                    )
                    if res:
                        w_pts   = res['winner_after']['points']
                        l_pts   = res['loser_after']['points']
                        w_delta = res['winner_after']['delta']
                        l_delta = res['loser_after']['delta']
                        w_rank  = res['winner_after'].get('rank', '—')
                        l_rank  = res['loser_after'].get('rank', '—')
                        w_strk  = res['winner_after'].get('streak', None)
                        priv_desc = (
                            f"**Winner:** {w_member.mention if w_member else f'<@{winner_id}>'} "
                            f"(+{w_delta} → **{w_pts}** | Tier **{w_rank}**"
                            f"{' | Streak **'+str(w_strk)+'**' if w_strk is not None else ''})\n"
                            f"**Loser:** {l_member.mention if l_member else f'<@{loser_id}>'} "
                            f"({l_delta} → **{l_pts}** | Tier **{l_rank}**)\n\n"
                            "This room will be removed in a few minutes."
                        )

                    result_embed = discord.Embed(
                        title="Result Confirmed ✅",
                        description=priv_desc,
                        color=discord.Color.green()
                    )
                    await room.send(embed=result_embed)
            except Exception:
                pass

        # Delete the private text & voice channels after ~3 minutes
        try:
            asyncio.create_task(cleanup_1v1_rooms(guild, text_id, voice_id, delay_seconds=180))
        except Exception as e:
            print(f"[Bot2] Failed to schedule cleanup for 1v1 rooms: {e}")

        # Refresh the leaderboard image after every result (best-effort)
        try:
            await refresh_leaderboard_message(guild)
        except Exception as e:
            print(f"[Bot2] Failed to refresh leaderboard after match: {e}")

    except Exception as e:
        print(f"[Bot2] on_raw_reaction_add error: {e}")





# ---- Commands ----

@bot2.event
async def on_ready():
    print(f"Bot 2 is online: {bot2.user}")

    # --- init ---
    try:
        init_db()
    except Exception as e:
        print(f"[Bot2] init_db error: {e}")

    try:
        _init_settings()
    except Exception as e:
        print(f"[Bot2] _init_settings error: {e}")

    # Preload message ids / settings for each guild (only where we have perms)
    for g in bot2.guilds:
        if not _has_perms(g):
            print(f"[Bot2] Skipping guild {g.id} during preload (insufficient perms).")
            continue
        try:
            load_leaderboard_message_id_from_db(g.id)
        except Exception as e:
            print(f"[Bot2] load_leaderboard_message_id_from_db({g.id}) error: {e}")
        try:
            load_color_message_id_from_db(g.id)
        except Exception as e:
            print(f"[Bot2] load_color_message_id_from_db({g.id}) error: {e}")

    # Presence
    try:
        await bot2.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="JacobXItachi in bed..."
            )
        )
    except Exception as e:
        print(f"[Bot2] change_presence error: {e}")

    # --- start background tasks (guard against multiple starts) ---
    try:
        if not booster_check_bot2.is_running():
            booster_check_bot2.start()
    except Exception as e:
        print(f"[Bot2] booster_check_bot2 start error: {e}")

    try:
        if not leaderboard_updater.is_running():
            leaderboard_updater.start()
    except Exception as e:
        print(f"[Bot2] leaderboard_updater start error: {e}")

    try:
        if not mm_queue_sweeper.is_running():
            mm_queue_sweeper.start()
    except Exception as e:
        print(f"[Bot2] mm_queue_sweeper start error: {e}")

    # --- fix legacy duplicate colour roles on startup (only where we have perms) ---
    for g in bot2.guilds:
        if not _has_perms(g):
            continue
        try:
            await _sweep_fix_duplicate_colors(g)
        except Exception as e:
            print(f"[Bot2] startup sweep error in guild {g.id}: {e}")

    # --- rebuild colour/self-role embed in the first guild we can manage ---
    try:
        target = next((g for g in bot2.guilds if _has_perms(g)), None)
        if target:
            await rebuild_embed(target)
        else:
            print("[Bot2] No guilds with sufficient perms to rebuild the color panel.")
    except Exception as e:
        print(f"[Bot2] rebuild_embed error: {e}")


@bot2.command(name="queue")
@channel_is(MATCH_CHANNEL_ID)
async def join_queue(ctx: commands.Context):
    """Join the 1v1 matchmaking queue (auto-match; 2-minute timeout)."""
    guild = ctx.guild
    user = ctx.author
    if guild is None:
        return await ctx.reply("This command only works in a server.")

    # already queued?
    if user.id in MM_INDEX:
        gid, joined = MM_INDEX[user.id]
        if gid == guild.id:
            remain = max(0, int(MM_TIMEOUT_S - (_now_mono() - joined)))
            return await ctx.reply(f"⏳ You’re already in the queue. Timeout in **{remain}s**.")
        else:
            # remove from old guild queue and requeue here
            _remove_from_queue(gid, user.id)

    q = _ensure_queue(guild.id)
    now_m = _now_mono()
    q.append((user.id, now_m))
    MM_INDEX[user.id] = (guild.id, now_m)

    await ctx.reply(f"✅ Added to 1v1 queue. We’ll match you with the next available player (**{_timeout_human()}** timeout).")

    # try an immediate match if someone is already waiting
    await _try_matchmake(guild)


@bot2.command(name="leavequeue", aliases=["cancelqueue"])
@channel_is(MATCH_CHANNEL_ID)
async def leave_queue(ctx: commands.Context):
    """Leave the matchmaking queue if you’re in it."""
    guild = ctx.guild
    user = ctx.author
    if guild is None:
        return

    removed = _remove_from_queue(guild.id, user.id)
    if removed:
        await ctx.reply("✅ You left the 1v1 queue.")
    else:
        await ctx.reply("ℹ️ You aren’t in the queue.")


@bot2.command(name="queuestatus", aliases=["qstat"])
@channel_is(MATCH_CHANNEL_ID)
async def queue_status(ctx: commands.Context):
    """Shows how many are waiting and your own remaining time if queued."""
    guild = ctx.guild
    if guild is None:
        return
    q = _ensure_queue(guild.id)
    count = len(q)

    msg = [f"📊 Players waiting: **{count}**"]
    if ctx.author.id in MM_INDEX and MM_INDEX[ctx.author.id][0] == guild.id:
        joined = MM_INDEX[ctx.author.id][1]
        remain = max(0, int(MM_TIMEOUT_S - (_now_mono() - joined)))
        msg.append(f"⏳ Your timeout in **{remain}s**.")
    await ctx.reply("\n".join(msg))

# ===== COMMANDS =====
@bot2.command(name="challenge", help="Challenge a specific user to a 1v1: ?challenge @user")
@channel_is(MATCH_CHANNEL_ID)
async def challenge(ctx, opponent: discord.Member):
    if ctx.guild is None:
        await ctx.send("Use this in a server.")
        return
    if opponent.bot:
        await ctx.send("You can’t challenge a bot.")
        return
    if opponent.id == ctx.author.id:
        await ctx.send("Challenging yourself is wild… but no. 😅")
        return

    status, cid = create_challenge(ctx.guild.id, ctx.author.id, opponent.id)
    if status == "exists":
        await ctx.send(f"There’s already a pending challenge between you and {opponent.mention}.")
        return

    view = ChallengeView(challenge_id=cid, challenger_id=ctx.author.id, opponent_id=opponent.id)
    await ctx.send(f"⚔️ {opponent.mention}, **{ctx.author.display_name}** has challenged you to a 1v1!",
                   view=view)

@bot2.command(name="challenges", help="See your pending 1v1 challenges (sent & received)")
@channel_is(MATCH_CHANNEL_ID)
async def challenges(ctx):
    rows = get_pending_for_user(ctx.guild.id, ctx.author.id)
    if not rows:
        await ctx.send("No pending challenges for you.")
        return

    sent, received = [], []
    for cid, challenger_id, opponent_id, created_at in rows:
        if challenger_id == ctx.author.id:
            target = ctx.guild.get_member(opponent_id)
            sent.append(f"→ {target.display_name if target else opponent_id} (id {cid}, {created_at})")
        else:
            source = ctx.guild.get_member(challenger_id)
            received.append(f"← {source.display_name if source else challenger_id} (id {cid}, {created_at})")

    desc = []
    if sent: desc.append("**Sent:**\n" + "\n".join(sent))
    if received: desc.append("**Received:**\n" + "\n".join(received))
    embed = discord.Embed(title="📜 Your 1v1 Challenge Queue",
                          description="\n\n".join(desc), color=discord.Color.blurple())
    await ctx.send(embed=embed)

@bot2.command(name="cancelchallenge", help="Cancel your latest pending 1v1 challenge")
@channel_is(MATCH_CHANNEL_ID)
async def cancelchallenge(ctx):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("""
            SELECT id, opponent_id, created_at
            FROM challenges
            WHERE guild_id=? AND challenger_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
        """, (ctx.guild.id, ctx.author.id))
        row = cur.fetchone()

    if not row:
        await ctx.send("You don’t have any pending challenges to cancel.")
        return

    cid, opponent_id, created_at = row
    if _expired(created_at):
        mark_challenge_status(cid, "expired")
        await ctx.send("Your pending challenge was already expired.")
        return

    mark_challenge_status(cid, "cancelled")
    opp = ctx.guild.get_member(opponent_id)
    await ctx.send(f"🗑️ Challenge to {opp.mention if opp else 'that user'} cancelled.")

@bot2.command(name="leaderboard")
@channel_is(STATS_CHANNEL_ID)
async def leaderboard(ctx):
    em, file = await build_leaderboard_embed_and_file(ctx.guild, limit=10)
    if not em:
        return await ctx.send("No leaderboard data yet.")
    await ctx.send(embed=em, file=file)


@bot2.command(name="mywins", aliases=["stats"], help="Show wins, losses, points, tier, streak, rank. Usage: ?mywins [@user|id|name]")
@channel_is(STATS_CHANNEL_ID)
async def mywins(ctx, *, who: str = None):
    member = resolve_member(ctx, who) if who else ctx.author
    if not member:
        await ctx.send("❌ Couldn't find that user. Try a mention, ID, exact name, or a clearer partial.")
        return

    # wins/losses from matches
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT loser_id FROM matches WHERE winner_id=?", (member.id,))
        wins_rows = cur.fetchall()
        cur.execute("SELECT winner_id FROM matches WHERE loser_id=?", (member.id,))
        loss_rows = cur.fetchall()

    wins_count = len(wins_rows)
    loss_count = len(loss_rows)

    # points & streak
    _w, points, streak = get_user_row(member.id)
    tier = rank_for_points(points)
    pos = get_leaderboard_position(member.id)

    def names_count(rows):
        counts = {}
        for (uid,) in rows:
            counts[uid] = counts.get(uid, 0) + 1
        parts = []
        for uid, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            m = ctx.guild.get_member(uid)
            nm = m.display_name if m else f"User {uid}"
            parts.append(f"{nm} (x{c})" if c > 1 else nm)
        return ", ".join(parts) if parts else "None"

    beaten = names_count(wins_rows)
    lostto = names_count(loss_rows)

    embed = discord.Embed(title=f"📊 1v1 Stats — {member.display_name}", color=discord.Color.blue())
    embed.add_field(name="Wins", value=str(wins_count), inline=True)
    embed.add_field(name="Losses", value=str(loss_count), inline=True)
    embed.add_field(name="Points", value=str(points), inline=True)
    embed.add_field(name="Tier", value=tier, inline=True)
    embed.add_field(name="Current Streak", value=str(streak), inline=True)
    embed.add_field(name="Leaderboard Rank", value=(f"#{pos}" if pos else "Unranked"), inline=True)
    embed.add_field(name="Beaten", value=beaten, inline=False)
    embed.add_field(name="Lost To", value=lostto, inline=False)
    embed.set_image(url="https://media.discordapp.net/attachments/1095053356478771202/1404403392251433081/Screenshot_2025-08-11_at_10.54.37.png?ex=689b1015&is=6899be95&hm=ab1652ce2d7207e90137257cc04a5c03f556ef53a2299e750036a3972b9ac266&=&format=webp&quality=lossless&width=3280&height=804")
    await ctx.send(embed=embed)


@bot2.command()
@commands.has_permissions(administrator=True)
async def resetcolors(ctx):
    await rebuild_embed(ctx.guild)
    await ctx.send("♻️ Embed has been rebuilt.")

@bot2.command()
async def clearcolors(ctx):
    admin_role = discord.utils.get(ctx.guild.roles, id=ADMIN_ROLE_ID)
    if admin_role not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You do not have permission to use this command.")
        return

    count = 0
    for member in ctx.guild.members:
        to_remove = []
        for role_id in COLOR_ROLE_MAP.values():
            role = ctx.guild.get_role(role_id)
            if role and role in member.roles:
                to_remove.append(role)
        if to_remove:
            await member.remove_roles(*to_remove, reason="Admin: clearcolors")
            count += len(to_remove)

    await ctx.send(f"✅ Cleared all color roles. Total removed: {count}")






@bot2.command(name="setleaderboard", help="Set the channel for the auto-updating leaderboard. Usage: ?setleaderboard #channel")
@commands.has_permissions(administrator=True)
async def setleaderboard(ctx, channel: discord.TextChannel):
    # Persist the chosen channel
    meta_set("leaderboard_channel_id", str(channel.id))

    # Build and post once immediately (image-based)
    em, file = await build_leaderboard_embed_and_file(ctx.guild, limit=10)
    if not em:
        await ctx.send("No leaderboard data yet. I set the channel and will post when there are results.")
        return

    # Delete old one if we have it
    old_id = LEADERBOARD_MESSAGE_ID or (int(get_setting(ctx.guild.id, LB_KEY)) if (get_setting(ctx.guild.id, LB_KEY) or "").isdigit() else None)
    if old_id:
        try:
            old_msg = await channel.fetch_message(old_id)
            await old_msg.delete()
        except Exception:
            pass

    new_msg = await channel.send(embed=em, file=file)
    await save_leaderboard_message_id(new_msg.id, ctx.guild.id)

    await ctx.send(f"✅ Leaderboard channel set to {channel.mention}. I’ll keep it updated every {LEADERBOARD_UPDATE_MINUTES} minutes.")


# =========================
# 1) 1v1 COMMANDS OVERVIEW
# =========================
@bot2.command(name="onevone", help="Show all 1v1 commands and how the flow works")
async def onevone_help(ctx: commands.Context):
    em = discord.Embed(
        title="⚔️ 1v1 — Commands & How It Works",
        color=discord.Color.blurple()
    )
    em.add_field(
        name="Player Commands",
        value=(
            "**?challenge @user** – Challenge someone to a 1v1. The opponent must tap **Accept** or **Decline**.\n"
            f"**?queue** – Join the random matchmaking queue (**{_timeout_human()}** timeout). "
            "When another player joins, you’ll be matched automatically.\n"
            "**?leavequeue** – Leave the random matchmaking queue.\n"
            "**?queuestatus** – See how many are in queue and your remaining time.\n"
            "**?cancelchallenge** – Cancel your latest pending challenge.\n"
            "**?leaderboard** – Show the current top 10 players.\n"
            "**?mywins [@user|id|name]** – View detailed stats for yourself or someone else.\n"
        ),
        inline=False
    )
    em.add_field(
        name="What Happens When a Match Starts",
        value=(
            "• The bot **creates a private text channel** and a **temporary voice channel** under the 1v1 category.\n"
            "  Only the **two players**, **admins**, and the **bot** can see/use them.\n"
            "• The bot also posts an **admin-only card** in the results channel for winner confirmation.\n"
            "• (Optional) A public ‘match confirmed’ card may be posted in the 1v1 announce channel."
        ),
        inline=False
    )
    em.add_field(
        name="How to Finish a Match",
        value=(
            "1) **Players** upload a **clear screenshot** of the result **in the private text room** (and may tag the public card if posted).\n"
            "2) **Admins** confirm the result by reacting **🅰️** (Player A) or **🅱️** (Player B) on the **admin card**.\n"
            "3) The bot updates **points, streaks, and ranks**, edits the public card with the result (if present), "
            "announces the result in the **private room**, and **refreshes the leaderboard**.\n"
            "4) The **private text + voice channels are auto‑deleted a few minutes after confirmation**."
        ),
        inline=False
    )
    em.set_footer(text="Reminder: Upload your screenshot in the private match room for faster admin confirmation.")
    em.set_image(url="https://media.discordapp.net/attachments/1095053356478771202/1404404134471270400/Screenshot_2025-08-11_at_11.59.46.png")
    await ctx.send(embed=em)


# ==================================
# 2) 1v1 SCORING & RANKING EXPLAINER
# ==================================
@bot2.command(name="onevone_rules", help="Show the 1v1 scoring, ranks, and procedure")
async def onevone_rules(ctx: commands.Context):
    win_pts = WIN_POINTS            # +10
    loss_pts = LOSS_POINTS          # -10
    streak_bonus = STREAK_BONUS     # +5 after streak >= 2

    rank_table = (
        "`Legendary    ≥ 800 pts`\n"
        "`Grand Master ≥ 500 pts`\n"
        "`Master       ≥ 250 pts`\n"
        "`Pro          ≥ 100 pts`\n"
        "`Elite        < 100 pts`"
    )

    scoring_lines = [
        f"• **Win:** +{win_pts} points",
        f"• **Loss:** {loss_pts} points",
        f"• **Win Streak Bonus:** +{streak_bonus} for each win after the first (streak ≥ 2)",
        "• Streak resets to **0** on a loss",
        "• Leaderboard sorts by **Points**, tie-breaker is **Wins**"
    ]

    em = discord.Embed(
        title="📏 1v1 Scoring, Ranks & Procedure",
        color=discord.Color.gold()
    )
    em.add_field(name="Scoring", value="\n".join(scoring_lines), inline=False)
    em.add_field(name="Ranks (by Points)", value=rank_table, inline=False)
    em.add_field(
        name="Match Procedure",
        value=(
            "1) Start via **?challenge @user** (opponent accepts) **OR** join **?queue** "
            f"(auto-match when another player joins; timeout **{_timeout_human()}**).\n"
            "2) Bot creates a **private text channel** and a **temporary voice channel** for the two players. "
            "An **admin-only card** is posted in the results channel. "
            "(A public card may also be posted in the announce channel.)\n"
            "3) **Players** upload a **clear screenshot** of the result in the **private text room**.\n"
            "4) **Admins** react **🅰️/🅱️** on the admin card to confirm the winner.\n"
            "5) Bot applies **points, streak, and rank**, updates the **public card** (if present), "
            "announces the result in the **private room**, **refreshes the leaderboard**, and then "
            "**auto‑deletes the private text & voice channels after a short delay**.\n"
            "6) If a match is never confirmed, the bot has a **safety timeout** that cleans up rooms."
        ),
        inline=False
    )
    em.add_field(
        name="Weekly Nitro Reward",
        value=(
            "Every week, the player ranked **#1** on the leaderboard will receive **Discord Nitro**.\n"
            "Each player can only win Nitro **once per month** — if the same player is #1 again, it passes to the next eligible player."
        ),
        inline=False
    )
    em.set_footer(text="Play fair. Clear screenshots help admins confirm quickly.")
    em.set_image(url="https://media.discordapp.net/attachments/1095053356478771202/1404403394201915462/Screenshot_2025-08-11_at_11.55.49.png")
    await ctx.send(embed=em)







@bot2.command(
    name="resetleaderboard",
    help="Reset ALL leaderboard stats and match history (Admin role only). Usage: ?resetleaderboard confirm"
)
async def reset_leaderboard(ctx, confirm: str = None):
    admin_role = discord.utils.get(ctx.guild.roles, id=ADMIN_ROLE_ID)
    if not admin_role or admin_role not in ctx.author.roles:
        await ctx.send("❌ You do not have permission to use this command.")
        return

    if confirm != "confirm":
        await ctx.send(
            "⚠️ This will reset **all** points, wins, streaks, and **delete the entire match history**.\n"
            "If you're sure, run: `?resetleaderboard confirm`"
        )
        return

    try:
        # 1) Do destructive edits inside a normal transaction
        with sqlite3.connect(DB_PATH) as con:
            con.execute("UPDATE wins SET wins = 0, points = 0, streak = 0")
            con.execute("DELETE FROM matches")
            con.commit()

        # 2) VACUUM MUST be outside any transaction; use autocommit connection
        try:
            with sqlite3.connect(DB_PATH, isolation_level=None) as con2:
                con2.execute("VACUUM")
        except Exception as e:
            # Optional: not fatal; DB will still work even if VACUUM fails
            print(f"[Bot2] VACUUM skipped: {e}")

        # 3) Refresh the live leaderboard
        await refresh_leaderboard_message(ctx.guild)
        await ctx.send("✅ Leaderboard and match history have been reset.")

    except Exception as e:
        await ctx.send(f"❌ Failed to reset leaderboard: `{e}`")

@bot2.command(
    name="cancelmatch",
    help="Admin: Cancel an in-progress 1v1 (no result). Usage: ?cancelmatch <admin_message_id> [reason...] OR ?cancelmatch @A @B [reason...]"
)
@commands.has_role(ADMIN_ROLE_ID)
async def cancelmatch_cmd(ctx: commands.Context, *args):
    # Restrict to the admin results channel
    if ctx.channel.id != WIN_REPORT_CHANNEL_ID:
        return await ctx.reply("⚠️ Please run this command in the results channel.")

    if not args:
        return await ctx.reply(
            "Usage:\n"
            "`?cancelmatch <admin_message_id> [reason...]`\n"
            "or\n"
            "`?cancelmatch @A @B [reason...]`"
        )

    reason = None
    admin_msg_id = None
    try:
        # Try path 1: admin message ID
        admin_msg_id = int(args[0])
        reason = " ".join(args[1:]).strip() or "Cancelled by admin"
    except ValueError:
        pass  # Not an int, fall through

    guild = ctx.guild
    actor = ctx.author

    if admin_msg_id is not None:
        match = MATCHES.get(admin_msg_id)
        if not match or match.get("resolved"):
            return await ctx.reply("No active match found with that admin message ID.")
        ok = await cancel_match(guild, admin_msg_id, reason=reason, actor=actor)
        if ok:
            return await ctx.reply(f"✅ Match **{admin_msg_id}** cancelled.")
        else:
            return await ctx.reply("⚠️ Could not cancel (maybe already resolved?).")

    # Path 2: cancel by two player mentions
    if len(ctx.message.mentions) >= 2:
        a = ctx.message.mentions[0]
        b = ctx.message.mentions[1]
        target_id = None
        for adm_id, m in list(MATCHES.items()):
            if m.get("resolved"):
                continue
            if {m.get("a"), m.get("b")} == {a.id, b.id}:
                target_id = adm_id
                break

        if not target_id:
            return await ctx.reply("No active match found for those two players.")

        reason = " ".join(args[2:]).strip() or "Cancelled by admin"
        ok = await cancel_match(guild, target_id, reason=reason, actor=actor)
        if ok:
            return await ctx.reply(f"✅ Match **{target_id}** cancelled.")
        else:
            return await ctx.reply("⚠️ Could not cancel (maybe already resolved?).")

    return await ctx.reply(
        "Please provide either the **admin message ID** or **two player mentions**."
    )


# =========================
# WARN COMMANDS
# =========================

# ---- /warn -> !warn ----
@bot2.command(name="warn", help="Warn a member (auto-timeout at 3 and 5 warnings). Use with !")
@warning_only()
@commands.has_permissions(moderate_members=True)        # user needs Timeout Members
@commands.bot_has_permissions(moderate_members=True)    # bot needs Timeout Members
async def warn_cmd(ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = None):
    # Self & hierarchy checks
    if member.id == ctx.author.id:
        return await ctx.reply("You can’t warn yourself 🙂")

    bot_member = ctx.guild.me
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        return await ctx.reply("You can’t warn someone with an equal or higher role.")

    if member.top_role >= bot_member.top_role:
        return await ctx.reply("I don’t have a high enough role to manage that member.")

    if member.bot:
        return await ctx.reply("I won’t warn bots.")

    guild_id = ctx.guild.id
    user_id = member.id

    try:
        # Increment + log (your helpers)
        current = _get_warn_count(guild_id, user_id)
        new_count = current + 1
        _set_warn_count(guild_id, user_id, new_count)
        _log_warning(guild_id, user_id, ctx.author.id, reason)

        base = f"⚠️ **{member.mention}** has been warned."
        detail = f" Current warnings: **{new_count}**."
        acted = ""

        # Thresholds
        if new_count == 3:
            ok, info = await _apply_timeout(member, WARN_TIMEOUT_AT_3_DAYS, reason=f"3 warnings (by {ctx.author})")
            acted += (
                f"\n⏳ Applied **{WARN_TIMEOUT_AT_3_DAYS} day** timeout "
                f"(until **{info.strftime('%Y-%m-%d %H:%M UTC')}**)." if ok
                else f"\n⚠️ Tried to timeout but failed: `{info}`"
            )

        if new_count == 5:
            ok, info = await _apply_timeout(member, WARN_TIMEOUT_AT_5_DAYS, reason=f"5 warnings (by {ctx.author})")
            acted += (
                f"\n⏳ Applied **{WARN_TIMEOUT_AT_5_DAYS} day** timeout "
                f"(until **{info.strftime('%Y-%m-%d %H:%M UTC')}**)." if ok
                else f"\n⚠️ Tried to timeout but failed: `{info}`"
            )
            if WARN_RESET_AT_5:
                _set_warn_count(guild_id, user_id, 0)
                detail = " Current warnings: **0** (auto-reset after 5)."

        embed = discord.Embed(
            title="Member Warned",
            description=f"{base}{detail}{acted}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Reason", value=(reason if reason else "(no reason)"), inline=False)
        embed.set_footer(text=f"By {ctx.author} • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        await ctx.reply(embed=embed, mention_author=False)

        # Log channel
        try:
            log_ch = ctx.guild.get_channel(1411283522131591178)
            if log_ch:
                new_count_for_log = 0 if (new_count == 5 and WARN_RESET_AT_5) else new_count
                log_em = discord.Embed(
                    title="⚠️ Warning Issued",
                    color=discord.Color.orange(),
                    description=(f"**User:** {member.mention} (`{member.id}`)\n"
                                 f"**Moderator:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                                 f"**Guild:** `{ctx.guild.name}` (`{ctx.guild.id}`)")
                )
                log_em.add_field(name="New Count", value=str(new_count_for_log), inline=True)
                log_em.add_field(name="Reason", value=(reason if reason else "(no reason)"), inline=False)

                actions = []
                if new_count == 3:
                    actions.append(f"Applied **{WARN_TIMEOUT_AT_3_DAYS} day** timeout.")
                if new_count == 5:
                    actions.append(f"Applied **{WARN_TIMEOUT_AT_5_DAYS} day** timeout.")
                    if WARN_RESET_AT_5:
                        actions.append("Warnings **auto-reset to 0**.")
                if actions:
                    log_em.add_field(name="Action", value="\n".join(actions), inline=False)

                log_em.set_footer(text=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
                await log_ch.send(embed=log_em)
            else:
                print("[WARNINGS] Log channel 1411283522131591178 not found in this guild.")
        except Exception as e:
            print(f"[WARNINGS] Failed to send warn log: {e}")

    except discord.Forbidden:
        await ctx.reply("❌ I’m missing permissions (Moderate/Ban Members or role position).")
    except Exception as e:
        logging.error("warn_cmd failed: %s", e)
        await ctx.reply("⚠️ Something went wrong processing the warning. Check logs.")

# ---- /warnings -> !warnings ----
@bot2.command(name="warnings", help="View your warnings or another member's. Use with !")
@warning_only()
async def warnings_cmd(ctx: commands.Context, member: Optional[discord.Member] = None):
    target = member or ctx.author
    count = _get_warn_count(ctx.guild.id, target.id)
    history = _get_warning_history(ctx.guild.id, target.id, limit=10)

    em = discord.Embed(
        title=f"Warnings for {target}",
        color=discord.Color.gold()
    )
    em.add_field(name="Current Count", value=str(count), inline=True)
    if history:
        lines = []
        for mod_id, reason, created_at in history:
            mod = ctx.guild.get_member(mod_id)
            mod_name = mod.mention if mod else f"Mod:{mod_id}"
            ts = created_at.replace('T', ' ').replace('+00:00', ' UTC')
            reason_show = reason if reason else "(no reason)"
            lines.append(f"• **{ts}** — by {mod_name}: {reason_show}")
        em.add_field(name="Recent History (latest 10)", value="\n".join(lines), inline=False)
    else:
        em.add_field(name="Recent History", value="No warnings logged.", inline=False)

    await ctx.reply(embed=em, mention_author=False)

# ---- /resetwarnings -> !clearwarnings (admins only) ----
@bot2.command(
    name="clearwarnings",
    help="Admin: Reset a member's warnings (count + full history) and clear any active timeout. Usage: ?clearwarnings @user [reason]"
)
@warning_only()
@commands.has_permissions(administrator=True)            # ONLY admins
@commands.bot_has_permissions(moderate_members=True)     # bot must be able to clear timeout
async def clearwarnings_cmd(ctx: commands.Context, member: discord.Member, *, reason: str = "Warnings reset by staff"):
    # --- role position checks ---
    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.reply("You can’t reset warnings for someone with an equal or higher role.", mention_author=False)
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.reply("I don’t have a high enough role to manage that member.", mention_author=False)

    guild_id = ctx.guild.id
    user_id = member.id

    # --- snapshot before reset (count + history size) ---
    try:
        before_count = _get_warn_count(guild_id, user_id)
    except Exception:
        before_count = 0

    # Count history entries (for nicer reporting)
    try:
        conn = _ensure_warn_conn()
        cur = conn.execute("SELECT COUNT(*) FROM warnings_log WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        history_entries = int(cur.fetchone()[0] or 0)
    except Exception:
        history_entries = 0

    # --- perform reset (count -> 0, purge history) ---
    try:
        _reset_user_warnings(guild_id, user_id)
        reset_ok = True
        reset_err = None
    except Exception as e:
        reset_ok = False
        reset_err = str(e)

    # Try to remove active timeout regardless of DB outcome (best-effort)
    timeout_removed = False
    timeout_info = None
    try:
        ok, info = await _remove_timeout(member, reason=f"Warnings reset by {ctx.author} • {reason}")
        timeout_removed = bool(ok)
        timeout_info = info
    except Exception as e:
        timeout_removed = False
        timeout_info = str(e)

    # --- build response message ---
    if reset_ok:
        base = (f"✅ Cleared **warnings & full history** for {member.mention}.\n"
                f"• Previous count: **{before_count}**\n"
                f"• History entries removed: **{history_entries}**")
    else:
        base = (f"⚠️ Tried to clear warnings/history for {member.mention} but hit an error:\n"
                f"`{reset_err}`")

    if timeout_removed:
        base += "\n• Timeout: **removed**"
    else:
        base += f"\n• Timeout: **not removed**" + (f" (error: `{timeout_info}`)" if timeout_info else "")

    base += f"\n🗒️ Reason: {reason}"

    await ctx.reply(base, mention_author=False)

    # --- LOG to channel 1411283522131591178 ---
    try:
        log_ch = ctx.guild.get_channel(1411283522131591178)
        if log_ch:
            color = discord.Color.green() if reset_ok else discord.Color.orange()
            log_em = discord.Embed(
                title="♻️ Warnings Reset",
                color=color,
                description=(f"**User:** {member.mention} (`{member.id}`)\n"
                             f"**By:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                             f"**Guild:** `{ctx.guild.name}` (`{ctx.guild.id}`)")
            )
            log_em.add_field(name="Previous Count", value=str(before_count), inline=True)
            log_em.add_field(name="History Removed", value=str(history_entries), inline=True)
            log_em.add_field(name="DB Reset", value=("Success" if reset_ok else f"Failed: {reset_err}"), inline=False)
            log_em.add_field(name="Timeout Cleared", value=("Yes" if timeout_removed else f"No{(' (error: ' + str(timeout_info) + ')') if timeout_info else ''}"), inline=False)
            log_em.add_field(name="Reason", value=reason or "—", inline=False)
            log_em.set_footer(text=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
            await log_ch.send(embed=log_em)
        else:
            print("[WARNINGS] Log channel 1411283522131591178 not found in this guild.")
    except Exception as e:
        print(f"[WARNINGS] Failed to send reset log: {e}")


# =========================
# RUNNER (env-based)
# =========================
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BOT2_TOKEN = os.getenv("BOT2_TOKEN")
if not BOT2_TOKEN:
    raise RuntimeError("Missing BOT2_TOKEN in environment/.env")

async def main():
    await bot2.start(BOT2_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down Bot 2...")

