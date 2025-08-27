# 📜 Discord Bots Command Reference

This document provides a full reference of commands available in **Bot 1 + Bot 3** and **Bot 2**.

---

## 🤖 Bot 1 + Bot 3 (`bot1.py`)

### 🔔 Presence & Utility
- *(Automatic)* → Sets custom **status/presence** like `Watching BisBis play CODM`.  

### 🎥 Stream Announcements
- *(Automatic)* → Sends announcement embeds when TikTok/YouTube links are posted.  

### 📝 Sticky Notes
- *(Automatic)* → Maintains sticky messages at the bottom of specified channels.  

### 🛡️ Moderation
- *(Automatic)* → Auto-deletes user mentions in restricted channels.  

*(Note: Bot 1 + Bot 3 are mainly utility/automation bots, not heavy on user-facing commands — they work mostly in the background.)*

---

## ⚔️ Bot 2 (`bot2.py`)

### 🎮 1v1 Matches
- `?challenge @user` → Challenge another user to a 1v1.  
- `?queue` → Join the matchmaking queue (auto-pairs you with the next available player).  
- `?leavequeue` → Leave the matchmaking queue.  
- `?queuestatus` / `?qstat` → Show the number of players waiting and your queue timeout.  
- `?cancelchallenge` → Cancel your last challenge request.  

### 📬 Challenges
- `?challenges` → View all of your pending challenges (both sent and received).  

### 🏆 Leaderboard & Stats
- `?leaderboard` → Display the current Top 10 players as an image card.  
- `?mywins [@user | id | name]` → Show stats for yourself or another player (wins, losses, streaks).  

### ⚔️ Admin Commands
- `?cancelmatch <message_id> [reason...]` → Cancel an in-progress match by referencing the admin message ID.  
- `?cancelmatch @A @B [reason...]` → Cancel a match by tagging both players.  
- `?resetleaderboard confirm` → Reset all stats and wipe leaderboard history.  
- `?resetcolors` → Rebuild the color role embed panel.  
- `?clearcolors` → Remove all color roles from every member.  

---

## 🛡️ Notes
- **Bot 1 + Bot 3** focus on background utilities: presence, announcements, moderation, sticky notes.  
- **Bot 2** is the competitive engine: 1v1 matches, queues, leaderboards, role panels.  
- Admin commands require elevated Discord roles.  
- Leaderboard stats persist in `leaderboard.db` (SQLite).  
