import logging
import aiohttp
import os
import random
import threading
import asyncio
import base64
import json
import discord

from discord.ext import tasks, commands
from dotenv import load_dotenv
from flask import Flask
from datetime import datetime, timedelta
load_dotenv()

token = os.getenv('DISCORD_TOKEN')
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PROMPT_CHANNEL_ID = int(os.getenv("PROMPT_CHANNEL_ID"))
COUNTER_CHANNEL_ID = int(os.getenv("COUNTER_CHANNEL_ID"))
#PROMPT_FILE_PATH = "prompts.txt"
GITHUB_PROMPTS_URL = os.getenv("GITHUB_PROMPTS_URL")
CURRENT_PROMPT_URL = os.getenv("CURRENT_PROMPT_URL")
CURRENT_PROMPT_UPLOAD_URL = os.getenv("CURRENT_PROMPT_UPLOAD_URL")


#check if 7 days passed since last prompt
async def should_run_weekly_prompt():
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(CURRENT_PROMPT_UPLOAD_URL, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                last_update = data.get("commit", {}).get("committer", {}).get("date")
                if last_update:
                    last_time = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
                    return datetime.utcnow() - last_time > timedelta(days=7)
    return True  # fallback to safe side
    
#fetch prompts from .txt file
async def save_current_prompt_to_github(prompt):
    # First, fetch the current file info to get the SHA (required for updates)
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(CURRENT_PROMPT_UPLOAD_URL, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                sha = data["sha"]
            else:
                print(f"❌ Could not get SHA for current_prompt.txt: {resp.status}")
                sha = None

        content_b64 = base64.b64encode(prompt.encode()).decode()

        payload = {
            "message": "Update current weekly prompt",
            "content": content_b64,
            "branch": "main"
        }

        if sha:
            payload["sha"] = sha

        async with session.put(CURRENT_PROMPT_UPLOAD_URL, headers=headers, data=json.dumps(payload)) as update_resp:
            if update_resp.status in (200, 201):
                print("✅ Successfully updated current_prompt.txt on GitHub")
            else:
                text = await update_resp.text()
                print(f"❌ Failed to update current_prompt.txt: {update_resp.status} - {text}")


# Dummy web server to keep Render happy
app = Flask(__name__)


#@app.route('/')
#def home():
#    return "Bot is running!"


def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Start web server in a separate thread
threading.Thread(target=run_web).start()

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

secret_role = "test"

@bot.event
async def on_ready():
    print("I am here, father")
    
    if not keep_alive_counter.is_running():
        keep_alive_counter.start()
        
    global prompts, current_weekly_prompt
   
    # Load prompts from GitHub
    prompts = await fetch_prompts()
    if not prompts:
        print("⚠️ No prompts loaded.")

    # Load current prompt
    current_weekly_prompt = await fetch_current_prompt()

    if not weekly_prompt.is_running():
        if await should_run_weekly_prompt():
            await weekly_prompt()
        weekly_prompt.start()


@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server, {member.name}!")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # text filter
    if "whiterose" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} Please don't blaspheme!")

    # bully Les moments
#    if "28" in message.content.lower():
#        await message.channel.send("<@394034047258460162> they said the number, nerd")

#    await bot.process_commands(message)


# !hello
@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello, {ctx.author.mention}!")


# !gold
@bot.command()
async def gold(ctx):
    await ctx.send(
        "You want the best writing ever? Here's my recommendation! https://archiveofourown.org/users/Lancaster_Knight/works!")


# add role
@bot.command()
async def assign(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"{ctx.author.mention} has been assigned the role {secret_role}.")
    else:
        await ctx.send("The role does not exist.")


# remove role
@bot.command()
async def remove(ctx):
    role = discord.utils.get(ctx.guild.roles, name=secret_role)
    if role:
        await ctx.author.remove_roles(role)
        await ctx.send(f"{ctx.author.mention} has had the {secret_role} role removed.")
    else:
        await ctx.send("The role does not exist.")


# secret command
@bot.command()
@commands.has_permissions(administrator=True)
async def secret(ctx):
    await ctx.send("This is a secret message!")


@secret.error
async def secret_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")


# dm command
@bot.command()
async def dm(ctx, user_id: int, *, msg):
    user = await bot.fetch_user(user_id)
    if user:
        try:
            await user.send(msg)
            await ctx.send(f"✅ Message sent to {user}")
        except discord.Forbidden:
            await ctx.send("❌ Cannot DM this user.")
    else:
        await ctx.send("❌ User not found.")


# reply command
@bot.command()
async def reply(ctx):
    await ctx.reply("I am replying to your message!")


#poll command
@bot.command()
async def poll(ctx, *, question):
    embed = discord.Embed(title="New Poll", description=question, color=discord.Color.red())
    poll_message = await ctx.send(embed=embed)
    await poll_message.add_reaction("👍")
    await poll_message.add_reaction("👎")


#----Prompt stuff----------------------------------------------------
# --- Utility Functions ---
current_weekly_prompt = None

async def fetch_prompts():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_PROMPTS_URL) as resp:
            if resp.status == 200:
                text = await resp.text()
                return [line.strip() for line in text.splitlines() if line.strip()]
            else:
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
        
# --- Core Prompt Logic ---
# weekly prompt timer
@tasks.loop(seconds=604800)
async def weekly_prompt():
    global current_weekly_prompt

    prompts = await fetch_prompts()
    if not prompts:
        print("⚠️ No prompts found to post.")
        return

    current_weekly_prompt = random.choice(prompts)

    # Post prompt to designated channel
    channel = bot.get_channel(PROMPT_CHANNEL_ID)
    if not channel:
        print("❌ Prompt channel not found.")
        return

    embed = discord.Embed(
        title="📝 Weekly Writing Prompt",
        description=f"```{current_weekly_prompt}```",
        color=discord.Color.red()
    )
    await channel.send(embed=embed)

    # Save current prompt to GitHub
    await save_current_prompt_to_github(current_weekly_prompt)

#kickstart
@bot.command()
@commands.has_permissions(administrator=True)
async def forceprompt(ctx):
    await weekly_prompt()
    await ctx.reply("✅ Prompt manually reset in the prompt channel.", mention_author=False)

#manual prompt
@bot.command()
async def prompt(ctx):
    global current_weekly_prompt
    if current_weekly_prompt is None:
        await ctx.reply("⚠️ No weekly prompt has been posted yet.", mention_author=False)
    else:
        embed = discord.Embed(
            title="📝 Current Weekly Prompt",
            description=f"```{current_weekly_prompt}```",
            color=discord.Color.orange()
        )
        channel = bot.get_channel(PROMPT_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)
            await ctx.reply("✅ Prompt re-posted in the prompt channel.", mention_author=False)
        else:
            await ctx.reply("❌ Prompt channel not found.", mention_author=False)

#--------------------------------------------------------


@bot.command()
async def gif(ctx, *, search: str):
    """Get a random GIF based on a search term."""
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


#----counter----------
counter = 0
counter_message = None  # global reference to the message

@tasks.loop(minutes=1)
async def keep_alive_counter():
    global counter, counter_message
    channel = bot.get_channel(COUNTER_CHANNEL_ID)  # or a separate keep-alive channel
    if channel is None:
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

@app.route('/')
def home():
    print("✅ Ping received to keep alive.")
    return "Bot is still running!"
#--------------------



bot.run(token, log_handler=handler, log_level=logging.DEBUG)
