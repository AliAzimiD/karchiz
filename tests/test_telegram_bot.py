from unittest.mock import AsyncMock

import pytest

from src.telegram_bot import TelegramNotifier


@pytest.mark.asyncio
async def test_send_message(monkeypatch):
    send_mock = AsyncMock()
    bot_mock = AsyncMock(send_message=send_mock, session=AsyncMock(close=AsyncMock()))

    monkeypatch.setattr("src.telegram_bot.Bot", lambda token: bot_mock)

    notifier = TelegramNotifier("token", 123)
    await notifier.send_message("hello")
    await notifier.close()

    send_mock.assert_called_with(chat_id=123, text="hello")

