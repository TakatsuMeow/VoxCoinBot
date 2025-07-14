# Import standard Python libraries
import os                      # For file path manipulations
import re                      # For regular expressions
import random                  # For random selections
import logging                 # For logging debug and info messages
import json                    # For reading and writing JSON files
from zoneinfo import ZoneInfo # For timezone support (Europe/Paris)
from datetime import datetime, time as dtime  # For time-related operations
from pathlib import Path       # For filesystem paths

# Import Telegram bot libraries
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

# Logger setup
logger = logging.getLogger(__name__)

# Import helper functions from the voxcoinbot module
from voxcoinbot import load_data, save_data, get_chat, update_chat_user, setup_logging

# File paths for different bot data
BASE_DIR = Path(__file__).resolve().parent
TOPICS_FILE = BASE_DIR / 'topics.txt'     # File storing conversation topics
SONGS_FILE = BASE_DIR / 'songs.txt'       # File storing songs
ACTIONS_FILE = BASE_DIR / "actions.json"  # File storing user-defined actions

BASE_DIR = os.path.dirname(__file__)
WEEKLY_FILE = os.path.join(BASE_DIR, 'weekly_counts.json')  # File to track weekly activity
REWARDS = [15, 10, 5]  # Rewards for weekly top 3 active users

# Create empty actions file if it doesn't exist
if not ACTIONS_FILE.exists():
    with ACTIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

# Load actions from file
def load_actions():
    with ACTIONS_FILE.open(encoding="utf-8") as f:
        return json.load(f)

# Save actions to file
def save_actions(actions):
    with ACTIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(actions, f, ensure_ascii=False, indent=2)

