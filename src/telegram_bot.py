from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot


class TelegramNotifier:
    """Simple helper for sending Telegram messages."""

    def __init__(self, token: str, chat_id: int, logger: Optional[logging.Logger] = None) -> None:
        self._bot = Bot(token)
        self._chat_id = chat_id
        self._logger = logger or logging.getLogger(__name__)

    async def send_message(self, text: str) -> None:
        """Send a plain text message."""
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=text)
        except Exception as exc:  # pragma: no cover - network errors
            self._logger.error(f"Failed to send telegram message: {exc}")

    async def close(self) -> None:
        await self._bot.session.close()

