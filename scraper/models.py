"""
Доменные модели парсера.

Вынесены отдельно, чтобы их можно было импортировать
в любой части проекта (analyze, report) без зависимости
от Telethon или логики парсинга.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Post:
    """
    Один пост из Telegram-канала.

    Используется как единица передачи данных между слоями:
    scraper → analyze → report.
    """

    channel: str
    """@username канала-источника."""

    date: datetime
    """Дата публикации в UTC."""

    text: str
    """Текст сообщения или подпись к медиафайлу."""

    message_id: int
    """ID сообщения внутри канала — используется для дедупликации."""

    views: Optional[int] = None
    """Количество просмотров. None, если Telegram не вернул значение."""

    def to_plain_text(self) -> str:
        """
        Сформировать строку для передачи в AI-агент.

        Формат: заголовок с источником и датой, затем текст поста.
        Такой формат хорошо воспринимается LLM.

        :return: Строка вида ``[@channel | 2026-01-15]\\nтекст``.
        """
        return f"[{self.channel} | {self.date.strftime('%Y-%m-%d')}]\n{self.text}"


@dataclass
class ScrapeResult:
    """
    Результат парсинга одного канала.

    Содержит либо список постов (при успехе), либо описание ошибки.
    Не бросает исключений — ошибки хранятся как данные, чтобы
    один недоступный канал не прерывал обработку остальных.
    """

    channel: str
    """@username канала."""

    posts: list[Post] = field(default_factory=list)
    """Собранные посты. Пустой список при ошибке."""

    error: Optional[str] = None
    """Описание ошибки или None при успехе."""

    @property
    def success(self) -> bool:
        """True, если канал обработан без ошибок."""
        return self.error is None