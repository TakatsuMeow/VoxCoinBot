# Import various necessary modules for bot logic and data handling
from voxcoinbot import logger, load_data, save_data, update_chat_user, get_chat
from datetime import datetime, timedelta
import random
import json
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# Set up file paths for storing casino-related data
BASE_DIR = Path(__file__).resolve().parent
QUOTA_FILE = BASE_DIR / 'casino_quota.json'      # User limits (cooldowns)
STATS_FILE = BASE_DIR / 'casino_stats.json'      # Game statistics
DATA_FILE  = BASE_DIR / 'casino_data.json'       # Placeholder (not actively used in this code)

# Create these files if they don't exist, filling them with default content
for fp, initial in [
    (QUOTA_FILE, {}),  # Empty dict for quotas
    (STATS_FILE, {"slots": {}, "roulette": {}, "dice": {}}),  # Game categories with empty stats
    (DATA_FILE, {})     # Just an empty object
]:
    if not fp.exists():
        fp.write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding='utf-8')

# Load JSON data from file
def load_json(fp: Path):
    return json.loads(fp.read_text(encoding='utf-8'))

# Save data into JSON file
def save_json(fp: Path, data):
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

# Helper to get user record and chat context from bot data
def get_user_record(update: Update):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    data = load_data()  # Load all persistent data
    update_chat_user(data, chat_id, update.effective_user)  # Ensure user info is fresh
    user_rec = get_chat(data, chat_id)['users'][user_id]  # Get specific user info
    return data, user_rec, chat_id, user_id

# Show the main casino menu with inline buttons
async def casino_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎰 Slots", callback_data='slots')],
        [InlineKeyboardButton("🎲 Dice", callback_data='dice')],
        [InlineKeyboardButton("🎡 Roulette", callback_data='roulette')],
        [InlineKeyboardButton("📈 Leaderboard", callback_data='leaderboard')],
    ]
    reply = "Welcome to the casino! Choose your game:"
    await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard))

# Handle what happens when a user clicks a button in the casino menu
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the click
    choice = query.data
    if choice == 'slots':
        await query.edit_message_text("Type /slots [bet ≥50]")
    elif choice == 'dice':
        await query.edit_message_text("Type /dice [bet ≥50]")
    elif choice == 'roulette':
        await query.edit_message_text("Type /roulette [number 0-36, bet]")
    elif choice == 'leaderboard':
        data = load_data()
        chat = get_chat(data, str(update.effective_chat.id))
        # Get the top 5 users with the most voxcent (gambling currency)
        top = sorted(
            chat['users'].items(),
            key=lambda item: item[1].get('voxcent', 0),
            reverse=True
        )[:5]
        lines = []
        for idx, (uid, user_rec) in enumerate(top, start=1):
            username = user_rec.get('username') or user_rec.get('first_name', 'User')
            mention = f"[{username}](tg://user?id={uid})"
            vc = user_rec.get('voxcent', 0)
            lines.append(f"{idx}. {mention} — {vc} voxcent")
        text = "🏅 Top Gamblers:\n" + "\n".join(lines)
        await query.edit_message_text(text, parse_mode="Markdown")

# Define slot machine emojis and payout multipliers
EMOJI_COMMON = ['🍒','🍋','🍊','🍉']        # Common emojis
EMOJI_RARE   = ['💎','👑']                  # Rare emojis with high payouts
ALL_EMOJI    = EMOJI_COMMON*4 + EMOJI_RARE  # Common emojis appear more frequently
PAYOUTS      = {
    **{e: (8,2) for e in EMOJI_COMMON},     # 3 symbols → x8, 2 symbols → x2
    **{e: (50,5) for e in EMOJI_RARE}       # Rare: 3 symbols → x50, 2 symbols → x5
}

