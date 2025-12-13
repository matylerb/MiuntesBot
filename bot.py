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
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from groq import Groq

load_dotenv()

# Discord & Groq / OpenAI API keys
TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

if not OPENAI_API_KEY:
    print("⚠️ OPENAI_API_KEY missing. Transcription will fail.")
if not GROQ_API_KEY:
    print("⚠️ GROQ_API_KEY missing. Summarization will fail.")

# Clients
openai_client = OpenAI(api_key=OPENAI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)
llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

# Logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('discord.ext.voice_recv.reader').setLevel(logging.ERROR)

# Discord bot
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Globals for recording
recording_data = defaultdict(list)
is_recording = False
meeting_start_time = None

# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')
    if not discord.opus.is_loaded():
        try:
            current_folder = os.path.dirname(os.path.abspath(__file__))
            opus_path = os.path.join(current_folder, 'libopus-0.x64.dll')
            discord.opus.load_opus(opus_path)
            print("✅ Opus library loaded successfully!")
        except Exception as e:
            print(f"⚠️ Opus Load Warning: {e}")

# --- Bot Commands ---
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
    global is_recording, recording_data, meeting_start_time

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

        await ctx.send(f"✅ Audio saved. Generating Meeting Minutes with AI...")

        try:
            minutes = await generate_minutes(saved_files, meeting_start_time, attendees)
    
            if len(minutes) > 1900:
                with open("meeting_minutes.txt", "w", encoding="utf-8") as f:
                    f.write(minutes)
                await ctx.send("📄 Meeting minutes are too long for chat, attached below:", file=discord.File("meeting_minutes.txt"))
            else:
                await ctx.send(f"**📝 Meeting Minutes:**\n{minutes}")
                
        except Exception as e:
            await ctx.send(f"❌ Error generating minutes: {e}")

        recording_data.clear()
    else:
        await ctx.send('I am not recording.')

# --- Helper: Save WAV ---
def save_audio(user, data: bytes):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_name = "".join([c for c in user.name if c.isalpha() or c.isdigit()]).rstrip()
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

# --- Generate Meeting Minutes ---
async def generate_minutes(file_list, start_time, attendees):
    full_transcript = ""
    
    print(f"--- 🔍 Processing {len(file_list)} audio files ---")

    for user_name, filename in file_list:
        try:
            print(f"   > Transcribing {filename}...")
            with open(filename, "rb") as audio_file:
                transcription = openai_client.audio.transcriptions.create(
                    model="gpt-4o-transcribe",
                    file=audio_file
                )
            text = transcription.text.strip()
            
            print(f"   🗣️ Text detected for {user_name}: '{text}'")
            
            if text and len(text) > 2: 
                full_transcript += f"\nSpeaker ({user_name}): {text}"
                
        except Exception as e:
            print(f"   ❌ FAILED to transcribe {filename}: {e}")

    if not full_transcript.strip():
        return "Audio recorded, but no clear speech was detected. Try speaking louder or longer."

    print("--- ✅ Transcript ready. Generating summary ---")

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

# --- Run bot ---
if TOKEN:
    bot.run(TOKEN)
