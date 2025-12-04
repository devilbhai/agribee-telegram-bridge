import os
import requests
from flask import Flask, request, jsonify
from telegram import Bot

app = Flask(__name__)

# ENV Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
WHATSAPP_API_TOKEN = os.environ.get("WHATSAPP_API_TOKEN")

bot = Bot(TELEGRAM_BOT_TOKEN)

# WhatsApp APIs
WHATSAPP_SEND_TEXT_URL  = "https://app.agribee.in/api/v1/agribee/messages/send"
WHATSAPP_SEND_MEDIA_URL = "https://app.agribee.in/api/v1/agribee/messages/media"

# -----------------------------
# HOME
# -----------------------------
@app.route("/")
def home():
    return "Bot Running", 200


# -----------------------------
# WHATSAPP → TELEGRAM
# -----------------------------
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    try:
        data = request.json or {}
        entry = data.get("entry", [])[0]
        value = entry.get("changes", [])[0].get("value", {})

        msgs     = value.get("messages", [])
        contacts = value.get("contacts", [])

        if not msgs:
            return jsonify({"status": "ok"})

        msg     = msgs[0]
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
        print("WhatsApp Webhook Error:", e)

    return jsonify({"status": "ok"})


# -----------------------------
# TELEGRAM → WHATSAPP (Webhook)
# -----------------------------
@app.route(f"/telegram-webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.json

    try:
        message = data.get("message", {})
        text    = message.get("text", "")
        reply   = message.get("reply_to_message", {})
        chat_id = message.get("chat", {}).get("id")

        # Only accept replies to forwarded WhatsApp messages
        if reply:
            original = reply.get("text", "")
            import re
            match = re.search(r"\((\d{10,15})\)", original)
            if not match:
                return jsonify({"ok": True})

            wa_number = match.group(1)

            payload = {
                "to": wa_number,
                "message": text
            }

            headers = {
                "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
                "Content-Type": "application/json"
            }

            requests.post(WHATSAPP_SEND_TEXT_URL, json=payload, headers=headers)

            bot.send_message(chat_id, "✅ Sent to WhatsApp")

    except Exception as e:
        print("Telegram Webhook Error:", e)

    return jsonify({"ok": True})


# -----------------------------
# Set Telegram Webhook on Startup
# -----------------------------
def set_telegram_webhook():
    url = f"https://agribee-telegram-bridge.onrender.com/telegram-webhook/{TELEGRAM_BOT_TOKEN}"
    bot.delete_webhook()
    bot.set_webhook(url=url)
    print("Telegram Webhook Set:", url)


# -----------------------------
# RUN FLASK
# -----------------------------
if __name__ == "__main__":
    set_telegram_webhook()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
