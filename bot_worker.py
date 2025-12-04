# bot_worker.py
import os
import time
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
WHATSAPP_API_TOKEN  = os.environ.get("WHATSAPP_API_TOKEN")
WHATSAPP_SEND_TEXT_URL = "https://app.agribee.in/api/v1/agribee/messages/send"
WHATSAPP_SEND_MEDIA_URL = "https://app.agribee.in/api/v1/agribee/messages/media"

# This should match the mapping used by app.py.
# If you want persistence, replace with a DB (sqlite/mysql).
thread_map = {}  # NOTE: For render, both processes are separate; to persist mapping across processes use a DB or Redis.

# If you used in-memory mapping in app.py, it won't be visible here.
# Recommended: Use a small sqlite DB or Redis. For simplicity we'll expect replies to include the WA number in the message or use Telegram reply_to_message caption parsing.

def extract_whatsapp_from_reply(update: Update):
    """
    Strategy: if reply_to_message caption contains the phone, parse it.
    Our app.py sends captions like: 'From: name (9198xxxxxxx)'
    """
    if not update.message.reply_to_message:
        return None
    replied = update.message.reply_to_message
    text = replied.text or replied.caption or ""
    # simple parse to find number between parentheses
    import re
    m = re.search(r"\((\d{10,15})\)", text)
    if m:
        return m.group(1)
    return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only handle replies
    if not update.message.reply_to_message:
        return

    wa_number = extract_whatsapp_from_reply(update)
    if not wa_number:
        await update.message.reply_text("Could not find WhatsApp number in the replied message. Make sure you reply to the original forwarded message.")
        return

    # If it's a text reply:
    if update.message.text:
        payload = {
            "to": wa_number,
            "message": update.message.text
        }
        headers = {"Authorization": f"Bearer {WHATSAPP_API_TOKEN}", "Content-Type": "application/json"}
        try:
            resp = requests.post(WHATSAPP_SEND_TEXT_URL, json=payload, headers=headers, timeout=20)
            if resp.ok:
                await update.message.reply_text("✅ Sent to WhatsApp.")
            else:
                await update.message.reply_text(f"❌ Failed to send. status:{resp.status_code} body:{resp.text}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    # If reply contains photo/document, send media back (basic)
    if update.message.photo or update.message.document:
        # take the first file
        file_obj = None
        file_id = None
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id

        if file_id:
            file = await context.bot.get_file(file_id)
            file_url = file.file_path  # telegram file URL (temporary). We can stream it and send to Agribee media endpoint.
            # download file bytes
            r = requests.get(file_url, stream=True, timeout=30)
            r.raise_for_status()
            files = {"file": ( "upload", r.content )}
            headers = {"Authorization": f"Bearer {WHATSAPP_API_TOKEN}"}
            data = {"to": wa_number}
            try:
                resp = requests.post(WHATSAPP_SEND_MEDIA_URL, files=files, data=data, headers=headers, timeout=60)
                if resp.ok:
                    await update.message.reply_text("✅ Media sent to WhatsApp.")
                else:
                    await update.message.reply_text(f"❌ Failed media send. {resp.status_code} {resp.text}")
            except Exception as e:
                await update.message.reply_text(f"❌ Error sending media: {e}")

async def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    print("Telegram worker started (polling)...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
