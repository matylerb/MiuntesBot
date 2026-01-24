import discord
from discord.ext import commands, voice_recv
import logging
from dotenv import load_dotenv
import os
import wave
from collections import defaultdict
from datetime import datetime
import asyncio

from openai import OpenAI
from groq import Groq
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

# --- Load environment ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
RAW_PASSWORD = os.getenv('BOT_PASSWORD', '')
BOT_PASSWORD = RAW_PASSWORD.strip()


if not TOKEN or not OPENAI_API_KEY or not GROQ_API_KEY:
    raise ValueError("DISCORD_TOKEN, OPENAI_API_KEY, and GROQ_API_KEY must be set in .env")

DATA_DIR = "data"
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
MINUTES_DIR = os.path.join(DATA_DIR, "minutes")

for folder in [RECORDINGS_DIR, MINUTES_DIR]:
    os.makedirs(folder, exist_ok=True)

# --- Clients ---
openai_client = OpenAI(api_key=OPENAI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)
llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logging.getLogger('discord.ext.voice_recv.reader').setLevel(logging.ERROR)

# --- Bot ---
bot = commands.Bot(command_prefix='?', intents=discord.Intents.all())

# --- Recording globals ---
recording_data = defaultdict(list)
is_recording = False
meeting_start_time = None
session_unlocked = False

async def check_password(ctx):


    try:
        dm_channel = await ctx.author.create_dm()
        await ctx.send(f"{ctx.author.mention}, check your DMs to enter the password to unlock the bot.")
        await dm_channel.send(f"**Authentication Required**\nPlease enter the bot password to join the call:")
    except discord.Forbidden:
        await ctx.send(f"{ctx.author.mention}, I cannot DM you. Enable Direct Messages.")
        return False
    def check_msg(m):
        return m.author == ctx.author and m.channel == dm_channel

    try:
        msg = await bot.wait_for('message', check=check_msg, timeout=30.0)

        if msg.content.strip() == BOT_PASSWORD:
            await dm_channel.send("**Password Accepted!** Joining channel...")
            await ctx.send(f"{ctx.author.mention} unlocked the bot.")
            return True
        else:
            await dm_channel.send("**Incorrect Password.**")
            await ctx.send(f"{ctx.author.mention} entered the wrong password.")
            return False

    except asyncio.TimeoutError:
        await dm_channel.send("Time out.")
        await ctx.send(f"{ctx.author.mention} took too long.")
        return False

# --- Bot Events ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if not discord.opus.is_loaded():
        try:
            if os.name == 'nt': # Windows
                current_folder = os.path.dirname(os.path.abspath(__file__))
                opus_path = os.path.join(current_folder, 'libopus-0.x64.dll')
                discord.opus.load_opus(opus_path)
            else: 
                discord.opus.load_opus('libopus.so.0')
            print("✅ Opus library loaded successfully!")
        except Exception as e:
            print(f"⚠️ Opus Load Warning: {e}")

@bot.event
async def you_need_a_password(ctx):
    await ctx.send("You need a password to use this bot.")

# --- Bot Commands ---
@bot.command()
async def join(ctx):

    global session_unlocked
    

    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel first!")
        return

    channel = ctx.author.voice.channel


    if ctx.voice_client is None:
    
        if await check_password(ctx):
            session_unlocked = True
            await channel.connect(cls=voice_recv.VoiceRecvClient)
            await ctx.send(f"Joined {channel.name} and ready to record.")
        else:
            return
    else:
        await ctx.voice_client.move_to(channel)
        await ctx.send(f"Moved to {channel.name}!")

@bot.command()
async def leave(ctx):
    global session_unlocked
    
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        session_unlocked = False  
        await ctx.send('👋 Disconnected. Bot is now locked.')
    else:
        await ctx.send("I'm not in a channel.")

@bot.command()
async def record(ctx):
    global is_recording, recording_data, meeting_start_time

    if not ctx.voice_client:
        await ctx.send('I am not in a voice channel. Type !join first.')
        return

    recording_data.clear()
    is_recording = True
    meeting_start_time = datetime.now()
    await ctx.send(f'🔴 Recording started at {meeting_start_time.strftime("%H:%M")}! Speak now.')

    def callback(user, data):
        if not is_recording or user is None:
            return
        if data and data.pcm:
            recording_data[user.id].append(data.pcm)

    ctx.voice_client.listen(voice_recv.BasicSink(callback))

