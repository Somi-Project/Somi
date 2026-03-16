# SOMI 🕊️
## Sovereign Operation Machine Intelligence

<p align="center"><strong>Run your own AI operating system on your own machine.</strong></p>

<p align="center">
  <img alt="Local First" src="https://img.shields.io/badge/Local--First-Yes-0f766e?style=for-the-badge">
  <img alt="Self Hosted" src="https://img.shields.io/badge/Self--Hosted-100%25-1d4ed8?style=for-the-badge">
  <img alt="Desktop" src="https://img.shields.io/badge/Desktop-PySide6-16a34a?style=for-the-badge">
  <img alt="Runtime" src="https://img.shields.io/badge/Runtime-Ollama-111827?style=for-the-badge">
  <img alt="Focus" src="https://img.shields.io/badge/Focus-Coding%20%7C%20Research%20%7C%20Speech-f59e0b?style=for-the-badge">
</p>

SOMI is a fully self-hosted, local-first AI agent framework built for people who want real capability without handing their data, workflows, or identity to a cloud platform.

It is designed to feel powerful for everyday users and credible for developers:

- local chat, memory, research, coding, OCR, speech, and automation
- desktop-first operator experience with dedicated studios and control surfaces
- approval-aware tools, sandboxed execution paths, and auditable actions
- modular architecture that still runs on consumer-grade hardware

No subscriptions. No forced SaaS. No hidden dependency on a remote agent service.

---

> [!IMPORTANT]
> SOMI is built for people who want an AI they can actually live with: local, capable, auditable, and enjoyable to use.

