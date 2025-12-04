import os
import asyncio
import requests
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# Flask app
app = Flask(__name__)

# ENV variables (set in Render Dashboard)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WHATSAPP_API_TOKEN = os.environ.get("WHATSAPP_API_TOKEN")

bot = Bot(TELEGRAM_BOT_TOKEN)

WHATSAPP_SEND_TEXT_URL = "https://app.agribee.in/api/v1/agribee/messages/send"
WHATSAPP_SEND_MEDIA_URL = "https://app.agribee.in/api/v1/agribee/messages/media"


# ---------------------------------------------------------------------
# HOME
# ---------------------------------------------------------------------
@app.route("/")
def home():
    return "OK - Telegram/WhatsApp Bridge Running", 200


# ---------------------------------------------------------------------
# WHATSAPP WEBHOOK → TELEGRAM
# ---------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
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

        # Text message
        if msg.get("type") == "text":
            text = msg["text"]["body"]

            message = f"📩 *WhatsApp message*\nFrom: {name} ({wa_number})\n\n{text}"

            asyncio.run(bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode="Markdown"
            ))

    except Exception as e:
        print("Webhook Error:", e)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------
# TELEGRAM WEBHOOK HANDLER → REPLY TO WHATSAPP
# ---------------------------------------------------------------------
async def telegram_webhook_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return

    if update.message.reply_to_message is None:
        await update.message.reply_text("Reply to a WhatsApp message to send back.")
        return

    original_text = update.message.reply_to_message.text

    import re
    match = re.search(r"\((\d{10,15})\)", original_text)
    if not match:
        await update.message.reply_text("Could not detect WhatsApp number.")
        return

    wa_number = match.group(1)

    # Sending text to WhatsApp
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
        await update.message.reply_text("✔ WhatsApp reply sent")
    else:
        await update.message.reply_text("❌ Failed to send WhatsApp message")


# ---------------------------------------------------------------------
# FLASK ROUTE → TELEGRAM WEBHOOK ENTRY
# ---------------------------------------------------------------------
@app.route(f"/telegram-webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        data = request.json
        update = Update.de_json(data, bot)
        application = app.config["tg_app"]
        asyncio.run(application.process_update(update))
    except Exception as e:
        print("Telegram Webhook Error:", e)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------
# SET TELEGRAM WEBHOOK
# ---------------------------------------------------------------------
async def setup_webhook():
    url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/telegram-webhook/{TELEGRAM_BOT_TOKEN}"

    await bot.delete_webhook()
    await bot.set_webhook(url=url)

    print("Telegram Webhook Set To:", url)


# ---------------------------------------------------------------------
# START BOT WITH WEBHOOK MODE
# ---------------------------------------------------------------------
def start_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_webhook_handler))

    app.config["tg_app"] = application

    asyncio.run(setup_webhook())


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    start_telegram()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
