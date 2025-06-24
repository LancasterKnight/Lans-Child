import logging
import aiohttp
import os
import random
import threading
import asyncio
import base64
import json
import discord

from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Malta")
load_dotenv()

token = os.getenv('DISCORD_TOKEN')
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PROMPT_CHANNEL_ID = int(os.getenv("PROMPT_CHANNEL_ID"))
COUNTER_CHANNEL_ID = int(os.getenv("COUNTER_CHANNEL_ID"))
GITHUB_PROMPTS_URL = os.getenv("GITHUB_PROMPTS_URL")
CURRENT_PROMPT_URL = os.getenv("CURRENT_PROMPT_URL")
CURRENT_PROMPT_UPLOAD_URL = os.getenv("CURRENT_PROMPT_UPLOAD_URL")

app = Flask(__name__)

@app.route('/')
def home():
    print("✅ Ping received to keep alive.")
    return "Bot is still running!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web).start()

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
secret_role = "test"
counter = 0
counter_message = None
current_weekly_prompt = None

# --- Prompt Utilities ---
async def should_run_weekly_prompt():
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(CURRENT_PROMPT_UPLOAD_URL, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                content_b64 = data.get("content")
                if content_b64:
                    content = base64.b64decode(content_b64).decode()
                    lines = content.splitlines()
                    for line in lines:
                        if line.startswith("Timestamp:"):
                            timestamp_str = line.replace("Timestamp:", "").strip()
                            last_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))  # UTC aware
                            now_local = datetime.now(LOCAL_TZ)
                            now_utc = now_local.astimezone(timezone.utc)
                            delta = now_utc - last_time

                            delta = now_utc - last_time
                            print(f"⏱️ It's been {delta.days} days since last prompt.")
                            return delta > timedelta(days=7)
            print("⚠️ No timestamp found. Resetting prompt.")
            return True

async def fetch_prompts():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_PROMPTS_URL) as resp:
            if resp.status == 200:
                text = await resp.text()
                return [line.strip() for line in text.splitlines() if line.strip()]
            print(f"❌ Failed to fetch prompts: {resp.status}")
            return []

