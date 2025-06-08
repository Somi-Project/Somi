# somi.py
import click
from agents import Agent
from handlers.twitter import TwitterHandler
from handlers.telegram import TelegramHandler
from config.settings import (
    DEFAULT_MODEL, DEFAULT_TEMP,
    AUTO_POST_INTERVAL_MINUTES, AUTO_POST_INTERVAL_LOWER_VARIATION,
    AUTO_POST_INTERVAL_UPPER_VARIATION, AUTO_REPLY_INTERVAL_MINUTES,
    AUTO_REPLY_INTERVAL_LOWER_VARIATION, AUTO_REPLY_INTERVAL_UPPER_VARIATION
)
import re
import asyncio
import time
import random
from functools import wraps
import os
from pathlib import Path
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def async_command(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

IMAGES_DIR = Path("images")

# Load personalities from personalC.json for validation
PERSONALITY_CONFIG = "config/personalC.json"

def load_personalities():
    try:
        with open(PERSONALITY_CONFIG, "r") as f:
            characters = json.load(f)
        alias_to_key = {}
        for key, config in characters.items():
            aliases = config.get("aliases", []) + [key, key.replace("Name: ", "")]
            for alias in aliases:
                alias_to_key[alias.lower()] = key
        return characters, alias_to_key
    except FileNotFoundError:
        click.echo(f"Error: {PERSONALITY_CONFIG} not found.")
        return {}, {}

def validate_agent_name(name):
    """Validate if the name or alias exists in personalC.json."""
    characters, alias_to_key = load_personalities()
    if not name:
        return None
    name_lower = name.lower()
    if name in characters or name_lower in alias_to_key:
        return name if name in characters else alias_to_key[name_lower]
    return None

def get_randomized_interval(base_interval, lower_variation, upper_variation):
    """Generate a randomized interval in minutes."""
    min_interval = max(1, base_interval - lower_variation)
    max_interval = base_interval + upper_variation
    return random.randint(min_interval, max_interval)

@click.group(name="agent")
def cli():
    """Agent CLI"""
    pass

@click.command()
@async_command
async def gencookies():
    """Generates Twitter cookies"""
    handler = TwitterHandler()
    await handler.initialize()
    click.echo("Cookies generated and saved.")

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--model", default=DEFAULT_MODEL, help="Ollama model to use")
@click.option("--temp", default=DEFAULT_TEMP, help="Temperature for generation")
@click.option("--use-studies", is_flag=True, help="Enable studied data for responses")
@async_command
async def aichat(name, model, temp, use_studies):
    """Chat continuously with the agent"""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    agent = Agent(agent_key, use_studies=use_studies)
    if model != DEFAULT_MODEL or temp != DEFAULT_TEMP:
        agent.model = model
        agent.temperature = temp
    display_name = agent_key.replace("Name: ", "")
    click.echo(f"Chatting with {display_name}{' using studies' if use_studies else ''}. Type 'quit' to exit.")
    while True:
        try:
            prompt = input(f"You: ")
            if prompt.lower() == "quit":
                click.echo(f"Goodbye from {display_name}!")
                break
            response = await agent.generate_response(prompt)
            click.echo(f"{display_name} says: {response}")
        except KeyboardInterrupt:
            click.echo(f"\nGoodbye from {display_name}!")
            break

@click.command()
@click.option("--message", prompt="Enter your tweet", help="Message to post on Twitter")
@async_command
async def devpost(message):
    """Post a message to Twitter"""
    handler = TwitterHandler()
    result = await handler.post(message)
    click.echo(result)

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--use-studies", is_flag=True, help="Enable studied data for tweet generation")
@async_command
async def aipost(name, use_studies):
    """Generate and post a tweet once"""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    handler = TwitterHandler(character_name=agent_key, use_studies=use_studies)
    message = await handler.generate_tweet()
    display_name = agent_key.replace("Name: ", "")
    display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
    result = await handler.post(message)
    click.echo(f"Generated tweet{' with studies' if use_studies else ''} by {display_name}: {display_message}")
    click.echo(result)

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--use-studies", is_flag=True, help="Enable studied data for tweet generation")
@async_command
async def aiautopost(name, use_studies):
    """Generate and post a tweet with randomized intervals from settings"""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    display_name = agent_key.replace("Name: ", "")
    handler = TwitterHandler(character_name=agent_key, use_studies=use_studies)
    try:
        await handler.initialize()
        while True:
            try:
                message = await handler.generate_tweet()
                display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
                result = await handler.post(message, cleanup=False)
                click.echo(f"Generated tweet by {display_name}: {display_message}")
                click.echo(result)
                delay_minutes = get_randomized_interval(
                    AUTO_POST_INTERVAL_MINUTES,
                    AUTO_POST_INTERVAL_LOWER_VARIATION,
                    AUTO_POST_INTERVAL_UPPER_VARIATION
                )
                delay_seconds = delay_minutes * 60
                click.echo(f"Waiting {delay_minutes} minutes for next tweet...")
                await asyncio.sleep(delay_seconds)
            except Exception as e:
                click.echo(f"Error in autopost: {str(e)}")
                await asyncio.sleep(60)
    except KeyboardInterrupt:
        click.echo(f"Stopping autopost for {display_name}...")
        await handler._cleanup()
        click.echo("Autopost stopped.")

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--limit", default=2, help="Number of mentions to reply to")
@async_command
async def aireply(name, limit):
    """Fetch latest mentions and reply using the agent's personality"""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    display_name = agent_key.replace("Name: ", "")
    handler = TwitterHandler(character_name=display_name)
    await handler.reply_to_mentions(limit=limit)
    click.echo(f"Processed {limit} mentions for {display_name}.")

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--limit", default=2, help="Number of mentions to reply to")
@click.option("--use-studies", is_flag=True, help="Enable studied data for reply generation")
@async_command
async def aiautoreply(name, limit, use_studies):
    """Auto scrape mentions and reply with randomized intervals, fast-tracking active threads"""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    display_name = agent_key.replace("Name: ", "")
    handler = TwitterHandler(character_name=display_name, use_studies=use_studies)
    try:
        await handler.initialize()
        fast_track_replies = {}  # Track replies per thread to cap at 2/hour
        while True:
            try:
                # Check repcache for active threads (within last 6 hours)
                current_time = time.time()
                active_threads = [
                    conv_id for conv_id, messages in handler.repcache.items()
                    if conv_id != "processed_tweets" and messages and (current_time - messages[-1]['timestamp'] < 3600)  # 1 hour
                ]
                is_fast_track = bool(active_threads)
                fast_track_interval = random.randint(5, 15) * 60  # 5-15 minutes in seconds
                standard_interval = handler._get_randomized_interval(
                    AUTO_REPLY_INTERVAL_MINUTES,
                    AUTO_REPLY_INTERVAL_LOWER_VARIATION,
                    AUTO_REPLY_INTERVAL_UPPER_VARIATION
                ) * 60  # Minutes to seconds

                if is_fast_track:
                    click.echo(f"Active threads detected: {active_threads}. Checking mentions every {fast_track_interval // 60} minutes.")
                    mentions_processed = await handler.reply_to_mentions(limit=limit, cleanup=False)
                    if mentions_processed:
                        # Update fast-track reply tracking
                        current_hour = time.strftime("%Y-%m-%d %H:00:00")
                        for conv_id in active_threads:
                            fast_track_replies.setdefault(current_hour, {}).setdefault(conv_id, 0)
                            fast_track_replies[current_hour][conv_id] += 1
                            # Cap at 2 replies per thread per hour
                            if fast_track_replies[current_hour][conv_id] > 2:
                                logger.info(f"Capped replies for thread {conv_id} at 2 this hour.")
                                continue
                        # Clean old fast-track data
                        fast_track_replies = {
                            hour: threads for hour, threads in fast_track_replies.items()
                            if hour == current_hour
                        }
                    delay_seconds = fast_track_interval
                else:
                    click.echo(f"No active threads. Checking mentions every {standard_interval // 60} minutes.")
                    mentions_processed = await handler.reply_to_mentions(limit=limit, cleanup=False)
                    delay_seconds = standard_interval

                click.echo(f"Processed {limit} mentions for {display_name}. Waiting {delay_seconds // 60} minutes...")
                await asyncio.sleep(delay_seconds)
            except Exception as e:
                click.echo(f"Error in autoreply: {str(e)}")
                await asyncio.sleep(60)
    except KeyboardInterrupt:
        click.echo(f"Stopping autoreply for {display_name}...")
        await handler._cleanup()
        click.echo("Autoreply stopped.")

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--use-studies", is_flag=True, help="Enable studied data for Telegram responses")
@async_command
async def telegram(name, use_studies):
    """Run the Telegram bot for chat interaction and scraping"""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    display_name = agent_key.replace("Name: ", "")
    bot = TelegramHandler(character_name=display_name, use_studies=use_studies)
    await bot.start()
    click.echo(f"Telegram bot for {display_name}{' using studies' if use_studies else ''} is running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        await bot.stop()
        click.echo("Telegram bot stopped.")

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--study", multiple=True, help="Data to study: 'pdfs', 'websites', or both", type=click.Choice(['pdfs', 'websites']))
@async_command
async def study(name, study):
    """Study data for RAG (PDFs and/or websites)"""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    if not study:
        click.echo("No study material specified. Use --study pdfs and/or --study websites.")
        return
    display_name = agent_key.replace("Name: ", "")
    from rag import RAGHandler
    rag = RAGHandler()
    if "pdfs" in study:
        await rag.ingest_pdfs()
    if "websites" in study:
        await rag.ingest_websites()
    click.echo(f"Studied data for {display_name}: {', '.join(study)}")

@click.command()
def clearstudies():
    """Clear all studied RAG data"""
    storage_path = Path("rag_data")
    vector_file = storage_path / "rag_vectors.faiss"
    text_file = storage_path / "rag_texts.json"

    if vector_file.exists():
        try:
            os.remove(vector_file)
            click.echo(f"Deleted {vector_file}")
        except Exception as e:
            click.echo(f"Error deleting {vector_file}: {str(e)}")
    else:
        click.echo(f"No vector file found at {vector_file}")

    if text_file.exists():
        try:
            os.remove(text_file)
            click.echo(f"Deleted {text_file}")
        except Exception as e:
            click.echo(f"Error deleting {text_file}: {str(e)}")
    else:
        click.echo(f"No text file found at {text_file}")

    click.echo("RAG data cleared. Run 'study' to add new data.")

@click.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@async_command
async def analyzeimages(name):
    """Analyze all images in the images folder and print results."""
    agent_key = validate_agent_name(name)
    if not agent_key:
        click.echo("please enter a valid personality name")
        return
    agent = Agent(agent_key)
    display_name = agent_key.replace("Name: ", "")
    if not IMAGES_DIR.exists():
        click.echo("Images directory does not exist. Please create it and add some images.")
        return

    image_files = [f for f in IMAGES_DIR.iterdir() if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
    if not image_files:
        click.echo("No images found in the images folder.")
        return

    for image_file in image_files:
        click.echo(f"\nAnalyzing {image_file.name}...")
        try:
            response = await agent.analyze_image(str(image_file), "No caption provided (CLI test)")
            click.echo(f"{display_name} says: {response}")
        except Exception as e:
            click.echo(f"Error analyzing {image_file.name}: {str(e)}")

# Register commands with the CLI group
cli.add_command(gencookies)
cli.add_command(aichat)
cli.add_command(devpost)
cli.add_command(aipost)
cli.add_command(aiautopost)
cli.add_command(aireply)
cli.add_command(aiautoreply)
cli.add_command(telegram)
cli.add_command(study)
cli.add_command(clearstudies)
cli.add_command(analyzeimages)

print("Registered commands:", [cmd.name for cmd in cli.commands.values()])

if __name__ == "__main__":
    cli()