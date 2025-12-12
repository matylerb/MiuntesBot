import discord
from discord.ext import commands, voice_recv
import logging
from dotenv import load_dotenv
import os
import wave
from collections import defaultdict
from datetime import datetime
import asyncio

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
ID = os.getenv('CHANNEL_ID')

# 1. SETUP LOGGING (Hide the RTCP noise)
logging.basicConfig(level=logging.INFO)
# This filters out the "Unexpected rtcp packet" spam
logging.getLogger('discord.ext.voice_recv.reader').setLevel(logging.ERROR)

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

recording_data = defaultdict(list)
is_recording = False

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')
    
    # 2. LOAD OPUS (Using Absolute Path to fix the error)
    if not discord.opus.is_loaded():
        try:
            # Gets the folder where this script is running
            current_folder = os.path.dirname(os.path.abspath(__file__))
            opus_path = os.path.join(current_folder, 'libopus-0.x64.dll')
            
            discord.opus.load_opus(opus_path)
            print("✅ Opus library loaded successfully!")
        except Exception as e:
            print(f"⚠️ Opus Load Warning: {e}")
            print("If you see 'Received Audio' below, you can ignore this warning.")

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect(cls=voice_recv.VoiceRecvClient)
        await ctx.send(f"Joined {channel.name}!")
    else:
        await ctx.send("You need to be in a voice channel first!")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send('Disconnected.')

@bot.command()
async def record(ctx):
    global is_recording, recording_data

    if not ctx.voice_client:
        await ctx.send('I am not in a voice channel. Type !join first.')
        return
    
    recording_data.clear()
    is_recording = True
    
    await ctx.send('🔴 Recording started! Speak now. Type !stop to save.')

    def callback(user, data):
        if not is_recording:
            return
        
        if user is None: 
            return

        if data and data.pcm:
            recording_data[user.id].append(data.pcm)

    ctx.voice_client.listen(voice_recv.BasicSink(callback))

@bot.command()
async def stop(ctx):
    global is_recording, recording_data 

    if ctx.voice_client and is_recording:
        is_recording = False
        ctx.voice_client.stop_listening()
        
        await ctx.send("💾 Processing audio...")
        await asyncio.sleep(1) 

        if not recording_data:
            await ctx.send('⚠️ Recording stopped, but no audio data was captured.')
            return

        files_saved = 0
        for user_id, audio_chunks in recording_data.items():
            user = bot.get_user(user_id)
            if not user:
                user = await bot.fetch_user(user_id)

            if audio_chunks:
                # Combine chunks
                combined_audio = b''.join(audio_chunks)
                
                # Only save if we have more than ~0.5 seconds of audio
                if len(combined_audio) > 50000: 
                    filename = save_audio(user, combined_audio)
                    if filename:
                        await ctx.send(f'✅ Saved: **{filename}**')
                        files_saved += 1
        
        if files_saved == 0:
            await ctx.send("Recording stopped. (Audio was too short/empty to save).")
            
        recording_data.clear()
    else:
        await ctx.send('I am not recording.')

def save_audio(user, data: bytes):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_name = "".join([c for c in user.name if c.isalpha() or c.isdigit()]).rstrip()
    filename = f'{clean_name}_{timestamp}.wav'
    
    channels = 2
    sample_width = 2
    sample_rate = 48000
    
    try:
        with wave.open(filename, 'wb') as f:
            f.setnchannels(channels)
            f.setsampwidth(sample_width)
            f.setframerate(sample_rate)
            f.writeframes(data)
        return filename
    except Exception as e:
        print(f'Error saving {filename}: {e}')
        return None

if TOKEN:
    bot.run(TOKEN)