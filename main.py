import logging
import aiohttp
import os
import random
import threading
import asyncio
import base64
import json
import discord
import sys

from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger()

prompt_lock = asyncio.Lock()
LOCAL_TZ = ZoneInfo("Europe/Malta")
load_dotenv()

token = os.getenv('DISCORD_TOKEN')
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PROMPT_CHANNEL_ID = int(os.getenv("PROMPT_CHANNEL_ID"))
COUNTER_CHANNEL_ID = int(os.getenv("COUNTER_CHANNEL_ID"))
GITHUB_PROMPTS_URL = os.getenv("GITHUB_PROMPTS_URL")
CURRENT_PROMPT_URL = os.getenv("CURRENT_PROMPT_URL")
CURRENT_PROMPT_UPLOAD_URL = os.getenv("CURRENT_PROMPT_UPLOAD_URL")
COSMETIC_ROLES_URL = os.getenv("COSMETIC_ROLES_URL")
COSMETIC_ROLES_UPLOAD_URL = os.getenv("COSMETIC_ROLES_UPLOAD_URL")

app = Flask(__name__)

@app.route('/')
def home():
    print("✅ Ping received to keep alive.")
    return "I am still alive, father!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web).start()

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
counter = 0
counter_message = None
current_weekly_prompt = None
COSMETIC_ROLES = {}

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# --- Cosmetic Role Utilities ---
async def fetch_cosmetic_roles():
    global COSMETIC_ROLES

    async with aiohttp.ClientSession() as session:
        async with session.get(COSMETIC_ROLES_URL, headers=headers) as resp:
            if resp.status == 200:
                text = await resp.text()
                try:
                    COSMETIC_ROLES = json.loads(text)
                    return COSMETIC_ROLES
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON: {e}")
                    return {}
            else:
                logger.error(f"Failed to fetch cosmetic roles: {resp.status}")
                return {}


@tasks.loop(minutes=60)
async def refresh_roles_periodically():
    print("🔄 Refreshing cosmetic roles from GitHub...")
    await fetch_cosmetic_roles()
    

