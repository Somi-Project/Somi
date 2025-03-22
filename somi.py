import click
from agents import SomiAgent
from handlers.twitter import TwitterHandler
from config.settings import DEFAULT_MODEL, DEFAULT_TEMP
import re
from twitter_scraper import TwitterScraper
import asyncio
import time
import random
from functools import wraps

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
def aichat(name, model, temp):
    """Chat continuously with the agent"""
    agent = SomiAgent(name)
    if model != DEFAULT_MODEL or temp != DEFAULT_TEMP:
        agent.model = model
        agent.temperature = temp
    click.echo(f"Chatting with {name}. Type 'quit' to exit.")
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
@async_command
async def aipost(name):
    """Generate and post a tweet once"""
    agent = SomiAgent(name)
    handler = TwitterHandler()
    message = agent.generate_tweet()
    display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
    result = await handler.post(message)
    click.echo(f"Generated tweet: {display_message}")
    click.echo(result)

# Auto-posts tweets every 10 minutes using the AI agent
@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@async_command
# Auto-posts tweets every 10 minutes using the AI agent
@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@async_command
async def aiautopost(name):
    """Generate and post a tweet initially, then every 10 minutes for stress testing"""
    agent = SomiAgent(name)  # AI agent for tweet generation
    while True:  # Infinite loop for continuous posting
        try:
            handler = TwitterHandler()  # Fresh handler each loop
            message = agent.generate_tweet()  # Generates tweet content
            display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)  # Replaces non-ASCII
            result = await handler.post(message)  # Posts to Twitter
            click.echo(f"Generated tweet: {display_message}")
            click.echo(result)
            delay_minutes = 10  # Fixed 10-minute delay
            delay_seconds = delay_minutes * 60
            click.echo(f"Waiting {delay_minutes} minutes for next tweet...")
            await asyncio.sleep(delay_seconds)  # Async wait
        except Exception as e:
            click.echo(f"Error in autopost: {str(e)}")  # Error handling
            await asyncio.sleep(60)  # Retry after 1 minute

# Replies to a set number of mentions once
@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--limit", default=2, help="Number of mentions to reply to")  # Default limit is 2
@async_command
async def aireply(name, limit):
    """Fetch latest mentions and reply using the agent's personality"""
    scraper = await TwitterScraper.create(character_name=name)  # Creates scraper instance
    await scraper.reply_to_mentions(limit=limit)  # Processes mentions
    click.echo(f"Processed {limit} mentions.")

# Auto-replies to mentions every 4 hours with configurable delay
@somi.command()
@click.option("--name", required=True, help="Name of the agent from personalC.json")
@click.option("--limit", default=2, help="Number of mentions to reply to")  # Default limit is 2
@async_command
async def aiautoreply(name, limit):
    """Auto scrape mentions and reply every 4 hours"""
    while True:  # Infinite loop for continuous operation
        try:
            scraper = await TwitterScraper.create(character_name=name)  # Fresh scraper each cycle
            await scraper.reply_to_mentions(limit=limit)  # Replies to mentions
            delay_hours = 4  # Fixed 4-hour delay (configurable here)
            delay_seconds = delay_hours * 60 * 60  # Converts hours to seconds (14400 for 4 hours)
            click.echo(f"Processed {limit} mentions. Waiting {delay_hours} hours...")
            await asyncio.sleep(delay_seconds)  # Waits 4 hours
        except Exception as e:
            click.echo(f"Error in autoreply: {str(e)}")  # Error handling
            await asyncio.sleep(60)  # Retry after 1 minute

# Debug: Shows all available commands
print("Registered commands:", [cmd.name for cmd in somi.commands.values()])

if __name__ == "__main__":
    somi()