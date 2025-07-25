import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import requests
import psycopg2
from psycopg2 import Error
from dailymotion import Dailymotion
import logging
import time
from flask import Flask, request
from urllib.parse import urlparse

# Initialize Flask app for webhook
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DAILYMOTION_API_KEY = os.getenv('DAILYMOTION_API_KEY')
DAILYMOTION_API_SECRET = os.getenv('DAILYMOTION_API_SECRET')
DAILYMOTION_USERNAME = os.getenv('DAILYMOTION_USERNAME')
DAILYMOTION_PASSWORD = os.getenv('DAILYMOTION_PASSWORD')
DAILYMOTION_EMAIL = os.getenv('DAILYMOTION_EMAIL')

# Parse DATABASE_URL for PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    db_url = urlparse(DATABASE_URL)
    DB_HOST = db_url.hostname or 'postgres.railway.internal'
    DB_NAME = db_url.path[1:]  # Remove leading slash
    DB_USER = db_url.username
    DB_PASSWORD = db_url.password
    DB_PORT = db_url.port or 5432
else:
    DB_HOST = os.getenv('DB_HOST', 'postgres.railway.internal')
    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_PORT = os.getenv('DB_PORT', '5432')

# Local Telegram API for large files
LOCAL_API_URL = os.getenv('LOCAL_API_URL', 'http://telegram-api:8081')
telebot.apihelper.API_URL = f"{LOCAL_API_URL}/bot{{0}}/{{1}}"

# Initialize bot
bot = telebot.TeleBot(TOKEN)

# Initialize Dailymotion client (for testing credentials)
dailymotion = Dailymotion()
dailymotion.set_grant_type('password', api_key=DAILYMOTION_API_KEY, api_secret=DAILYMOTION_API_SECRET,
                          info={'username': DAILYMOTION_USERNAME, 'password': DAILYMOTION_PASSWORD})

# PostgreSQL connection
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
        )
        logger.info("Successfully connected to PostgreSQL")
        return conn
    except Error as e:
        logger.error(f"Error connecting to PostgreSQL: {e}")
        return None

