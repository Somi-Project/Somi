# somi.py
import click
from agents import SomiAgent
from handlers.twitter import TwitterHandler
from config.settings import DEFAULT_MODEL, DEFAULT_TEMP
import re

@click.group()
def somi():
    """Somi CLI"""
    pass

@somi.command()
@click.option("--name", default="Somi", help="Name of the agent")
@click.option("--model", default=DEFAULT_MODEL, help="Ollama model to use")
@click.option("--temp", default=DEFAULT_TEMP, help="Temperature for generation")
@click.option("--prompt", prompt="Enter your prompt", help="Prompt for the agent")
def ask(name, model, temp, prompt):
    """Ask the agent a question"""
    agent = SomiAgent(name)
    if model != DEFAULT_MODEL or temp != DEFAULT_TEMP:
        agent.model = model
        agent.temperature = temp
    response = agent.generate_response(prompt)
    click.echo(f"{name} says: {response}")

@somi.command()
@click.option("--message", prompt="Enter your tweet", help="Message to post on Twitter")
def tweet(message):
    """Post a message to Twitter"""
    handler = TwitterHandler()
    result = handler.post(message)
    click.echo(result)

@somi.command()
@click.option("--name", default="MissNovel90s", help="Name of the agent")
def auto_tweet(name):
    """Generate and post a tweet based on agent's personality"""
    agent = SomiAgent(name)
    message = agent.generate_tweet()
    # Clean message for CMD display (remove or replace problematic chars)
    display_message = re.sub(r'[^\x00-\x7F]+', '[emoji]', message)
    handler = TwitterHandler()
    result = handler.post(message)
    click.echo(f"Generated tweet: {display_message}")
    click.echo(result)

@somi.command()
@click.option("--name", default="MissNovel90s", help="Name of the agent")
@click.option("--model", default=DEFAULT_MODEL, help="Ollama model to use")
@click.option("--temp", default=DEFAULT_TEMP, help="Temperature for generation")
def chat(name, model, temp):
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

if __name__ == "__main__":
    somi()