"""
Pydantic-схема пресета.

Пресет — единственный источник правды для одного сценария запуска:
он описывает, откуда брать каналы, до какой даты парсить, какой
промпт использовать и какие AI-модели пробовать в порядке ротации.

Структура JSON-файла пресета::

    {
      "source": "russian_regions.json",   // файл с каналами (если channels: null)
      "channels": null,                   // или явный список: ["@ch1", "@ch2"]
      "parse_until": {"year": 2026, "month": 4, "day": 20},
      "prompt_file": "birth_support_check.txt",
      "system_instruction_file": "analyst_role.txt",
      "preferred_models": [
        {"provider": "mistral", "model": "mistral-small-latest"},
        {"provider": "groq",    "model": "llama-3.1-8b-instant"}
      ],
      "temperature": 0.1
    }

Либо ``source``, либо ``channels`` должны быть заполнены —
валидатор ``check_channels_source`` это гарантирует.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ParseUntilDate(BaseModel):
    """
    Граница парсинга — три отдельных поля вместо строки с датой.

    Раздельные поля удобнее редактировать вручную в JSON и
    исключают неоднозначность форматов (DD/MM vs MM/DD).
    """

    year: int  = Field(ge=2020, le=2100)
    month: int = Field(ge=1,    le=12)
    day: int   = Field(ge=1,    le=31)

    def to_date(self) -> date:
        """Конвертировать в стандартный ``datetime.date`` для сравнений."""
        return date(self.year, self.month, self.day)


class ModelEntry(BaseModel):
    """
    Одна запись в списке ротации AI-моделей.

    :param provider: Провайдер — ``"mistral"``, ``"groq"``, ``"openrouter"``.
    :param model:    Идентификатор модели у провайдера.
    """

    provider: str
    model: str


class Preset(BaseModel):
    """
    Полная конфигурация одного сценария запуска.

    Атрибуты:
        source:                   Имя JSON-файла в ``sources/`` с маппингом
                                  ``{"Регион": "@channel"}``. Используется,
                                  если ``channels`` не задан явно.
        channels:                 Явный список каналов. Если задан — ``source``
                                  игнорируется.
        parse_until:              Граница парсинга по дате.
        prompt_file:              Имя файла промпта в ``llm_prompts/``.
        system_instruction_file:  Имя файла системной инструкции в
                                  ``llm_system_instructions/``.
        preferred_models:         Список моделей в порядке приоритета.
                                  AgentPool выберет первую доступную.
        temperature:              Параметр генерации (0.0–1.0).
        output_label:             Опциональный суффикс для имени отчёта.
        limit_per_channel:        Максимум постов с одного канала.
    """

    source: Optional[str] = None
    channels: Optional[list[str]] = None

    parse_until: ParseUntilDate

    prompt_file: str
    system_instruction_file: str

    preferred_models: list[ModelEntry] = Field(min_length=1)
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)

    output_label: str = ""
    limit_per_channel: int = Field(default=999, gt=0)

    @model_validator(mode="after")
    def _check_channels_source(self) -> "Preset":
        """
        Гарантировать, что задан хотя бы один источник каналов.

        Допустимые варианты:
        - задан ``source``   (каналы будут загружены из JSON-файла)
        - задан ``channels`` (явный список)
        - заданы оба         (``channels`` имеет приоритет)

        :raises ValueError: Если оба поля пусты.
        """
        if not self.source and not self.channels:
            raise ValueError(
                "Необходимо задать 'source' (файл с каналами) "
                "или 'channels' (явный список)."
            )
        return self