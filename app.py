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
# WHATSAPP / GENERIC WEBHOOK → TELEGRAM (improved logging + debug)
# ---------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    try:
        raw = request.get_data(as_text=True)
        # log raw payload for debugging
        try:
            with open("webhook_received.log", "a", encoding="utf-8") as f:
                f.write("=== " + asyncio.get_event_loop().time().__str__() + " ===\n")
                f.write(raw + "\n\n")
        except Exception as log_exc:
            print("Log write error:", log_exc)

        data = request.json or {}

        # immediate debug ping to Telegram so you see webhook arrived (small summary)
        try:
            summary = None
            # If it's the "model update" shape you posted:
            if data.get("event") == "updated" and data.get("model"):
                contact = data.get("data", {}).get("attributes", {})
                phone = contact.get("phone")
                name = (contact.get("firstname") or "") + " " + (contact.get("lastname") or "")
                summary = f"Webhook: model update — {data.get('model')} — phone: {phone} name: {name}"
            else:
                # fallback: try WhatsApp style
                entry = data.get("entry", [None])[0]
                if entry:
                    try:
                        value = entry.get("changes", [])[0].get("value", {})
                        msgs = value.get("messages", [])
                        if msgs:
                            m = msgs[0]
                            phone = (value.get("contacts") or [{}])[0].get("wa_id") or m.get("from")
                            body = m.get("text", {}).get("body") if m.get("type") == "text" else str(m.get("type"))
                            summary = f"WhatsApp msg from {phone}: {body[:120]}"
                    except Exception:
                        summary = "Webhook: unknown entry shape"
                else:
                    summary = "Webhook: unknown shape"
            if summary:
                # send small debug to telegram
                try:
                    asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=summary))
                except Exception as send_exc:
                    print("Debug send to telegram failed:", send_exc)
        except Exception as e_debug:
            print("Debug summary error:", e_debug)

        # --- Now try to handle WhatsApp-style payload if present ---
        try:
            entry = data.get("entry", [])[0]
            value = entry.get("changes", [])[0].get("value", {})
            msgs = value.get("messages", [])
            contacts = value.get("contacts", [])
        except Exception:
            msgs = []
            contacts = []

        if msgs:
            msg = msgs[0]
            contact = contacts[0] if contacts else {}
            wa_number = contact.get("wa_id") or msg.get("from")
            name = contact.get("profile", {}).get("name", wa_number)
            if msg.get("type") == "text":
                text = msg["text"]["body"]
                message = f"📩 *WhatsApp message*\nFrom: {name} ({wa_number})\n\n{text}"
                try:
                    asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown"))
                except Exception as e_send:
                    print("Send to TG error:", e_send)
        else:
            # If not WhatsApp shape, check the model-update shape you pasted and forward minimal info
            try:
                if data.get("event") == "updated" and data.get("model"):
                    attrs = data.get("data", {}).get("attributes", {})
                    phone = attrs.get("phone")
                    firstname = attrs.get("firstname")
                    lastname = attrs.get("lastname")
                    text = f"Model update: {data.get('model')} id:{data.get('data',{}).get('id')}\nName: {firstname} {lastname}\nPhone: {phone}"
                    try:
                        asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text))
                    except Exception as e_send2:
                        print("Send to TG error (model):", e_send2)
            except Exception as handle_exc:
                print("Handle non-whatsapp shape error:", handle_exc)

    except Exception as e:
        print("Webhook Error (outer):", e)

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
