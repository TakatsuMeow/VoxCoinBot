import os
import json
import random
import logging
import threading
from collections import deque, Counter, defaultdict
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, CommandHandler, filters

from voxcoinbot import setup_logging

logger = logging.getLogger(__name__)

# Path to the memory file where all stored messages are saved
BASE_DIR = os.path.dirname(__file__)
MEMORY_FILE = os.path.join(BASE_DIR, 'flood_memory.json')
MAX_MEMORY = 100000  # Max number of messages to store

# Size of the N-gram used to generate responses (e.g., 3-gram means "word pairs → next word")
N = 3

# Internal state of the flood module
_memory_lock = threading.Lock()  # Prevents multiple things editing memory at once
_memory = None           # List of saved messages
_memory_set = None       # Same messages as a set (for quick duplicate check)
_last_messages = deque(maxlen=3)  # Stores the last 3 received messages
_counter = 0             # Counts messages until bot replies
_next_trigger = random.randint(25, 50)  # How many messages before bot replies

def _load_memory():
    """
    Loads messages from file if memory is empty.
    Creates new empty memory if file doesn’t exist.
    """
    global _memory, _memory_set
    if _memory is not None:
        return
    if os.path.isfile(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            _memory = json.load(f)
    else:
        _memory = []
    _memory_set = set(_memory)

def _save_memory():
    """
    Saves the current list of messages to a JSON file.
    """
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(_memory, f, ensure_ascii=False)

def _add_message(text: str):
    """
    Adds a new message to memory if it’s not already there.
    If memory is full, deletes the oldest message.
    """
    logger.debug("_add_message called with text=%r", text)
    _load_memory()
    if text in _memory_set:
        return
    _memory.append(text)
    _memory_set.add(text)
    if len(_memory) > MAX_MEMORY:
        old = _memory.pop(0)
        _memory_set.remove(old)
    _save_memory()

def _build_ngram_model():
    """
    Builds a 3-gram model from the stored messages.
    Each pair of words is mapped to possible next words.
    """
    model = defaultdict(list)
    for msg in _memory:
        words = msg.split()
        if len(words) < N:
            continue
        for i in range(len(words) - N):
            key = tuple(words[i:i+N-1])
            next_word = words[i+N-1]
            model[key].append(next_word)
    return model

def _choose_seed():
    """
    Picks a rare word from the last 3 user messages.
    The rarer the word is in memory, the more likely it's picked.
    """
    _load_memory()
    recent = []
    for msg in _last_messages:
        recent.extend(msg.split())
    if not recent:
        return None
    counts = Counter()
    for msg in _memory:
        counts.update(msg.split())
    unique = set(recent)
    rare = sorted(unique, key=lambda w: counts.get(w, 0))
    return random.choice(rare)

def _generate_text(seed: str, length: int = 20) -> str:
    """
    Generates a sentence using the 3-gram model starting from the seed word(s).
    If the seed is too short, fills in with random known words.
    """
    model = _build_ngram_model()
    words = seed.split()
    if len(words) < N-1:
        candidates = [msg for msg in _memory if len(msg.split()) >= N-1]
        if candidates:
            words = random.choice(candidates).split()[:N-1]
    gen = words[-(N-1):]
    output = gen.copy()
    for _ in range(length):
        key = tuple(gen[-(N-1):])
        choices = model.get(key)
        if not choices:
            break
        next_word = random.choice(choices)
        output.append(next_word)
        gen.append(next_word)
    return ' '.join(output)

def _generate_reply(min_words: int = 5, max_words: int = 25) -> str:
    """
    Tries up to 10 times to generate a coherent sentence
    of at least `min_words` and up to `max_words`.
    """
    reply = ''
    for _ in range(10):
        seed = _choose_seed()
        text = _generate_text(seed, length=max_words)
        words = text.split()
        if len(words) >= min_words:
            reply = ' '.join(words[:max_words])
            break
    if not reply:
        text = _generate_text('', length=max_words)
        words = text.split()
        reply = ' '.join(words[:max_words])
    return reply

async def flood_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Main message handler.
    Adds incoming messages to memory, and after a random number of them, replies.
    """
    global _counter, _next_trigger
    text = update.message.text.strip()
    logger.info("flood_handler message=%r", text)
    with _memory_lock:
        _add_message(text)
    _last_messages.append(text)
    _counter += 1
    if _counter >= _next_trigger:
        _counter = 0
        _next_trigger = random.randint(25, 50)
        seed = _choose_seed() or ''
        reply = _generate_text(seed)
        if reply:
            await update.message.reply_text(reply)

# /kidsay command
async def kidsay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command: /kidsay
    Instantly generates and sends a short sentence.
    """
    logger.info("kidsay command called")
    reply = _generate_reply()
    if reply:
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text("I have nothing to say...")

# /kiddebug command
async def kiddebug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command: /kiddebug
    Shows diagnostic information about FloodKid’s internal memory and state.
    """
    logger.info("kiddebug command called")
    _load_memory()
    mem_len = len(_memory)
    model = _build_ngram_model()
    keys = len(model)
    recent = list(_last_messages)
    seed = _choose_seed() or '<none>'

    text = (
        f"FloodKid Debug:\n\n"
        f"Stored memory: {mem_len}\n"
        f"Unique messages in memory: {len(_memory_set)}\n"
        f"N-gram keys: {keys}\n"
        f"Last messages (max 3): {recent}\n"
        f"Chosen seed: {seed}\n"
        f"Next trigger in: {_next_trigger - _counter if _next_trigger >= _counter else _next_trigger} messages"
    )
    await update.message.reply_text(text)

def register_kid_handlers(app):
    """
    Adds all FloodKid-related message and command handlers to the bot.
    """
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, flood_handler), 3)
    app.add_handler(CommandHandler('kidsay', kidsay))
    app.add_handler(CommandHandler('kiddebug', kiddebug))