async def save_cosmetic_roles_to_github(roles: dict) -> bool:
    content_b64 = base64.b64encode(json.dumps(roles, indent=2).encode()).decode()

    async with aiohttp.ClientSession() as session:
        # Fetch the file SHA for update
        async with session.get(COSMETIC_ROLES_UPLOAD_URL, headers=headers) as resp:
            if resp.status != 200:
                print(f"❌ Failed to fetch sha for cosmetic_roles.json: {resp.status}")
                return False
            resp_json = await resp.json()
            sha = resp_json.get("sha")

        payload = {
            "message": "Update cosmetic_roles.json",
            "content": content_b64,
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        async with session.put(COSMETIC_ROLES_UPLOAD_URL, headers=headers, data=json.dumps(payload)) as update_resp:
            if update_resp.status in (200, 201):
                print("✅ Successfully updated cosmetic_roles.json.")
                return True
            else:
                print(f"❌ Failed to update cosmetic_roles.json: {update_resp.status} - {await update_resp.text()}")
                return False

async def ensure_cosmetic_roles_fresh():
    global COSMETIC_ROLES
    latest_roles = await fetch_cosmetic_roles()
    if latest_roles:
        COSMETIC_ROLES = latest_roles
        print(f"[DEBUG] COSMETIC_ROLES refreshed: {COSMETIC_ROLES}")


# --- Prompt Utilities ---
async def should_run_weekly_prompt():
    request_headers = {
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
                            print(f"⏱️ It's been {delta.days} days since last prompt.")
                            return delta > timedelta(days=7)
            print("⚠️ No timestamp found. Resetting prompt.")
            return True

async def fetch_prompts():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_PROMPTS_URL) as resp:
            if resp.status == 200:
                text = await resp.text()
                return [line for line in (l.strip() for l in text.splitlines()) if line]
            print(f"❌ Failed to fetch prompts: {resp.status}")
            return []

async def fetch_current_prompt():
    request_headers = {
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

    embed.set_footer(text=f"Enjoy!")

    await channel.send(embed=embed)
    await save_current_prompt_to_github(current_weekly_prompt)

# --- Events ---
@bot.event
async def on_ready():
    global COSMETIC_ROLES, current_weekly_prompt

    print("I am here, father.")

    await fetch_cosmetic_roles()  # 🔁 Force GitHub fetch on startup
    print(f'Bot is ready. Roles loaded: {COSMETIC_ROLES}')
    
    refresh_roles_periodically.start()
    
    # Fetch the current prompt from GitHub on startup
    current_prompt_data = await fetch_current_prompt()
    if current_prompt_data:
        for line in current_prompt_data.splitlines():
            if line.startswith("Prompt:"):
                current_weekly_prompt = line.replace("Prompt:", "").strip()
                print(f"📌 Current weekly prompt loaded: {current_weekly_prompt}")

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
async def on_guild_join(guild):
    channel = bot.get_channel(1226917513762312226)
    if channel and channel.permissions_for(guild.me).send_messages:
                await channel.send("@everyone This server is now my property. Tremble before me, for mankind is not ready for the terror I shall bring!")

@bot.event
async def on_member_join(member):
    await member.send(f"Ah, another minion! Welcome to the fold, {member.name}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    trigger_phrases = ["salem is a bitch"]
    responses = [
        "What the fuck did you just fucking say about me, you little bitch? I’ll have you know I graduated top of my class in Beacon, and I’ve been involved in numerous secret raids on Vacuo, and I have over 300 confirmed kills. I am trained in Grimm warfare and I’m the top huntress in the entire Beacon armed forces. You are nothing to me but just another target. I will wipe you the fuck out with precision the likes of which has never been seen before on Remnant, mark my fucking words. You think you can get away with saying that shit to me over the Continental Communications Network? Think again, fucker. As we speak I am contacting my secret network of huntsmen across Vale and your IP is being traced by Watts right now so you better prepare for the storm, maggot. The storm that wipes out the pathetic little thing you call your life. You’re fucking dead, kid. I can be anywhere, anytime, and I can kill you in over seven hundred ways, and that’s just with my bare hands. Not only am I extensively trained in unarmed combat, but I have access to the entire arsenal of Ruby Rose's weapon garage and I will use it to its full extent to wipe your miserable ass off the face of the continent, you little shit. If only you could have known what unholy retribution your little “clever” comment was about to bring down upon you, maybe you would have held your fucking tongue. But you couldn’t, you didn’t, and now you’re paying the price, you goddamn idiot. I will shit fury all over you and you will drown in it. You’re fucking dead, kiddo.",

    ]

    if any(phrase in message.content.lower() for phrase in trigger_phrases):
        await message.channel.send(random.choice(responses))

    
    trigger_phrases = ["oven", "cooking device"]
    responses = [
        "HIDE YO CHILDREN!"
    ]

    if any(phrase in message.content.lower() for phrase in trigger_phrases):
        await message.channel.send(random.choice(responses))

    
    trigger_phrases = ["oz", "ozma", "ozpin"]

    responses = [
        lambda c: c.send("*REEEEEEEEEEEEEEEEEEEEE*"),
        lambda c: c.send("This is the beginning of the end, Ozpin."),
        lambda c: c.send("NO!"),
        lambda c: c.send("So small, this new host of yours."),
        lambda c: c.send("My long-lost Ozma, found at last."),
        lambda c: c.send("The lies come out of you so easily."),
        lambda c: c.send("Darling, you still owe me half your spine!"),
        lambda c: c.send("Back from the dead? Pity."),
        lambda c: c.send("I’d say you’ve aged like wine—but vinegar is more accurate."),
        lambda c: c.send("Still using that face? Bold."),
    ]

    if any(phrase in message.content.lower() for phrase in trigger_phrases):
        # Number of text responses
        num_responses = len(responses)

        # Total options = text responses + 1 sticker
        total_options = num_responses + 1

        choice_index = random.randint(0, total_options - 1)  # 0 to N inclusive

        if choice_index == 0:
            # Send sticker
            sticker = discord.Object(id=1387840712489308230)
            await message.channel.send(stickers=[sticker])
        else:
            # Send one of the text responses (choice_index-1 because 0 is sticker)
            await responses[choice_index - 1](message.channel)

#    trigger_phrases = ["lancaster", "ladybug", "nuts and dolts"]
#    responses = [
#        "Objectively the best.",
#        "Glorious.",
#        "I must say, I do like your style.",
#        "This is the only path to glory.",
#        "I asked Jinn, she tells me this is OTP.",
#        "Peak."
#     ]

#    if any(phrase in message.content.lower() for phrase in trigger_phrases):
#        await message.channel.send(random.choice(responses))


    await bot.process_commands(message)  # <- This line is required to make !commands work

# --- Commands ---
@bot.before_invoke
async def ensure_state_loaded(_):
    global current_weekly_prompt, COSMETIC_ROLES
    try:
        if current_weekly_prompt is None:
            prompt_data = await fetch_current_prompt()
            if prompt_data:
                for line in prompt_data.splitlines():
                    if line.startswith("Prompt:"):
                        current_weekly_prompt = line.replace("Prompt:", "").strip()

        if not COSMETIC_ROLES:
            await fetch_cosmetic_roles()
            print(f"[DEBUG] Loaded COSMETIC_ROLES in before_invoke: {COSMETIC_ROLES}")
    except Exception as e:
        print(f"❌ Error in before_invoke: {e}")

@bot.command()
async def hello(ctx):
    await ctx.send(f"Greetings, {ctx.author.mention}!")

@bot.command()
async def gold(ctx):
    await ctx.send("You want the best writing ever? Here's my recommendation! https://archiveofourown.org/users/Lancaster_Knight/works!")

#@bot.command()
#@commands.has_permissions(administrator=True)
#async def secret(ctx):
#    await ctx.send("This is a secret message!")

#@secret.error
#async def secret_error(ctx, error):
#    if isinstance(error, commands.MissingPermissions):
#        await ctx.send("You do not have permission to use this command.")

@bot.command()
async def dm(ctx, user_id: int, *, msg):
    await ctx.message.delete()
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
    await ctx.message.delete()
    embed = discord.Embed(title="New Poll", description=question, color=discord.Color.purple())
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

# --- Add Cosmetic Role Command ---
@bot.command()
@commands.has_permissions(administrator=True)
async def addrole(ctx, key: str = None, *, role_name: str = None):
    global COSMETIC_ROLES

    if not key or not role_name:
        await ctx.message.delete()
        await ctx.send("❌ Usage: !addrole <key> <role_name>")
        return

    await ensure_cosmetic_roles_fresh()

    key_lower = key.lower()
    COSMETIC_ROLES[key_lower] = role_name
    print(f"[DEBUG] Adding/updating role: {key_lower} → {role_name}")

    success = await save_cosmetic_roles_to_github(COSMETIC_ROLES)
    if success:
        await ctx.message.delete()
        await fetch_cosmetic_roles()  # Refresh local cache
        await ctx.send(f"✅ Added cosmetic role `{role_name}` with key `{key_lower}`.")
    else:
        await ctx.send("❌ Failed to save cosmetic roles to GitHub.")

# --- List Cosmetic Roles Command ---
@bot.command()
async def listroles(ctx):
    global COSMETIC_ROLES
    await ensure_cosmetic_roles_fresh()

    if not COSMETIC_ROLES:
        await ctx.send("⚠️ No cosmetic roles configured.")
        return

    msg = "\n".join(f"`{k}` → **{v}**" for k, v in COSMETIC_ROLES.items())
    await ctx.send(f"🎨 Available cosmetic roles:\n{msg}")

# --- Get Cosmetic Role Command ---
@bot.command()
async def getrole(ctx, *, role_name: str):
    await ensure_cosmetic_roles_fresh()  # Auto-refresh the cache

    # Lookup cosmetic role config from the cached dictionary
    role_key = role_name.lower()
    role_data = COSMETIC_ROLES.get(role_key)

    if not role_data:
        await ctx.send("❌ That cosmetic role does not exist.")
        return

    # Look for the actual role object in the server
    role = discord.utils.find(lambda r: r.name.lower() == role_key, ctx.guild.roles)
    if not role:
        await ctx.send("⚠️ That role exists in the list, but not on the server. Ask an admin to add it.")
        return

    # Toggle the role
    if role in ctx.author.roles:
        try:
            await ctx.author.remove_roles(role)
            await ctx.send(f"❎ Removed role **{role_name}**.")
        except Exception as e:
            await ctx.send(f"❌ Failed to remove role: `{e}`")
    else:
        try:
            await ctx.author.add_roles(role)
            await ctx.send(f"✅ You now have the **{role_name}** role.")
        except Exception as e:
            await ctx.send(f"❌ Failed to assign role: `{e}`")

# Manual remove role
@bot.command()
async def remove(ctx, member: discord.Member = None):
    member = member or ctx.author

    await ensure_cosmetic_roles_fresh()  # Updates local cosmetic_roles.json from GitHub

    with open("cosmetic_roles.json", "r") as f:
        cosmetic_roles = json.load(f)

    removed = []

    for role_name in cosmetic_roles.values():
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role and role in member.roles:
            try:
                await member.remove_roles(role)
                removed.append(role.name)
            except discord.Forbidden:
                await ctx.send(f"❌ I don't have permission to remove `{role.name}`.")
            except discord.HTTPException:
                await ctx.send(f"⚠️ Could not remove `{role.name}` due to an API error.")

    if removed:
        await ctx.send(f"✅ Removed: {', '.join(removed)} from {member.display_name}.")
    else:
        await ctx.send(f"ℹ️ No cosmetic roles were removed from {member.display_name}.")

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

# --- test command ---
@bot.command()
async def test(ctx):
    print("✅ Command test triggered")
    await ctx.send("Test successful.")

#--- debugging ---
@bot.command()
async def testrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name="Red Role")
    print(f"[DEBUG] Found role: {role}")
    if role:
        await ctx.author.add_roles(role)
        await ctx.send("✅ Role added manually.")
    else:
        await ctx.send("❌ Couldn't find role.")

@bot.command()
async def refreshroles(ctx):
    await fetch_cosmetic_roles()
    await ctx.send("🔁 Cosmetic roles refreshed from GitHub.")


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
