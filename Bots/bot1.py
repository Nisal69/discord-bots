# =========================
# bots1.py  (Bot 1 + Bot 3)
# =========================
# - Bot 1 and Bot 3 running together in one process
# - Command prefixes:
#       Bot 1: !
#       Bot 3: $

import asyncio
import discord
from discord.ext import commands, tasks

# -------- Intents (shared) --------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

# -------- Create bots --------
bot1 = commands.Bot(command_prefix='!', intents=intents)
bot3 = commands.Bot(command_prefix='$', intents=intents)

# =========================
# BOT 1
# =========================
@bot1.event
async def on_ready():
    print(f'Bot 1 ready as {bot1.user}')
    await bot1.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="BisBis play CODM"))

@bot1.command()
async def ping(ctx):
    await ctx.reply("Pong from Bot 1!")

# === BEGINNING OF BOT 1 SECTION ===
# Sticky note config (for bot1)
STICKY_CHANNEL_ID = 1104523494508724325
STICKY_NOTE_MESSAGE = (
    "**__Loadout Channel__**\n\n"
    "Welcome to the Loadout Channel! Here, you can share your custom weapon loadouts and explore loadouts shared by the CODM community. "
    "To find all of Balor's loadouts, please refer #👑╏balor-gunsmith channel \n\n"
    "Kindly keep the chat limited to screenshots only as much as possible.\n\n"
    "Thank you for your cooperation! 🎮"
)

# Shared sticky note reference
latest_sticky_note = None

# ========== BOT 1 ==========

@bot1.event
async def on_message(message):
    global latest_sticky_note

    if message.channel.id == STICKY_CHANNEL_ID and message.author != bot1.user:
        if latest_sticky_note:
            try:
                await latest_sticky_note.delete()
            except discord.NotFound:
                pass
        latest_sticky_note = await message.channel.send(STICKY_NOTE_MESSAGE)

    await bot1.process_commands(message)

@bot1.command(name='live')
async def live_bot1(ctx):
    channel = bot1.get_channel(1104488124165394452)
    if channel:
        await channel.send("@everyone **BalorCodm Is Live!!** 🎉")

        embed = discord.Embed(
            title="BalorCodm Is Live!",
            description="**Streaming Now**\nHolyyyy Join for some Crazy Flicks",
            color=discord.Color.red(),
        )
        embed.set_footer(text="Join the fun and chaos!")
        embed.set_image(url="https://cdn.discordapp.com/attachments/1095053356478771202/1307970625704431616/ukKf1nu.gif")

        view = View()
        view.add_item(Button(label="Watch on TikTok", url="https://www.tiktok.com/@bxlormobile/live?enter_from_merge=share&enter_method=share_copy_link", style=discord.ButtonStyle.link))
        view.add_item(Button(label="Watch on YouTube", url="https://www.youtube.com/@BalorCODM", style=discord.ButtonStyle.link))

        await channel.send(embed=embed, view=view)
        await ctx.message.delete()

@bot1.command(name='end')
async def end_bot1(ctx):
    channel = bot1.get_channel(1104488124165394452)
    if channel:
        embed = discord.Embed(
            title="Stream Ended",
            description="**Thanks for everyone who joined!**",
            color=discord.Color.red()
        )
        embed.set_footer(text="Hope to see you again next time!")
        await channel.send(embed=embed)
        await ctx.message.delete()



# =========================
# BOT 3
# =========================
@bot3.event
async def on_ready():
    print(f'Bot 3 ready as {bot3.user}')
    await bot3.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Draco Crashout 👀"))

# Example command (keep/remove as you like)
@bot3.command()
async def ping(ctx):
    await ctx.reply("Pong from Bot 3!")

# === BEGINING OF BOT 3 SECTION
mention_deletion_enabled = True
MENTIONED_USER_ID = 636508971036966922
ALLOWED_ROLE_ID = 1352378784329891980


