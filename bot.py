import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os

load_dotenv()   
TOKEN = os.getenv('DISCORD_TOEKN')
ID = os.getenv('CHANNEL_ID')

handlers = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

if ID is None:
    raise ValueError("Channel ID not found in environment variables.")
CHANNEL_ID = int(ID)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

@bot.command()
async def join(ctx):

    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send(f'Joined {channel}')
    else:
        await ctx.send('You are not connected to a voice channel.')

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.guild.voice_client.disconnect()
        await ctx.send('Disconnected from the voice channel.')
    else:
        await ctx.send('I am not connected to any voice channel.')


if TOKEN:
    bot.run(TOKEN, log_handler=handlers)
else:
    print("Error: DISCORD_TOKEN not found in .env file")