import re
import os
import sys
import json
import threading
import time
import pytz
import subprocess
from telegram import Update, User, ChatMemberUpdated  # Telegram event types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, Defaults, JobQueue,
    ChatMemberHandler  # This one is for member join/leave events
)
from telegram.error import NetworkError, TimedOut
from telegram.constants import ParseMode
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from voxcoinbot import logger, load_data, get_chat  # Use shared utilities from main bot

# This function is triggered when a user leaves the chat
async def on_member_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member  # The chat member update event
    old, new = cm.old_chat_member, cm.new_chat_member

    # If they were a member/admin/creator and now they are gone
    if old.status in ("member", "administrator", "creator") and new.status == "left":
        chat_id = str(cm.chat.id)
        uid = str(old.user.id)
        full_name = old.user.full_name

        # Try to detect user's custom title (like "mod") or use status fallback
        title = None
        if hasattr(old, "custom_title") and old.custom_title:
            title = old.custom_title
        elif old.status == "creator":
            title = "Creator"
        elif old.status == "administrator":
            title = "Administrator"

        # Escape markdown characters (so usernames don’t break formatting)
        def esc(s): return re.sub(r"([_*\[\]()~`>#+-=|{}.!])", r"\\\1", s)

        # Add the title to the message if there is one
        sig_part = f" «{esc(title)}»" if title else ""
        logger.info(f"TITLE: {sig_part}")

        # Mention the admin who should be notified
        admin_id = 44444444  # Replace this with your Telegram user ID
        admin_mention = f"[Admin alert!](tg://user?id={admin_id})"

        # Create the message about the user leaving
        text = (
            f"❗ User *{esc(full_name)}*{sig_part} "
            f"has left the chat. {admin_mention}"
        )

        logger.info(f"USER HAS LEFT INFO: {text}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN
        )

# Register the above handler when this module is loaded
def register_admin(app):
    logger.info("Registering admin handlers...")
    app.add_handler(ChatMemberHandler(on_member_leave, ChatMemberHandler.CHAT_MEMBER))
    app.run_polling(allowed_updates=Update.ALL_TYPES)  # Not recommended if called from main.py too
