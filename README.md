## Somi - AI-Powered Automation

Somi is a Python-based CLI tool for social interactions using an AI agent. It can post tweets, reply to mentions, and chat interactively, all driven by customizable character personalities stored in `personalC.json`.
This current version can also perform Retrieval Augmentation Generation with Faiss to add PDF data or static website data to the feed (Do not recommend crypto. prices via this route - recommend API integration which is coming soon)

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
- **Ollama**: An AI model server running locally at `http://127.0.0.1:11434` (e.g., LLaMA). [Install Ollama](https://ollama.ai/). - must run ollama while running the agent and pull the relevant model via command - ollama pull <model name>

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
  gencookies   Generates Twitter cookies (recommend doing first)
  aiautopost   Generate and post a tweet initially, then every 10 minutes...(Can edit this in the code - 10 minutes has been for testing - edit in somi.py delay minutes = 10)
  aiautoreply  Auto scrape mentions and reply every 4 hours
  aichat       Chat continuously with the agent
  aipost       Generate and post a tweet once
  aireply      Fetch latest mentions and reply using the agent's personality
  devpost      Post a message to Twitter
```

## Retrieval Augmentation thinking 
Edit setting.py to reflect intended ingestion websites then use the following commands to ingest into a FAISS system
If you want to add PDFS simply put the intended pdfs in the pdf folder of root directory then:
```bash
 --study pdfs
 --study websites (static scraping only)
 ```
 Simply add --use-studies at the end of your Agent Commands to use the added data analyzed to its thinking

## Commands summary
python somi.py gencookies

python somi.py aichat --name <agent> --model <model> --temp <temp> --use-studies

python somi.py devpost --message "<message>"

python somi.py aipost --name <agent> --use-studies

python somi.py aiautopost --name <agent>

python somi.py aireply --name <agent> --limit <limit>

python somi.py aiautoreply --name <agent> --limit <limit>

python somi.py telegram --name <agent> --use-studies

python somi.py study --name <agent> --study pdfs --study websites

python somi.py clearstudies

Agent-Specific Options
--name <agent> (e.g., degenia)

--model <model> (e.g., llama3, default: llama3)

--temp <temp> (e.g., 0.9, default: 0.7)

--limit <limit> (e.g., 3, default: 2)

RAG-Specific Options
--use-studies (enables RAG for aichat, aipost, telegram)

--study pdfs (studies PDFs for RAG)

--study websites (studies websites for RAG)



## Fin
I've added comments throughout the code to highlight relevant parts for now 
