# S.O.M.I.
### Local-First AI Agent Framework

⚡ Runs on consumer hardware  
🔒 No cloud required  
🧠 Persistent memory included  
🛠️ Modular tools + automation  
💬 GUI + CLI + Telegram  

---

⭐ If Somi saves you time or inspires you, consider starring the repo.

---

## What Is Somi?

Somi is a **fully self-hosted AI agent framework** designed to run entirely on your own machine using local models via Ollama.

No SaaS.  
No hidden API calls.  
No data leaving your system.  

It combines:

- Local LLM execution  
- Persistent memory  
- Retrieval-Augmented Generation (RAG)  
- Tool + handler routing  
- Telegram automation  
- Desktop GUI  
- Experimental speech interface  

All modular. All hardware-aware. All under your control.

---

# Why Somi Exists

Most “AI agents” today are:

- Cloud dependent  
- Prompt wrappers  
- Unstable automation chains  
- Overengineered research experiments  

Somi focuses on something different:

> A practical, local, extensible AI operating layer for everyday automation.

---

# Quick Start

## Requirements

- Python 3.11+
- Git
- Ollama running locally at `http://127.0.0.1:11434`

Optional:
- CUDA GPU (recommended for performance)
- Node.js (for advanced automation modules)

---

## Install

```bash
git clone https://github.com/Somi-Project/Somi.git
cd Somi
pip install -r requirements.txt
pip install torch torchvision #for pure cpu loading
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121 #for gpu loading (faster) - please change cu121 to match your cude compatible version
```

Pull models:

```bash
ollama pull dolphin3:latest #General 
ollama pull stable-code:3b #Instructor
ollama pull glm-ocr:latest #Vision 
ollama pull qwen2.5-coder:3b #Coding
```

Launch GUI:

```bash
python somicontroller.py
```

You now have a sovereign AI agent running locally.

---

# Core Capabilities

## 💬 AI Chat (CLI + GUI)
- Continuous sessions
- Agent personality switching
- Memory injection
- Study (RAG) toggle

## 🧠 Persistent Memory
- Structured memory storage
- Injected per session
- Bounded for performance

## 📚 Study Injection (RAG)
- Drop PDFs into `/PDFs`
- Ingest websites
- FAISS vector search backend
- Bitcoin Whitepaper included

## 🔎 Websearch Tools
- Asset prices
- News headlines
- Weather
- General search queries

## 📱 Telegram Agent
- Conversational bot
- Image analysis support
- Configurable aliases
- Group compatible

## 🎙️ Speech Interface (Experimental)
- Audio input/output
- Model-based pipeline
- Hardware dependent

## 🛠️ Modular Architecture
- Swap models freely
- Extend handlers
- Add tools
- Expand jobs

---

# Architecture Overview

```text
User Input
   ↓
agents.py (Routing + Memory + Tool Decision)
   ↓
Handler / Tool / RAG / LLM
   ↓
Response
```

Design principles:

- Deterministic routing  
- Bounded context usage  
- Local-first execution  
- Consumer hardware compatibility  
- Modular extensibility  

---

# Configuration

Primary settings:

```
config/settings.py
```

Control:
- Default model
- Vision model
- Temperature
- Memory limits
- RAG toggles
- Websearch settings

Persona configuration:

```
config/personalC.json
```

Define:
- Agent name
- Tone
- Constraints
- Behavioral traits

---

# CLI Commands

Basic usage:

```bash
python somi.py <command> --name <agent_name>
```

Example:

```bash
python somi.py aichat --name somi
```

Available commands:

```
aichat       Continuous chat
telegram     Start Telegram bot
--study pdfs
--study websites
--clearstudies
--use-studies
```

Independent scripts:

```
python speech.py
python persona.py
```

---

# Telegram Setup

1. Message `@BotFather`
2. Create a new bot
3. Copy bot token
4. Paste into settings
5. Add bot to group with admin rights

---

# GPU Acceleration (Optional)

Install CUDA from NVIDIA.

Then install matching PyTorch build:

```bash
pip install torch==2.4.1+cu121 torchvision==0.19.1+cu121 --index-url https://download.pytorch.org/whl/cu121
```

Replace `cu121` with your CUDA version.

---

# Known Minor Limitations

- CLI chat currently does not support image uploads  
- GUI settings may repopulate after save  
- Initial model warmup ~3 seconds  
- Latency issues
---

# Philosophy

Somi is built around:

- Local sovereignty  
- Modularity  
- Human control  
- Practical autonomy  
- Hardware realism  

It is not a cloud wrapper.  
It is not a subscription service.  

It is a framework you control.

---

# Roadmap

- Faster routing
- Deterministic memory system
- Skill registry
- Tool sandboxing
- Improved voice latency
- Enterprise-grade execution layer

---

# Contributing

Ways to help:

- Improve quickstart clarity  
- Add demo screenshots  
- Submit modular tools  
- Improve routing reliability  
- Expand test coverage  

PRs welcome.

---

# Community

Telegram:
https://t.me/+0ug5tDcPBXNjMTMx

Twitter:
https://x.com/SomiProject

---

Enjoy your sovereign AI companion.  
Built locally. Controlled locally. Extended locally.
