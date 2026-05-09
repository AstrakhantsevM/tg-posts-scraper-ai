"""
_04_01_report/_1_searcher.py

Поиск результатов LLM-обработки для построения отчёта.
"""

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from _01_01_core.run_context import RunContext
from _04_01_reporting._0_models import RegionLLMResult


logger = logging.getLogger(__name__)


class ReportDataSearcher:
    """
    Ищет llm_results.json по регионам.
    """

    RESULT_FILENAME = "llm_results.json"

    def find_results(
        self,
        *,
        ctx: RunContext,
        target_date: str | date | None = None,
    ) -> list[RegionLLMResult]:
        """
        Найти LLM-результаты для всех регионов из контекста.

        :param ctx: Контекст запуска.
        :param target_date: Дата отчёта. Если None — используется ctx.data_dir.
        """

        base_dir = self._resolve_report_dir(ctx=ctx, target_date=target_date)

        if not base_dir.exists():
            logger.warning("Папка с данными для отчёта не найдена: %s", base_dir)
            return []

        results: list[RegionLLMResult] = []

        for region in ctx.region_channels:
            region_dir = base_dir / self._safe_dir_name(region)
            result_path = region_dir / self.RESULT_FILENAME

            if not result_path.exists():
                logger.warning(
                    "  ⚠️ Для региона «%s» не найден %s",
                    region,
                    result_path,
                )
                continue

            payload = self._read_json(result_path)

            if not payload:
                continue

            results.append(
                self._parse_region_result(
                    payload=payload,
                    path=result_path,
                    fallback_region=region,
                )
            )

        logger.info(
            "ReportDataSearcher: найдено LLM-результатов: %d",
            len(results),
        )

        return results

    def _resolve_report_dir(
        self,
        *,
        ctx: RunContext,
        target_date: str | date | None,
    ) -> Path:
        """
        Определить папку с результатами.

        Обычно ctx.data_dir уже указывает на:
            _01_03_data/<output_label>/<YYYY-MM-DD>

        Если target_date передан явно, берём:
            _01_03_data/<output_label>/<target_date>
        """

        if target_date is None:
            return Path(ctx.data_dir)

        target_date_str = self._normalize_date(target_date)

        current_data_dir = Path(ctx.data_dir)

        # Если ctx.data_dir заканчивается датой, значит parent — это output_label.
        if self._looks_like_date_dir(current_data_dir.name):
            return current_data_dir.parent / target_date_str

        return current_data_dir / target_date_str

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.exception("Ошибка парсинга JSON: %s", path)
            return None
        except OSError:
            logger.exception("Ошибка чтения файла: %s", path)
            return None

    def _parse_region_result(
        self,
        *,
        payload: dict[str, Any],
        path: Path,
        fallback_region: str,
    ) -> RegionLLMResult:
        return RegionLLMResult(
            region=payload.get("region") or fallback_region,
            path=str(path),
            preset=payload.get("preset"),
            processed_at=payload.get("processed_at"),
            posts_total=int(payload.get("posts_total") or 0),
            batches_total=int(payload.get("batches_total") or 0),
            mode=payload.get("mode"),
            results=payload.get("results") or [],
            final_summary=payload.get("final_summary"),
            errors=payload.get("errors") or [],
        )

    def _normalize_date(self, value: str | date) -> str:
        if isinstance(value, date):
            return value.isoformat()

        value = str(value).strip()

        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value

        return datetime.fromisoformat(value).date().isoformat()

    def _looks_like_date_dir(self, name: str) -> bool:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", name))

    def _safe_dir_name(self, name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
        return cleaned or "_unknown_region"