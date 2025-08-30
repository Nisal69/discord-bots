# 📜 Discord Bots Command Reference

This document provides a full reference of commands available in **Bot 1 + Bot 3** and **Bot 2 (Jacoblina)**.

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

*(Note: Bot 1 + Bot 3 are mainly background utility/automation bots, not heavy on user-facing commands — they work mostly in the background.)*

---

## ⚔️ Bot 2 — Jacoblina (`bot2.py`)

### 🎮 1v1 Matches
- `?challenge @user` → Challenge someone to a 1v1. Opponent accepts/declines.  
- `?queue` → Join **auto-matchmaking** (expires in 1 hour if no one joins).  
- `?leavequeue` / `?cancelqueue` → Leave the matchmaking queue.  
- `?queuestatus` / `?qstat` → View queue size + your remaining timeout.  

### 📬 Challenges (Manual)
- `?challenges` → View your **pending challenges** (sent & received).  
- `?cancelchallenge` → Cancel your most recent pending challenge.  

### 🏆 Stats & Leaderboard
- `?leaderboard` → Show the current Top 10 (auto-updates).  
- `?mywins [@user | id | name]` → Detailed stats: wins, losses, points, tier, streak, rank.  

### ⚠️ Warnings System
- `?warn @user [reason...]` → Warns a member.  
  - At **3 warnings** → 2-day timeout.  
  - At **5 warnings** → 3-day timeout + warnings reset to 0.  
- `?warnings [@user]` → View your warnings (or another member’s). Shows count + last 10 reasons.  
- `?resetwarnings @user` → Reset all warnings for a member and clear any active timeout.  

### 📖 Help
- `?onevone_help` → How 1v1 works + list of commands (queue + challenges).  
- `?onevone_rules` → Scoring rules (+10/−10, streak bonus +5), tiers, and full procedure.  

---

## ⚔️ Jacoblina — Admin Quick Reference

### 🔧 Admin Commands
- `?setleaderboard #channel` → Set the auto-updating leaderboard channel (refreshes every 15 min + after each result).  
- `?resetleaderboard confirm` → Wipe all wins, points, streaks, and match history.  
- `?clearcolors` → Remove all color roles from members (**restricted — co-owner approval**).  
- `?resetcolors` → Rebuild the color-picker embed.  
- `?cancelmatch <admin_msg_id | @A @B> [reason...]` → Cancel an in-progress 1v1.  
  - Works by **admin results card ID** *or* both player mentions.  
  - Marks the match as **CANCELLED**, notifies players, deletes temp rooms, and skips scoring.  
- `?warn @user [reason...]` → Issue warnings (auto-escalates timeouts).  
- `?resetwarnings @user` → Fully clear warnings and remove any timeout.  

### 🎯 Admin Actions
- React with **:a: / :b:** on the **admin results card** to confirm winner (A or B).  
  → Bot records the match, updates **points/streak/rank**, edits the public result card, and refreshes the leaderboard.  

### 📢 Channel Use
- Use **match commands** (`?challenge`, `?queue`, `?leavequeue`, `?cancelchallenge`) in `#》︱1v1-requests`.  
- Use **stats commands** (`?leaderboard`, `?mywins`, `?warnings`) in `#》︱check-stats`.  
- All warnings are automatically **logged** to the moderation channel (`1411283522131591178`).  

---

## 🛡️ Notes
- **Bot 1 + Bot 3** provide automation utilities: presence, announcements, moderation, sticky notes.  
- **Bot 2 (Jacoblina)** is the competitive engine: 1v1 matches, queues, leaderboards, warnings, role panels.  
- Admin commands require elevated Discord roles.  
- Leaderboard stats persist in `leaderboard.db` (SQLite).  
