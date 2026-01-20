# relational-ai
From CHI 2026 Paper: Scaffolded Vulnerability: Chatbot-Mediated Reciprocal Self-Disclosure and Need-Supportive Interaction in Couples

Echo: A Conversation Companion
Echo is a Telegram chatbot designed to help partners and close friends engage in meaningful self-disclosure. It guides users through structured conversation phases to help them feel more seen, known, and connected.

🌟 Features
Structured Phases: Guides users through rapport-building and three deep, reflective questions.

AI-Driven Mediation: Uses GPT-4o to provide warm, casual, and emotionally intelligent responses.

Partner Reflection: Encourages users to reflect on and support their partner’s answers.

Automated Summaries: Analyzes the conversation in real-time to provide a final summary of shared insights.

🛠️ Project Structure
main.py: The core bot logic and Telegram integration.

prompts.py: Contains the detailed system instructions for the AI's personality and conversation phases.

requirements.txt: List of necessary Python libraries.

.env: (Private) Stores your API keys and bot tokens.

message_logs/: (Private) Local storage for chat histories and logs.

🚀 Getting Started
1. Prerequisites
Python 3.10 or higher.

A Telegram Bot Token (from @BotFather).

An OpenAI API Key.

2. Installation
Clone this repository or download the files, then install the dependencies:

Bash

pip install -r requirements.txt
3. Configuration
Create a file named .env in the root folder and add your keys:

Code snippet

OPENAI_API_KEY=your_openai_key_here
TELEGRAM_TOKEN=your_telegram_bot_token_here
API_MODEL=gpt-4o
TELEGRAM_BOT_NAME=@your_bot_username
4. Running the Bot
Start the bot by running:

Bash

python main.py
📝 Usage
Add the bot to a Telegram group with your partner or friend.

Type /start to see the welcome message.

Type /continue whenever you are both ready to move to the next part of the conversation.

Use /pause if you need to take a break.