# Slot machine logic
async def slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data, user_rec, chat_id, user_id = get_user_record(update)
    try:
        stake = max(50, int(context.args[0]))  # Minimum bet = 50
    except:
        return await update.message.reply_text("⚠️ Specify bet: /slots [number ≥50]")
    balance = user_rec.get('voxcent',0)
    if balance < stake:
        return await update.message.reply_text(f"Not enough balance ({balance} voxcent)")
    
    # Load spin quota (limit to 5 spins per 6 hours)
    quota = load_json(QUOTA_FILE)
    user_q = quota.setdefault(chat_id, {}).setdefault(user_id, {"slots": {"count":5, "last_ts":None}})
    now = datetime.utcnow().timestamp()
    if not user_q['slots']['last_ts'] or now - user_q['slots']['last_ts'] >= 6*3600:
        user_q['slots'] = {"count":5, "last_ts":now}
    if user_q['slots']['count'] <= 0:
        return await update.message.reply_text("⏳ Slot limit reached.")
    
    # Spin the slot machine: pick 3 emojis
    reels = [random.choice(ALL_EMOJI) for _ in range(3)]
    counts = {r: reels.count(r) for r in set(reels)}
    multiplier = 0
    for sym, cnt in counts.items():
        if cnt >= 2:
            multiplier = PAYOUTS[sym][1] if cnt == 2 else PAYOUTS[sym][0]
            break
    reward = stake * multiplier
    user_rec['voxcent'] = balance - stake + reward
    save_data(data)

    # Update statistics (net gain/loss)
    stats = load_json(STATS_FILE)
    stats['slots'].setdefault(chat_id, {}).setdefault(user_id, 0)
    stats['slots'][chat_id][user_id] += reward - stake
    save_json(STATS_FILE, stats)

    # Decrease spin quota and save
    user_q['slots']['count'] -= 1
    save_json(QUOTA_FILE, quota)

    # Prepare result message
    bar = ' | '.join(reels)
    if multiplier:
        res = f"[ {bar} ]\n🎉 You win: {reward} voxcent (x{multiplier})"
    else:
        res = f"[ {bar} ]\n💔 Lost {stake} voxcent"
    await update.message.reply_text(res)

# Dice game: 1-6 roll, win if 1 or 6 (x3 payout)
async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data, user_rec, *_ = get_user_record(update)
    try:
        stake = max(50, int(context.args[0]))
    except:
        return await update.message.reply_text("⚠️ Specify bet: /dice [number ≥50]")
    bal = user_rec.get('voxcent', 0)
    if bal < stake:
        return await update.message.reply_text(f"Not enough balance ({bal} voxcent)")
    roll = random.randint(1, 6)
    if roll in (1, 6):
        prize = stake * 3
        result = f"Rolled: {roll}. 🎉 You win {prize} voxcent"
    else:
        prize = 0
        result = f"Rolled: {roll}. 💔 Lost {stake} voxcent"
    user_rec['voxcent'] = bal - stake + prize
    save_data(data)
    await update.message.reply_text(result)

# Roulette: guess number (0–36), x35 if exact, x2 if parity matches
async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data, user_rec, *_ = get_user_record(update)
    try:
        num = int(context.args[0])
        stake = int(context.args[1])
        assert 0 <= num <= 36
    except:
        return await update.message.reply_text("⚠️ Usage: /roulette [number 0-36] [bet]")
    bal = user_rec.get('voxcent', 0)
    if bal < stake:
        return await update.message.reply_text(f"Not enough balance ({bal} voxcent)")
    result = random.randint(0, 36)
    if result == num:
        prize = stake * 35
        res = f"Roulette: {result}. 🎉 Jackpot! {prize} voxcent"
    elif result % 2 == num % 2:
        prize = stake * 2
        res = f"Roulette: {result}. 🎉 Win! {prize} voxcent (same parity)"
    else:
        prize = 0
        res = f"Roulette: {result}. 💔 Lost {stake} voxcent"
    user_rec['voxcent'] = bal - stake + prize
    save_data(data)
    await update.message.reply_text(res)

# Passive reward: every non-command message gives 1 voxcent
async def reward_voxcent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '')
    if len(text) <= 10 or text.startswith('/'):
        return
    data, user_rec, _, _ = get_user_record(update)
    user_rec['voxcent'] = user_rec.get('voxcent', 0) + 1
    save_data(data)

# Register all commands and handlers with the app
def register_handlers(app):
    app.add_handler(CommandHandler('casino', casino_menu))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.add_handler(CommandHandler('slots', slots))
    app.add_handler(CommandHandler('dice', dice))
    app.add_handler(CommandHandler('roulette', roulette))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reward_voxcent), group=100)