async def fetch_current_prompt():
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(CURRENT_PROMPT_UPLOAD_URL, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                content_b64 = data.get("content")
                if content_b64:
                    return base64.b64decode(content_b64).decode().strip()
            print(f"❌ Failed to fetch current prompt: {resp.status}")
            return None

async def save_current_prompt_to_github(prompt):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    # New content with timestamp
    now_local = datetime.now(LOCAL_TZ)
    now_iso = now_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    content_raw = f"Prompt: {prompt}\nTimestamp: {now_iso}"
    content_b64 = base64.b64encode(content_raw.encode()).decode()

    async with aiohttp.ClientSession() as session:
        async with session.get(CURRENT_PROMPT_UPLOAD_URL, headers=headers) as resp:
            sha = (await resp.json()).get("sha") if resp.status == 200 else None

        payload = {
            "message": "Update current weekly prompt",
            "content": content_b64,
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        async with session.put(CURRENT_PROMPT_UPLOAD_URL, headers=headers, data=json.dumps(payload)) as update_resp:
            if update_resp.status not in (200, 201):
                print(f"❌ Failed to update current_prompt.txt: {update_resp.status} - {await update_resp.text()}")

async def weekly_prompt_run_once():
    global current_weekly_prompt
    prompts = await fetch_prompts()
    if not prompts:
        print("⚠️ No prompts found to post.")
        return

    current_weekly_prompt = random.choice(prompts)
    channel = bot.get_channel(PROMPT_CHANNEL_ID)
    if not channel:
        print("❌ Prompt channel not found.")
        return
        
    now_utc = datetime.now(timezone.utc)
    unix_ts = int(now_utc.timestamp())
    embed = discord.Embed(
        title="📝 Weekly Writing Prompt",
        description=f"```{current_weekly_prompt}```\n\nPosted at <t:{unix_ts}:F>",
        color=discord.Color.red()
    )

    embed.set_footer(text=f"Posted at <t:{unix_ts}:F>")

    await channel.send(embed=embed)
    await save_current_prompt_to_github(current_weekly_prompt)

# --- Events ---
@bot.event
async def on_ready():
    print("I am here, father.")
    if not keep_alive_counter.is_running():
        keep_alive_counter.start()
    if not prompt_scheduler.is_running():
        prompt_scheduler.start()

@tasks.loop(hours=1)
async def prompt_scheduler():
    print("🕒 Checking if weekly prompt needs to update...")
    if await should_run_weekly_prompt():
        print("✅ It's time! Posting a new weekly prompt.")
        await weekly_prompt_run_once()
    else:
        print("⏳ Not time yet for a new prompt.")

@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server, {member.name}!")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if "whiterose" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} Please don't blaspheme!")

    if "28" in message.content.lower():
        await message.reply("<@394034047258460162> they said the number! Nerd.")

    if "milk & cereal" in message.content.lower():
        await message.reply("Delusional. smh")

    await bot.process_commands(message)  # <- This line is required to make !commands work

# --- Commands ---
@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello, {ctx.author.mention}!")

@bot.command()
async def gold(ctx):
    await ctx.send("You want the best writing ever? Here's my recommendation! https://archiveofourown.org/users/Lancaster_Knight/works!")

@bot.command()
async def assign(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"{ctx.author.mention} has been assigned the role {secret_role}.")

@bot.command()
async def remove(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    if role:
        await ctx.author.remove_roles(role)
        await ctx.send(f"{ctx.author.mention} has had the {secret_role} role removed.")

@bot.command()
@commands.has_permissions(administrator=True)
async def secret(ctx):
    await ctx.send("This is a secret message!")

@secret.error
async def secret_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")

@bot.command()
async def dm(ctx, user_id: int, *, msg):
    user = await bot.fetch_user(user_id)
    if user:
        try:
            await user.send(msg)
            await ctx.send(f"✅ Message sent to {user}")
        except discord.Forbidden:
            await ctx.send("❌ Cannot DM this user.")

@bot.command()
async def reply(ctx):
    await ctx.reply("I am replying to your message!")

@bot.command()
async def poll(ctx, *, question):
    embed = discord.Embed(title="New Poll", description=question, color=discord.Color.red())
    poll_message = await ctx.send(embed=embed)
    await poll_message.add_reaction("👍")
    await poll_message.add_reaction("👎")

@bot.command()
@commands.has_permissions(administrator=True)
async def forceprompt(ctx):
    await weekly_prompt_run_once()
    await ctx.reply("✅ Prompt manually reset in the prompt channel.", mention_author=False)

@bot.command()
async def prompt(ctx):
    global current_weekly_prompt
    if current_weekly_prompt is None:
        await ctx.reply("⚠️ No weekly prompt has been posted yet.", mention_author=False)
    else:
        embed = discord.Embed(title="📝 Current Weekly Prompt", description=f"```{current_weekly_prompt}```", color=discord.Color.orange())
        channel = bot.get_channel(PROMPT_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)
            await ctx.reply("✅ Prompt re-posted in the prompt channel.", mention_author=False)
        else:
            await ctx.reply("❌ Prompt channel not found.", mention_author=False)

@bot.command()
async def gif(ctx, *, search: str):
    api_key = os.getenv("GIPHY_API_KEY")
    url = f"https://api.giphy.com/v1/gifs/search?api_key={api_key}&q={search}&limit=50&offset=0&rating=g&lang=en"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            results = data.get("data")
            if not results:
                await ctx.reply(f"❌ No GIFs found for `{search}`.")
                return
            gif_url = random.choice(results)['images']['original']['url']
            await ctx.reply(gif_url)

# --- Keep-Alive Counter ---
@tasks.loop(minutes=1)
async def keep_alive_counter():
    global counter, counter_message
    channel = bot.get_channel(COUNTER_CHANNEL_ID)
    if not channel:
        print("❌ Keep-alive channel not found.")
        return
    counter += 1
    try:
        if counter_message is None:
            counter_message = await channel.send(f"⏱️ Keep-alive counter: `{counter}` minutes")
        else:
            await counter_message.edit(content=f"⏱️ Keep-alive counter: `{counter}` minutes")
    except Exception as e:
        print(f"❌ Failed to send/edit keep-alive message: {e}")

bot.run(token, log_handler=handler, log_level=logging.DEBUG)
