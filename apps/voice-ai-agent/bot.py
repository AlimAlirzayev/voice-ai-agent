"""Telegram entry point for the demo.

Send a voice note and the bot answers with a voice note; send text and it answers
with text. It is a thin client: every request goes to the FastAPI backend, so the
LangGraph agent, the memory and the LangSmith traces all live in one place.

Run the backend first, then:  uv run python bot.py
"""

import asyncio
import logging
import sys

import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.core.config import settings

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("voice-bot")

TIMEOUT = httpx.Timeout(180.0)
CAPTION_LIMIT = 1024

WELCOME = (
    "Salam! Mən LangGraph əsaslı səsli köməkçiyəm.\n\n"
    "🎙 Səsli mesaj göndər — səslə cavab verim.\n"
    "⌨️ Yaz — yazı ilə cavab verim.\n"
    "🧠 Söhbəti yadda saxlayıram: adını de, sonra soruş.\n"
    "/reset — yaddaşı təmizlə."
)


def thread_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """One memory thread per chat. /reset moves the chat to a fresh thread."""
    generation = context.chat_data.get("generation", 0)
    return f"tg-{update.effective_chat.id}-{generation}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["generation"] = context.chat_data.get("generation", 0) + 1
    await update.message.reply_text("Yaddaş təmizləndi. Təzə söhbətə başlayırıq.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        response = await context.bot_data["http"].post(
            f"{settings.BACKEND_URL}/chat",
            json={"message": update.message.text, "thread_id": thread_id(update, context)},
            headers={"X-Agent-Channel": "telegram"},
        )
        response.raise_for_status()
        await update.message.reply_text(response.json()["reply"])
    except Exception as exc:  # noqa: BLE001 - always answer the user
        log.exception("text turn failed")
        await update.message.reply_text(f"Backend cavab vermədi: {_short(exc)}")


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
    message = update.message
    source = message.voice or message.audio

    try:
        remote = await source.get_file()
        audio = bytes(await remote.download_as_bytearray())

        response = await context.bot_data["http"].post(
            f"{settings.BACKEND_URL}/voice",
            files={"file": ("voice.ogg", audio, "audio/ogg")},
            data={"thread_id": thread_id(update, context)},
            headers={"X-Agent-Channel": "telegram"},
        )
        response.raise_for_status()
        payload = response.json()

        import base64

        caption = f"🎙 {payload['transcript']}\n\n💬 {payload['reply']}"
        await message.reply_voice(
            voice=base64.b64decode(payload["audio_base64"]),
            caption=caption[:CAPTION_LIMIT],
        )
    except Exception as exc:  # noqa: BLE001 - always answer the user
        log.exception("voice turn failed")
        await message.reply_text(f"Səsi işləyə bilmədim: {_short(exc)}")


def _short(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return text[:200]


async def _open_http(application: Application) -> None:
    application.bot_data["http"] = httpx.AsyncClient(timeout=TIMEOUT)


async def _close_http(application: Application) -> None:
    await application.bot_data["http"].aclose()


def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN is not set in .env - get one from @BotFather.")

    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(_open_http)
        .post_shutdown(_close_http)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Bot is polling. Backend: %s", settings.BACKEND_URL)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
