## Somi - AI-Powered Everyday Automation

Somi is a Python-based CLI tool for automating Twitter interactions using an AI agent. It can post tweets, reply to mentions, and chat interactively, all driven by customizable character personalities stored in `personalC.json`.

## Overview
- **Tweet Posting**: Generate and post tweets manually or automatically every 10 minutes.
- **Mention Replies**: Reply to Twitter mentions once or auto-reply every 4 hours.
- **Chat**: Interact with the AI agent in the terminal.

## Prerequisites
Before running Somi, ensure you have the following installed:
- **Python 3.11.0+**: [Download Python](https://www.python.org/downloads/release/python-3110/)
- **Git**: [Install Git](https://git-scm.com/downloads)
- **Node.js** (optional, for Playwright): [Download Node.js](https://nodejs.org/) if not using pre-installed Playwright binaries.
- **Twitter Account**: Credentials (`TWITTER_USERNAME` and `TWITTER_PASSWORD`) stored in `config/settings.py`.
- **Ollama**: An AI model server running locally at `http://127.0.0.1:11434` (e.g., LLaMA). [Install Ollama](https://ollama.ai/).

## Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Somi-Project/Somi.git
   cd path/Somi
   pip install -r requirements.txt
   Ollama pull phi4-mini
   Ollama pull codegemma:2b
   Ollama pull gemma3:4b (optional for vision analysis model)

## Edit Login
folder: config/settings.py

TWITTER_USERNAME = "your_twitter_username"
TWITTER_PASSWORD = "your_twitter_password"
TWITTER_API = "your developer api - can get for free on developer X"
TWITTER TIME INTERVALS = Time you wish to post materials with bound limits for organic activity
TELEGRAM BOT TOKEN = "your bot token from telegram bot father"
TELEGRAM USERNAME = "your set username for the bot"
DEFAULT MODEL = "Ollama model you wish to use - defaulted to a low requirement model"
other settings self explanatory 


## Edit Personality Construct
folder: config/personalC.json

default name is somi with defining parameters - edit as you see fit

## Agent Commands 
Begin by typing python somi.py <command> --name <agent name>
e.g. python somi.py <command> --name somi
```bash
  aiautopost   Generate and post a tweet initially, then every interval +/-bound minutes...
  aiautoreply  Auto scrape mentions and reply every 4 hours
  aichat       Chat continuously with the agent
  aipost       Generate and post a tweet once by personality
  aireply      Fetch latest mentions and reply = can use --limit added parameter
  devpost      Post a message to Twitter as a developer via agent
  gencookies   Generates Twitter cookies 
  telegram     Starts the Telegram bot
  speech       Audio I/O
  vba          Gui
  Persona      Personality editor
```

## Retrieval Augmentation thinking 
Edit setting.py to reflect intended ingestion websites then use the following commands to ingest into a FAISS system
If you want to add PDFS simply put the intended pdfs in the pdf folder of root directory then:
```bash
 --study pdfs
 --study websites
 --clearstudies deletes the above db
 ```
 Simply add --use-studies at the end of your Agent Commands to use the added data analyzed to its thinking
## Fin
I've added comments throughout the code to highlight relevant parts for now 
