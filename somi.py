import click
from agents import SomiAgent
from handlers.twitter import TwitterHandler
from handlers.telegram import TelegramHandler
from config.settings import DEFAULT_MODEL, DEFAULT_TEMP
import re
from twitter_scraper import TwitterScraper
import asyncio
import time
import random
from functools import wraps
import os
from pathlib import Path

# Makes async functions work with click by running them in a new event loop
def async_command(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@click.group()
def somi():
    """Somi CLI"""
    pass

@somi.command()
@async_command
async def gencookies():
    """Generates Twitter cookies"""
    handler = TwitterHandler()
    await handler.initialize()
    click.echo("Cookies generated and saved.")

@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--model", default=DEFAULT_MODEL, help="Ollama model to use")
@click.option("--temp", default=DEFAULT_TEMP, help="Temperature for generation")
@click.option("--use-studies", is_flag=True, help="Enable studied data for responses")
def aichat(name, model, temp, use_studies):
    """Chat continuously with the agent"""
    agent = SomiAgent(name, use_studies=use_studies)
    if model != DEFAULT_MODEL or temp != DEFAULT_TEMP:
        agent.model = model
        agent.temperature = temp
    click.echo(f"Chatting with {name}{' using studies' if use_studies else ''}. Type 'quit' to exit.")
    while True:
        try:
            prompt = input(f"You: ")
            if prompt.lower() == "quit":
                click.echo(f"Goodbye from {name}!")
                break
            response = agent.generate_response(prompt)
            click.echo(f"{name} says: {response}")
        except KeyboardInterrupt:
            click.echo(f"\nGoodbye from {name}!")
            break

@somi.command()
@click.option("--message", prompt="Enter your tweet", help="Message to post on Twitter")
@async_command
async def devpost(message):
    """Post a message to Twitter"""
    handler = TwitterHandler()
    result = await handler.post(message)
    click.echo(result)

@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--use-studies", is_flag=True, help="Enable studied data for tweet generation")
@async_command
async def aipost(name, use_studies):
    """Generate and post a tweet once"""
    agent = SomiAgent(name, use_studies=use_studies)
    handler = TwitterHandler()
    message = agent.generate_tweet()
    display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
    result = await handler.post(message)
    click.echo(f"Generated tweet{' with studies' if use_studies else ''}: {display_message}")
    click.echo(result)

@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@async_command
async def aiautopost(name):
    """Generate and post a tweet initially, then every 10 minutes for stress testing"""
    agent = SomiAgent(name)
    while True:
        try:
            handler = TwitterHandler()
            message = agent.generate_tweet()
            display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
            result = await handler.post(message)
            click.echo(f"Generated tweet: {display_message}")
            click.echo(result)
            delay_minutes = 10
            delay_seconds = delay_minutes * 60
            click.echo(f"Waiting {delay_minutes} minutes for next tweet...")
            await asyncio.sleep(delay_seconds)
        except Exception as e:
            click.echo(f"Error in autopost: {str(e)}")
            await asyncio.sleep(60)

@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--limit", default=2, help="Number of mentions to reply to")
@async_command
async def aireply(name, limit):
    """Fetch latest mentions and reply using the agent's personality"""
    scraper = await TwitterScraper.create(character_name=name)
    await scraper.reply_to_mentions(limit=limit)
    click.echo(f"Processed {limit} mentions.")

@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--limit", default=2, help="Number of mentions to reply to")
@async_command
async def aiautoreply(name, limit):
    """Auto scrape mentions and reply every 4 hours"""
    while True:
        try:
            scraper = await TwitterScraper.create(character_name=name)
            await scraper.reply_to_mentions(limit=limit)
            delay_hours = 4
            delay_seconds = delay_hours * 60 * 60
            click.echo(f"Processed {limit} mentions. Waiting {delay_hours} hours...")
            await asyncio.sleep(delay_seconds)
        except Exception as e:
            click.echo(f"Error in autoreply: {str(e)}")
            await asyncio.sleep(60)

@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--use-studies", is_flag=True, help="Enable studied data for Telegram responses")
@async_command
async def telegram(name, use_studies):
    """Run the Telegram bot for chat interaction and scraping"""
    bot = TelegramHandler(character_name=name, use_studies=use_studies)
    await bot.start()
    click.echo(f"Telegram bot for {name}{' using studies' if use_studies else ''} is running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        await bot.stop()
        click.echo("Telegram bot stopped.")

@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--study", multiple=True, help="Data to study: 'pdfs', 'websites', or both", type=click.Choice(['pdfs', 'websites']))
@async_command
async def study(name, study):
    """Study data for RAG (PDFs and/or websites)"""
    from rag import RAGHandler
    if not study:
        click.echo("No study material specified. Use --study pdfs and/or --study websites.")
        return

    rag = RAGHandler()
    if "pdfs" in study:
        await rag.ingest_pdfs()
    if "websites" in study:
        await rag.ingest_websites()
    click.echo(f"Studied data for {name}: {', '.join(study)}")

@somi.command()
def clearstudies():
    """Clear all studied RAG data"""
    storage_path = Path("rag_data")
    vector_file = storage_path / "rag_vectors.faiss"
    text_file = storage_path / "rag_texts.json"

    # Check and delete the vector file
    if vector_file.exists():
        try:
            os.remove(vector_file)
            click.echo(f"Deleted {vector_file}")
        except Exception as e:
            click.echo(f"Error deleting {vector_file}: {str(e)}")
    else:
        click.echo(f"No vector file found at {vector_file}")

    # Check and delete the text file
    if text_file.exists():
        try:
            os.remove(text_file)
            click.echo(f"Deleted {text_file}")
        except Exception as e:
            click.echo(f"Error deleting {text_file}: {str(e)}")
    else:
        click.echo(f"No text file found at {text_file}")

    click.echo("RAG data cleared. Run 'study' to add new data.")

print("Registered commands:", [cmd.name for cmd in somi.commands.values()])

if __name__ == "__main__":
    somi()