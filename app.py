# app.py
import os
import io
import requests
from flask import Flask, request, jsonify
from telegram import Bot
from telegram import InputFile

app = Flask(__name__)

# CONFIG (from env)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")   # your group or admin chat id
WHATSAPP_API_TOKEN  = os.environ.get("WHATSAPP_API_TOKEN")

# Agribee endpoints (fixed)
WHATSAPP_BASE = "https://app.agribee.in/api/v1/agribee"
WHATSAPP_SEND_TEXT_URL = f"{WHATSAPP_BASE}/messages/send"
WHATSAPP_SEND_MEDIA_URL = f"{WHATSAPP_BASE}/messages/media"

bot = Bot(TELEGRAM_BOT_TOKEN)

# In-memory map (persist with DB if needed)
# mapping: telegram_thread_message_id -> whatsapp_number
thread_map = {}

def save_mapping(telegram_msg_id: int, whatsapp_number: str):
    thread_map[telegram_msg_id] = whatsapp_number

def get_whatsapp_for_telegram_msg(telegram_msg_id: int):
    return thread_map.get(telegram_msg_id)

@app.route("/", methods=["GET"])
def index():
    return "OK"

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Receives WhatsApp webhook from Agribee panel.
    Expects the standard agribee payload with messages and contacts.
    """
    payload = request.json or {}
    try:
        # Navigate to first message and contact (adjust if payload structure differs)
        entry = payload.get("entry", [])
        if not entry:
            return jsonify({"ok": True})
        changes = entry[0].get("changes", [])
        if not changes:
            return jsonify({"ok": True})
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        if not messages:
            return jsonify({"ok": True})

        msg = messages[0]
        contact = contacts[0] if contacts else {}
        wa_number = contact.get("wa_id") or msg.get("from")
        name = contact.get("profile", {}).get("name", wa_number)

        # Handle text message
        if msg.get("type") == "text":
            text = msg["text"].get("body", "")
            caption = f"📩 *WhatsApp message*\nFrom: {name} ({wa_number})\nMessage ID: {msg.get('id')}\n\n{text}"
            sent = bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode="Markdown")
            # save mapping so replies to this message go back to wa_number
            save_mapping(sent.message_id, wa_number)
            return jsonify({"ok": True})

        # Handle image / document / video (basic)
        if msg.get("type") in ("image", "document", "video", "audio"):
            # Agribee payload may include media object with 'id' or 'url'. Try to get direct link.
            media = msg.get(msg.get("type"), {})
            media_url = media.get("url") or media.get("link") or media.get("id")
            caption_text = f"📩 *WhatsApp {msg.get('type').capitalize()}*\nFrom: {name} ({wa_number})"
            # If we have a URL, download it and forward to Telegram
            if media_url and media_url.startswith("http"):
                try:
                    r = requests.get(media_url, stream=True, timeout=30)
                    r.raise_for_status()
                    bio = io.BytesIO(r.content)
                    bio.name = "file"
                    if msg.get("type") == "image":
                        sent = bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=InputFile(bio), caption=caption_text, parse_mode="Markdown")
                    else:
                        sent = bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=InputFile(bio), caption=caption_text, parse_mode="Markdown")
                    save_mapping(sent.message_id, wa_number)
                    return jsonify({"ok": True})
                except Exception as e:
                    # fallback: send text with media url
                    sent = bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"{caption_text}\n\nMedia URL: {media_url}")
                    save_mapping(sent.message_id, wa_number)
                    return jsonify({"ok": True})
            else:
                # no direct url — just notify in telegram (admin can ask for media)
                sent = bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"{caption_text}\n\n(Media not available in webhook payload)")
                save_mapping(sent.message_id, wa_number)
                return jsonify({"ok": True})

    except Exception as e:
        print("Webhook error:", e)

    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
