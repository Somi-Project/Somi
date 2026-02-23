## S.O.M.I. - AI-Powered Everyday Automation

Somi is an A.I. Agent framework for automating interactions using an AI agent stored and operated on your computer. No data is leaked or uploaded elsewhere allowing you to control your information. Only limited by your hardware, the framework can perform a variety of tasks highlighted below. 

## Features Overview
- **Personality Construct**: Give your agent its own personality for unique responses
- **Chat**: Interact with the AI agent in the terminal
- **Telegram**: Telegram Agent interactable and image analysis abilities
- **Tweet Posting**: Generate and post tweets manually or automatically every determined interval in settings
- **Twitter Replies**: Reply to Twitter mentions once or auto-reply every determined interval in settings
- **Speech**: An experimental Input/Output mixture of models for a speech interface (Hardware speed dependant)
- **Modularity**: Change Models depending on your available hardware
- **Unrestricted**: Framework does not restrict behaviors this is handled by Large Language Model guardrails (if any)
- **Graphical User Interface**: For easy, convenient use of buttons
- **Study Injection**: Add Specific/New data to achieve better responses
- **Image Analysis**: Built into Telegram and Ai chat windows, dependant on visual Large Language Model chosen
- **Persistent Memories**: Database for important personal memories
- **Websearch**: Search for specific queries such as common asset prices, news headlines, weather, general web searches

## Prerequisites
Before running Somi, ensure you have the following installed:
- **Python 3.11.0+**: [Download Python](https://www.python.org/downloads/release/python-3110/)
- **Git**: [Install Git](https://git-scm.com/downloads)
- **Node.js** (optional, for Playwright): [Download Node.js](https://nodejs.org/) if not using pre-installed Playwright binaries.
- **Twitter Account**: Credentials (`TWITTER_USERNAME` and `TWITTER_PASSWORD`) stored in `config/twittersettings.py`. As well as Api keys
- **Telegram Token**: Install Telegram, message @Botfather send the message "/newbot" and setup to get a Name and Bot Token
- **Ollama**: An AI model server running locally at `http://127.0.0.1:11434` (e.g., LLaMA). [Install Ollama](https://ollama.ai/).

## Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Somi-Project/Somi.git
   cd path/Somi
   pip install -r requirements.txt
   Ollama pull phi4-mini-reasoning:3.8b
   Ollama pull codegemma:2b
   Ollama pull qwen2.5vl:3b (optional for vision analysis model)
   ```
 
   For Gpu use and faster response times install cuda for your gpu via https://developer.nvidia.com/cuda-downloads
   
Please note switch pytorch and torchvision to gpu modes with cuda enabled. Replace cu121 with your relevant cuda version in the command example below
```bash
pip install torch==2.4.1+cu121 torchvision==0.19.1+cu121 --index-url https://download.pytorch.org/whl/cu121 
```

All features are designed for **self-hosting** — no cloud, no subscriptions, full control.

You can apply a manual approach as below or use the GUI section for easier interface - both are supplied below
## GUI ease of use
Start the gui to make things easier

known issues may include repopulation of settings field when savings settings
no image upload for chat cli as yet only image analysis on telegram so far
delay in qThread by 3 seconds so for ai chat and RAG please wait 3 seconds for initialization

Start by running the command to initiate the gui 
```bash
python somicontroller.py
```

### Dependency mismatch fix (NumPy/Pandas)
If startup fails with an error like `ValueError: numpy.dtype size changed, may indicate binary incompatibility`, your local wheels are mixed after an update. Reinstall core scientific packages in one shot:

```bash
python -m pip install --upgrade --force-reinstall numpy==1.26.4 pandas==2.2.2 scikit-learn==1.5.2 sentence-transformers==5.2.2
```

Then rerun:

```bash
python somicontroller.py
```

### Initiate Agent
Starts the Ollama server in the background and loads your selected A.I. model (set in **General Settings**) into RAM/VRAM.  
Once running, all chat, voice, and RAG features become active.

### A.I. Chat
Opens the main chat window where you can:
- Select any agent from your `personalC.json`
- Enable/disable **Studies (RAG)** for knowledge-enhanced responses
- Click **Start Chat** to begin
- Change agents mid-session using **Apply Agent**

### Study Injection
Powerful Retrieval-Augmented Generation (RAG) tool:
- Automatically ingests all PDFs from the `PDFs/` folder
- Add websites via the **Ingest Websites** button
- Clear all studied data with one click
- Data stored in FAISS vector database for fast, accurate context retrieval
- Bitcoin Whitepaper included by default

### Social Media Agent Button
Central hub for automated posting and interaction:
- Controls both **Twitter** and **Telegram** bots
- All help documentation available inside (and below)

### Telegram Bot Setup
1. Message `@BotFather` on Telegram
2. Create a new bot → get your **Bot Token**
3. Paste token into **Telegram Settings**
4. Add bot to your group and grant admin rights
5. Use **Telegram Settings** to customize trigger aliases (default: `Somi`, `Retard`)

### Twitter / X Automation
Automated posting and smart replies using your agent’s personality.

**Features:**
- Auto-tweets at configurable intervals
- Auto-replies to mentions
- Manual **DevPost** for instant posting

**Setup (Free Tier):**
1. Go to https://developer.x.com → Projects & Apps
2. Create a project → enable **Read + Write + Direct Messages**
3. Generate and copy:
   - API Key & Secret
   - Access Token & Secret
   - Bearer Token
   - Client ID & Secret
4. Fill in **Twitter Settings** in the app

**Pro Tips:**
- New accounts: Post ~12 tweets + 6 replies manually first
- Switch account to **Bot Mode** in settings to avoid shadowbans
- Fill in username/password for better compliance (optional but recommended)

### General Settings
Customize core A.I. behavior:
- Change default model (`gemma3:4b`, `llama3.1`, etc.)
- Adjust temperature (creativity vs accuracy)
- Set vision model for image understanding



Enjoy your sovereign A.I. companion — built by you, for you.
## Edit Login
folder: config/settings.py
```bash
TWITTER_USERNAME = "your_twitter_username"
TWITTER_PASSWORD = "your_twitter_password"
TWITTER developer inserts  = "your developer apis which are MANY - can get for free tier on developer X"
TWITTER TIME INTERVALS = Time you wish to post materials with bound limits for organic activity
TELEGRAM BOT TOKEN = "your bot token from telegram bot father"
TELEGRAM USERNAME = "your set username for the bot"
DEFAULT MODEL = "Ollama model you wish to use - defaulted to a low requirement model"
other settings self explanatory 
```

## Edit Personality Construct
folder: config/personalC.json

default name is somi with defining parameters - edit as you see fit

## Direct Agent Commands 
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
```

Independant commands
Begin by typing python insertscriptname.py
```base
  speech       Audio I/O
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

 ## Other
 Type python somi.py - - help to see the available lists if interested 

 ## Fin

