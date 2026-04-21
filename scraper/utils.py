"""
Вспомогательные функции парсера.

Изолированы от основного класса, чтобы их можно было
тестировать независимо и переиспользовать в других модулях.
"""

from datetime import date, datetime, timezone


def ensure_utc(dt: date | datetime | None) -> datetime | None:
    """
    Привести входящую дату к timezone-aware datetime в UTC.

    Telethon возвращает даты сообщений с tzinfo=UTC, поэтому
    для корректного сравнения стоп-дата тоже должна быть UTC.

    Поддерживаемые входные типы:

    - ``None``             → возвращает None
    - ``date``             → преобразует в начало дня UTC
    - ``datetime`` без tz  → считает UTC, добавляет tzinfo
    - ``datetime`` с tz    → конвертирует в UTC

    :param dt: Дата или дата-время для нормализации.
    :return:   timezone-aware datetime в UTC или None.

    Примеры::

        ensure_utc(date(2026, 1, 1))
        # datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

        ensure_utc(datetime(2026, 1, 1, 12, 0))
        # datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    """
    if dt is None:
        return None

    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)