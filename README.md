## Somi - AI-Powered Twitter Automation

Somi is a Python-based CLI tool for automating Twitter interactions using an AI agent. It can post tweets, reply to mentions, and chat interactively, all driven by customizable character personalities stored in `personalC.json`.

## Overview
- **Tweet Posting**: Generate and post tweets manually or automatically every 10 minutes.
- **Mention Replies**: Reply to Twitter mentions once or auto-reply every 4 hours.
- **Chat**: Interact with the AI agent in the terminal.

## Prerequisites
Before running Somi, ensure you have the following installed:
- **Python 3.8+**: [Download Python](https://www.python.org/downloads/)
- **Git**: [Install Git](https://git-scm.com/downloads)
- **Node.js** (optional, for Playwright): [Download Node.js](https://nodejs.org/) if not using pre-installed Playwright binaries.
- **Twitter Account**: Credentials (`TWITTER_USERNAME` and `TWITTER_PASSWORD`) stored in `config/settings.py`.
- **Ollama**: An AI model server running locally at `http://127.0.0.1:11434` (e.g., LLaMA). [Install Ollama](https://ollama.ai/).

## Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Somi-Project/Somi.git
   cd Somi

## Dependancies install with commands
1. **Click** pip install click
2. **playwright** pip install playwright
3. **playwright browsers** playwright install
4. **requests** pip install requests

## Edit Login
folder: config/settings.py

TWITTER_USERNAME = "your_twitter_username"
TWITTER_PASSWORD = "your_twitter_password"

## Edit Personality Construct
folder: config/personalC.json

default name is degenia with defining parameters - edit as you see fit but keep major functions intact i.e. memories,inhibitions,hobbies etc. 

## Agent Commands 
Begin by typing python somi.py <command> --name <agent name>
e.g. python somi.py aichat --name degenia 
```bash
  aiautopost   Generate and post a tweet initially, then every 10 minutes...
  aiautoreply  Auto scrape mentions and reply every 4 hours
  aichat       Chat continuously with the agent
  aipost       Generate and post a tweet once
  aireply      Fetch latest mentions and reply using the agent's personality
  devpost      Post a message to Twitter
  gencookies   Generates Twitter cookies
```
## Fin
I've added comments throughout the code to highlight relevant parts for now 
