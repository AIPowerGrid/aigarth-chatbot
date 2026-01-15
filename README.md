# 🤖 aigarth

**Your AI-powered Discord companion for the AI Power Grid community.**

aigarth is a context-aware chat buddy powered by decentralized GPU workers on the AI Power Grid network. Every response comes from community-operated infrastructure—not centralized cloud servers—making aigarth living proof that the Grid works.

---

## ✨ Features

### 💬 Intelligent Conversations
- **Context-aware responses** — Remembers conversation history and picks up on context
- **Natural chat flow** — Responds when relevant, stays quiet when people are just chatting
- **Adjustable chattiness** — Admins can dial responsiveness from 1 (minimal) to 10 (very active)
- **Emoji reactions** — Uses reactions for quick acknowledgments instead of cluttering chat

### 🧠 Knowledge & Memory
- **RAG-powered answers** — Retrieves relevant documentation to answer questions accurately
- **Long-term memory** — Stores facts and personality traits that persist across sessions
- **Mood awareness** — Maintains a mood state that influences responses
- **Cross-channel awareness** — Keeps track of what's happening across different channels

### 📚 Document Management
- **Vector database** — Stores documents locally with ChromaDB for fast semantic search
- **Multi-format support** — Ingests `.md`, `.mdx`, and `.txt` files
- **GitHub auto-sync** — Automatically pulls documentation from configured GitHub repos
- **Discord uploads** — Admins can upload documents directly through Discord
- **URL ingestion** — Ingest content from web pages

### 🔐 Security & Moderation
- **AI scam detection** — Automatically analyzes messages with links for potential scams
- **Community voting** — Suspicious messages trigger community ban votes (3 votes to ban)
- **Smart allow-lists** — Trusted domains (DEXes, explorers, official sites) are never flagged
- **Discord invite blocking** — Automatically flags server invite links

### 📊 Crypto Integration
- **CoinGecko data** — Pulls live market data when crypto topics come up
- **Link previews** — Extracts OpenGraph metadata from shared URLs for context

### 🛠️ Admin Tools
- **Memory management** — View, add, update, and delete bot memories via DM
- **Chattiness control** — Adjust how often aigarth speaks up
- **Document CRUD** — Upload, list, and delete knowledge base documents

---

## 🚀 Quick Start

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **"New Application"** and give it a name
3. Go to the **"Bot"** section in the left sidebar
4. Click **"Add Bot"** and confirm
5. Under the bot's username, click **"Reset Token"** and copy your bot token
6. Enable these **Privileged Gateway Intents**:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
7. Go to **"OAuth2" → "URL Generator"**:
   - Select scopes: `bot`
   - Select permissions: `Send Messages`, `Read Message History`, `Add Reactions`, `Ban Members` (for moderation)
8. Copy the generated URL and use it to invite the bot to your server

### 2. Get a Grid API Key

