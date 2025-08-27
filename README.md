text
# Discord Bots Collection

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)  
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)  
[![Discord.py](https://img.shields.io/badge/discord.py-2.0%2B-5865F2.svg)](https://discordpy.readthedocs.io/en/stable/)  

This repository contains **two custom Discord bots** (plus Bot 3 bundled inside Bot 1’s script) written in Python.  
They are designed for **community engagement, matchmaking, leaderboard tracking, role management, and server automation**.  

The project is built for **easy setup, modularity, and extensibility**, with tokens securely managed via environment variables (`.env`).  

---

## ✨ Features

### Bot 1 + Bot 3 (`bot1.py`)
- Runs **two separate bots** in a single script (`bot1` and `bot3`).
- Custom status presence to display **dynamic activities** in the server.
- Stream announcement embeds (TikTok/YouTube links).
- Sticky note system for structured channels.
- Moderation utility (e.g., mention auto-deletion).
- Clean and extensible for further custom features.

---

### Bot 2 (`bot2.py`)
A full‑featured **competitive 1v1 system** with matchmaking, leaderboards, and admin controls.

- **1v1 Matchmaking**
  - Direct challenges with accept/decline buttons.
  - Auto‑matchmaking queue with timeout.
  - Private text + voice channels created for each match.
  - Automatic cleanup of match rooms after confirmation.

- **Leaderboard & Ranking**
  - Persistent stats backed by local **SQLite** database.
  - Tracks wins, losses, streaks, and seasonal points.
  - Generates leaderboard images with **Pillow**.
  - Ranks by points → *Elite, Pro, Master, Grand Master, Legendary*.
  - Leaderboard auto‑updates every 15 minutes.

- **Embeds & Images**
  - Uses Discord `Embed` for announcements.
  - Rich match cards for admin confirmation and public view.
  - Dynamic leaderboard images with avatars, ranks, and stats.

- **Admin Tools**
  - Cancel pending or live matches.
  - Reset leaderboard and stats.
  - Manage roles, colors, and boosters automatically.

- **Self‑Assignable Roles**
  - Reaction role panel for color roles.
  - Enforces **single color role per member**.
  - Auto‑cleans duplicate roles on startup.

---

## ⚙️ Installation

### 1️⃣ Clone Repo
```bash
git clone https://github.com/Nisal69/discord-bots.git
cd discord-bots
```

### 2️⃣ Install Dependencies
Requires Python **3.10+**:
```bash
pip install -r requirements.txt
```


#### Main Dependencies
- `discord.py` → Core bot framework
- `aiohttp` → Async HTTP client APIs
- `Pillow` → Image rendering for leaderboard cards
- `python-dotenv` → Load tokens from `.env`

---

### 3️⃣ Environment Variables
Create `.env` at repo root:
```env
# Bot Tokens (Never share or commit these!)
BOT1_TOKEN=your_bot1_token_here
BOT3_TOKEN=your_bot3_token_here
BOT2_TOKEN=your_bot2_token_here
```


⚠️ **Important:** Never push tokens to GitHub. Reset immediately if leaked in the Discord Developer Portal.

---

## ▶️ Running the Bots

Run **Bot 1 + Bot 3 (combined)**:

```bash
python Bots/bot1.py
```

Run **Bot 2 (standalone)**:

```bash
python Bots/bot2.py
```

---

## 📜 Commands Reference

For a quick overview of **Bot 2** commands, see the highlights below.  
For the full detailed reference of **Bot 1 + Bot 3** and **Bot 2**, check the separate documentation here:  
👉 [Full Commands Reference](COMMANDS.md)

### 🎮 Bot 2 (Highlights)
- `?challenge @user` → Challenge a user.  
- `?queue` → Join matchmaking queue.  
- `?leaderboard` → Show top 10 players.  
- `?mywins [@user|id|name]` → Show stats for a player.  
- `?cancelmatch` → Admin: cancel an active/pending match.  


---

## 📂 Repository Structure

discord-bots/
│
├── Bots/
│ ├── bot1.py # Bot 1 & Bot 3 (combined script)
│ ├── bot2.py # Bot 2 (1v1, leaderboard, etc.)
│ ├── leaderboard.db # SQLite database (ignored by git)
│
├── .env # Bot tokens (not in git)
├── .gitignore # Ignore tokens, DB files, cache
├── requirements.txt # Dependencies
└── README.md # Documentation


---

## 🛡️ Security Notes
- `.env` and `leaderboard.db` are excluded from git.
- GitHub push protection prevents accidental secret leaks.
- Reset credentials immediately if leaked.
- Each bot must use its own token.

---

## 🧩 Extending Bots
- Add commands with `@bot.command()` decorators.
- Create shared utility modules for reusability.
- Use `discord.ext.tasks` for scheduled jobs.
- Extend matchmaking with more competitive features.

---

## 📜 License
This project is licensed under the **MIT License**.  
You may use, modify, and distribute it freely with attribution.

---

## 🤝 Contributing
Contributions welcome! 🚀  
- Report bugs via Issues.  
- Suggest features or improvements.  
- Submit PRs with tested, modular code.  

