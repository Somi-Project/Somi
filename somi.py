import click
from agents import SomiAgent
from handlers.twitter import TwitterHandler
from config.settings import DEFAULT_MODEL, DEFAULT_TEMP
import re
from twitter_scraper import TwitterScraper  # Assuming this is the file name
import time
import random  # For random delay

@click.group()
def somi():
    """Somi CLI"""
    pass

# gencookies - Generates cookies
@somi.command()
def gencookies():
    """Generates Twitter cookies"""
    handler = TwitterHandler()
    click.echo("Cookies generated and saved.")

# aichat - Chats with agent
@somi.command()
@click.option("--name", default="MissNovel90s", help="Name of the agent")
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

# devpost - Tweets using Selenium (was aipost)
@somi.command()
@click.option("--message", prompt="Enter your tweet", help="Message to post on Twitter")
def devpost(message):
    """Post a message to Twitter"""
    handler = TwitterHandler()
    result = handler.post(message)
    click.echo(result)

# aipost - Posts once and ends (was aiautopost)
@somi.command()
@click.option("--name", default="MissNovel90s", help="Name of the agent")
def aipost(name):
    """Generate and post a tweet once"""
    agent = SomiAgent(name)
    handler = TwitterHandler()
    message = agent.generate_tweet()
    display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
    result = handler.post(message)
    click.echo(f"Generated tweet: {display_message}")
    click.echo(result)

# aiautopost - Posts initially, then every 5-7 hours (was aiautoposttime)
@somi.command()
@click.option("--name", default="MissNovel90s", help="Name of the agent")
def aiautopost(name):
    """Generate and post a tweet initially, then every 5-7 hours"""
    agent = SomiAgent(name)
    handler = TwitterHandler()
    while True:
        message = agent.generate_tweet()
        display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
        result = handler.post(message)
        click.echo(f"Generated tweet: {display_message}")
        click.echo(result)
        delay_hours = random.uniform(5, 7)  # Random delay between 5 and 7 hours
        delay_seconds = delay_hours * 60 * 60
        click.echo(f"Waiting {delay_hours:.2f} hours for next tweet...")
        time.sleep(delay_seconds)

# aireply - Scrapes Twitter mentions and replies to them
@somi.command()
@click.option("--name", default="MissNovel90s", help="Name of the agent")
@click.option("--limit", default=5, help="Number of mentions to reply to")
def aireply(name, limit):
    """Fetch latest mentions and reply using the agent's personality"""
    scraper = TwitterScraper(use_selenium=True)
    scraper.agent = SomiAgent(name)  # Override default agent
    scraper.reply_to_mentions(limit=limit)
    click.echo(f"Processed {limit} mentions.")

# aiautoreply - Scrapes Twitter mentions and replies every 4 hours
@somi.command()
@click.option("--name", default="MissNovel90s", help="Name of the agent")
@click.option("--limit", default=5, help="Number of mentions to reply to")
def aiautoreply(name, limit):
    """Auto scrape mentions and reply every 4 hours"""
    scraper = TwitterScraper(use_selenium=True)
    scraper.agent = SomiAgent(name)
    while True:
        scraper.reply_to_mentions(limit=limit)
        click.echo(f"Processed {limit} mentions. Waiting 4 hours...")
        time.sleep(4 * 60 * 60)  # 4 hours in seconds

if __name__ == "__main__":
    somi()