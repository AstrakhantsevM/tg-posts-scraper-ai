"""
_04_01_report/_2_builder.py

Сборка логической структуры отчёта из LLM-результатов.

Исправленная версия:
- нормализует разные ключи LLM-ответов в единую схему;
- корректно использует type как название меры;
- чистит строковые "null", "None", "не указано";
- убирает очевидные дубли;
- делает summary пригодным и для Markdown, и для DOCX.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from _01_01_core.run_context import RunContext
from _04_01_reporting._0_models import (
    RegionLLMResult,
    RegionReport,
    ReportDocument,
    ReportSection,
)

logger = logging.getLogger(__name__)


NULL_MARKERS = {
    "",
    "null",
    "none",
    "nil",
    "нет",
    "не указано",
    "не указаны",
    "не указан",
    "n/a",
    "na",
    "—",
    "-",
}


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

        summary = self._format_summary(found, measures, raw_summary)

        status = "ok"
        if item.errors:
            status = "with_errors"
        if not raw_summary:
            status = "empty"

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
            3. последний успешный batch response
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

        return str(successful_responses[-1]).strip()

    def _parse_llm_json(self, raw: str | None) -> tuple[bool, list[dict]]:
        """
        Парсит JSON-ответ LLM вида:
            {"found": true/false, "measures": [...]}

        Возвращает:
            found: bool
            measures: list[dict]

        Нормализованная схема measure:
            {
                "title": str,
                "form": str | None,
                "amount": str | None,
                "conditions": str | None,
                "notes": str | None,
                "details": str | None,
            }
        """
        if not raw:
            return False, []

        raw = raw.strip()
        payload = self._extract_json_payload(raw)

        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            text_lower = raw.lower()

            if any(
                marker in text_lower
                for marker in [
                    '"found": false',
                    '"found":false',
                    "упоминаний не найдено",
                    "ничего не найдено",
                    "нет упоминаний",
                    "no mentions",
                    "not found",
                ]
            ):
                return False, []

            cleaned = self._clean_text(raw)
            if not cleaned:
                return False, []

            return True, [
                {
                    "title": cleaned,
                    "form": None,
                    "amount": None,
                    "conditions": None,
                    "notes": None,
                    "details": None,
                }
            ]

        if not isinstance(data, dict):
            return False, []

        raw_found = bool(data.get("found", False))
        raw_measures = data.get("measures") or []

        if not isinstance(raw_measures, list):
            raw_measures = []

        measures: list[dict] = []

        for measure in raw_measures:
            normalized = self._normalize_measure(measure)
            if normalized:
                measures.append(normalized)

        measures = self._deduplicate_measures(measures)

        # Если LLM сказала found=true, но после чистки ничего не осталось,
        # считаем, что пригодных упоминаний нет.
        found = bool(raw_found and measures)

        return found, measures

    def _normalize_measure(self, measure: Any) -> dict | None:
        """
        Приводит одну меру к единой структуре.

        Поддерживаемые входные ключи:
        - title/name/type/measure/description -> title
        - form/kind/category/support_form -> form
        - amount/sum/size/payment/value -> amount
        - conditions/eligibility/for_whom/target_group/recipients -> conditions
        - notes/comment/nuances -> notes
        - details/extra -> details
        """
        if isinstance(measure, str):
            title = self._clean_text(measure)
            if not title:
                return None

            return {
                "title": title,
                "form": None,
                "amount": None,
                "conditions": None,
                "notes": None,
                "details": None,
            }

        if not isinstance(measure, dict):
            return None

        title = self._first_clean(
            measure,
            "title",
            "name",
            "type",
            "measure",
            "description",
        )

        form = self._first_clean(
            measure,
            "form",
            "kind",
            "category",
            "support_form",
        )

        amount = self._first_clean(
            measure,
            "amount",
            "sum",
            "size",
            "payment",
            "value",
        )

        conditions = self._first_clean(
            measure,
            "conditions",
            "condition",
            "eligibility",
            "for_whom",
            "target_group",
            "recipients",
        )

        notes = self._first_clean(
            measure,
            "notes",
            "note",
            "comment",
            "nuances",
        )

        details = self._first_clean(
            measure,
            "details",
            "detail",
            "extra",
        )

        if not title:
            fallback_parts = [
                part for part in [amount, conditions, notes, details]
                if part
            ]

            if not fallback_parts:
                return None

            title = "Мера поддержки без уточнённого названия"

        return {
            "title": title,
            "form": form,
            "amount": amount,
            "conditions": conditions,
            "notes": notes,
            "details": details,
        }

    def _first_clean(self, data: dict, *keys: str) -> str | None:
        for key in keys:
            if key in data:
                value = self._clean_text(data.get(key))
                if value:
                    return value

        return None

    def _clean_text(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).strip()

        if not text:
            return None

        text = re.sub(r"\s+", " ", text)

        if text.lower() in NULL_MARKERS:
            return None

        return text

    def _deduplicate_measures(self, measures: list[dict]) -> list[dict]:
        """
        Убирает очевидные дубли по названию + форме + размеру.
        """
        result: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        for measure in measures:
            key = (
                self._dedupe_key(measure.get("title")),
                self._dedupe_key(measure.get("form")),
                self._dedupe_key(measure.get("amount")),
            )

            if key in seen:
                continue

            seen.add(key)
            result.append(measure)

        return result

    def _dedupe_key(self, value: str | None) -> str:
        if not value:
            return ""

        value = value.lower()
        value = value.replace("ё", "е")
        value = re.sub(r"[^а-яa-z0-9]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()

        return value

    def _format_summary(
        self,
        found: bool,
        measures: list[dict],
        raw: str | None,
    ) -> str | None:
        """
        Человекочитаемый текст для Markdown-рендерера.
        """
        if not found:
            return "Упоминаний не найдено."

        if not measures:
            return raw or "Найдено, но меры не структурированы."

        lines: list[str] = []

        for measure in measures:
            title = measure.get("title") or "Мера поддержки без названия"
            lines.append(f"- **{title}**")

            if measure.get("form"):
                lines.append(f"  - Форма: {measure['form']}")

            if measure.get("amount"):
                lines.append(f"  - Размер: {measure['amount']}")

            if measure.get("conditions"):
                lines.append(f"  - Условия: {measure['conditions']}")

            if measure.get("notes"):
                lines.append(f"  - Нюансы: {measure['notes']}")

            if measure.get("details"):
                lines.append(f"  - Детали: {measure['details']}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Вспомогательные методы
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
        Может прийти как строка, список строк или None.
        """
        if value is None:
            return None

        if isinstance(value, str):
            return value or None

        if isinstance(value, (list, tuple)) and value:
            return str(value[0]) or None

        return str(value) or None

    def _extract_json_payload(self, raw: str) -> str:
        """
        Достаёт JSON из ответа LLM.

        Поддерживает варианты:
        1. Чистый JSON:
           {"found": true, "measures": [...]}

        2. Markdown code fence:
           ```json
           {"found": true, "measures": [...]}
           ```

        3. Текст вокруг JSON:
           Вот результат:
           {"found": true, "measures": [...]}
        """
        text = raw.strip()

        # Убираем markdown code fence целиком.
        fence_match = re.search(
            r"```(?:json|JSON)?\s*(.*?)\s*```",
            text,
            flags=re.DOTALL,
        )

        if fence_match:
            text = fence_match.group(1).strip()

        # Если вокруг JSON есть поясняющий текст, пытаемся вытащить объект.
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")

            if start != -1 and end != -1 and end > start:
                text = text[start: end + 1].strip()

        return text