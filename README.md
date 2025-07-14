# VoxCoinBot

VoxCoinBot is a modular Telegram bot designed for private communities. It features a built-in economy, gambling mini-games, and moderation tools.

## Features

- **In-chat currency system**  
  Users can earn and spend coins through mini-games and admin-set rewards.  
  Three main currencies are currently used:  
  - *Voxcents* — earned automatically by sending messages over 10 characters, used in casino games.  
  - *Voxcoins* — manually awarded, used in economy features like salaries and admin rewards.  
  - *TVCoins* — used for organizing movie nights.  
  A fourth event-based currency exists in development (one per deadly sin) for themed in-chat events.

- **Gambling and mini-games**
  - Casino games (roulette, slots, dice)
  - UNO
  - Nonsense (a collaborative story game; experimental)
  - Neural net imitation (Markov chain-based chat learner trained on up to 100k messages)

- **Moderation Tools**
  - Calls the administrator when the user leaves the chat
  - Tools for assigning salaries, tracking activity, and rewarding users

- **Easter Eggs and Roleplay**
  - Customizable reaction triggers for specific messages
  - Lightweight roleplay system with user-defined actions (up to 10,000 entries)
  - Hidden responses and fun interactions with the bot

- **Top Charts & Activity Tracking**
  - Weekly leaderboard of the most talkative users (currently broken)

- **Music and Conversation Starters**
  - Users can request a random song recommendation
  - Users can request random conversation topics
  - Both lists are community-editable via commands

- **Modular Architecture**
  Easily extendable structure: each feature resides in its own module.

## Demonstration

Watch a quick demo of core features (currency, admin protection, and casino):  
[▶️ Watch on YouTube](https://youtube.com/shorts/xf4u3fW7VUE?feature=share)

**Note**: The demonstration includes both English and Russian versions of the bot. Some features behave differently depending on admin privileges and language settings.

## Requirements

- Python 3.10+
- Telegram Bot API token

## Environment Setup

You can start by copying `.env.example` to `.env` and filling in the required values (e.g., `BOT_TOKEN`).

## Installation

1. Clone this repository:
```
git clone https://github.com/TakatsuMeow/VoxCoinBot.git
cd VoxCoinBot
```

2. Install dependencies:
```
pip install -r requirements.txt
```

3. Write in a `.env` file your bot token:
```
BOT_TOKEN=your_telegram_token_here
```

4. Run the bot:
```
python voxcoinbot.py
```

Or use the provided `run.bat` (Windows only).

## File Structure

- `voxcoinbot.py` — main entry point
- `modules/` — contains modular features (games, moderation, etc.)
- `data/` — runtime and persistent JSON storage
- `.env` — contains environment variables (not included in repo)
- `run.bat` — quick launch on Windows

## Tech Stack

**Language**: Python 3.x  
**Bot Framework**: python-telegram-bot  
**Task Scheduling**: APScheduler  
**Environment Management**: python-dotenv  
**Timezone Handling**: pytz  
**Async Support**: asyncio  
**Date/Time**: datetime, pytz  
**Other**: standard Python libraries (os, json, etc.)

## Notes

- This project is actively maintained as a personal project.
- Not all features are production-stable; some are experimental.
- All Python files are well-commented for clarity and learning purposes.

## Known Issues

- Nonsense game is untested
  - The collaborative storytelling game (nonsense) has not been tested in live chat environments and may not function as intended.

- Weekly activity tracking is broken
  - The system responsible for counting messages and rewarding the most active users each week currently does not work.

- Admin configuration is hardcoded
  - Administrator privileges are assigned via hardcoded Telegram user IDs. There is no user-friendly or dynamic configuration system for admin roles.

## License

This project is released under the MIT License.  
You are free to use, modify, and distribute the code, as long as the original license and copyright notice are included.

## Contact

Created by Takato Atsushi  
Telegram: @meowtakato

GitHub: https://github.com/TakatsuMeow