> [!TIP]
> If you are new to this kind of project, jump straight to [Quick Start](#quick-start). If you are evaluating it as a framework, head to [Repo Tour For Developers](#developer-view).

## 🧭 Choose Your Path

| If you are here to... | Start here |
| --- | --- |
| try SOMI quickly | [Quick Start](#quick-start) |
| see what it can do | [Flagship Capabilities](#flagship-capabilities) |
| understand the architecture | [What The Architecture Looks Like](#architecture) |
| inspect the codebase | [Repo Tour For Developers](#developer-view) |
| join the community | [Community](#community) |

---

## ✨ Why People Get Excited About SOMI

Most "AI agents" are one of these:

- a chatbot with a few extra buttons
- a cloud workflow dressed up as autonomy
- a research demo that is hard to live with every day
- a coding shell with no real operating layer around it

SOMI aims higher.

SOMI is a local AI workstation and agent framework that gives you:

- a desktop command center
- a coding workspace
- a research workspace
- speech input and output
- local memory and session recall
- OCR and document extraction
- automations and workflows
- a tool and skill system that can grow over time
- a secure path toward remote nodes and distributed execution

The goal is simple:

> make self-hosted AI feel practical, capable, safe, and genuinely enjoyable to use

---

## 🧠 What You Can Do With It

Use SOMI as:

- your local AI assistant
- your coding partner
- your research analyst
- your OCR and document extraction tool
- your voice-enabled desktop helper
- your Telegram-connected agent
- your automation engine
- your modular AI framework for building new tools and skills

---

## 👀 At A Glance

### For Everyday Users

- Run AI on your own hardware
- Keep your data local
- Talk to SOMI through the desktop, chat, Telegram, or speech
- Research, summarize, extract, organize, and automate from one system
- Use a futuristic but practical GUI instead of living in a terminal

### For Developers

- PySide6 desktop shell
- modular agent runtime
- tool registry and execution backends
- coding workspaces and guarded execution
- workflow runtime and subagents
- ontology, state plane, and control room
- local-first speech, OCR, browser automation, and research stacks
- release gate, freeze artifacts, replay harness, and security audit tooling

---

<a id="flagship-capabilities"></a>

## 🚀 Flagship Capabilities

### Desktop AI Workstation

SOMI is not just a CLI project. It includes a desktop shell with dedicated operator surfaces such as:

- Control Room
- Coding Studio
- Research Studio
- Speech controls
- Node Manager

### Self-Hosted Chat And Memory

- continuous local chat sessions
- persistent memory and recall
- compaction-aware history handling
- configurable personas and model routing

### Coding Mode

- managed coding workspaces
- Python-first, multi-language capable workflow
- guarded file operations and runtime actions
- benchmark and verify loops
- coding-focused studio UI

### Research And Evidence Workflows

- web and document research
- evidence graphs
- export bundles
- contradiction-aware synthesis
- local-first research orchestration

### OCR And Structured Extraction

- document OCR
- schema-based extraction
- table and form heuristics
- export-ready results for spreadsheets and downstream workflows

### Speech

- local TTS and STT pipeline
- pyttsx3 and local whisper-based flow
- desktop speech controls and test tooling

### Skills, Tools, And Automation

- modular tool registry
- skill marketplace and trust metadata
- workflow manifests
- automation runtime
- self-expansion path through skill drafting and approval

### Security And Control

- approval-aware execution
- audit trails
- scoped remote behavior
- gateway and node mesh foundations
- security audit and release gate tooling

---

<a id="quick-start"></a>

## ⚡ Quick Start

### Requirements

- Python 3.11+
- Git
- Ollama running locally at `http://127.0.0.1:11434`

Recommended:

- a modern CPU and at least 16 GB RAM
- an NVIDIA GPU for faster local inference
- Node.js for some advanced coding and browser workflows

### Install

```bash
git clone https://github.com/Somi-Project/Somi.git
cd Somi
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux / macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Optional PyTorch install for your hardware:

CPU:

```bash
pip install torch torchvision
```

CUDA example:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

Replace `cu121` with the build that matches your CUDA version.

### Pull Recommended Models

```bash
ollama pull dolphin3:latest
ollama pull stable-code:3b
ollama pull glm-ocr:latest
ollama pull qwen2.5-coder:3b
```

> [!TIP]
> For better private web search and research performance, pair SOMI with a properly configured SearXNG instance.
> Community setup guide: [SearXNG guide](https://x.com/frostyflak3s/status/2023202944397541418?s=20)

### Launch The Desktop App

```bash
python somicontroller.py
```

> [!NOTE]
> If you just want the main experience, start with the desktop app. It is the easiest way to feel what SOMI is supposed to be.

If you prefer CLI utilities:

```bash
python somi.py doctor
python somi.py release gate
python somi.py freeze
```

---

<a id="architecture"></a>

## 🏗️ What The Architecture Looks Like

SOMI is built as a local AI operating stack, not a single monolithic agent loop.

```text
Desktop / Chat / Telegram / Speech / Nodes
                  |
               Gateway
                  |
          Agent Runtime + Executive Layer
                  |
    Tools / Skills / Workflows / Subagents
                  |
      State Plane / Ontology / Memory / Audit
                  |
     Coding / Research / OCR / Browser / Speech
```

Core design pillars:

- best possible user experience for ordinary humans
- security-aware by default
- reliable on consumer hardware
- fast enough to feel usable every day
- modular enough to extend without rewriting the core

---

<a id="developer-view"></a>

<details>
<summary><strong>🧩 Want the developer view?</strong></summary>

## 🧩 Repo Tour For Developers

If you are evaluating SOMI as a framework, these are the most important entry points:

- [`somicontroller.py`](somicontroller.py) - desktop application entry
- [`somi.py`](somi.py) - doctor, security, release, replay, and freeze CLI
- [`agents.py`](agents.py) - agent compatibility wrapper and runtime binding
- [`agent_methods`](agent_methods) - split agent behavior modules
- [`gui`](gui) - PySide6 application surfaces
- [`workshop/toolbox`](workshop/toolbox) - tool stacks and runtime capabilities
- [`workshop/skills`](workshop/skills) - skills, marketplace, trust, and self-expansion
- [`execution_backends`](execution_backends) - execution routing and backend contracts
- [`workflow_runtime`](workflow_runtime) - bounded workflow runner
- [`ontology`](ontology) - typed operational graph
- [`gateway`](gateway) - channel and node-facing control surface
- [`speech`](speech) - local speech runtime
- [`docs/architecture/SYSTEM_MAP.md`](docs/architecture/SYSTEM_MAP.md) - architecture backbone
- [`docs/release/FRAMEWORK_FREEZE.md`](docs/release/FRAMEWORK_FREEZE.md) - current readiness snapshot

---

</details>

## ✅ Real Features, Not Just Claims

SOMI currently includes:

- local desktop GUI built on PySide6
- coding workspaces and guarded code execution
- research supermode with evidence graph exports
- OCR presets and structured extraction
- local speech pipeline with doctoring tools
- workflow runtime and subagents
- control room and observability surfaces
- skill forge, skill marketplace, and trust labeling
- node mesh and pairing foundations
- ontology-backed actions and human oversight
- release gate, framework freeze, replay harness, and security audit tooling

---

## 🔒 Security Philosophy

SOMI is built to be powerful without pretending power has no cost.

That means:

- approvals for sensitive execution paths
- explicit trust states for remote behavior
- auditable operations
- modular isolation boundaries
- local-first defaults whenever practical

SOMI is not trying to be reckless autonomy.
It is trying to be usable sovereignty.

---

## 🎮 Consumer Hardware Focus

SOMI is built for real machines people actually own.

That means the framework is designed around:

- local Ollama-hosted models
- bounded memory and context handling
- modular components you can enable gradually
- practical performance on prosumer and gamer-class hardware

You do not need a rack of servers to benefit from SOMI.

---

## 🌍 Cross-Platform Direction

SOMI is being built as a cross-platform framework with a local desktop-first experience.

Current development has been exercised most heavily on Windows, with architecture and packaging direction aimed at Windows, Linux, and macOS support.

---

<a id="community"></a>

## 🤝 Community

- Telegram: [https://t.me/+0ug5tDcPBXNjMTMx](https://t.me/+0ug5tDcPBXNjMTMx)
- Twitter / X: [https://x.com/SomiProject](https://x.com/SomiProject)

---

## 🛠️ Contributing

Contributions that help most:

- better onboarding and docs
- stronger modular tools and skills
- benchmark improvements
- performance and hardware tuning
- UI polish
- platform packaging and installer work

If SOMI saves you time, inspires a project, or feels like the kind of AI future you want to exist, star the repo and share it.

SOMI is meant to be something people can actually live with.
