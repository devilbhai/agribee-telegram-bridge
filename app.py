import os
import io
import threading
import time
import requests
from flask import Flask, request, jsonify
from telegram import Bot, Update, InputFile
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackContext

# Flask Webhook App
app = Flask(__name__)

# ENV Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WHATSAPP_API_TOKEN = os.environ.get("WHATSAPP_API_TOKEN")

# WhatsApp API Endpoints
WHATSAPP_SEND_TEXT_URL = "https://app.agribee.in/api/v1/agribee/messages/send"
WHATSAPP_SEND_MEDIA_URL = "https://app.agribee.in/api/v1/agribee/messages/media"

bot = Bot(TELEGRAM_BOT_TOKEN)


# -------------------------
# WHATSAPP WEBHOOK HANDLER
# -------------------------

@app.route("/")
def home():
    return "OK"

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.json
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        message = change["messages"][0]
        contact = change["contacts"][0]

        wa_number = contact["wa_id"]
        name = contact["profile"]["name"]

        # Handle Text Message
        if message["type"] == "text":
            text = message["text"]["body"]
            caption = f"📩 WhatsApp message\nFrom: {name} ({wa_number})\n\n{text}"

            sent = bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=caption
            )
            return jsonify({"ok": True})

        # Other message types can be added later

    except Exception as e:
        print("Webhook Error:", e)

    return jsonify({"ok": True})


# -------------------------
# TELEGRAM REPLY HANDLER
# -------------------------

async def telegram_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    # extract WhatsApp number from Telegram forwarded message
    text = update.message.reply_to_message.text
    import re
    match = re.search(r"\((\d{10,15})\)", text)
    if not match:
        await update.message.reply_text("Could not detect WhatsApp number.")
        return

    wa_number = match.group(1)

    # TEXT REPLY
    if update.message.text:
        payload = {
            "to": wa_number,
            "message": update.message.text
        }
        headers = {"Authorization": f"Bearer {WHATSAPP_API_TOKEN}"}

        r = requests.post(WHATSAPP_SEND_TEXT_URL, json=payload, headers=headers)
        if r.ok:
            await update.message.reply_text("✅ Sent to WhatsApp")
        else:
            await update.message.reply_text("❌ Failed to send")
        return


# -------------------------
# RUN TELEGRAM POLLING IN THREAD
# -------------------------

def start_telegram_bot():
    print("Starting Telegram Polling...")
    appTG = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    appTG.add_handler(MessageHandler(filters.ALL, telegram_reply))
    appTG.run_polling()


# -------------------------
# START BOTH SYSTEMS
# -------------------------

if __name__ == "__main__":
    # Start Telegram bot in separate thread
    t = threading.Thread(target=start_telegram_bot)
    t.daemon = True
    t.start()

    # Start Flask for webhook
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