# Initialize database
def init_db():
    conn = get_db_connection()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    chat_id BIGINT PRIMARY KEY,
                    channel_name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dailymotion_accounts (
                    chat_id BIGINT PRIMARY KEY,
                    username TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    api_secret TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password TEXT NOT NULL,
                    api_type TEXT NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES channels(chat_id)
                );
            """)
            conn.commit()
    except Error as e:
        logger.error(f"Error initializing database: {e}")
    finally:
        conn.close()

# State storage
user_states = {}

# Menu commands
def setup_menu_commands():
    bot.set_my_commands([
        telebot.types.BotCommand("/start", "Start the bot"),
        telebot.types.BotCommand("/addchannel", "Add a channel"),
        telebot.types.BotCommand("/channellist", "List channels"),
        telebot.types.BotCommand("/removechannel", "Remove a channel")
    ])

# Command handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    try:
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("/upload"))
        bot.send_message(chat_id, "Welcome! Upload videos to Dailymotion with /upload or manage channels with /addchannel, /channellist, /removechannel.", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in /start: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")

@bot.message_handler(commands=['addchannel'])
def add_channel(message):
    chat_id = message.chat.id
    try:
        logger.info(f"Processing /addchannel for chat_id: {chat_id}")
        user_states[chat_id] = {'state': 'awaiting_channel_name', 'data': {}}
        bot.send_message(chat_id, "🔧 Let's add your Dailymotion channel!\n\nI'll need the following information:\n1. Channel name (for your reference)\n2. Dailymotion username\n3. API Key\n4. API Secret\n5. Email address\n6. Password\n7. API Type (Public/Private)\n\nPlease reply with your channel name first:")
    except Exception as e:
        logger.error(f"Error in /addchannel: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")

@bot.message_handler(commands=['channellist'])
def list_channels(message):
    chat_id = message.chat.id
    try:
        conn = get_db_connection()
        if conn is None:
            bot.send_message(chat_id, "Database error.")
            return
        with conn.cursor() as cur:
            cur.execute("SELECT channel_name FROM channels WHERE chat_id = %s", (chat_id,))
            channels = cur.fetchall()
            if channels:
                bot.send_message(chat_id, f"Your channels:\n{'\n'.join(row[0] for row in channels)}")
            else:
                bot.send_message(chat_id, "No channels found.")
    except Error as e:
        logger.error(f"Error listing channels: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")
    finally:
        if conn:
            conn.close()

@bot.message_handler(commands=['removechannel'])
def remove_channel(message):
    chat_id = message.chat.id
    try:
        logger.info(f"Processing /removechannel for chat_id: {chat_id}")
        bot.send_message(chat_id, "Enter channel name to remove:")
        user_states[chat_id] = 'awaiting_channel_remove'
    except Exception as e:
        logger.error(f"Error in /removechannel: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")

@bot.message_handler(commands=['upload'])
def upload_video(message):
    chat_id = message.chat.id
    try:
        bot.send_message(chat_id, "Send the video to upload to Dailymotion.")
        user_states[chat_id] = 'awaiting_video'
    except Exception as e:
        logger.error(f"Error in /upload: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")

# Handle video
@bot.message_handler(content_types=['video'])
def handle_video(message):
    chat_id = message.chat.id
    try:
        if user_states.get(chat_id) != 'awaiting_video':
            bot.send_message(chat_id, "Use /upload first.")
            return
        file_id = message.video.file_id
        bot.send_message(chat_id, "Received video! Enter the video title:")
        user_states[chat_id] = {'state': 'awaiting_title', 'file_id': file_id}
    except Exception as e:
        logger.error(f"Error in handle_video: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")

# Handle text input
@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    text = message.text
    if chat_id not in user_states:
        return

    state = user_states[chat_id]
    try:
        if isinstance(state, dict) and state['state'] == 'awaiting_channel_name':
            state['data']['channel_name'] = text
            state['state'] = 'awaiting_username'
            bot.send_message(chat_id, "👤 Enter your Dailymotion username:")
        elif isinstance(state, dict) and state['state'] == 'awaiting_username':
            state['data']['username'] = text
            state['state'] = 'awaiting_api_key'
            bot.send_message(chat_id, "🔑 Enter your API Key:")
        elif isinstance(state, dict) and state['state'] == 'awaiting_api_key':
            state['data']['api_key'] = text
            state['state'] = 'awaiting_api_secret'
            bot.send_message(chat_id, "🔐 Enter your API Secret:")
        elif isinstance(state, dict) and state['state'] == 'awaiting_api_secret':
            state['data']['api_secret'] = text
            state['state'] = 'awaiting_email'
            bot.send_message(chat_id, "📧 Enter your email address:")
        elif isinstance(state, dict) and state['state'] == 'awaiting_email':
            state['data']['email'] = text
            state['state'] = 'awaiting_password'
            bot.send_message(chat_id, "🔒 Enter your password:")
        elif isinstance(state, dict) and state['state'] == 'awaiting_password':
            state['data']['password'] = text
            state['state'] = 'awaiting_api_type'
            bot.send_message(chat_id, "🌐 Enter API Type (Public/Private):")
        elif isinstance(state, dict) and state['state'] == 'awaiting_api_type':
            state['data']['api_type'] = text
            channel_name = state['data']['channel_name']
            username = state['data']['username']
            api_key = state['data']['api_key']
            api_secret = state['data']['api_secret']
            email = state['data']['email']
            password = state['data']['password']
            api_type = state['data']['api_type']

            conn = get_db_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO channels (chat_id, channel_name) VALUES (%s, %s) ON CONFLICT (chat_id) DO UPDATE SET channel_name = %s",
                                    (chat_id, channel_name, channel_name))
                        cur.execute("""
                            INSERT INTO dailymotion_accounts (chat_id, username, api_key, api_secret, email, password, api_type)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (chat_id) DO UPDATE SET username = %s, api_key = %s, api_secret = %s, email = %s, password = %s, api_type = %s
                        """, (chat_id, username, api_key, api_secret, email, password, api_type,
                              username, api_key, api_secret, email, password, api_type))
                        conn.commit()
                    bot.send_message(chat_id, f"✅ Channel '{channel_name}' added successfully with Dailymotion account!")
                except Error as e:
                    logger.error(f"Error saving channel and Dailymotion account: {e}")
                    bot.send_message(chat_id, f"❌ Failed to add channel. Error: {str(e)}")
                finally:
                    conn.close()
            user_states.pop(chat_id)
        elif state == 'awaiting_channel_remove':
            conn = get_db_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM channels WHERE chat_id = %s AND channel_name = %s", (chat_id, text))
                        conn.commit()
                        if cur.rowcount > 0:
                            bot.send_message(chat_id, f"Channel '{text}' removed!")
                        else:
                            bot.send_message(chat_id, "Channel not found.")
                except Error as e:
                    logger.error(f"Error removing channel: {e}")
                    bot.send_message(chat_id, "An error occurred. Please try again later.")
                finally:
                    conn.close()
            user_states.pop(chat_id)
        elif isinstance(state, dict) and state['state'] == 'awaiting_title':
            # ... (rest of the upload logic remains the same)
            user_states[chat_id]['state'] = 'awaiting_hashtags'
            user_states[chat_id]['title'] = text
            bot.send_message(chat_id, "Enter hashtags (e.g., #fun #video):")
        # ... (rest of handle_text for upload remains the same)
    except Exception as e:
        logger.error(f"Error in handle_text for state {state}: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")
        user_states.pop(chat_id, None)

# Webhook endpoint
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_json())
    bot.process_new_updates([update])
    return '', 200

# Set up webhook
def set_webhook():
    webhook_url = os.getenv('WEBHOOK_URL', f'https://<your-railway-app>.railway.app/{TOKEN}')
    bot.remove_webhook()
    time.sleep(0.1)
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

if __name__ == '__main__':
    init_db()
    setup_menu_commands()
    set_webhook()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
