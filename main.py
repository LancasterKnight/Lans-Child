import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

secret_role = "test"

@bot.event
async def on_ready():
  print("I am here, father")

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
    await ctx.send("You want the best writing ever? Here's my recommendation! https://archiveofourown.org/users/Lancaster_Knight/works!")

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




bot.run(token, log_handler=handler, log_level=logging.DEBUG)