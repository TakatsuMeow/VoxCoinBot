# --- Basic imports ---
import re                # For working with regular expressions (like checking if a string looks like "+10")
import os                # For dealing with file paths and environment variables
import sys               # For exiting the script if needed
import json              # To save and load user data in JSON format
import logging           # To log events and errors for debugging
import threading         # So we can lock access to data when multiple things happen at once
import time              # Time-related functions (like waiting or timestamps)
import secrets           # Secure random code generation
import pytz              # Time zone support
import subprocess        # (Not used in this script yet, but allows running other programs)
from pathlib import Path # Easier way to handle file paths across OS
from dotenv import load_dotenv  # Loads environment variables (like your bot token) from a .env file

# --- Telegram bot imports ---
from telegram import Update, User  # Represents a message and user in a Telegram chat
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, Defaults, JobQueue
)
from telegram.error import NetworkError, TimedOut

# --- Scheduling related ---
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta  # Working with date/time
from zoneinfo import ZoneInfo  # Timezone support for newer Python versions

# --- File setup ---
BASE_DIR = Path(__file__).resolve().parent  # The folder this file is in
DATA_FILE = os.path.join(BASE_DIR / 'data' / 'data.json')  # Where we'll save user data
LOG_DIR = os.path.join(BASE_DIR / 'data' / 'logs')         # Folder for logs
STOP_FILE = os.path.join(BASE_DIR, 'stop.txt')             # A file that might be used to stop the bot (not in this version)
SCRIPT = os.path.abspath(__file__)                         # The full path to this script itself

# Replace with your real Telegram ID to unlock admin-only commands
ADMIN_ID = "write ur telegram ID"

# --- Logging setup ---
logger = logging.getLogger(__name__)
os.makedirs(LOG_DIR, exist_ok=True)  # Make sure the logs folder exists

