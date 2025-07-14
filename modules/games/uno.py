# Importing standard libraries
import random           # Used to shuffle the deck and randomize choices
import time             # Used for sleep delays in fallback error cases
import json             # For reading/writing JSON game state
import logging          # For logging errors and activity

# Path and typing support
from pathlib import Path                    # Used to locate and work with files
from typing import Tuple, List              # Type hints for function inputs/outputs
from datetime import datetime, timedelta, timezone  # Managing time and inactivity

# Telegram bot library
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

# Logger from the main bot file
from voxcoinbot import logger

# Set up file paths
BASE_DIR    = Path(__file__).resolve().parent                # Path to the current file's directory
STATS_FILE  = BASE_DIR / "uno_stats.json"                   # File where player win statistics are stored

# If the stats file doesn't exist yet — create an empty one
if not STATS_FILE.exists():
    STATS_FILE.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

# Function to load player statistics from file
def load_stats():
    return json.loads(STATS_FILE.read_text(encoding="utf-8"))

# Function to save player statistics to file
def save_stats(stats):
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

# File to store ongoing games
GAMES_FILE = BASE_DIR / "uno_games.json"

def load_games():
    """
    Loads all active UNO games from file into memory.
    Deserializes JSON into the global dictionary GAMES,
    converting string keys and date strings back into usable Python objects.
    """
    global GAMES
    if GAMES_FILE.exists():
        try:
            raw = json.loads(GAMES_FILE.read_text(encoding="utf-8"))
            new_games = {}
            for cid_str, g in raw.items():
                cid = int(cid_str)  # Convert chat ID string back to int
                new_games[cid] = {
                    "players": g["players"],  # List of player IDs
                    "hands": {
                        int(uid): [tuple(card) for card in cards]  # Convert hands back to tuples
                        for uid, cards in g["hands"].items()
                    },
                    "deck": [tuple(card) for card in g["deck"]],     # Remaining cards in deck
                    "pile": [tuple(card) for card in g["pile"]],     # Discard pile
                    "current": g["current"],                         # Index of current player
                    "direction": g["direction"],                     # 1 = clockwise, -1 = counter-clockwise
                    "current_color": g["current_color"],             # Color currently in play
                    "started": g["started"],                         # Has the game started?
                    "last_active": datetime.fromisoformat(g["last_active"]),  # Parse timestamp
                }
            GAMES = new_games
            logger.info(f"[UNO] Loaded {len(GAMES)} games from file")
        except Exception as e:
            logger.exception(f"Failed to load UNO games state: {e}")
            if not GAMES:
                GAMES = {}
    else:
        if not GAMES:
            GAMES = {}
        logger.info("[UNO] No games file found, using empty games dict")

