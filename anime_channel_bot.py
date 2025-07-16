import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import psycopg2
import os
import re

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app for webhooks
app = Flask(__name__)

# Bot token from environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Initialize Telegram application
application = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Welcome to the Anime Channel Search Bot! Use /search <keyword> to find anime channels."
    )

def search_channels(keyword):
    """Query PostgreSQL database for channels matching the keyword."""
    DATABASE_URL = os.environ.get('DATABASE_URL')
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT name, link FROM channels WHERE name ILIKE %s", (f"%{keyword}%",))
        matches = cur.fetchall()
        cur.close()
        conn.close()
        return matches
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        return []

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /search command to find anime channels."""
    if not context.args:
        await update.message.reply_text("Please provide a keyword. Usage: /search <keyword>")
        return

    keyword = " ".join(context.args).lower()
    matches = search_channels(keyword)

    if not matches:
        await update.message.reply_text("No channels found matching your keyword.")
        return

    for name, link in matches:
        keyboard = [
            [
                InlineKeyboardButton("Visit Channel", url=link),
                InlineKeyboardButton("More Info", callback_data=f"info_{name}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"[{name}]({link})", parse_mode="MarkdownV2", reply_markup=reply_markup
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("info_"):
        channel_name = data.split("_")[1]
        info_text = f"More info about {channel_name}:\n" \
                    f"Link: {channel_name}\n" \
                    f"Description: A great channel for anime content!"
        await query.message.reply_text(info_text)

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Handle incoming Telegram updates via webhook."""
    update = Update.de_json(request.get_json(), application.bot)
    await application.process_update(update)
    return 'OK'

def main() -> None:
    """Initialize and run the bot."""
    global application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Run Flask app
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