1. Go to [dashboard.aipowergrid.io](https://dashboard.aipowergrid.io)
2. Create an account or log in
3. Navigate to **API Keys**
4. Generate a new API key and copy it

### 3. Clone & Setup Environment

```bash
git clone https://github.com/AIPowerGrid/aigarth-chatbot.git
cd aigarth-chatbot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment

Copy `.env.example` to `.env` and fill in your keys:

```env
# Required
DISCORD_TOKEN=your_discord_bot_token       # From step 1
GRID_API_KEY=your_aipg_api_key             # From step 2

# Channels (comma-separated IDs)
BOT_CHANNELS=123456789,987654321           # Active channels (respond + learn)
BOT_READONLY_CHANNELS=111222333            # Read-only (learn only)

# Optional
ADMIN_USER_ID=your_discord_user_id         # For admin commands
BOT_NAME=aigarth                           # Bot's name
GRID_MODEL=grid/meta-llama/llama-4-maverick-17b-128e-instruct

# GitHub Auto-Ingest (optional)
GITHUB_REPO=owner/repo
GITHUB_REPO_PATH=docs
GITHUB_REPO_BRANCH=main
GITHUB_TOKEN=ghp_xxxxx                     # For private repos
```

> 💡 **Tip:** To get channel IDs, enable Developer Mode in Discord (Settings → Advanced → Developer Mode), then right-click any channel and select "Copy ID".

### 6. Ingest Documentation

```bash
# Ingest a directory
python ingest.py --dir docs

# Ingest a single file
python ingest.py -f your_file.md

# Ingest from URL
python ingest.py -u https://example.com/document
```

### 7. Start aigarth

```bash
python bot.py
```

---

## 💡 Usage

### Talking to aigarth

**In active channels:**
- `@aigarth what is AI Power Grid?` — Mention for direct questions
- Just chat naturally — aigarth decides when to chime in based on relevance
- Reply to aigarth's messages for follow-up questions

**aigarth responds when:**
- Directly @mentioned
- Someone says "aigarth" in their message
- The conversation is relevant and aigarth can help

**aigarth stays quiet when:**
- People are chatting with each other
- Messages aren't relevant to topics aigarth knows about

### Admin Commands

**In Discord DMs:**

| Command | Description |
|---------|-------------|
| `!memory list` | View all stored memories |
| `!memory raw <key>` | See full text of a memory |
| `!memory set key=value` | Add or update a memory |
| `!memory delete <key>` | Remove a memory |
| `!chattiness` | View current chattiness level |
| `!chattiness <1-10>` | Set chattiness (1=quiet, 10=chatty) |

**In channels:**

| Command | Description |
|---------|-------------|
| `!help` | Show help message |
| `!upload` | Upload document (attach file) |
| `!list` | List all documents |
| `!delete <filename>` | Remove a document |

**Teaching aigarth:**
Mention aigarth with a fact and it'll remember it:
```
@aigarth The bridge to Base went live on January 5th, 2025
```
→ aigarth saves this to memory with a descriptive key

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Discord                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        bot.py                                │
│  • Message handling & routing                                │
│  • Scam detection & moderation                               │
│  • Admin commands                                            │
└─────────────────────────────────────────────────────────────┘
          │              │              │              │
          ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  retriever   │ │ grid_client  │ │conversation_ │ │  coingecko   │
│              │ │              │ │    db        │ │    _mcp      │
│ ChromaDB     │ │ AI Power     │ │ SQLite       │ │ Market data  │
│ RAG search   │ │ Grid API     │ │ History &    │ │ integration  │
│              │ │              │ │ Memories     │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

---

## 🔧 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | ✅ | — | Discord bot token |
| `GRID_API_KEY` | ✅ | — | AI Power Grid API key |
| `BOT_CHANNELS` | ✅ | — | Active channel IDs (comma-separated) |
| `BOT_READONLY_CHANNELS` | ❌ | — | Read-only channel IDs |
| `ADMIN_USER_ID` | ❌ | `0` | Discord ID for admin commands |
| `BOT_NAME` | ❌ | `ask-ai` | Bot's display name |
| `GRID_MODEL` | ❌ | `grid/meta-llama/...` | Model for inference |
| `CHROMA_DB_PATH` | ❌ | `./chroma_db` | ChromaDB storage path |
| `GITHUB_REPO` | ❌ | — | GitHub repo for auto-ingest |
| `GITHUB_REPO_PATH` | ❌ | `/` | Path within repo |
| `GITHUB_REPO_BRANCH` | ❌ | `main` | Branch to pull |
| `GITHUB_TOKEN` | ❌ | — | For private repos |

---

## 🐳 Docker

```bash
docker build -t aigarth .
docker run -d --env-file .env aigarth
```

---

## 🤝 Contributing

aigarth is part of the AI Power Grid ecosystem. Contributions welcome!

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Submit a PR

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Powered by AI Power Grid</strong><br>
  <em>Decentralized AI infrastructure for the community, by the community.</em>
</p>