def setup_logging(LOG_DIR: str):
    """
    Sets up how the bot logs things to a file and to the console.
    Keeps only the last 500 lines of the log to prevent the file from growing forever.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, 'bot.log')

    # Trim the log file if it's too long
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        if len(lines) > 500:
            with open(log_file, 'w', encoding='utf-8') as f:
                f.writelines(lines[-500:])
    except FileNotFoundError:
        pass  # No log file yet, no problem
    except Exception as e:
        logging.warning(f"Couldn't trim log file: {e}")

    # Set up file logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.DEBUG,
        filename=log_file,
        filemode='a',
    )

    # Also show important info in the console (not just in the log file)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logging.getLogger().addHandler(console)

# --- Data handling ---
data_lock = threading.Lock()  # This prevents race conditions when saving data at the same time

def load_data():
    """
    Loads the JSON file with all user data.
    If the file doesn't exist or fails, starts fresh with default data.
    """
    logging.debug(f"Loading data from {DATA_FILE}")
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'chats': {}, 'code': ''}
    except Exception as e:
        logging.exception('Failed to load data.json: %s', e)
        time.sleep(1.5)
        return {'chats': {}, 'code': ''}

def save_data(data):
    """
    Saves the updated user data to the JSON file.
    Uses a lock so it doesn't break if multiple things try to write at once.
    """
    with data_lock:
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            logging.exception('Failed to save data.json')
            time.sleep(1.5)

def get_chat(data, chat_id: str):
    """
    Makes sure this chat has a space in the data file.
    If not, creates a new entry with empty user list and no privileges.
    """
    if chat_id not in data['chats']:
        data['chats'][chat_id] = {'users': {}, 'privileged': []}
    return data['chats'][chat_id]

def update_chat_user(data, chat_id: str, user: User):
    """
    Makes sure this user is registered in the current chat.
    Adds them if they aren’t, or updates their username if they changed it.
    """
    chat = get_chat(data, chat_id)
    uid = str(user.id)
    if uid not in chat['users']:
        chat['users'][uid] = {
            'username': user.username or user.full_name,
            'balance': 0,
            'voxcent': 0,
            'tvcoin': 0
        }
    else:
        chat['users'][uid]['username'] = user.username or user.full_name

def _ensure_message_stats(chat: dict):
    """
    Makes sure the chat has a structure to track how many messages users send.
    This is used to give out free coins for being active.
    """
    if 'message_stats' not in chat:
        chat['message_stats'] = {
            'last_reset': datetime.now(datetime.timezone.utc).timestamp(),
            'counts': {},      # user_id → how many messages they sent
            'awarded': []      # list of user_ids that already got their reward today
        }

def _check_and_reset_stats(chat: dict):
    """
    Every 24 hours, resets the message counters and the list of who got coins.
    """
    now = datetime.now(datetime.timezone.utc).timestamp()
    last = chat['message_stats']['last_reset']
    if now - last >= 86400:  # 24 hours in seconds
        chat['message_stats']['last_reset'] = now
        chat['message_stats']['counts'].clear()
        chat['message_stats']['awarded'].clear()

def update_message_stats_and_award(data: dict, chat_id: str, user_id: str) -> bool:
    """
    Called every time someone sends a message.
    Increases their message count. If they hit 1000 messages in 24h,
    gives them a 10-coin reward — but only once per day.
    """
    chat = get_chat(data, chat_id)
    _ensure_message_stats(chat)
    _check_and_reset_stats(chat)

    stats = chat['message_stats']
    stats['counts'][user_id] = stats['counts'].get(user_id, 0) + 1

    if stats['counts'][user_id] >= 1000 and user_id not in stats['awarded']:
        chat['users'][user_id]['balance'] += 10
        stats['awarded'].append(user_id)
        return True
    return False

def find_user_by_mention(chat, mention: str):
    """
    Finds a user in the chat by their @username.
    Returns the user ID if found, otherwise None.
    """
    for uid, info in chat['users'].items():
        if info['username'] and ('@' + info['username']).lower() == mention.lower():
            return uid
    return None

def get_level(balance: str) -> int:
    """
    Converts a user's balance into a level. Just for fun/ranking.
    """
    if balance < 300:
        return "level 1"
    elif balance < 500:
        return "level 2"
    elif balance < 800:
        return "level 3"
    elif balance < 1000:
        return "level 4"
    elif balance < 1300:
        return "level 5"
    elif balance < 1500:
        return "level 6"
    elif balance < 1800:
        return "level 7"
    elif balance < 2000:
        return "level 8"
    elif balance < 5000:
        return "level 9"
    else:
        return "level 10"

# /voxstart — Starts the bot and registers the user
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("start handler called")
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        data = load_data()
        update_chat_user(data, chat_id, user)
        save_data(data)
        uid = str(user.id)
        user_rec = data['chats'][chat_id]['users'][uid]
        bal = user_rec['balance']
        lvl = get_level(bal)
        sig = user_rec.get('signature', '')
    
        text = f"Hello, {user.first_name}!\n"
        text += f"Level: {lvl}\n"
        if sig:
            text += f"Signature: {sig}\n"
        text += f"Your balance: {bal} voxcoins."
        await update.message.reply_text(text)
    except Exception:
        logging.exception('Error in start handler')
        time.sleep(1.5)

# /voxbalance — Check balance (your own or someone else’s)
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("balance handler called with args=%s", context.args)
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        data = load_data()
        update_chat_user(data, chat_id, user)
        chat = get_chat(data, chat_id)
        args = context.args

        if args:
            # Check someone else's balance
            target = args[0]
            uid = find_user_by_mention(chat, target)
            if not uid:
                await update.message.reply_text("User not found.")
                return
            user_rec = chat['users'][uid]
            bal = user_rec['balance']
            voxcent = user_rec.get('voxcent', 0)
            tvcoin = user_rec.get('tvcoin', 0)
            lvl = get_level(bal)
            sig = user_rec.get('signature', '')
            name = user_rec['username']
            text = f"Profile of {name}:\n"
            text += f"Level: {lvl}\n\n"
            if sig:
                text += f"Signature: {sig}\n\n"
            text += f"Voxcoins: {bal}\nVoxcents: {voxcent}\nTVcoins: {tvcoin}"
            await update.message.reply_text(text)
        else:
            # Check your own balance
            uid = str(user.id)
            user_rec = chat['users'][uid]
            bal = user_rec['balance']
            lvl = get_level(bal)
            sig = user_rec.get('signature', '')
            voxcent = user_rec.get('voxcent', 0)
            tvcoin = user_rec.get('tvcoin', 0)
            text = f"Level: {lvl}\n\n"
            if sig:
                text += f"Signature: {sig}\n\n"
            text += f"Your balance:\n\n{bal} voxcoins\n{voxcent} voxcents\n{tvcoin} TVcoins"
            await update.message.reply_text(text)

    except Exception:
        logging.exception('Error in balance handler')
        time.sleep(1.5)

# /signa <text> — Set a profile signature
async def signa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /signa <text> — sets a custom signature for your profile.
    """
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    data = load_data()
    chat = get_chat(data, chat_id)
    update_chat_user(data, chat_id, user)

    uid = str(user.id)
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /signa <your signature text>")
        return

    chat['users'][uid]['signature'] = text
    save_data(data)
    await update.message.reply_text(f"Your signature has been set to: {text}")

