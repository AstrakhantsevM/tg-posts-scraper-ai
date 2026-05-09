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

from _01_02_configs.presets.preset_model import Preset
from _01_02_configs.settings import settings

logger = logging.getLogger(__name__)

_DATA_DIR = settings.BASE_DIR / "_01_03_data"
_SOURCES_DIR = _DATA_DIR / "sources"

_PROMPTS_DIR = settings.BASE_DIR / "_03_02_llm_prompts"
_SYSTEM_INSTRUCTIONS_DIR = settings.BASE_DIR / "_03_03_llm_system_instructions"


@dataclass
class RunContext:
    """
    Всё необходимое для одного запуска парсинга.

    Атрибуты:
        preset:          Конфигурация пресета.
        region_channels: Словарь вида {"Регион": ["@channel1", "@channel2"]}.
        data_dir:        Папка для сохранения результатов.
                         Формат: ``data/<output_label>/<YYYY-MM-DD>/``
    """

    preset: Preset
    region_channels: dict[str, list[str]]   # ← было channels: list[str]
    data_dir: Path
    prompt: str
    system_instruction: str

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
            _DATA_DIR
            / (preset.output_label or "default")
            / str(stop_date)
        )
        data_dir.mkdir(parents=True, exist_ok=True)

        prompt = cls._load_prompt_file(preset.prompt_file)
        system_instruction = cls._load_system_instruction_file(
            preset.system_instruction_file
        )

        cls._ensure_session()

        logger.info(
            "RunContext готов | регионов: %d | каналов: %d | стоп-дата: %s | папка: %s",
            len(region_channels), total_channels, stop_date, data_dir,
        )
        return cls(
            preset=preset,
            region_channels=region_channels,
            data_dir=data_dir,
            prompt=prompt,
            system_instruction=system_instruction,
        )

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

    @classmethod
    def _load_prompt_file(cls, filename: str) -> str:
        """
        Прочитать пользовательский prompt из папки prompts.
        """

        if not filename:
            raise ValueError("В пресете не задан prompt_file.")

        path = _PROMPTS_DIR / filename

        if not path.exists():
            raise FileNotFoundError(f"Prompt-файл не найден: {path}")

        content = path.read_text(encoding="utf-8").strip()

        if not content:
            raise ValueError(f"Prompt-файл пустой: {path}")

        return content

    @classmethod
    def _load_system_instruction_file(cls, filename: str) -> str:
        """
        Прочитать system instruction из папки system_instructions.
        """

        if not filename:
            raise ValueError("В пресете не задан system_instruction_file.")

        path = _SYSTEM_INSTRUCTIONS_DIR / filename

        if not path.exists():
            raise FileNotFoundError(f"System instruction файл не найден: {path}")

        content = path.read_text(encoding="utf-8").strip()

        if not content:
            raise ValueError(f"System instruction файл пустой: {path}")

        return content