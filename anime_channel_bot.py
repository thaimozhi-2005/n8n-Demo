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

# Parse DATABASE_URL for PostgreSQL (for tracking uploads)
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

# Initialize Dailymotion client
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
                CREATE TABLE IF NOT EXISTS video_uploads (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    file_id TEXT NOT NULL,
                    title TEXT,
                    hashtags TEXT,
                    status TEXT,
                    dailymotion_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        telebot.types.BotCommand("/upload", "Upload a video")
    ])

# Command handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    try:
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("/upload"))
        bot.send_message(chat_id, "Welcome! Upload videos to Dailymotion with /upload.", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in /start: {e}")
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
        if isinstance(state, dict) and state['state'] == 'awaiting_title':
            user_states[chat_id]['state'] = 'awaiting_hashtags'
            user_states[chat_id]['title'] = text
            bot.send_message(chat_id, "Enter hashtags (e.g., #fun #video):")
        elif isinstance(state, dict) and state['state'] == 'awaiting_hashtags':
            file_id = state['file_id']
            title = state['title']
            hashtags = text
            conn = get_db_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO video_uploads (chat_id, file_id, title, hashtags, status) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                                    (chat_id, file_id, title, hashtags, 'pending'))
                        upload_id = cur.fetchone()[0]
                        conn.commit()
                except Error as e:
                    logger.error(f"Error saving upload: {e}")
                    bot.send_message(chat_id, "Error saving upload details.")
                    user_states.pop(chat_id)
                    conn.close()
                    return
                finally:
                    conn.close()

            bot.send_message(chat_id, "Received details! Uploading to Dailymotion...")
            try:
                file_info = bot.get_file(file_id)
                file_url = f"{LOCAL_API_URL}/file/bot{TOKEN}/{file_info.file_path}"
                response = requests.get(file_url, stream=True)
                if response.status_code != 200:
                    bot.send_message(chat_id, "Error downloading video.")
                    user_states.pop(chat_id)
                    return
                video_path = f"/tmp/temp_{chat_id}_{int(time.time())}.mp4"
                with open(video_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                logger.info(f"File downloaded to {video_path}")

                dailymotion.upload(video_path, title=title, tags=hashtags.split(), published=True)
                video_url = dailymotion.get('/me/videos', fields=['url'])['list'][0]['url']
                conn = get_db_connection()
                if conn:
                    try:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE video_uploads SET status = %s, dailymotion_url = %s WHERE id = %s",
                                        ('success', video_url, upload_id))
                            conn.commit()
                    finally:
                        conn.close()
                bot.send_message(chat_id, f"Done! Watch it here: {video_url}")
            except Exception as e:
                logger.error(f"Error uploading to Dailymotion: {e}")
                bot.send_message(chat_id, f"Upload failed: {str(e)}")
                conn = get_db_connection()
                if conn:
                    try:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE video_uploads SET status = %s WHERE id = %s", ('failed', upload_id))
                            conn.commit()
                    finally:
                        conn.close()
            finally:
                if os.path.exists(video_path):
                    os.remove(video_path)
                user_states.pop(chat_id)
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