# Load weekly stats from file
def _load_weekly():
    if not os.path.isfile(WEEKLY_FILE):
        return {}
    with open(WEEKLY_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

# Save weekly stats to file
def _save_weekly(data):
    with open(WEEKLY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

# Return top 3 users based on weekly stats
def _get_weekly_top(chat_id):
    weekly = _load_weekly()
    stats = weekly.get(str(chat_id), {})
    return sorted(stats.items(), key=lambda x: x[1], reverse=True)[:3]

# Reward the weekly top 3 active users and reset the counter
async def _weekly_process(chat_id: str, bot):
    logger.info("_weekly_process for chat_id=%s", chat_id)
    data = load_data()
    top = _get_weekly_top(chat_id)
    if not top:
        await bot.send_message(chat_id=chat_id, text='[TRANSLATE] No messages this week.')
        return
    text = '🏆 Weekly Top-3 active members:\n'
    for idx, (uid, cnt) in enumerate(top):
        user_rec = data['chats'].get(str(chat_id), {}).get('users', {}).get(uid, {})
        uname = '@' + user_rec.get('username', uid)
        reward = REWARDS[idx] if idx < len(REWARDS) else 0
        data['chats'][str(chat_id)]['users'][uid]['balance'] = (
            data['chats'][str(chat_id)]['users'][uid].get('balance', 0) + reward
        )
        text += f"{idx+1}. {uname} — {cnt} messages → +{reward} voxcoin\n"
    save_data(data)
    # Reset the weekly counter
    weekly = _load_weekly()
    weekly[str(chat_id)] = {}
    _save_weekly(weekly)
    await bot.send_message(chat_id=chat_id, text=text)

# Message counter handler — called on every text message
async def weekly_count_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Message counter for the weekly report (currently non-functional)."""
    logger.debug("weekly_count_handler: user=%s text=%r", update.effective_user.id, update.message.text)
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    weekly = _load_weekly()
    stats = weekly.setdefault(chat_id, {})
    uid = str(user.id)
    stats[uid] = stats.get(uid, 0) + 1
    _save_weekly(weekly)

# Scheduled weekly report job (currently not active)
async def weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Weekly report and reward distribution (not active)."""
    logger.info("weekly_report_job for chat_id=%s", context.job.chat_id)
    job = context.job
    await _weekly_process(str(job.chat_id), context.bot)

# Manual command to trigger weekly report and rewards
async def weeklytop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger /weeklytop command and distribute rewards."""
    chat_id = str(update.effective_chat.id)
    logger.info("weeklytop command by chat=%s", chat_id)
    await _weekly_process(chat_id, update.message.bot)

# Command to show current weekly top-3 without rewards
async def voxactivetop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/voxactivetop — show the top-3 active users of the week without giving rewards."""
    chat_id = str(update.effective_chat.id)
    logger.info("voxactivetop called for chat=%s", chat_id)
    top = _get_weekly_top(chat_id)
    if not top:
        await update.message.reply_text('[TRANSLATE] No messages this week.')
        return
    text = '📈 Current weekly message Top-3:\n'
    for idx, (uid, cnt) in enumerate(top):
        data = load_data()
        user_rec = data['chats'].get(chat_id, {}).get('users', {}).get(uid, {})
        uname = '@' + user_rec.get('username', uid)
        text += f"{idx+1}. {uname} — {cnt} messages\n"
    await update.message.reply_text(text)

# Easter egg responses: keywords → replies (some are random)
EASTER_EGGS = {
    'hello': 'world!',
    'who am I': ['who are you?', 'no idea', 'and who am I?', 'just a user', 'slave of weekly quota',
              'the deepest question here', 'Val’s servant', 'pleb', 'horse in a coat', 'Alastor fanboy', 'raider maybe'],
    'omg': ['faith won’t help here', 'god save the king—', 'were you calling me?', 
             'prayer received, expect divine delay...',
             'if you talk to god — prayer; if god talks to you — psychosis',
             'I’m listening', 'my creator is probably online if I answered ;)']
}

# Randomly pick a song from songs.txt
async def random_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/song — pick a random song from songs.txt"""
    logger.info("random_song called")
    if not os.path.isfile(SONGS_FILE):
        with open(SONGS_FILE, 'w', encoding='utf-8'):
            pass  # Create an empty file if missing
    with open(SONGS_FILE, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    if not lines:
        await update.message.reply_text("No songs yet. Use /addsong to add the first one!")
        return
    song = random.choice(lines)
    await update.message.reply_text(f'🎲 Random song:\n\n{song}')

# Add a new song to songs.txt with auto-numbering
async def add_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addsong <title by artist> — add a new song to songs.txt with auto-incremented number
    """
    text = ' '.join(context.args).strip()
    logger.info("addsong called with text=%r", text)
    if not text:
        await update.message.reply_text("Usage: /addsong <title by artist>")
        return
    if not os.path.isfile(SONGS_FILE):
        with open(SONGS_FILE, 'w', encoding='utf-8'):
            pass
    # Note: song isn't actually saved in current version — you might want to implement this.

# Pick a random conversation topic
async def random_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/topic — pick a random conversation topic from topics.txt"""
    logger.info("random_topic called")
    if not os.path.isfile(TOPICS_FILE):
        with open(TOPICS_FILE, 'w', encoding='utf-8'):
            pass
    with open(TOPICS_FILE, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    if not lines:
        await update.message.reply_text("No topics yet. Use /addnewtopic to create one!")
        return
    topic = random.choice(lines)
    await update.message.reply_text(f'🎲 Conversation topic:\n\n{topic}')

# Add a new conversation topic with automatic numbering
async def addnewtopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addnewtopic <text> — adds a new conversation topic to topics.txt with auto-incremented number
    """
    text = ' '.join(context.args).strip()
    logger.info("addnewtopic called with text=%r", text)
    if not text:
        await update.message.reply_text("Usage: /addnewtopic <topic text>")
        return

    if not os.path.isfile(TOPICS_FILE):
        with open(TOPICS_FILE, 'w', encoding='utf-8'):
            pass

    max_num = 0
    with open(TOPICS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'^(\d+)\.', line)
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num

    new_num = max_num + 1
    entry = f"{new_num}. {text}\n"
    with open(TOPICS_FILE, 'a', encoding='utf-8') as f:
        f.write(entry)

    await update.message.reply_text(f"Topic #{new_num} added:\n{entry}")

# Responds to Easter Egg trigger words
async def easter_eggs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Responds to messages starting with keys from EASTER_EGGS.
    Can return either a string or a random item from a list of strings.
    """
    text = update.message.text.strip().lower()
    for key, resp in EASTER_EGGS.items():
        if text.startswith(key.lower()):
            reply = random.choice(resp) if isinstance(resp, (list, tuple)) else resp
            await update.message.reply_text(reply)
            return

# Add a new user-defined action (like /slap or /hug)
async def addaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addaction <word>|<emoji>|<action text>
    Adds a new custom action (max 10,000 entries).
    """
    if not context.args:
        await update.message.reply_text("Usage: /addaction <word>|<emoji>|<action text>")
        return

    payload = update.message.text.split(" ", 1)[1]
    parts = payload.split("|")
    if len(parts) != 3:
        await update.message.reply_text("Wrong format. Use | to separate: word|emoji|text")
        return

    word, emoji, action_text = parts
    word = word.strip().lower()
    emoji = emoji.strip()
    action_text = action_text.strip()

    if len(emoji) != 1:
        await update.message.reply_text("Emoji must be a single character.")
        return
    if not (1 <= len(action_text) <= 100):
        await update.message.reply_text("Action text must be 1 to 100 characters long.")
        return

    actions = load_actions()
    if len(actions) >= 10000:
        await update.message.reply_text("Cannot add more than 10,000 actions.")
        return
    if any(a["word"] == word for a in actions):
        await update.message.reply_text(f"The action “{word}” already exists.")
        return

    actions.append({"word": word, "emoji": emoji, "text": action_text})
    save_actions(actions)
    await update.message.reply_text(f"✅ Action “{word}” added successfully.")

# Handles user-triggered actions like “/slap @someone”
async def user_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text or ""
        logger.debug(f"[DEBUG user_action] raw text: {text!r}")

        lines = text.split("\n", 1)
        first_line = lines[0].strip()
        comment = lines[1].strip() if len(lines) > 1 else None

        parts = first_line.split()
        if not parts:
            logger.debug("[DEBUG user_action] no parts found, exiting")
            return
        word = parts[0].strip().lower()
        logger.debug(f"[DEBUG user_action] parsed word: {word!r}")

        target_name = None
        if update.message.reply_to_message:
            target_name = update.message.reply_to_message.from_user.first_name
        elif len(parts) > 1 and parts[1].startswith('@'):
            target_name = parts[1]

        actions = load_actions()
        for a in actions:
            if a["word"].lower() == word:
                author = update.effective_user.first_name
                emoji = a["emoji"]
                action_text = a["text"]
                reply = f"{author} {action_text} {emoji}"
                if target_name:
                    reply += f" {target_name}"
                if comment:
                    reply += f'\n"{comment[:500]}"'
                await update.message.reply_text(reply)
                return
    except Exception as e:
        logger.error(f"[ERROR user_action] Exception: {e}")
        import traceback; traceback.print_exc()

# Register all handlers with the bot
def register_fun_handlers(app):
    logger.info("››› Registering fun handlers…")

    # Message filters — record message count and actions
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_count_handler), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_action), group=1)

    # Commands for weekly top and rewards
    app.add_handler(CommandHandler('weeklytop', weeklytop))
    app.add_handler(CommandHandler('voxactivetop', voxactivetop))

    # Commands for topics and songs
    app.add_handler(CommandHandler('topic', random_topic))
    app.add_handler(CommandHandler('addnewtopic', addnewtopic))
    app.add_handler(CommandHandler('addsong', add_song))
    app.add_handler(CommandHandler('song', random_song))

    # Command for adding custom actions
    app.add_handler(CommandHandler('addaction', addaction))

    # Final fallback: check for Easter eggs
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, easter_eggs_handler), 2)

    # Weekly scheduled job every Saturday at 21:00 Paris time
    tz = ZoneInfo('Europe/Paris')
    app.job_queue.run_daily(weekly_report_job, time=dtime(21, 0, tzinfo=tz), days=(6,))