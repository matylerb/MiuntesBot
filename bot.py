import discord
from discord.ext import commands, voice_recv
import logging
from dotenv import load_dotenv
import os
import wave
import asyncio

load_dotenv()   

# Fixed typo: DISCORD_TOEKN -> DISCORD_TOKEN
TOKEN = os.getenv('DISCORD_TOKEN')
ID = os.getenv('CHANNEL_ID')

handlers = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

if ID is None:
    raise ValueError("Channel ID not found in environment variables.")

CHANNEL_ID = int(ID)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  

bot = commands.Bot(command_prefix='!', intents=intents)

recording_data = {}

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
    
    if ctx.voice_client.is_listening():
        await ctx.send('I am already recording.')
        return
    

    def callback(user, data):
        on_recording_finished(user, data)
    
    sink = voice_recv.BasicSink(callback)
    ctx.voice_client.listen(sink)
    

    ctx.voice_client.recording_sink = sink
    
    await ctx.send('Recording started...')

@bot.command()
async def stop(ctx):
    if ctx.voice_client and ctx.voice_client.is_listening():
        ctx.voice_client.stop_listening()
        await ctx.send('Recording stopped. Check console for saved files.')
    else:
        await ctx.send('I am not recording right now.')

def on_recording_finished(user, data):

    if hasattr(data, 'pcm'):
        audio_bytes = data.pcm
    elif hasattr(data, 'packet'):
        audio_bytes = data.packet.decrypted_data
    else:
        audio_bytes = bytes(data)
    
    if audio_bytes:
        save_audio(user, audio_bytes)
        print(f"Received audio from {user.name}: {len(audio_bytes)} bytes")

def save_audio(user, data: bytes):

    filename = f'recording_{user.name}_{user.id}.wav'
    
    print(f"Writing {len(data)} bytes to {filename}...")
    
    # Discord voice data specs
    channels = 2
    sample_width = 2  # 16-bit
    sample_rate = 48000
    
    try:
        with wave.open(filename, 'wb') as f:
            f.setnchannels(channels)
            f.setsampwidth(sample_width)
            f.setframerate(sample_rate)
            f.writeframes(data)
        
        print(f'Successfully saved {filename}')
    except Exception as e:
        print(f'Error saving {filename}: {e}')

if TOKEN:
    bot.run(TOKEN, log_handler=handlers)
else:
    print("Error: DISCORD_TOKEN not found in .env file")