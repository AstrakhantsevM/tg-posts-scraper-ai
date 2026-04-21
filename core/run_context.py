"""
RunContext — контекст одного запуска парсинга.

Сейчас реализован только этап сбора данных.
AI-анализ и отчёт будут добавлены позже.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from configs.presets.preset_model import Preset
from configs.settings import settings

logger = logging.getLogger(__name__)

_SOURCES_DIR = settings.BASE_DIR / "data/sources"


@dataclass
class RunContext:
    """
    Всё необходимое для одного запуска парсинга.

    Атрибуты:
        preset:          Конфигурация пресета.
        region_channels: Словарь вида {"Регион": ["@channel1", "@channel2"]}.
        data_dir:        Папка для сохранения результатов.
                         Формат: ``data/<preset_name>/<YYYY-MM-DD>/``
    """

    preset: Preset
    region_channels: dict[str, list[str]]   # ← было channels: list[str]
    data_dir: Path

    @classmethod
    def from_preset(cls, preset: Preset) -> RunContext:
        """
        Собрать контекст из пресета.

        :param preset: Валидированный объект Preset.
        :return:       Готовый RunContext.
        :raises FileNotFoundError: Если source-файл с каналами не найден.
        :raises ValueError:        Если source-файл пуст или неверного формата.
        """
        region_channels = cls._resolve_region_channels(preset)
        stop_date = preset.parse_until.to_date()

        total_channels = sum(len(v) for v in region_channels.values())

        data_dir = (
            settings.BASE_DIR
            / "data"
            / (preset.output_label or "default")
            / str(stop_date)
        )
        data_dir.mkdir(parents=True, exist_ok=True)

        cls._ensure_session()

        logger.info(
            "RunContext готов | регионов: %d | каналов: %d | стоп-дата: %s | папка: %s",
            len(region_channels), total_channels, stop_date, data_dir,
        )
        return cls(preset=preset, region_channels=region_channels, data_dir=data_dir)

    @classmethod
    def _resolve_region_channels(cls, preset: Preset) -> dict[str, list[str]]:
        """
        Прочитать source-файл и привести к формату {"Регион": ["@channel"]}.

        Поддерживает два формата:
        1. ``{"Москва": "@channel"}``         — один канал на регион
        2. ``{"Москва": ["@ch1", "@ch2"]}``   — несколько каналов на регион
        """
        if preset.channels:
            raise ValueError(
                "Для сохранения по регионам нужен source-файл. "
                "Явный список 'channels' без регионов не поддерживается."
            )

        if not preset.source:
            raise ValueError("В пресете не задан source-файл с регионами.")

        path = _SOURCES_DIR / preset.source
        if not path.exists():
            raise FileNotFoundError(f"Source-файл не найден: {path}")

        raw_data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(raw_data, dict) or not raw_data:
            raise ValueError(f"Source-файл '{preset.source}' пуст или неверного формата.")

        region_channels: dict[str, list[str]] = {}

        for region, value in raw_data.items():
            if isinstance(value, str):
                region_channels[region] = [value]
            elif isinstance(value, list):
                region_channels[region] = [
                    ch for ch in value if isinstance(ch, str) and ch.strip()
                ]
            else:
                raise ValueError(
                    f"Регион '{region}': неподдерживаемый тип значения {type(value)}"
                )

        # Убираем регионы без каналов
        region_channels = {k: v for k, v in region_channels.items() if v}

        if not region_channels:
            raise ValueError(f"Source-файл '{preset.source}' не содержит каналов.")

        return region_channels

    @staticmethod
    def _ensure_session() -> None:
        """
        Убедиться, что папка для файла сессии Telethon существует.
        """
        session_path = Path(settings.tg.session_path)
        session_path.parent.mkdir(parents=True, exist_ok=True)

        if not session_path.with_suffix(".session").exists():
            logger.warning(
                "Файл сессии не найден: %s.session — "
                "при первом запуске Telethon запросит номер телефона.",
                session_path,
            )