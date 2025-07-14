# Import necessary modules
import json
import random
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode
from voxcoinbot import load_data, save_data  # Custom functions to handle bot data

# Define the path to the template file (where question sets are stored)
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_FILE = BASE_DIR / 'nonsense_templates.json'

# Default question templates for the "Nonsense" game — a story-building activity
default_templates = [
    [
        "How did the story begin?",
        "Who is the main character?",
        "Where did they go next?",
        "What was the main obstacle?",
        "How did the story end?"
    ],
    [
        "Where is the story set?",
        "What unusual thing happened?",
        "Who did the hero meet?",
        "What did the hero do first?",
        "How did it all end?"
    ],
    [
        "What did the hero find on the road?",
        "Why was it important?",
        "How did others react?",
        "What did the hero decide to do?",
        "What is the moral of the story?"
    ],
    [
        "How did an ordinary day begin?",
        "What interrupted it suddenly?",
        "Who did the hero meet along the way?",
        "Where did it all lead?",
        "What did the hero understand in the end?"
    ],
    [
        "Why did the hero wake up at night?",
        "What did they see?",
        "Where did they go?",
        "What was waiting for them?",
        "What was the final revelation?"
    ]
]

# If the template file doesn't exist, write the default templates into it
if not TEMPLATES_FILE.exists():
    TEMPLATES_FILE.write_text(json.dumps(default_templates, ensure_ascii=False, indent=2), encoding='utf-8')

# Load templates from file
def load_templates():
    return json.loads(TEMPLATES_FILE.read_text(encoding='utf-8'))

# /start_nonsense — starts a new game of Nonsense in the chat
async def start_nonsense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    templates = load_templates()
    questions = random.choice(templates)  # Pick a random question set
    # Register the game in memory
    data.setdefault('nonsense_games', {})[chat_id] = {
        'questions': questions,
        'participants': [],
        'answers': [],
        'current_q': 0
    }
    save_data(data)
    await update.message.reply_text(
        "📜 The 'Nonsense' game has started!\n"
        "To join, type /nonsense_join"
    )

# /nonsense_join — lets a user join the current game
async def nonsense_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    data = load_data()
    game = data.get('nonsense_games', {}).get(chat_id)
    if not game:
        return await update.message.reply_text("No active game. Start one with /start_nonsense")
    if user_id in game['participants']:
        return await update.message.reply_text("You're already in the game.")
    game['participants'].append(user_id)
    save_data(data)
    await update.message.reply_text(
        f"✅ You’re registered! Total players: {len(game['participants'])}."
    )

# /nonsense_begin — begins asking questions to the players
async def nonsense_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    game = data.get('nonsense_games', {}).get(chat_id)
    if not game:
        return await update.message.reply_text("No active game. Start one with /start_nonsense")
    if not game['participants']:
        return await update.message.reply_text("No participants yet. Use /nonsense_join first.")
    await _ask_next_question(chat_id, context)

# Internal function: sends the next question to the correct player in the game
async def _ask_next_question(chat_id: str, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    game = data['nonsense_games'][chat_id]
    idx = game.get('current_q', 0)  # Current question index
    questions = game['questions']
    participants = game['participants']
    
    # If all questions have been asked, reveal the full story
    if idx >= len(questions):
        await _reveal_story(chat_id, context)
        return

    # Determine which participant should answer next
    user_id = participants[idx % len(participants)]
    q_text = questions[idx]
    
    # Store pending question info to track direct message replies
    data.setdefault('nonsense_pending', {})[user_id] = {'chat_id': chat_id, 'q_idx': idx}
    game['current_q'] = idx  # Save current question index
    save_data(data)

    mention = f"[player](tg://user?id={user_id})"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"❓ Question #{idx+1}: {q_text}\n{mention}, please reply in private chat.",
        parse_mode=ParseMode.MARKDOWN
    )

# /nonsense — this is the DM command players use to submit their answer
async def nonsense_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return  # Only allow responses via private messages
    user_id = str(update.effective_user.id)
    data = load_data()
    pend = data.get('nonsense_pending', {})
    info = pend.get(user_id)
    if not info:
        return await update.message.reply_text("You don't have a question to answer.")
    chat_id = info['chat_id']
    q_idx = info['q_idx']
    
    # Parse the player's response text
    answer = ' '.join(context.args) if context.args else ''
    if not answer:
        return await update.message.reply_text("Please provide an answer: /nonsense <your answer>")
    
    # Store the answer into the game record
    game = data['nonsense_games'][chat_id]
    game['answers'].append({
        'user_id': user_id,
        'question': game['questions'][q_idx],
        'answer': answer
    })

    # Clear the pending question and move to next
    del pend[user_id]
    game['current_q'] = q_idx + 1
    save_data(data)
    await update.message.reply_text("✅ Answer received!")
    await _ask_next_question(chat_id, context)

# When all questions are answered, this sends the final story to the group
async def _reveal_story(chat_id: str, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    game = data['nonsense_games'].pop(chat_id)  # Remove the game record
    lines = []
    for idx, item in enumerate(game['answers'], start=1):
        mention = f"[player](tg://user?id={item['user_id']})"
        lines.append(f"{idx}. {item['question']}\n→ {item['answer']} (by {mention})")
    text = "📖 Final Nonsense Story:\n" + "\n\n".join(lines)
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN
    )
    save_data(data)

# Register all commands used by the nonsense module
def register_nonsense_handlers(app):
    app.add_handler(CommandHandler('start_nonsense', start_nonsense))
    app.add_handler(CommandHandler('nonsense_join', nonsense_join))
    app.add_handler(CommandHandler('nonsense_begin', nonsense_begin))
    app.add_handler(CommandHandler('nonsense', nonsense_dm))
