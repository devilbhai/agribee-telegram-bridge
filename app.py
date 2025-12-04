import os
import threading
import requests
from flask import Flask, request, jsonify
from telegram import Bot
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
WHATSAPP_API_TOKEN = os.environ.get("WHATSAPP_API_TOKEN")

bot = Bot(TELEGRAM_BOT_TOKEN)

WHATSAPP_SEND_TEXT_URL  = "https://app.agribee.in/api/v1/agribee/messages/send"
WHATSAPP_SEND_MEDIA_URL = "https://app.agribee.in/api/v1/agribee/messages/media"


@app.route("/")
def home():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json or {}
        entry = data.get("entry", [])[0]
        value = entry.get("changes", [])[0].get("value", {})

        msgs = value.get("messages", [])
        contacts = value.get("contacts", [])

        if not msgs:
            return jsonify({"ok": True})

        msg = msgs[0]
        contact = contacts[0] if contacts else {}
        wa_number = contact.get("wa_id") or msg.get("from")
        name = contact.get("profile", {}).get("name", wa_number)

        # TEXT MESSAGE
        if msg.get("type") == "text":
            text = msg["text"]["body"]
            message = f"📩 *WhatsApp message*\nFrom: {name} ({wa_number})\n\n{text}"

            bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode="Markdown"
            )

    except Exception as e:
        print("Webhook Error:", e)

    return jsonify({"ok": True})


# ------------------------
# TELEGRAM BOT (Polling)
# ------------------------

async def reply_handler(update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message.reply_to_message:
        return

    original_msg = update.message.reply_to_message.text
    import re

    match = re.search(r"\((\d{10,15})\)", original_msg)
    if not match:
        await update.message.reply_text("Could not extract WhatsApp number.")
        return

    wa_number = match.group(1)

    # TEXT
    if update.message.text:
        payload = {
            "to": wa_number,
            "message": update.message.text
        }
        headers = {
            "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
            "Content-Type": "application/json"
        }

        r = requests.post(WHATSAPP_SEND_TEXT_URL, json=payload, headers=headers)
        if r.ok:
            await update.message.reply_text("✅ Sent to WhatsApp")
        else:
            await update.message.reply_text("❌ Failed to send")


def start_polling():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), reply_handler)
    )

    print("Telegram polling started...")
    application.run_polling()


# ------------------------
# RUN BOTH SYSTEMS
# ------------------------

if __name__ == "__main__":
    # Telegram polling thread
    t = threading.Thread(target=start_polling)
    t.daemon = True
    t.start()

    # Flask webhook
    port = int(os.environ.get("PORT", 5000))
    print("Flask server running...")
    app.run(host="0.0.0.0", port=port)