def save_games():
    """
    Saves current game state to file.
    Converts all data structures into JSON-serializable types (lists, strings).
    """
    if not GAMES:
        logger.debug("[UNO] No games to save")
        return
        
    ser = {}
    for cid, g in GAMES.items():
        ser[str(cid)] = {
            "players": g["players"],
            "hands": {
                str(uid): [list(card) for card in cards]  # Convert cards to list of lists
                for uid, cards in g["hands"].items()
            },
            "deck": [list(card) for card in g["deck"]],
            "pile": [list(card) for card in g["pile"]],
            "current": g["current"],
            "direction": g["direction"],
            "current_color": g["current_color"],
            "started": g["started"],
            "last_active": g["last_active"].isoformat(),  # Convert datetime to ISO string
        }
    try:
        GAMES_FILE.write_text(json.dumps(ser, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[UNO] Saved {len(GAMES)} games to file")
    except Exception as e:
        logger.exception(f"Failed to save UNO games state: {e}")

def cleanup_old_games():
    """
    Deletes all games that were inactive for more than 24 hours.
    """
    global GAMES
    current_time = datetime.now(timezone.utc)
    to_remove = []
    
    for cid, game in GAMES.items():
        time_diff = current_time - game["last_active"]
        if time_diff > timedelta(hours=24):
            to_remove.append(cid)
            logger.info(f"[UNO] Removing inactive game in chat {cid}")
    
    for cid in to_remove:
        del GAMES[cid]
    
    if to_remove:
        save_games()

def initialize_games():
    """
    Called at module load. Ensures that GAMES is populated.
    """
    global GAMES
    if not GAMES:  # Load only if GAMES is still empty
        load_games()
        cleanup_old_games()

def ensure_games_loaded():
    """
    Sanity check to ensure GAMES is a dict.
    """
    global GAMES
    if not isinstance(GAMES, dict):
        logger.warning("[UNO] GAMES is not a dict, reinitializing")
        GAMES = {}
        load_games()

# Global dictionary that stores all active games.
GAMES: dict[int, dict] = {}

def log_handler(func):
    """
    Decorator for logging which command was triggered and by whom.
    Also wraps function in try-except to catch and log any errors.
    """
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        chat_id = update.effective_chat.id if update.effective_chat else None
        logger.info(f"[UNO] Handler {func.__name__} triggered by user={user_id} chat={chat_id}")
        try:
            return await func(update, context)
        except Exception:
            logger.exception(f"[UNO] Exception in handler {func.__name__}")
    return wrapper

# List of card colors (in Russian — now translated)
COLORS = ["red", "green", "blue", "yellow"]

# Mapping of special card types (skip, reverse, etc.)
SPECIAL = {
    "skip": "skip",
    "reverse": "reverse",
    "draw2": "+2",
    "wild": "wild",
    "wild4": "wild4",
}

def create_deck() -> List[Tuple[str, str]]:
    """
    Creates a full UNO deck: color-number and special cards.
    Each color gets:
      - One "0"
      - Two of each 1–9
      - Two of each special: skip, reverse, draw2
    Also adds:
      - 4 wild cards
      - 4 wild draw four cards
    Then shuffles the full deck.
    """
    deck: List[Tuple[str, str]] = []

    for c in COLORS:
        deck.append((c, "0"))  # One zero card per color
        for n in range(1, 10):  # Two of each number 1-9
            deck.extend([(c, str(n)), (c, str(n))])
        for sp in ("skip", "reverse", "draw2"):  # Two of each special
            deck.extend([(c, sp), (c, sp)])

    # Add wild and wild draw four cards
    deck.extend([("wild", "wild")] * 4)
    deck.extend([("wild", "wild4")] * 4)

    random.shuffle(deck)
    return deck

def advance_turn(game: dict):
    """
    Moves the turn to the next player, depending on direction (1 or -1).
    Uses modulo to loop over the player list.
    """
    game["current"] = (game["current"] + game["direction"]) % len(game["players"])

@log_handler
async def uno_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts a new UNO game in the chat.
    Initializes the game state for the current chat ID.
    """
    cid = update.effective_chat.id
    GAMES[cid] = {
        "players": [],             # List of user IDs
        "hands": {},               # Maps user ID to list of cards
        "deck": create_deck(),     # The shuffled deck of cards
        "pile": [],                # Cards that have been played
        "current": 0,              # Index of current player in `players`
        "direction": 1,            # Direction of play: 1 or -1
        "current_color": None,     # Active color for matching
        "started": False,          # Whether the game has begun
        "last_active": datetime.now(timezone.utc),  # Timestamp for cleanup
    }
    save_games()
    await update.message.reply_text(
        "🃏 New UNO game started!\n"
        "Send /uno_join to join the game."
    )

    # Try to delete the command message to reduce clutter
    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Adds the user to the list of players in the current chat's UNO game.
    """
    cid = update.effective_chat.id
    game = GAMES.get(cid)
    if not game:
        return await update.message.reply_text("❗ Start the game first with /uno_start.")
    if game["started"]:
        return await update.message.reply_text("❗ Game already started!")
    uid = update.effective_user.id
    if uid in game["players"]:
        return await update.message.reply_text("You are already in the game.")
    game["players"].append(uid)
    game["last_active"] = datetime.now(timezone.utc)
    save_games()
    await update.message.reply_text(
        f"✅ @{update.effective_user.username} joined! Total: {len(game['players'])}"
    )

    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Begins the game by dealing cards and placing the first card on the pile.
    Also announces which player goes first.
    """
    cid = update.effective_chat.id
    game = GAMES.get(cid)
    if not game:
        return await update.message.reply_text("❗ Start the game first with /uno_start.")
    if game["started"]:
        return await update.message.reply_text("❗ Game already in progress.")
    if len(game["players"]) < 2:
        return await update.message.reply_text("❗ Need at least 2 players.")

    # Deal 7 cards to each player
    for uid in game["players"]:
        game["hands"][uid] = [game["deck"].pop() for _ in range(7)]

    # Place the first card from the deck onto the pile
    top = game["deck"].pop()
    game["pile"].append(top)
    game["current_color"] = random.choice(COLORS) if top[0] == "wild" else top[0]
    game["started"] = True
    game["last_active"] = datetime.now(timezone.utc)
    save_games()

    first = game["players"][game["current"]]
    member = await context.bot.get_chat_member(cid, first)
    await update.message.reply_text(
        f"🃏 Game started!\n"
        f"Top card: {top[0]} {top[1] if top[1].isdigit() else SPECIAL[top[1]]}\n"
        f"Current color: {game['current_color']}\n"
        f"First player: @{member.user.username}"
    )

    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Deletes the current UNO game for this chat, if it exists.
    """
    cid = int(update.effective_chat.id)

    if cid in GAMES:
        del GAMES[cid]
        save_games()
        await update.message.reply_text("🔄 UNO game reset. Start a new one with /uno_start.")
        logger.info(f"[UNO] Game reset in chat {cid}")
    else:
        await update.message.reply_text("❗ No active game to reset.")

    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shows the current status of the game:
    - Number of players
    - Whether the game has started
    - Whose turn it is
    - Top card and current color
    """
    ensure_games_loaded()
    cid = int(update.effective_chat.id)
    game = GAMES.get(cid)
    if not game:
        return await update.message.reply_text("❗ No active game in this chat.")

    status_text = f"🎮 UNO game status:\n"
    status_text += f"📊 Players: {len(game['players'])}\n"
    status_text += f"🎯 Started: {'Yes' if game.get('started', False) else 'No'}\n"

    if game.get('started', False):
        current_player = game["players"][game["current"]]
        try:
            current_username = (await context.bot.get_chat_member(cid, current_player)).user.username
        except:
            current_username = str(current_player)
        status_text += f"🔄 Current turn: @{current_username}\n"
        status_text += f"🎨 Current color: {game.get('current_color', 'not set')}\n"

        if game.get('pile'):
            top_card = game['pile'][-1]
            display = f"{top_card[0]} {top_card[1] if top_card[1].isdigit() else SPECIAL.get(top_card[1], top_card[1])}"
            status_text += f"🃏 Top card: {display}\n"

    await update.message.reply_text(status_text)

    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_hand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends the user a private message with the list of their current cards.
    Only available if the game has started.
    """
    cid = update.effective_chat.id
    game = GAMES.get(cid)
    if not game or not game["started"]:
        return await update.message.reply_text("❗ The game is not running.")
    uid = update.effective_user.id
    hand = game["hands"].get(uid, [])
    if not hand:
        return await update.message.reply_text("❗ You have no cards.")
    game["last_active"] = datetime.now(timezone.utc)
    save_games()

    # Format cards into a readable string
    txt = "Your cards:\n" + " | ".join(
        f"{c} {v if v.isdigit() else SPECIAL[v]}" for c, v in hand
    )
    await context.bot.send_message(chat_id=uid, text=txt)

    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Allows a player to play a card.
    Handles rules, special effects (+2, reverse, skip, wild, wild4),
    and manages turn logic and win detection.
    """
    cid = update.effective_chat.id
    msg_id = update.message.message_id
    game = GAMES.get(cid)
    if not game or not game["started"]:
        return await update.message.reply_text("❗ The game is not running.")
    uid = update.effective_user.id
    if game["players"][game["current"]] != uid:
        return await update.message.reply_text("❗ It's not your turn.")

    args = [arg.lower() for arg in context.args]
    if not args:
        return await update.message.reply_text(
            "Usage:\n"
            "/uno_play <color> <number|skip|reverse|+2>\n"
            "or /uno_play wild <color>\n"
            "or /uno_play wild4 <color>"
        )

    # Determine card
    if args[0] in ("wild", "wild4"):
        if len(args) < 2 or args[1] not in COLORS:
            return await update.message.reply_text("🎨 Choose a color: red/green/blue/yellow")
        card = ("wild", args[0])
        chosen_color = args[1]
    else:
        color, value = args[0], args[1]
        card = (color, value)

    hand = game["hands"].get(uid, [])
    if card not in hand:
        return await update.message.reply_text("❗ You don't have that card.")

    # Check play validity
    top_color = game["current_color"]
    top_value = game["pile"][-1][1]
    if card[0] != "wild" and card[0] != top_color and card[1] != top_value:
        return await update.message.reply_text("❗ Invalid card: does not match color or value.")

    # Play the card
    hand.remove(card)
    game["pile"].append(card)
    game["current_color"] = chosen_color if card[0] == "wild" else card[0]
    game["last_active"] = datetime.now(timezone.utc)

    uname = f"@{update.effective_user.username}"
    disp = f"{card[0]} {card[1] if card[1].isdigit() else SPECIAL[card[1]]}"
    await update.message.reply_text(f"{uname} played {disp}\n▶️ Current color: {game['current_color']}")

    # Handle special card effects
    if card[1] == "skip":
        advance_turn(game)
        advance_turn(game)
    elif card[1] == "reverse":
        game["direction"] *= -1
        if len(game["players"]) == 2:
            advance_turn(game)
        advance_turn(game)
    elif card[1] == "draw2":
        advance_turn(game)
        nxt = game["players"][game["current"]]
        draw = [game["deck"].pop() for _ in range(2)]
        game["hands"][nxt].extend(draw)
        member = await context.bot.get_chat_member(cid, nxt)
        await update.message.reply_text(
            f"➕2: @{member.user.username} draws 2 cards and skips turn"
        )
        advance_turn(game)
    elif card[1] == "wild4":
        advance_turn(game)
        nxt = game["players"][game["current"]]
        draw = [game["deck"].pop() for _ in range(4)]
        game["hands"][nxt].extend(draw)
        member = await context.bot.get_chat_member(cid, nxt)
        await update.message.reply_text(
            f"🎴 Wild Draw Four: @{member.user.username} draws 4 cards and skips turn"
        )
        advance_turn(game)
    else:
        advance_turn(game)

    # Check for victory
    if not hand:
        await update.message.reply_text(f"🏆 {uname} has won the UNO game!")
        stats = load_stats()
        chat_stats = stats.setdefault(str(cid), {})
        chat_stats[str(uid)] = chat_stats.get(str(uid), 0) + 1
        save_stats(stats)
        del GAMES[cid]
        save_games()
        return

    save_games()
    nxt = game["players"][game["current"]]
    member = await context.bot.get_chat_member(cid, nxt)
    await update.message.reply_text(f"➡️ Next turn: @{member.user.username}")

    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Draws a card from the deck.
    Automatically skips the turn after drawing.
    If the deck is empty, reshuffles the pile.
    """
    cid = update.effective_chat.id
    msg_id = update.message.message_id
    game = GAMES.get(cid)
    if not game or not game["started"]:
        return await update.message.reply_text("❗ The game is not running.")
    uid = update.effective_user.id
    if game["players"][game["current"]] != uid:
        return await update.message.reply_text("❗ It's not your turn.")

    # Rebuild deck if empty
    if not game["deck"]:
        last = game["pile"].pop()
        game["deck"] = game["pile"]
        game["pile"] = [last]
        random.shuffle(game["deck"])

    # Draw card
    card = game["deck"].pop()
    game["hands"][uid].append(card)
    game["last_active"] = datetime.now(timezone.utc)
    save_games()

    await update.message.reply_text(
        f"🃏 You drew: {card[0]} {card[1] if card[1].isdigit() else SPECIAL[card[1]]}\n⏭️ Your turn is skipped."
    )
    advance_turn(game)
    nxt = game["players"][game["current"]]
    member = await context.bot.get_chat_member(cid, nxt)
    await update.message.reply_text(f"➡️ Next turn: @{member.user.username}")

    try:
        await context.bot.delete_message(cid, update.message.message_id)
    except:
        pass

@log_handler
async def uno_top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays top 10 players with the most UNO wins in the current chat.
    """
    cid = str(update.effective_chat.id)
    stats = load_stats().get(cid, {})
    if not stats:
        return await update.message.reply_text("No wins yet.")

    # Sort by win count
    top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
    text = "🏆 Top 10 UNO Winners:\n"
    for i, (uid, wins) in enumerate(top, start=1):
        try:
            member = await context.bot.get_chat_member(int(cid), int(uid))
            name = "@" + member.user.username
        except:
            name = uid
        text += f"{i}. {name} — {wins} wins\n"
    await update.message.reply_text(text)

async def uno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays a list of all available UNO commands.
    """
    logger.info("UNO help command called")
    try:
        text = (
            "UNO Commands:\n\n"
            "/uno_start — Start a new UNO game\n"
            "/uno_join — Join the UNO game\n"
            "/uno_begin — Begin the game\n"
            "/uno_hand — Send your cards via private message\n"
            "/uno_play <color> <number|skip|reverse|+2> — Play a card\n"
            "or /uno_play wild <color> or /uno_play wild4 <color>\n"
            "/uno_draw — Draw a card and skip your turn\n"
            "/uno_top10 — Show top 10 UNO winners\n"
            "/uno_status — Check the current game state\n"
            "/uno_reset — Reset the current game"
        )
        await update.message.reply_text(text)
    except Exception:
        logging.exception("Error in help_command")
        time.sleep(1.5)

# === Initialization block ===

initialize_games()
# Initializes the GAMES dictionary by loading from file and cleaning up old games.
# Called once on module load. Without this, the bot forgets all your precious UNO chaos.

def register_handlers(app):
    """
    Registers all UNO-related command handlers to the bot application.
    This binds the command names (e.g., /uno_start) to their respective functions.
    """
    app.add_handler(CommandHandler('uno_start', uno_start))       # Start a new UNO session
    app.add_handler(CommandHandler('uno_join', uno_join))         # Join the game
    app.add_handler(CommandHandler('uno_begin', uno_begin))       # Begin the game after players have joined
    app.add_handler(CommandHandler('uno_hand', uno_hand))         # Show a user's hand (sent in private)
    app.add_handler(CommandHandler('uno_play', uno_play))         # Play a card
    app.add_handler(CommandHandler('uno_draw', uno_draw))         # Draw a card and skip turn
    app.add_handler(CommandHandler('uno_top10', uno_top10))       # Show leaderboard for this chat
    app.add_handler(CommandHandler('uno_status', uno_status))     # Get current game status
    app.add_handler(CommandHandler('uno_reset', uno_reset))       # Reset the current game
    app.add_handler(CommandHandler('uno', uno))                   # Help command that lists all others
