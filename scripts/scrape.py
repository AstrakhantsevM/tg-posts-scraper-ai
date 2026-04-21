"""
scripts/scrape.py — этап парсинга каналов.

Единственная публичная функция: ``run(ctx)``.

Результат сохраняется в:
    data/<preset_name>/<YYYY-MM-DD>/raw_posts.json

Структура файла::

    {
      "preset":     "birth_support_check",
      "stop_date":  "2026-04-20",
      "scraped_at": "2026-04-20T17:00:00+00:00",
      "posts": [
        {
          "channel":    "@channel1",
          "date":       "2026-04-19T10:30:00+00:00",
          "text":       "...",
          "message_id": 1234,
          "views":      500
        }
      ]
    }
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from configs.settings import settings
from core.run_context import RunContext
from scraper.client import TelegramScraper
from scraper.models import Post, ScrapeResult
from scraper.utils import ensure_utc

logger = logging.getLogger(__name__)


def run(ctx: RunContext) -> None:
    """
    Запарсить все регионы из контекста и сохранить результат по папкам.

    Синхронная обёртка над async-логикой — asyncio.run() внутри,
    чтобы main.py оставался синхронным.

    :param ctx: Контекст запуска.
    """
    asyncio.run(_run_async(ctx))


async def _run_async(ctx: RunContext) -> None:
    stop_dt = ensure_utc(ctx.preset.parse_until.to_date())

    async with TelegramScraper(
        session_path=settings.tg.session_path,
        api_id=settings.tg.api_id,
        api_hash=settings.tg.api_hash,
    ) as scraper:
        # Обходим регионы последовательно, внутри каждого — параллельно по каналам
        for region, channels in ctx.region_channels.items():
            logger.info("▶ Регион: %s | каналов: %d", region, len(channels))

            results: list[ScrapeResult] = await asyncio.gather(*[
                scraper._scrape_channel(
                    channel=ch,
                    stop_date=stop_dt,
                    limit=ctx.preset.limit_per_channel,
                )
                for ch in channels
            ])

            posts: list[Post] = sorted(
                (p for r in results if r.success for p in r.posts),
                key=lambda p: p.date,
                reverse=True,
            )

            failed = [r for r in results if not r.success]
            for r in failed:
                logger.warning("  ❌ %s: %s", r.channel, r.error)

            logger.info(
                "  ✅ %s: постов %d | ошибок %d",
                region, len(posts), len(failed),
            )

            _save_region(ctx, region, posts)


def _save_region(ctx: RunContext, region: str, posts: list[Post]) -> None:
    """
    Сохранить посты региона в:
        data/<output_label>/<YYYY-MM-DD>/<РЕГИОН>/raw_posts.json

    :param ctx:    Контекст запуска.
    :param region: Название региона (используется как имя папки).
    :param posts:  Список постов для сохранения.
    """
    region_dir = ctx.data_dir / _safe_dir_name(region)
    region_dir.mkdir(parents=True, exist_ok=True)

    output_path = region_dir / "raw_posts.json"

    payload = {
        "preset":     ctx.preset.output_label or "default",
        "region":     region,
        "stop_date":  str(ctx.preset.parse_until.to_date()),
        "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
        "posts": [
            {
                "channel":    p.channel,
                "date":       p.date.isoformat(),
                "text":       p.text,
                "message_id": p.message_id,
                "views":      p.views,
            }
            for p in posts
        ],
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("  💾 Сохранено → %s", output_path)


def _safe_dir_name(name: str) -> str:
    """
    Очистить имя региона для использования как имя папки.

    Убирает символы, недопустимые в именах файлов на macOS/Windows/Linux.
    """
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
    return cleaned or "_unknown_region"