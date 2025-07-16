import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Replace with your Telegram Bot Token
TELEGRAM_BOT_TOKEN = 'Bot token'
# Replace with your n8n webhook URL
N8N_WEBHOOK_URL = 'webhook url'
# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Send me a YouTube URL and a number between 1 and 10.\n'
        'Format: YouTube_URL Number\n'
        'Example: https://youtu.be/abc123 5'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.message.chat_id

    # Process message using provided logic
    parts = message.strip().split()
    url_part = next((part for part in parts if 'youtube.com' in part or 'youtu.be' in part), None)
    number_part = next((part for part in parts if part.isdigit()), None)

    if url_part and number_part:
        number = int(number_part)
        if 1 <= number <= 10:
            payload = {
                'action': 'process',
                'YouTube URL': url_part,
                'How many shorts to generate?': number,
                'chat_id': chat_id
            }
        else:
            payload = {
                'action': 'invalid_number',
                'chat_id': chat_id,
                'message': 'Please use a number between 1 and 10'
            }
    else:
        payload = {
            'action': 'invalid_format',
            'chat_id': chat_id,
            'message': 'Send: YouTube_URL Number\nExample:\nhttps://youtu.be/abc123 5'
        }

    # Send payload to n8n webhook
    try:
        response = requests.post(N8N_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        logger.info(f"Sent to n8n: {payload}")
    except requests.RequestException as e:
        logger.error(f"Error sending to n8n: {e}")
        await update.message.reply_text("Error processing your request. Please try again later.")
        return

    # Respond to user based on payload
    if payload['action'] == 'process':
        await update.message.reply_text(f"Processing YouTube URL: {url_part} to generate {number} shorts.")
    else:
        await update.message.reply_text(payload['message'])

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
