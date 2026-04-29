# relational-ai

Code for the CHI 2026 paper: **Scaffolded Vulnerability: Chatbot-Mediated Reciprocal Self-Disclosure and Need-Supportive Interaction in Couples**

## Overview

**Echo** is a Telegram-based chatbot designed to support meaningful self-disclosure between partners or close friends.  
It guides users through structured conversation phases, encourages reflection on each other’s responses, and helps facilitate supportive interaction.

This repository contains the research prototype used in our study.

## Features

- **Structured conversation phases** for guided self-disclosure
- **LLM-based responses** for warm and adaptive conversational support
- **Partner reflection prompts** that encourage supportive engagement
- **Conversation summarization** during or after the interaction
- **Telegram group-chat integration** for two-person conversations

## Repository Structure

```text
relational-ai/
├── main.py           # Main Telegram bot logic
├── prompts.py        # Prompt templates and phase instructions
├── requirements.txt  # Project dependencies
├── README.md
└── .env              # Local configuration file (not committed)
```

## Requirements

- Python 3.10+
- A Telegram bot token from `@BotFather`
- An OpenAI API key

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/AMAAI-Lab/relational-ai.git
cd relational-ai
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key
TELEGRAM_TOKEN=your_telegram_bot_token
API_MODEL=gpt-4o
TELEGRAM_BOT_NAME=@your_bot_username
```

## Running the Bot

```bash
python main.py
```

## Usage

1. Add the bot to a Telegram group chat with two users.
2. Start the bot with:
   - `/start` to begin
   - `/continue` to move to the next phase
   - `/pause` to pause the interaction
3. Follow the prompts in the group chat.

## Notes

- This repository provides a **research prototype** and is not intended as a production deployment.
- The bot assumes a Telegram-based, two-user conversation setting.
- Local message logs may be stored during execution; make sure these are excluded from version control.

## Citation

```bibtex
@inproceedings{10.1145/3772318.3791370,
author = {Jiang, Zhuoqun and Yeo, ShunYi and Herremans, Dorien and Tangi Perrault, Simon},
title = {Scaffolded Vulnerability: Chatbot-Mediated Reciprocal Self-Disclosure and Need-Supportive Interaction in Couples},
year = {2026},
isbn = {9798400722783},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3772318.3791370},
doi = {10.1145/3772318.3791370},
abstract = {While reciprocal self-disclosure drives intimacy, digital tools seldom scaffold autonomy, competence, and relatedness—the motivational underpinnings defined by Self-Determination Theory (SDT) that enable deep exchange. We introduce a chatbot employing dual-layer scaffolding to satisfy these needs: first providing enabling affordances (instrumental support) for vulnerability, then mediating affordances (relational support) for responsiveness. In a randomized study (N = 72; 36 couples) comparing Partner Support (PS: both layers), Direct Support (DS: enabling only), and Basic Prompt (BP: questions only), results reveal a critical distinction. While enabling affordances (PS, DS) were sufficient to deepen disclosure, only mediating affordances (PS) reliably elicited partner-provided need support and increased perceived closeness. Furthermore, controlled motivation decreased across conditions, and scaffolding buffered vitality, which remained stagnant in BP. We contribute empirical evidence that SDT-guided mediation fosters connection, offering a practical framework for designing AI-mediated conversations that support, rather than replace, human intimacy.},
booktitle = {Proceedings of the 2026 CHI Conference on Human Factors in Computing Systems},
articleno = {1296},
numpages = {39},
keywords = {Human-human interaction, Self-disclosure, Conversational agent, Social computing, Relational technology},
location = {
},
series = {CHI '26}
}
```
