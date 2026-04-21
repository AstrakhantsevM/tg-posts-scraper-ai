"""
TelegramScraper — асинхронный клиент для парсинга постов из Telegram-каналов.

Ключевые особенности:
- Async context manager: соединение открывается и закрывается автоматически.
- Параллельный обход каналов через asyncio.gather.
- Двухуровневая защита от ошибок: канал-уровень и сообщение-уровень.
- Graceful FloodWait: при rate-limit ждёт и повторяет запрос.
- Возвращает плоский список строк, готовых для передачи в AI-агент.
"""

import asyncio
import logging
from datetime import datetime

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from scraper.models import Post, ScrapeResult
from scraper.utils import ensure_utc

logger = logging.getLogger(__name__)

class TelegramScraper:
    """
    Асинхронный парсер Telegram-каналов.

    Использование::

        async with TelegramScraper(
            session_path="sessions/main",
            api_id=12345,
            api_hash="abc...",
        ) as scraper:
            texts = await scraper.scrape_region(
                channels=["@channel1", "@channel2"],
                stop_date=datetime(2026, 1, 1),
                limit_per_channel=200,
            )
    """

    def __init__(self, session_path: str, api_id: int, api_hash: str) -> None:
        """
        :param session_path: Путь к файлу сессии Telethon (без расширения .session).
        :param api_id:       Telegram API ID из my.telegram.org.
        :param api_hash:     Telegram API Hash из my.telegram.org.
        """
        self._client = TelegramClient(session_path, api_id, api_hash)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "TelegramScraper":
        """Открыть соединение с Telegram при входе в блок ``async with``."""
        await self._client.start()
        logger.info("Соединение с Telegram установлено.")
        return self

    async def __aexit__(self, *_) -> None:
        """Закрыть соединение при выходе из блока — в том числе при исключении."""
        await self._client.disconnect()
        logger.info("Соединение с Telegram закрыто.")

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------
    async def scrape_region(
        self,
        channels: list[str],
        stop_date: datetime,
        limit_per_channel: int = 999,
    ) -> list[str]:
        """
        Параллельно обойти все каналы региона и вернуть тексты постов.

        Посты сортируются от новых к старым. Каналы с ошибками пропускаются —
        ошибка логируется, но не прерывает обработку остальных.

        :param channels:           Список @username каналов для парсинга.
        :param stop_date:          Граница: посты старше этой даты не собираются.
        :param limit_per_channel:  Максимальное число постов с одного канала.
        :return:                   Плоский список строк для ``agent.process(data=...)``.
        """
        stop_date = ensure_utc(stop_date)

        logger.info(
            "Парсинг %d каналов | стоп-дата: %s | лимит: %d/канал",
            len(channels),
            stop_date.date(),
            limit_per_channel,
        )

        results: list[ScrapeResult] = await asyncio.gather(*[
            self._scrape_channel(ch, stop_date, limit_per_channel)
            for ch in channels
        ])

        self._log_summary(results)

        all_posts = sorted(
            (post for r in results if r.success for post in r.posts),
            key=lambda p: p.date,
            reverse=True,
        )
        return [post.to_plain_text() for post in all_posts]

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    async def _scrape_channel(
            self,
            channel: str,
            stop_date: datetime,
            limit: int,
    ) -> ScrapeResult:
        """
        Собрать посты из одного канала.

        Итератор пересоздаётся при ошибке через offset_id — это решает
        проблему ``'_MessagesIter' object has no attribute 'request'``,
        которая возникает когда Telethon ломает итератор на альбомах
        или сервисных сообщениях. Вместо continue на сломанном итераторе
        стартуем новый итератор с last_id - 1, пропуская битое сообщение.
        """
        result = ScrapeResult(channel=channel)

        # offset_id = 0 означает "начать с самого последнего сообщения".
        # После ошибки выставляем last_id - 1, чтобы пропустить сломанное.
        offset_id = 0

        try:
            while True:
                iterator = self._client.iter_messages(channel, offset_id=offset_id)
                iterator_broken = False
                last_id = offset_id  # fallback на случай ошибки до первого сообщения

                while True:
                    try:
                        message = await iterator.__anext__()

                        last_id = message.id  # запоминаем для перезапуска при ошибке

                        if message.date < stop_date:
                            logger.debug("%s: достигнута стоп-дата.", channel)
                            return result

                        text = message.text or getattr(message, "caption", "") or ""
                        if not text.strip():
                            continue

                        result.posts.append(Post(
                            channel=channel,
                            date=message.date,
                            text=text.strip(),
                            message_id=message.id,
                            views=getattr(message, "views", None),
                        ))

                        if len(result.posts) >= limit:
                            logger.debug("%s: достигнут лимит %d постов.", channel, limit)
                            return result

                    except StopAsyncIteration:
                        return result

                    except AttributeError as e:
                        # Итератор Telethon сломался — пересоздаём с last_id - 1,
                        # тем самым пропуская проблемное сообщение.
                        logger.debug(
                            "%s: итератор сломан на ID %s (%s), пересоздаём.",
                            channel, last_id, e,
                        )
                        offset_id = max(last_id - 1, 0)
                        iterator_broken = True
                        break

                    except Exception as e:
                        # Ошибка конкретного сообщения — итератор жив, продолжаем.
                        logger.warning("%s: пропущено сообщение (%s).", channel, e)
                        continue

                if not iterator_broken:
                    break  # штатное завершение внешнего цикла

        except ChannelPrivateError:
            result.error = "Канал приватный или аккаунт не подписан"

        except (UsernameInvalidError, UsernameNotOccupiedError):
            result.error = "Канал не найден (неверный @username)"

        except FloodWaitError as e:
            logger.warning("FloodWait %ds для %s. Ожидаем...", e.seconds, channel)
            await asyncio.sleep(e.seconds)
            return await self._scrape_channel(channel, stop_date, limit)

        except Exception as e:
            result.error = f"Неожиданная ошибка: {e}"

        return result

    @staticmethod
    def _log_summary(results: list[ScrapeResult]) -> None:
        """
        Вывести итоговую статистику по каждому каналу.

        Выделено в отдельный метод, чтобы не загромождать ``scrape_region``.
        Успешные каналы логируются на уровне INFO, ошибки — WARNING.
        """
        total = sum(len(r.posts) for r in results if r.success)
        for r in results:
            if r.success:
                logger.info("  ✅ %-35s %d постов", r.channel, len(r.posts))
            else:
                logger.warning("  ❌ %-35s %s", r.channel, r.error)
        logger.info("Итого собрано постов: %d", total)