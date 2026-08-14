"""Telegram entry point for the Divan council.

Send a voice note and the bot answers with voice (one clip per legendary
advisor who actually spoke, in their own voice); send text and it answers
with text, naming which advisor(s) spoke. When Koroğlu's bold advice needs a
human sign-off, the bot shows it with Təsdiqlə/İmtina buttons and waits - it
never invents an answer on the council's behalf.

It is a thin client: every request goes to the FastAPI backend, so the
LangGraph agent, the memory and the LangSmith traces all live in one place.

Run the backend first, then:  uv run python bot.py
"""

import base64
import logging
import sys

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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
    "Salam! Mən Divan-am - əfsanəvi məsləhətçilər şurası.\n\n"
    "Şurada altı üzv var: Molla Nəsrəddin, Koroğlu, Simurğ, Nəsimi, Dədə Qorqud "
    "və Nizami Gəncəvi. Sualını sor, ən uyğun üzv(lər) cavab versin.\n\n"
    "🎙 Səsli mesaj göndər — hər müşavir öz səsi ilə cavab versin.\n"
    "⌨️ Yaz — yazı ilə cavab verim.\n"
    "🧠 Söhbəti yadda saxlayıram: adını de, sonra soruş.\n"
    "⚖️ Koroğlu cəsarətli bir tövsiyə verəndə, təsdiqini gözləyəcəm.\n"
    "👍👎 Cavabı qiymətləndir, ✍️ ilə düzəliş yaza bilərsən.\n"
    "/reset — yaddaşı təmizlə."
)


def thread_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """One memory thread per chat. /reset moves the chat to a fresh thread."""
    generation = context.chat_data.get("generation", 0)
    return f"tg-{update.effective_chat.id}-{generation}"


def _approval_keyboard(tid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Təsdiqlə", callback_data=f"da:a:{tid}"),
                InlineKeyboardButton("🚫 İmtina", callback_data=f"da:r:{tid}"),
            ]
        ]
    )


def _feedback_keyboard(turn_id: str) -> InlineKeyboardMarkup | None:
    if not turn_id:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👍", callback_data=f"fb:u:{turn_id}"),
                InlineKeyboardButton("👎", callback_data=f"fb:d:{turn_id}"),
                InlineKeyboardButton("✍️ Düzəliş", callback_data=f"fb:c:{turn_id}"),
            ]
        ]
    )


def _speaker_line(consulted: list[str] | None) -> str:
    names = {
        "nesreddin": "Molla Nəsrəddin",
        "koroglu": "Koroğlu",
        "simurg": "Simurğ",
        "nesimi": "Nəsimi",
        "dedeqorqud": "Dədə Qorqud",
        "nizami": "Nizami Gəncəvi",
    }
    consulted = consulted or []
    if not consulted:
        return ""
    return "🏛 " + ", ".join(names.get(key, key) for key in consulted) + "\n\n"


async def _send_narration(message, narration: list[str] | None) -> None:
    """The Divanbəyi's own brief commentary, sent as its own message before
    the actual answer - "here's what LangGraph is doing" in-character,
    matching the same field the /voice segments open with."""
    if not narration:
        return
    await message.reply_text("🏛 Divanbəyi: " + " ".join(narration))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["generation"] = context.chat_data.get("generation", 0) + 1
    context.chat_data.pop("pending_modality", None)
    await update.message.reply_text("Yaddaş təmizləndi. Təzə söhbətə başlayırıq.")


