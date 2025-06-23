import logging
import aiohttp
import os
import random
import threading

import discord
from discord.ext import tasks, commands
from dotenv import load_dotenv
from flask import Flask

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
PROMPT_CHANNEL_ID = int(os.getenv("PROMPT_CHANNEL_ID"))

# Dummy web server to keep Render happy
app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is running!"


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

writing_prompts = [
    "Two strangers meet in a laundromat at 2 AM.",
    "A letter is delivered 50 years late.",
    "A character wakes up with a tattoo they don't remember getting.",
    "The world has stopped spinning. What happens next?",
    "Your protagonist finds a message in a bottle... from themselves.",
    "Someone gets a voicemail from the future.",
    "The moon is suddenly much closer. How does the world react?",
    "A child draws something — and it becomes real.",
    "You wake up in a world where your favorite book is reality.",
    "Everyone can see the date they will die. Except one person.",
    "A stranger offers you a suitcase full of money — with one condition.",
    "An elevator stops on a floor that doesn't exist.",
    "A character has never seen their own reflection.",
    "You hear your favorite song. No one else does.",
    "Time freezes for everyone but your protagonist.",
    "Your character inherits a key. No one knows what it unlocks.",
    "Every lie your character tells becomes true.",
    "Your dreams start leaving physical evidence.",
    "A character is followed by a cloud that rains only on them.",
    "You receive a photo in the mail — of you sleeping.",
    "You move into a new apartment and find a locked door with no key.",
    "You're reborn every time you die — in a new body, but with all memories.",
    "You find a hidden room in your house no one knew existed.",
    "Everyone you touch hears your thoughts.",
    "You receive a text from someone who died last year.",
    "You can pause time, but only while holding your breath.",
    "You wake up with someone else's memories.",
    "A library book contains handwritten notes — in your handwriting.",
    "A childhood imaginary friend suddenly appears as an adult.",
    "You keep reliving the same hour over and over.",
    "Every time you fall asleep, you wake up in a different reality.",
    "Everyone gets one wish — yours comes true 10 years late.",
    "You discover your life is a story being written by someone else.",
    "A mirror shows a different version of you.",
    "You can see the strings connecting people who love each other.",
    "The stars vanish from the night sky.",
    "Everyone in the world forgets your name overnight.",
    "Your voice changes depending on who you talk to.",
    "Your shadow starts acting on its own.",
    "Rain never touches your skin — not once in your life.",
    "Your house plants begin whispering secrets to you.",
    "You write stories — and they come true.",
    "You wake up speaking a language that doesn't exist.",
    "Your phone shows texts from 100 years ago.",
    "You open a book, and it describes exactly what you're doing right now.",
    "You find a door labeled 'Do Not Open.' It opens itself.",
    "Each time you look in the mirror, your reflection is older than you.",
    "You sneeze and swap bodies with someone nearby.",
    "You discover a second heartbeat inside your chest.",
    "A bird follows you everywhere and speaks only in riddles.",
    "You inherit a cabin. It has no doors.",
    "You hear your name whispered in the wind — constantly."
]

secret_role = "test"


@bot.event
async def on_ready():
    print("I am here, father")
    if not weekly_prompt.is_running():
        weekly_prompt.start()


@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server, {member.name}!")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    #text filter
    if "whiterose" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} Please don't blaspheme!")

    await bot.process_commands(message)


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


#--------------------------------------------------------

current_weekly_prompt = None


async def send_weekly_prompt(channel):
    global current_weekly_prompt
    current_weekly_prompt = random.choice(writing_prompts)

    embed = discord.Embed(
        title="📝 Weekly Writing Prompt",
        description=f"```{current_weekly_prompt}```",
        color=discord.Color.purple()
    )
    await channel.send(embed=embed)


#--------------------------------------------------------

# weekly prompt
@tasks.loop(seconds=604800)  # 1 week
async def weekly_prompt():
    try:
        channel = await bot.fetch_channel(PROMPT_CHANNEL_ID)
        if channel:
            await send_weekly_prompt(channel)
        else:
            print("❌ Weekly prompt channel not found.")
    except Exception as e:
        print(f"❌ Error sending weekly prompt: {e}")


#manual launch of prompt
@bot.command()
@commands.has_permissions(administrator=True)
async def startprompt(ctx):
    """Manually trigger a new weekly prompt."""
    await send_weekly_prompt(ctx.channel)
    await ctx.reply("✅ Weekly prompt manually posted.")


#manual prompt
@bot.command()
async def prompt(ctx):
    if current_weekly_prompt is None:
        await ctx.reply("⚠️ No weekly prompt has been posted yet.")
    else:
        embed = discord.Embed(
            title="📝 Current Weekly Prompt",
            description=f"```{current_weekly_prompt}```",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)


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


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
