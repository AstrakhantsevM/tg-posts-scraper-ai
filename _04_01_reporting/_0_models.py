"""
Модели данных для этапа report.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegionLLMResult:
    """
    Сырые результаты LLM-обработки одного региона.
    """

    region: str
    path: str
    preset: str | None
    processed_at: str | None
    posts_total: int
    batches_total: int
    mode: str | None
    results: list[dict[str, Any]]
    final_summary: dict[str, Any] | None
    errors: list[str] = field(default_factory=list)


@dataclass
class ReportSection:
    """
    Один раздел отчёта.
    """

    title: str
    content: str
    level: int = 2


@dataclass
class RegionReport:
    """
    Готовая отчетная секция по одному региону.
    """

    region: str
    posts_total: int
    batches_total: int
    status: str
    summary: str | None
    errors: list[str] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)

    # --- поля для красивого docx-отчёта ---
    # Флаг: LLM нашёл релевантные упоминания
    found: bool = False
    # Список мер поддержки из JSON-ответа LLM
    measures: list[dict[str, Any]] = field(default_factory=list)
    # Telegram-канал региона (если известен из контекста)
    channel: str | None = None
    # Дата данных (обычно из processed_at)
    data_date: str | None = None


@dataclass
class ReportDocument:
    """
    Итоговый отчёт по запуску.
    """

    title: str
    preset: str
    generated_at: str
    regions_total: int
    posts_total: int
    regions: list[RegionReport]
    sections: list[ReportSection] = field(default_factory=list)