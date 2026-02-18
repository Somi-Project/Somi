# speech.py
import numpy as np
import sounddevice as sd
import soundfile as sf
import whisper
import json
import os
import time
from queue import Queue
from threading import Thread
from scipy import signal
import re
import logging
from TTS.api import TTS
import torch
import warnings
import click
from config.audiosettings import *
from config.settings import DEFAULT_MODEL, MEMORY_MODEL, SYSTEM_TIMEZONE, DISABLE_MEMORY_FOR_FINANCIAL
from handlers.twitter import TwitterHandler
import asyncio
import glob
import random
from agents import Agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    handlers=[
        logging.FileHandler("speech_pipeline.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

audio_queue = Queue()
debug_audio_buffer = []
is_synthesizing = False
tts = None
device = None
is_wake_session_active = False
wake_session_start_time = 0
somi_agent = None
twitter_handler = None

def get_available_agents():
    """Retrieve available agent names from personalC.json."""
    try:
        with open("config/personalC.json", "r") as f:
            characters = json.load(f)
        return list(characters.keys())
    except FileNotFoundError:
        logger.error("personalC.json not found.")
        return []

def validate_agent_name(name):
    """Validate if the name or alias exists in personalC.json."""
    try:
        with open("config/personalC.json", "r") as f:
            characters = json.load(f)
        alias_to_key = {}
        for key, config in characters.items():
            aliases = config.get("aliases", []) + [key, key.replace("Name: ", "")]
            for alias in aliases:
                alias_to_key[alias.lower()] = key
        if not name:
            return None
        name_lower = name.lower()
        if name in characters:
            return name
        if name_lower in alias_to_key:
            return alias_to_key[name_lower]
        logger.warning(f"Agent '{name}' not found in personalC.json.")
        return None
    except FileNotFoundError:
        logger.error("personalC.json not found, creating default.")
        os.makedirs("config", exist_ok=True)
        default_config = {
            "Name: DefaultAgent": {
                "aliases": ["DefaultAgent"],
                "description": "Friendly AI assistant",
                "behaviors": ["neutral"],
                "role": "assistant"
            }
        }
        with open("config/personalC.json", "w") as f:
            json.dump(default_config, f)
        return "Name: DefaultAgent"

def prompt_for_agent_name():
    """Prompt the user to enter an agent name, showing available agents."""
    available_agents = get_available_agents()
    if available_agents:
        print("Available agents from personalC.json:")
        for agent in available_agents:
            print(f"- {agent.replace('Name: ', '')}")
    else:
        print("No agents found in personalC.json. A default agent will be created if you proceed.")
    
    while True:
        agent_name = input("Please enter an agent name: ").strip()
        validated_name = validate_agent_name(agent_name)
        if validated_name:
            return validated_name
        print(f"Invalid agent name '{agent_name}'. Please choose a valid name or alias from the list above.")

def generate_inchime_sound():
    """Generate a pleasant, 'Ding...ding...ding!' with three high-pitched tones."""
    audio = []
    for freq in INCHIME_FREQUENCIES:
        t = np.linspace(0, INCHIME_TONE_DURATION, int(SAMPLE_RATE * INCHIME_TONE_DURATION), False)
        tone = INCHIME_AMPLITUDE * np.sin(2 * np.pi * freq * t)
        envelope = np.hanning(len(t))
        tone *= envelope
        audio.extend(tone)
        pause = np.zeros(int(SAMPLE_RATE * INCHIME_PAUSE))
        audio.extend(pause)
    audio = np.array(audio)[:int(SAMPLE_RATE * INCHIME_DURATION)]
    return audio / np.max(np.abs(audio)) * INCHIME_AMPLITUDE

def generate_outchime_sound():
    """Generate a soft, low-pitched 'Dong...dong' to indicate session end."""
    audio = []
    for freq in OUTCHIME_FREQUENCIES:
        t = np.linspace(0, OUTCHIME_TONE_DURATION, int(SAMPLE_RATE * OUTCHIME_TONE_DURATION), False)
        tone = OUTCHIME_AMPLITUDE * np.sin(2 * np.pi * freq * t)
        envelope = np.hanning(len(t))
        tone *= envelope
        audio.extend(tone)
        if freq != OUTCHIME_FREQUENCIES[-1]:
            pause = np.zeros(int(SAMPLE_RATE * INCHIME_PAUSE))
            audio.extend(pause)
    audio = np.array(audio)[:int(SAMPLE_RATE * OUTCHIME_DURATION)]
    return audio / np.max(np.abs(audio)) * OUTCHIME_AMPLITUDE

def play_sound(audio):
    """Play a sound with sounddevice."""
    try:
        sd.play(audio, SAMPLE_RATE, blocking=False)
        sd.wait()
        logger.debug("Played sound")
    except Exception as e:
        logger.error(f"Error playing sound: {e}")

def apply_high_pass_filter(audio, sample_rate, cutoff=80):
    sos = signal.butter(10, cutoff, 'hp', fs=sample_rate, output='sos')
    filtered = signal.sosfilt(sos, audio)
    return filtered

def clean_text(text):
    text = re.sub(r'\*{1,2}', '', text)
    text = re.sub(r'\[.*?(https?://\S+|www\.\S+).*?\]', '', text)
    text = re.sub(r'https?://\S+|www\.\S+', '', text)
    text = re.sub(r'Source:.*?(?=\.|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[\[\]\(\)]', '', text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\.+$', '', text)
    return text

def is_repetitive_transcription(text):
    pattern = r"\b(\w+\s+\w+)\b.*\1.*\1"
    return len(text) > 50 and re.search(pattern, text) is not None

def check_wake_word(text):
    """Check if text contains any wake word and return cleaned text if wake word is found."""
    text_lower = text.lower().strip()
    for word, pattern in zip(WAKE_WORDS, WAKE_WORD_PATTERNS):
        if pattern.search(text_lower):
            cleaned_text = pattern.sub('', text_lower).strip()
            logger.info(f"Wake word triggered: {word}")
            return True, cleaned_text
    return False, text_lower

def check_wake_session_timeout():
    """Check if wake session has timed out."""
    global is_wake_session_active, wake_session_start_time
    if is_wake_session_active:
        if time.time() - wake_session_start_time > WAKE_SESSION_TIMEOUT:
            logger.info("Wake word session ended")
            is_wake_session_active = False
            wake_session_start_time = 0
            play_sound(generate_outchime_sound())
    return is_wake_session_active

def post_tweet(tweet_content):
    """Post a tweet using TwitterHandler."""
    global twitter_handler
    if not twitter_handler:
        logger.error("TwitterHandler not initialized.")
        return "Sorry, I can't post tweets right now. Twitter integration is not set up."
    
    if not tweet_content:
        logger.warning("Empty tweet content provided.")
        return "I need something to tweet! Please provide a message."
    
    tweet_content = tweet_content.strip()
    if len(tweet_content) > 280:
        logger.warning(f"Tweet exceeds 280 characters: {len(tweet_content)}")
        tweet_content = tweet_content[:277] + "..."
    
    try:
        twitter_handler.post_tweet(tweet_content)
        logger.info(f"Tweet posted: {tweet_content}")
        return "Tweet posted!"
    except Exception as e:
        logger.error(f"Failed to post tweet: {e}")
        return f"Sorry, I couldn't post the tweet. Error: {str(e)}"

def capture_audio():
    def callback(indata, frames, time_info, status):
        if status:
            logger.error(f"Audio capture error: {status}")
        if not is_synthesizing:
            amplified = indata * AUDIO_GAIN
            audio_queue.put(amplified)
            debug_audio_buffer.append(amplified)
    
    logger.info("Listening... Press Ctrl+C to stop.")
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                          callback=callback, blocksize=int(SAMPLE_RATE * CHUNK_DURATION)):
            while True:
                time.sleep(0.1)
    except Exception as e:
        logger.error(f"Microphone error: {e}")

async def process_with_somi_agent(text, user_id="default_user"):
    """Process text using Agent's generate_response method."""
    try:
        response = await somi_agent.generate_response(text, user_id=user_id, dementia_friendly=True)
        logger.info(f"Agent response: {response}")
        
        # Process memory storage
        should_store, mem_type, mem_content = somi_agent.process_memory(text, response, user_id)
        if should_store:
            somi_agent.store_memory(mem_content, user_id, mem_type)
            logger.info(f"Stored memory: {mem_content}")
        
        return response
    except Exception as e:
        logger.error(f"Agent error: {e}")
        return "I couldn't process that, please try again!"

def synthesize_speech(text, is_greeting=False):
    global is_synthesizing
    is_synthesizing = True
    try:
        logger.info(f"Synthesizing text: {text} {'(greeting)' if is_greeting else ''}")
        start_time = time.time()
        text = clean_text(text)
        if not text:
            logger.warning("Cleaned text is empty; skipping synthesis")
            return
        sentences = [s.strip() for s in text.split('. ') if s.strip()]
        if not sentences:
            logger.warning("No valid sentences after splitting; skipping synthesis")
            return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for sentence in sentences:
            with torch.inference_mode():
                with torch.cuda.amp.autocast() if device == "cuda" else torch.no_grad():
                    audio = tts.tts(text=sentence, speaker=None)
            sampling_rate = tts.synthesizer.output_sample_rate
            if audio is None or len(audio) == 0:
                logger.error(f"Coqui generated empty audio for sentence: {sentence}")
                continue
            audio = np.array(audio, dtype=np.float32)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            max_amplitude = np.max(np.abs(audio)) if len(audio) > 0 else 0
            logger.info(f"Generated audio shape: {audio.shape}, sampling rate: {sampling_rate}, max amplitude: {max_amplitude:.4f}, generation time: {time.time() - start_time:.2f}s")
            try:
                output_file = os.path.join(OUTPUT_DIR, f"coqui_output_{int(time.time())}.wav")
                sf.write(output_file, audio, sampling_rate)
                logger.info(f"Saved audio to {output_file}")
            except Exception as e:
                logger.error(f"Failed to save {output_file}: {e}")
            try:
                sd.play(audio, sampling_rate, blocking=False)
                duration = len(audio) / sampling_rate
                time.sleep(duration)
                sd.wait()
                logger.info(f"Speech synthesized for sentence: {sentence}")
            except Exception as e:
                logger.error(f"Sounddevice playback error: {e}")
    except Exception as e:
        logger.error(f"Coqui TTS error: {e}")
    finally:
        is_synthesizing = False

def process_audio_and_transcribe():
    whisper_model = whisper.load_model(WHISPER_MODEL)
    audio_buffer = []
    last_process_time = time.time()
    
    # Tweet command patterns
    tweet_patterns = [
        re.compile(r'^(tweet this|post tweet)\s*:\s*(.+)$', re.IGNORECASE),
        re.compile(r'^(tweet|post)\s+(.+)$', re.IGNORECASE)
    ]
    
    while True:
        if not audio_queue.empty():
            chunk = audio_queue.get()
            audio_buffer.append(chunk)
            
            audio_array = np.concatenate(audio_buffer, axis=0).flatten()
            audio_duration = len(audio_array) / SAMPLE_RATE
            
            current_time = time.time()
            logger.debug(f"Audio queue processed: duration={audio_duration:.2f}s, time_since_last={current_time - last_process_time:.2f}s")
            if audio_duration >= MIN_AUDIO_LENGTH and (current_time - last_process_time) >= SEGMENT_DURATION:
                logger.info(f"Processing audio buffer: {audio_duration:.2f}s")
                pre_filter_amplitude = np.max(np.abs(audio_array))
                logger.info(f"Pre-filter max amplitude: {pre_filter_amplitude:.4f}")
                filtered_audio = apply_high_pass_filter(audio_array, SAMPLE_RATE)
                sf.write(TEMP_AUDIO, filtered_audio, SAMPLE_RATE)
                max_amplitude = np.max(np.abs(filtered_audio))
                logger.info(f"Post-filter max amplitude: {max_amplitude:.4f}")
                if max_amplitude < SILENCE_THRESHOLD:
                    logger.info("Skipping silent/noisy segment.")
                    audio_buffer = []
                    last_process_time = current_time
                    continue
                sf.write(LAST_AUDIO, filtered_audio, SAMPLE_RATE)
                try:
                    result = whisper_model.transcribe(TEMP_AUDIO, language="en")
                    transcription = result["text"].strip()[:MAX_TRANSCRIPTION_LENGTH]
                    logger.info(f"Whisper raw transcription: '{transcription}'")
                    
                    has_wake_word, cleaned_transcription = check_wake_word(transcription)
                    is_session_active = check_wake_session_timeout()
                    
                    if has_wake_word:
                        global is_wake_session_active, wake_session_start_time
                        is_wake_session_active = True
                        wake_session_start_time = time.time()
                        logger.info("Wake word session active")
                        play_sound(generate_inchime_sound())
                    elif not is_session_active:
                        logger.info("No wake word or active session, skipping processing")
                        audio_buffer = []
                        last_process_time = current_time
                        os.remove(TEMP_AUDIO) if os.path.exists(TEMP_AUDIO) else None
                        continue
                    
                    if cleaned_transcription.lower() in ["okay", "ok"]:
                        logger.info("Skipping 'okay' or 'ok' transcription.")
                        audio_buffer = []
                        last_process_time = current_time
                        os.remove(TEMP_AUDIO) if os.path.exists(TEMP_AUDIO) else None
                        continue
                    if cleaned_transcription and not cleaned_transcription.startswith(".") and len(cleaned_transcription) > 2:
                        if is_repetitive_transcription(cleaned_transcription):
                            logger.info("Skipping repetitive transcription.")
                            audio_buffer = []
                            last_process_time = current_time
                            os.remove(TEMP_AUDIO) if os.path.exists(TEMP_AUDIO) else None
                            continue
                        
                        # Check for tweet command
                        tweet_content = None
                        for pattern in tweet_patterns:
                            match = pattern.match(cleaned_transcription)
                            if match:
                                tweet_content = match.group(2).strip()
                                break
                        
                        if tweet_content:
                            logger.info(f"Tweet command detected: '{tweet_content}'")
                            response = post_tweet(tweet_content)
                            synthesize_speech(response)
                        else:
                            logger.info(f"Cleaned transcription sent to Agent: '{cleaned_transcription}'")
                            loop = asyncio.get_event_loop()
                            processed_text = loop.run_until_complete(process_with_somi_agent(cleaned_transcription))
                            synthesize_speech(processed_text)
                    else:
                        logger.info("Skipping empty/noisy transcription.")
                except Exception as e:
                    logger.error(f"Transcription error: {e}")
                audio_buffer = []
                last_process_time = current_time
                os.remove(TEMP_AUDIO) if os.path.exists(TEMP_AUDIO) else None
        else:
            logger.debug("Audio queue empty")
            time.sleep(0.01)

@click.command()
@click.option("--name", default=None, help="Name of the agent from personalC.json")
@click.option("--use-studies", is_flag=True, help="Enable studied data for responses")
def main(name, use_studies):
    global tts, device, somi_agent, GREETING_MESSAGE, twitter_handler
    try:
        logger.info(f"Using default input device: {sd.query_devices(kind='input')['name']}")
        logger.info(f"Available audio devices: {sd.query_devices()}")
        logger.info(f"CUDA available: {torch.cuda.is_available()}")
        if not torch.cuda.is_available():
            logger.warning("CUDA not available; using CPU")
        else:
            logger.info(f"GPU: {torch.cuda.get_device_name(0)}, VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Initializing Coqui TTS pipeline...")
        tts = TTS(model_name=TTS_MODEL, progress_bar=True)
        tts.to(device)
        logger.info("Coqui TTS pipeline initialized successfully.")
        
        # Initialize TwitterHandler
        logger.info("Initializing TwitterHandler...")
        try:
            twitter_handler = TwitterHandler()
            logger.info("TwitterHandler initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize TwitterHandler: {e}")
            twitter_handler = None
        
        # If no agent name provided, prompt the user
        if name is None:
            agent_key = prompt_for_agent_name()
        else:
            agent_key = validate_agent_name(name)
            if not agent_key:
                print(f"Invalid agent name '{name}'. Prompting for a valid name.")
                agent_key = prompt_for_agent_name()
        
        display_name = agent_key.replace("Name: ", "")
        logger.info(f"Initializing Agent with name: {agent_key}, display name: {display_name}")
        somi_agent = Agent(name=agent_key, use_studies=use_studies)
        
        # Load personality details from personalC.json
        try:
            with open("config/personalC.json", "r") as f:
                characters = json.load(f)
            character = characters.get(agent_key, {"description": "Friendly AI assistant", "behaviors": ["neutral"], "role": "assistant"})
            description = character.get("description", "Friendly AI assistant")
            behavior = random.choice(character.get("behaviors", ["neutral"]))
        except FileNotFoundError:
            logger.error("personalC.json not found, using default description")
            description = "Friendly AI assistant"
            behavior = "neutral"
        
        # Update GREETING_MESSAGE with personality
        GREETING_MESSAGE = f"Hi! I'm {display_name}, your {description.lower()}. Say a trigger word to chat with me in a {behavior} tone!"
        logger.info(f"Updated GREETING_MESSAGE: {GREETING_MESSAGE}")
        
        if GREETING_MESSAGE:
            logger.info(f"Playing startup greeting: {GREETING_MESSAGE}")
            synthesize_speech(GREETING_MESSAGE, is_greeting=True)
        
        def cleanup_old_files():
            while True:
                try:
                    now = time.time()
                    for file in glob.glob(os.path.join(OUTPUT_DIR, "coqui_output_*.wav")):
                        if now - os.path.getctime(file) > FILE_RETENTION_SECONDS:
                            os.remove(file)
                            logger.info(f"Deleted old audio file: {file}")
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
                time.sleep(CLEANUP_INTERVAL)
        
        cleanup_thread = Thread(target=cleanup_old_files)
        cleanup_thread.daemon = True
        cleanup_thread.start()
        logger.info(f"Started cleanup thread: checking every {CLEANUP_INTERVAL} seconds")
        
        audio_thread = Thread(target=capture_audio)
        audio_thread.daemon = True
        audio_thread.start()
        process_audio_and_transcribe()
    except KeyboardInterrupt:
        logger.info("\nStopped by user.")
        if debug_audio_buffer:
            debug_array = np.concatenate(debug_audio_buffer, axis=0).flatten()
            sf.write(DEBUG_AUDIO, debug_array, SAMPLE_RATE)
            logger.info(f"Saved all captured audio to {DEBUG_AUDIO}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if os.path.exists(TEMP_AUDIO):
            os.remove(TEMP_AUDIO)

if __name__ == "__main__":
    main()