@bot.command()
async def stop(ctx):
    global is_recording, recording_data, meeting_start_time, session_unlocked

    if not session_unlocked:
        await ctx.send("You need to unlock the bot first using the password.")
        return

    if ctx.voice_client and is_recording:
        is_recording = False
        ctx.voice_client.stop_listening()
        await ctx.send("💾 Recording stopped. Saving audio and generating minutes...")
        await asyncio.sleep(1)

        if not recording_data:
            await ctx.send('⚠️ No audio data was captured.')
            return

        saved_files = []
        attendees = []

        for user_id, audio_chunks in recording_data.items():
            user = bot.get_user(user_id)
            if not user:
                user = await bot.fetch_user(user_id)
            attendees.append(user.name)

            if audio_chunks:
                combined_audio = b''.join(audio_chunks)
                if len(combined_audio) > 50000:
                    filename = save_audio(user, combined_audio)
                    if filename:
                        saved_files.append((user.name, filename))

        if not saved_files:
            await ctx.send("Audio was too short to process.")
            recording_data.clear()
            return

        await ctx.send(f"✅ Audio saved. Generating Meeting Minutes (saved to file)...")

        try:
            minutes = await generate_minutes(saved_files, meeting_start_time, attendees)
            output_file = f"meeting_minutes_{meeting_start_time.strftime('%Y%m%d_%H%M%S')}.txt"
            
            # Save locally
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(minutes)

            # Send into Discord channel
            await ctx.send(f"📄 Meeting minutes generated:", file=discord.File(output_file))

        except Exception as e:
            await ctx.send(f"❌ Error generating minutes: {e}")

        recording_data.clear()
    else:
        await ctx.send('I am not recording.')


# --- Helpers ---
def save_audio(user, data: bytes):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_name = "".join([c for c in user.name if c.isalnum()]).rstrip()
    filename = f'{clean_name}_{timestamp}.wav'
    try:
        with wave.open(filename, 'wb') as f:
            f.setnchannels(2)
            f.setsampwidth(2)
            f.setframerate(48000)
            f.writeframes(data)
        return filename
    except Exception as e:
        print(f'Error saving {filename}: {e}')
        return None

async def transcribe_user_audio(user_name, filename):
    """Transcribe a single user's audio file asynchronously."""
    try:
        print(f"   > Transcribing {filename} for {user_name}...")
        with open(filename, "rb") as audio_file:
            transcription = openai_client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=audio_file
            )
        text = transcription.text.strip()
        print(f"   🗣️ Text detected for {user_name}: '{text}'")
        if text and len(text) > 2:
            return f"\nSpeaker ({user_name}): {text}"
        return ""
    except Exception as e:
        print(f"   ❌ FAILED to transcribe {filename} for {user_name}: {e}")
        return ""

async def generate_minutes(file_list, start_time, attendees):
    # Transcribe all users concurrently
    transcription_tasks = [transcribe_user_audio(user_name, filename) for user_name, filename in file_list]
    results = await asyncio.gather(*transcription_tasks)

    full_transcript = "".join(results)
    if not full_transcript.strip():
        return "Audio recorded, but no clear speech was detected. Try speaking louder or longer."

    # Summarization prompt
    system_prompt = """You are an efficient executive secretary. 
You will be given a raw transcript of a voice chat, the start time, and the attendance list.
Your goal is to generate professional Meeting Minutes.

Format:
1. Meeting Details (Date/Time/Attendees)
2. Executive Summary
3. Key Discussion Points (Bulleted)
4. Action Items (Who needs to do what)
"""

    user_input = f"""
MEETING START TIME: {start_time.strftime("%Y-%m-%d %H:%M:%S")}
ATTENDEES: {", ".join(attendees)}

TRANSCRIPT:
{full_transcript}
"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}")
    ])
    chain = prompt | llm
    response = await chain.ainvoke({"input": user_input})
    return response.content

# --- Run Bot ---
if TOKEN:
    bot.run(TOKEN)
