import logging
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Telegram Bot Token
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
# n8n Webhook
N8N_WEBHOOK_URL = "https://your-n8n-host.com/webhook/reel-generator"

logging.basicConfig(level=logging.INFO)

# Message handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    user_id = update.message.chat_id

    # Send the idea to n8n webhook
    try:
        response = requests.post(N8N_WEBHOOK_URL, json={
            "idea": user_input,
            "telegram_user": user_id
        })

        if response.status_code == 200:
            data = response.json()
            await update.message.reply_text(data.get("script", "No script generated."))
        else:
            await update.message.reply_text("Something went wrong with the generator.")
    except Exception as e:
        await update.message.reply_text("Error: " + str(e))

# App runner
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
app.run_polling()