# /add @user amount — Give voxcoins (VOX-admin only)
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("add handler called by user=%s args=%s", update.effective_user.id, context.args)
    try:
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        data = load_data()
        chat = get_chat(data, chat_id)

        # Only users with privileges can use this
        if str(user.id) not in chat['privileged']:
            await update.message.reply_text("❌ You don't have permission to use this command.")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /add @username <amount>")
            return

        mention, amount = args[0], float(args[1])
        uid = find_user_by_mention(chat, mention)
        if not uid:
            await update.message.reply_text("User not found.")
            return

        chat['users'][uid]['balance'] += amount
        save_data(data)
        name = chat['users'][uid]['username']
        await update.message.reply_text(f"✅ Added {amount} voxcoins to {name}.")
    except Exception:
        logging.exception('Error in add handler')
        time.sleep(1.5)

# /remove @user amount — Take away voxcoins (VOX-admin only)
async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("remove handler called by user=%s args=%s", update.effective_user.id, context.args)
    try:
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        data = load_data()
        chat = get_chat(data, chat_id)

        if str(user.id) not in chat['privileged']:
            await update.message.reply_text("❌ You don't have permission to use this command.")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /remove @username <amount>")
            return

        mention, amount = args[0], float(args[1])
        uid = find_user_by_mention(chat, mention)
        if not uid:
            await update.message.reply_text("User not found.")
            return

        chat['users'][uid]['balance'] -= amount
        save_data(data)
        name = chat['users'][uid]['username']
        await update.message.reply_text(f"❌ Removed {amount} voxcoins from {name}.")
    except Exception:
        logging.exception('Error in remove handler')
        time.sleep(1.5)

# /voxtop — Show top 30 richest users in the chat
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("top handler called")
    try:
        chat_id = str(update.effective_chat.id)
        data = load_data()
        chat = get_chat(data, chat_id)
        users = chat['users']

        # Sort users by balance in descending order
        top30 = sorted(users.items(), key=lambda kv: kv[1]['balance'], reverse=True)[:30]

        text = "🏆 Top 30 Users by Balance:\n"
        for i, (uid, info) in enumerate(top30, 1):
            text += f"{i}. {info['username']}: {info['balance']} voxcoins\n"

        await update.message.reply_text(text)
    except Exception:
        logging.exception('Error in top handler')
        time.sleep(1.5)

# /vox <code> — Enter secret code to become a privileged user
async def vox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("vox handler called with code=%s", context.args[0] if context.args else None)
    try:
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        data = load_data()
        args = context.args

        if not args:
            await update.message.reply_text("Please provide a code: /vox <code>")
            return

        code = args[0]
        if code == data.get('code'):
            priv = get_chat(data, chat_id)['privileged']
            uid = str(user.id)
            if uid not in priv:
                priv.append(uid)

            new_code = secrets.token_urlsafe(8)
            data['code'] = new_code  # generate new code so no one can reuse
            save_data(data)
            print(f"New vox code: {new_code}")
            await update.message.reply_text("✅ Access granted. You can now use admin commands.")
        else:
            await update.message.reply_text("Invalid code.")
    except Exception:
        logging.exception('Error in vox handler')
        time.sleep(1.5)

