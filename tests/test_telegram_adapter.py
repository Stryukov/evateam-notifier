"""Проверки Telegram-адаптера, не требующие сети."""

from evateam_bot.transports.telegram.adapter import (
    CAPTION_LIMIT,
    _clip_caption,
    _parse_command,
)


def test_parse_command_strips_slash_bot_name_and_case():
    assert _parse_command("/summary") == ("summary", "")
    assert _parse_command("/Summary") == ("summary", "")
    assert _parse_command("/summary@evateam_bot") == ("summary", "")
    assert _parse_command("/summary  за неделю ") == ("summary", "за неделю")


def test_clip_caption_respects_telegram_limit():
    assert _clip_caption("коротко") == "коротко"
    long = "я" * (CAPTION_LIMIT + 50)
    clipped = _clip_caption(long)
    assert len(clipped) == CAPTION_LIMIT
    assert clipped.endswith("…")


def test_command_route_registered_between_start_and_text():
    """aiogram проверяет хендлеры по порядку: команда обязана опередить F.text,
    иначе «/summary» уйдёт в поиск сотрудника."""
    from evateam_bot.transports.telegram.adapter import TelegramTransport

    transport = TelegramTransport("123:FAKE")
    handlers = transport._dp.message.handlers
    names = [h.callback.__name__ for h in handlers]
    assert names.index("_on_command") < names.index("_on_text")
    assert names.index("_on_start") < names.index("_on_command")


def test_transport_declares_document_support():
    from evateam_bot.transports.telegram.adapter import TelegramTransport

    assert TelegramTransport.supports_documents is True