@bot3.command(name='mentiontoggle')
async def toggle_mention_deletion(ctx):
    global mention_deletion_enabled
    if ALLOWED_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    mention_deletion_enabled = not mention_deletion_enabled
    await ctx.send(f"Mention-deletion feature is now **{'enabled ✅' if mention_deletion_enabled else 'disabled ❌'}**.")

@bot3.event
async def on_message(message):
    if message.author.bot:
        return
    if mention_deletion_enabled and any(user.id == MENTIONED_USER_ID for user in message.mentions):
        try:
            await message.delete()
        except Exception as e:
            print(f"[Bot3] Error deleting mention: {e}")
    await bot3.process_commands(message)

@bot3.command(name='live')
async def live_bot3(ctx):
    ALLOWED_LIVE_ROLE_ID = 1352378784329891980
    TARGET_CHANNEL_ID = 1352401213387313213
    try:
        await ctx.message.delete()
    except:
        pass
    if ALLOWED_LIVE_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You are not authorized to use this command.")
        return
    channel = bot3.get_channel(TARGET_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="DracoCodm Is Live!",
            description="**Streaming Now**\nJoin and say Hiii",
            color=discord.Color.red(),
        )
        embed.set_footer(text="Join the fun and chaos!")
        embed.set_image(url="https://media.discordapp.net/attachments/1237658544598290482/1398395136844759231/itoshi-sae.gif?ex=68853475&is=6883e2f5&hm=cd03023f0184fd968022c8b3d3f12766ee2f068f64ff6149a748e7cd7315e20a&=&width=996&height=424")

        view = View()
        view.add_item(Button(label="Watch on TikTok", url="https://www.tiktok.com/@dracocodm_/live?enter_from_merge=share&enter_method=share_copy_link", style=discord.ButtonStyle.link))

        await channel.send("@everyone **DracoCodm Is Live!!** ")
        await channel.send(embed=embed, view=view)

@bot3.command(name='tiktok')
async def post_tiktok_embed(ctx, video_url: str):
    ALLOWED_TIKTOK_ROLE_ID = 1352378643019599994
    try:
        await ctx.message.delete()
    except:
        pass
    if ALLOWED_TIKTOK_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You are not authorized to use this command.")
        return

    channel = bot3.get_channel(1352401263073034332)
    oembed_url = f"https://www.tiktok.com/oembed?url={video_url}"

    async with aiohttp.ClientSession() as session:
        async with session.get(oembed_url) as response:
            if response.status != 200:
                await ctx.send("❌ Failed to fetch TikTok data. Check the link.")
                return
            data = await response.json()

    author = data.get("author_name", "Unknown Creator")
    title = data.get("title", "No caption available")
    thumbnail = data.get("thumbnail_url")

    embed = discord.Embed(description=f"> *{title}*", color=discord.Color.purple())
    embed.set_author(name=author)
    embed.set_image(url=thumbnail)
    embed.set_footer(text=f"TikTok | @{author}")

    view = View()
    view.add_item(Button(label="Watch Video", url=video_url, style=discord.ButtonStyle.link))

    if channel:
        await channel.send(f"@everyone **{author}** just posted a new TikTok video!")
        await channel.send(embed=embed, view=view)





# =========================
# RUNNER (env-based)
# =========================
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # python-dotenv is optional; if not installed, rely on OS env vars
    pass

BOT1_TOKEN = os.getenv("BOT1_TOKEN")
BOT3_TOKEN = os.getenv("BOT3_TOKEN")

if not BOT1_TOKEN or not BOT3_TOKEN:
    raise RuntimeError("Missing BOT1_TOKEN or BOT3_TOKEN in environment/.env")

async def _start_bot(bot, token):
    await bot.start(token)

async def main():
    await asyncio.gather(
        _start_bot(bot1, BOT1_TOKEN),
        _start_bot(bot3, BOT3_TOKEN),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down Bot 1 & Bot 3...")

