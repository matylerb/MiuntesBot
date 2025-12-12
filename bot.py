import discord
from discord.ext import commands, voice_recv
import logging
from dotenv import load_dotenv
import os
import asyncio


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
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect(cls=voice_recv.VoiceRecvClient)
        await ctx.send(f"Joined {channel.name} and ready to record!")
    else:
        await ctx.send("You need to be in a voice channel first!")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.guild.voice_client.disconnect()
        await ctx.send('Disconnected from the voice channel.')
    else:
        await ctx.send('I am not connected to any voice channel.')

@bot.command()
async def record(ctx):
    if not ctx.voice_client:
        await ctx.send('I am not connected to a voice channel.')
        return
    
    sink = voice_recv.BasicSink(on_recording_finished)
    ctx.voice_client.listen(sink)
    await ctx.send('Recording started...')

def on_recording_finished(user, data: bytes):
    filename = f'recrecorded_{user.name}.mp3'
    with open(filename, 'wb') as f:
        f.write(data)   
    print(f'Recording saved as {filename}')

@bot.command()
async def stop(ctx):
    if ctx.voice_client and ctx.voice_client.is_listening():
        ctx.voice_client.stop_listening()
        await ctx.send('Recording stopped.')

    else:
        await ctx.send('I am not recording right now.')

if TOKEN:
    bot.run(TOKEN, log_handler=handlers)
else:
    print("Error: DISCORD_TOKEN not found in .env file")