"""The Divan bot answers only the allowed Telegram users."""
import asyncio
from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

import bot
from app.core.config import settings


def _update(uid):
    replies = []

    async def reply_text(t):
        replies.append(t)

    return SimpleNamespace(effective_user=SimpleNamespace(id=uid),
                           effective_message=SimpleNamespace(reply_text=reply_text)), replies


def test_owner_passes(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USERS", "111, 222")
    upd, replies = _update(222)
    asyncio.run(bot._gate(upd, None))
    assert replies == []


def test_stranger_is_stopped(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USERS", "111")
    upd, replies = _update(999)
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot._gate(upd, None))
    assert replies and "bağlı" in replies[0]
