"""
_04_01_report/_2_builder.py

Сборка логической структуры отчёта из LLM-результатов.
"""

import json
import logging
from datetime import datetime, timezone

from _01_01_core.run_context import RunContext
from _04_01_reporting._0_models import (
    RegionLLMResult,
    RegionReport,
    ReportDocument,
    ReportSection,
)

logger = logging.getLogger(__name__)


class ReportBuilder:
    """
    Превращает сырые LLM-результаты в ReportDocument.
    """

    def build(
        self,
        *,
        ctx: RunContext,
        results: list[RegionLLMResult],
    ) -> ReportDocument:
        preset_label = getattr(ctx.preset, "output_label", None) or "default"

        # region_channels: dict[str, str] — регион → @handle
        region_channels: dict = getattr(ctx, "region_channels", {}) or {}

        region_reports = [
            self._build_region_report(item, region_channels)
            for item in results
        ]

        posts_total = sum(item.posts_total for item in region_reports)

        return ReportDocument(
            title=f"AI-отчёт по Telegram-постам — {preset_label}",
            preset=preset_label,
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            regions_total=len(region_reports),
            posts_total=posts_total,
            regions=region_reports,
            sections=[
                self._build_overview_section(region_reports),
            ],
        )

    def _build_region_report(
        self,
        item: RegionLLMResult,
        region_channels: dict[str, str],
    ) -> RegionReport:
        raw_summary = self._extract_raw_summary(item)
        found, measures = self._parse_llm_json(raw_summary)

        # Человекочитаемое summary для Markdown-рендерера
        summary = self._format_summary(found, measures, raw_summary)

        status = "ok"
        if item.errors:
            status = "with_errors"
        if not raw_summary:
            status = "empty"

        # Дата данных — берём из processed_at, оставляем только дату
        data_date = None
        if item.processed_at:
            try:
                data_date = datetime.fromisoformat(item.processed_at).strftime("%Y-%m-%d")
            except ValueError:
                data_date = item.processed_at

        sections = [
            ReportSection(
                title="Краткая сводка",
                content=summary or "Нет итогового summary.",
                level=3,
            ),
            ReportSection(
                title="Техническая информация",
                content=self._build_technical_info(item),
                level=3,
            ),
        ]

        if item.errors:
            sections.append(
                ReportSection(
                    title="Ошибки обработки",
                    content="\n".join(f"- {error}" for error in item.errors),
                    level=3,
                )
            )

        return RegionReport(
            region=item.region,
            posts_total=item.posts_total,
            batches_total=item.batches_total,
            status=status,
            summary=summary,
            errors=item.errors,
            sections=sections,
            found=found,
            measures=measures,
            channel=self._resolve_channel(region_channels.get(item.region)),
            data_date=data_date,
        )

    # ------------------------------------------------------------------
    # Разбор ответа LLM
    # ------------------------------------------------------------------

    def _extract_raw_summary(self, item: RegionLLMResult) -> str | None:
        """
        Достать сырой текст итогового ответа LLM.

        Приоритет:
            1. final_summary.response
            2. если один батч — results[0].response
            3. склейка успешных batch responses
        """
        if item.final_summary and item.final_summary.get("response"):
            return str(item.final_summary["response"]).strip()

        successful_responses = [
            result.get("response")
            for result in item.results
            if result.get("success") and result.get("response")
        ]

        if not successful_responses:
            return None

        if len(successful_responses) == 1:
            return str(successful_responses[0]).strip()

        # Для многобатчевого режима — берём последний (итоговый) ответ,
        # или склеиваем, если не можем определить финальный
        return successful_responses[-1].strip()

    def _parse_llm_json(self, raw: str | None) -> tuple[bool, list[dict]]:
        """
        Попытаться распарсить JSON-ответ LLM вида:
            {"found": true/false, "measures": [...]}

        Возвращает (found, measures). При любой ошибке — (False, []).
        """
        if not raw:
            return False, []

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # LLM вернул свободный текст — считаем это «найдено»,
            # если там нет явного «нет» / «no»
            text_lower = raw.lower()
            if any(w in text_lower for w in ["нет", "no", '"found": false', '"found":false']):
                return False, []
            # Возвращаем свободный текст как единственную «меру»
            return True, [{"description": raw}]

        if not isinstance(data, dict):
            return False, []

        found = bool(data.get("found", False))
        measures = data.get("measures") or []

        if not isinstance(measures, list):
            measures = []

        return found, measures

    def _format_summary(
        self,
        found: bool,
        measures: list[dict],
        raw: str | None,
    ) -> str | None:
        """
        Человекочитаемый текст для Markdown-отчёта.
        """
        if not found:
            return "Упоминаний не найдено."

        if not measures:
            return raw or "Найдено, но меры не структурированы."

        lines: list[str] = []
        for m in measures:
            if isinstance(m, dict):
                # Пробуем стандартные ключи; всё остальное — через repr
                parts = []
                for key in ("name", "title", "description", "amount", "conditions", "notes"):
                    val = m.get(key)
                    if val:
                        parts.append(f"**{key}:** {val}")
                if parts:
                    lines.append("- " + "; ".join(parts))
                else:
                    lines.append(f"- {m}")
            else:
                lines.append(f"- {m}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Вспомогательные методы (без изменений)
    # ------------------------------------------------------------------

    def _build_technical_info(self, item: RegionLLMResult) -> str:
        providers = []
        models = []

        for result in item.results:
            provider = result.get("provider_used")
            model = result.get("model_used")
            if provider:
                providers.append(provider)
            if model:
                models.append(model)

        if item.final_summary:
            provider = item.final_summary.get("provider_used")
            model = item.final_summary.get("model_used")
            if provider:
                providers.append(provider)
            if model:
                models.append(model)

        return "\n".join(
            [
                f"- Постов обработано: {item.posts_total}",
                f"- Батчей: {item.batches_total}",
                f"- Режим: {item.mode}",
                f"- Провайдеры: {', '.join(sorted(set(providers))) or '—'}",
                f"- Модели: {', '.join(sorted(set(models))) or '—'}",
                f"- Источник: `{item.path}`",
            ]
        )

    def _build_overview_section(
        self,
        regions: list[RegionReport],
    ) -> ReportSection:
        if not regions:
            return ReportSection(
                title="Обзор",
                content="Нет данных для построения отчёта.",
                level=2,
            )

        lines = [
            "| Регион | Постов | Батчей | Найдено | Статус |",
            "|---|---:|---:|:---:|---|",
        ]

        for region in regions:
            found_mark = "✅" if region.found else "—"
            lines.append(
                f"| {region.region} | {region.posts_total} | "
                f"{region.batches_total} | {found_mark} | {region.status} |"
            )

        return ReportSection(
            title="Обзор обработки",
            content="\n".join(lines),
            level=2,
        )

    @staticmethod
    def _resolve_channel(value) -> str | None:
        """
        Нормализует значение канала из region_channels.
        Может прийти как строка, как список строк, или None.
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value or None
        if isinstance(value, (list, tuple)) and value:
            return str(value[0]) or None
        return str(value) or None