async def _submit_feedback(context: ContextTypes.DEFAULT_TYPE, *, turn_id: str, tid: str, kind: str, text: str | None = None) -> None:
    await context.bot_data["http"].post(
        f"{settings.BACKEND_URL}/feedback",
        json={"turn_id": turn_id, "thread_id": tid, "kind": kind, "text": text},
        headers={"X-Agent-Channel": "telegram"},
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = thread_id(update, context)

    awaiting = context.chat_data.pop("awaiting_correction", None)
    if awaiting:
        try:
            await _submit_feedback(context, turn_id=awaiting, tid=tid, kind="correction", text=update.message.text)
            await update.message.reply_text("Düzəliş qeyd edildi, təşəkkürlər! 🙏")
        except Exception as exc:  # noqa: BLE001 - always answer the user
            log.exception("correction submit failed")
            await update.message.reply_text(f"Düzəlişi göndərə bilmədim: {_short(exc)}")
        return

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        response = await context.bot_data["http"].post(
            f"{settings.BACKEND_URL}/chat",
            json={"message": update.message.text, "thread_id": tid},
            headers={"X-Agent-Channel": "telegram"},
        )
        response.raise_for_status()
        payload = response.json()

        await _send_narration(update.message, payload.get("narration"))

        if payload["status"] == "pending_approval":
            context.chat_data["pending_modality"] = "text"
            approval = payload["approval"]
            text = (
                f"🏛 {approval['advisor']} belə tövsiyə edir:\n\n"
                f"“{approval['draft']}”\n\n{approval['question']}"
            )
            await update.message.reply_text(text, reply_markup=_approval_keyboard(tid))
            return

        text = _speaker_line(payload.get("consulted")) + payload["reply"]
        await update.message.reply_text(text, reply_markup=_feedback_keyboard(payload.get("turn_id", "")))
    except Exception as exc:  # noqa: BLE001 - always answer the user
        log.exception("text turn failed")
        await update.message.reply_text(f"Backend cavab vermədi: {_short(exc)}")


async def _send_voice_segments(message, segments: list[dict], keyboard=None) -> None:
    """One voice note per segment, captioned with who is speaking. The
    approval keyboard (if any) attaches to the last note."""
    for i, segment in enumerate(segments):
        caption = f"🏛 {segment['name']}" if segment.get("name") else None
        is_last = i == len(segments) - 1
        await message.reply_voice(
            voice=base64.b64decode(segment["audio_base64"]),
            caption=(caption or "")[:CAPTION_LIMIT] or None,
            reply_markup=keyboard if is_last else None,
        )


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
    message = update.message
    source = message.voice or message.audio
    tid = thread_id(update, context)

    try:
        remote = await source.get_file()
        audio = bytes(await remote.download_as_bytearray())

        response = await context.bot_data["http"].post(
            f"{settings.BACKEND_URL}/voice",
            files={"file": ("voice.ogg", audio, "audio/ogg")},
            data={"thread_id": tid},
            headers={"X-Agent-Channel": "telegram"},
        )
        response.raise_for_status()
        payload = response.json()

        transcript_note = f"🎙 {payload['transcript']}" if payload.get("transcript") else None
        if transcript_note:
            await message.reply_text(transcript_note[:CAPTION_LIMIT])

        pending = payload.get("status") == "pending_approval"
        context.chat_data["pending_modality"] = "voice" if pending else context.chat_data.get(
            "pending_modality"
        )
        if pending:
            keyboard = _approval_keyboard(tid)
        else:
            keyboard = _feedback_keyboard(payload.get("turn_id", ""))
        await _send_voice_segments(message, payload.get("segments", []), keyboard)
    except Exception as exc:  # noqa: BLE001 - always answer the user
        log.exception("voice turn failed")
        await message.reply_text(f"Səsi işləyə bilmədim: {_short(exc)}")


async def on_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        _, code, tid = query.data.split(":", 2)
    except ValueError:
        return
    decision = {"a": "approve", "r": "reject"}.get(code)
    if decision is None:
        return

    await query.edit_message_reply_markup(reply_markup=None)
    modality = context.chat_data.get("pending_modality", "text")

    try:
        http = context.bot_data["http"]
        if modality == "voice":
            response = await http.post(
                f"{settings.BACKEND_URL}/voice/resume",
                data={"thread_id": tid, "decision": decision},
                headers={"X-Agent-Channel": "telegram"},
            )
            response.raise_for_status()
            payload = response.json()
            await _send_voice_segments(
                query.message, payload.get("segments", []), _feedback_keyboard(payload.get("turn_id", ""))
            )
        else:
            response = await http.post(
                f"{settings.BACKEND_URL}/chat/resume",
                json={"thread_id": tid, "decision": decision},
                headers={"X-Agent-Channel": "telegram"},
            )
            response.raise_for_status()
            payload = response.json()
            await query.message.reply_text(
                payload["reply"], reply_markup=_feedback_keyboard(payload.get("turn_id", ""))
            )
    except Exception as exc:  # noqa: BLE001 - always answer the user
        log.exception("resume failed")
        await query.message.reply_text(f"Qərarı tətbiq edə bilmədim: {_short(exc)}")
    finally:
        context.chat_data.pop("pending_modality", None)


async def on_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        _, code, turn_id = query.data.split(":", 2)
    except ValueError:
        await query.answer()
        return

    tid = thread_id(update, context)

    if code == "c":
        await query.answer()
        context.chat_data["awaiting_correction"] = turn_id
        await query.message.reply_text("Düzgün cavab necə olmalı idi? Bu mesaja cavab olaraq yaz:")
        return

    kind = "up" if code == "u" else "down"
    await query.answer("Təşəkkürlər! 🙏" if kind == "up" else "Qeyd etdim, təşəkkürlər.")
    try:
        await _submit_feedback(context, turn_id=turn_id, tid=tid, kind=kind)
    except Exception:  # noqa: BLE001 - the user already got an ack above
        log.exception("feedback submit failed")
    await query.edit_message_reply_markup(reply_markup=None)


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
    application.add_handler(CallbackQueryHandler(on_approval, pattern=r"^da:[ar]:"))
    application.add_handler(CallbackQueryHandler(on_feedback, pattern=r"^fb:[udc]:"))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Bot is polling. Backend: %s", settings.BACKEND_URL)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