# /payto @user amount — Transfer coins to another user
async def payto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("payto handler called by user=%s args=%s", update.effective_user.id, context.args)
    try:
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        data = load_data()
        update_chat_user(data, chat_id, user)
        args = context.args

        if len(args) < 2:
            await update.message.reply_text("Usage: /payto @username <amount>")
            return

        mention, amount = args[0], float(args[1])
        chat = get_chat(data, chat_id)
        sender_id = str(user.id)
        uid = find_user_by_mention(chat, mention)
        if not uid:
            await update.message.reply_text("User not found.")
            return
        if chat['users'][sender_id]['balance'] < amount:
            await update.message.reply_text("Insufficient funds.")
            return

        chat['users'][sender_id]['balance'] -= amount
        chat['users'][uid]['balance'] += amount
        save_data(data)
        name = chat['users'][uid]['username']
        await update.message.reply_text(
            f"{user.first_name} sent {amount} voxcoins to {name}."
        )
    except Exception:
        logging.exception('Error in payto handler')
        time.sleep(1.5)

# /voxhelp — Shows all available bot commands
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends a help message listing all commands available in the bot.
    Translates all Russian descriptions to English.
    """
    logger.info("help_command called")
    try:
        text = (
            "— Voxbank Commands —\n"
            "/voxhelp — show this message\n"
            "/voxstart — register and check your balance\n"
            "/vox <code> — gain admin access with a secret code\n"
            "/payto @user <amount> — send voxcoins to someone\n"
            "/voxbalance OR /voxbalance @user — check your or someone else's balance\n"
            "/signa <text> — set a profile signature\n"
            "/voxtop — view the top 30 richest users\n"
            "/add @user <amount> — add voxcoins to user (requires admin access)\n"
            "/remove @user <amount> — remove voxcoins from user (requires admin access)\n"
            "/voxactivetop — show top 3 users by message count over the week\n"
            "\n"
            "— Extras —\n"
            "/topic — get a random conversation topic\n"
            "/addnewtopic — add your own topic to the list\n"
            "/song — pick a random song from the list\n"
            "/addsong <title by artist> — add your song to the list\n"
            "/kidsay — ask the flood neural net to say something (WIP)\n"
            "/addaction <action>|<emoji>|<description> — add custom actions (up to 10k stored)\n"
            "\n"
            "— UNO Game —\n"
            "/uno_start — begin recruitment for UNO game\n"
            "/uno_join — join an ongoing UNO game\n"
            "/uno_begin — start the game\n"
            "/uno_hand — send your cards privately\n"
            "/uno_play <color> <number|skip|reverse|+2> — play a card\n"
            "/uno_play wild <color> or /uno_play wild4 <color> — play wild cards\n"
            "/uno_draw — draw a card and skip your turn\n"
            "/uno_top10 — view top 10 UNO players\n"
            "/uno_status — see if there’s an active game\n"
            "/uno_reset — reset the game\n"
            "\n"
            "— Nonsense Game —\n"
            "/start_nonsense — begin recruitment\n"
            "/nonsense_join — join the game\n"
            "/nonsense_begin — start the game\n"
            "/nonsense <answer text> — SEND IN PRIVATE MESSAGE! continue the story\n"
            "\n"
            "— Casino —\n"
            "/casino — open casino menu\n"
            "/slots — play slots (minimum 50 voxcents)\n"
            "/dice — roll dice (minimum 50 voxcents)\n"
            "/roulette — spin the roulette (choose number 0-36 and bet)\n"
            "(Also shows top gamblers in /casino)"
        )
        await update.message.reply_text(text)
    except Exception:
        logging.exception("Error in help_command")
        time.sleep(1.5)

# /cmp +N or /cmp -N — Adjust voxcents for all users (admin only)
async def compensation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = 44444444  # Only this user can use the command
    user     = update.effective_user
    chat_id  = str(update.effective_chat.id)

    # Check admin permission
    if user.id != admin_id:
        await update.message.reply_text("🚫 You do not have permission to use this command.")
        return

    # Validate argument: must be +N or -N
    if not context.args or not re.match(r'^[+-]\d+$', context.args[0]):
        await update.message.reply_text("Usage: /cmp +<number> or -<number>")
        return

    delta = int(context.args[0])
    logger.info("compensation called with delta=%d by admin", delta)

    data = load_data()
    chat = get_chat(data, chat_id)
    count = 0

    # Apply change to each user
    for rec in chat['users'].values():
        old_vc = rec.get('voxcent', 0)
        new_vc = max(old_vc + delta, 0)
        if new_vc != old_vc:
            rec['voxcent'] = new_vc
            count += 1

    save_data(data)
    await update.message.reply_text(f"✅ Compensation of {delta} voxcents applied to {count} users.")

# /tvchange @user +N or /tvchange @user -N — Adjust TVcoins (admin only)
async def tvchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = str(update.effective_chat.id)

    # Check if user is the admin
    if user.id != ADMIN_ID:
        await update.message.reply_text("🚫 You do not have permission to change TVcoins.")
        return

    # Require exactly 2 arguments
    if len(context.args) != 2:
        return await update.message.reply_text(
            "Usage: /tvchange @user +<number> or -<number>"
        )

    mention = context.args[0]
    delta_s = context.args[1]

    # Validate the number format
    if not re.fullmatch(r'[+-]\d+', delta_s):
        return await update.message.reply_text(
            "Error: second argument must be +<number> or -<number>."
        )
    delta = int(delta_s)

    # Look for the user by mention
    data = load_data()
    update_chat_user(data, chat_id, update.effective_user)
    chat = get_chat(data, chat_id)
    uid = find_user_by_mention(chat, mention)
    if not uid:
        return await update.message.reply_text("User not found in this chat.")

    # Update TVcoins (can't go below zero)
    user_rec = chat['users'][uid]
    old_tv = user_rec.get('twcoin', 0)
    new_tv = max(old_tv + delta, 0)
    user_rec['twcoin'] = new_tv

    save_data(data)
    await update.message.reply_text(
        f"✅ TVcoins of <b>{user_rec.get('username','')}</b> changed: {old_tv} → {new_tv}.",
        parse_mode="HTML"
    )

# Main Function — Starting the Bot
def main():
    setup_logging(BASE_DIR)         # Start logging
    load_dotenv()                   # Load secrets from .env file
    token = os.getenv('BOT_TOKEN')  # Get bot token from environment

    if not token:
        logging.error('BOT_TOKEN not found in .env')
        sys.exit(1)

    data = load_data()

    # If there's no access code yet, generate one and save it
    if not data.get('code'):
        data['code'] = secrets.token_urlsafe(8)
        save_data(data)
        print(f"Initial vox code: {data['code']}")

    # Set bot default timezone to UTC
    defaults = Defaults(tzinfo=ZoneInfo("UTC"))
    app = (
        ApplicationBuilder()
        .token(token)
        .defaults(defaults)
        .build()
    )

    # Configure the scheduler (for future jobs, if needed)
    sched: AsyncIOScheduler = app.job_queue.scheduler
    sched.configure(
        timezone=ZoneInfo("UTC"),
        job_defaults={ 
            'max_instances': 2,
            'coalesce': True,
        },
    )

    job_queue: JobQueue = app.job_queue

    # Register all command handlers
    app.add_handler(CommandHandler('voxstart', start))
    app.add_handler(CommandHandler('voxbalance', balance))
    app.add_handler(CommandHandler('add', add))
    app.add_handler(CommandHandler('remove', remove))
    app.add_handler(CommandHandler('voxtop', top))
    app.add_handler(CommandHandler('vox', vox))
    app.add_handler(CommandHandler('payto', payto))
    app.add_handler(CommandHandler('voxhelp', help_command))
    app.add_handler(CommandHandler('signa', signa))
    app.add_handler(CommandHandler('cmp', compensation))
    app.add_handler(CommandHandler('tvchange', tvchange))

    # Register extra modules (easter eggs, floodbot, games, admin tools)
    from modules.other.eastereggsplus import register_fun_handlers
    register_fun_handlers(app)

    from modules.other.floodkid import register_kid_handlers
    register_kid_handlers(app)

    from modules.games.uno import register_handlers as register_uno
    register_uno(app)

    from modules.games.casino import register_handlers as register_casino
    register_casino(app)

    from modules.other.adminlol import register_admin
    register_admin(app)

    from modules.games.nonsense import register_nonsense_handlers
    register_nonsense_handlers(app)

    try:
        logger.info("Starting polling")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception:
        logging.exception('Unexpected error in bot polling')
        time.sleep(1.5)

if __name__ == '__main__':
    main()  # Runs the bot when you launch this file