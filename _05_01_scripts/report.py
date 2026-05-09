"""
_05_01_scripts/report.py

Оркестратор построения отчёта по результатам LLM-обработки.

Единственная публичная функция:
    run(ctx, target_date=None)

Этапы:
    1. Найти llm_results.json по регионам.
    2. Собрать логическую структуру отчёта.
    3. Отрендерить красивый Markdown.
    4. Сохранить report.md в папку запуска.

Ожидаемый путь:
    _01_03_data/<output_label>/<YYYY-MM-DD>/report.md
"""

import logging
from datetime import date
from pathlib import Path

from _01_01_core.run_context import RunContext

from _04_01_reporting._1_searcher import ReportDataSearcher
from _04_01_reporting._2_builder import ReportBuilder
from _04_01_reporting._3_renderer import DocxReportRenderer
from _04_01_reporting._4_exporter import ReportExporter

logger = logging.getLogger(__name__)

def run(
    ctx: RunContext,
    target_date: str | date | None = None,
) -> Path | None:
    """
    Построить отчёт по результатам LLM-обработки.

    :param ctx: Контекст запуска.
    :param target_date: Дата данных. Если None — используется ctx.data_dir.
    :return: Путь к сохранённому report.md или None, если данных нет.
    """

    logger.info("▶ Старт построения отчёта")

    searcher = ReportDataSearcher()
    builder = ReportBuilder()
    renderer = DocxReportRenderer()
    exporter = ReportExporter()

    # 1. Найти результаты LLM-обработки
    results = searcher.find_results(
        ctx=ctx,
        target_date=target_date,
    )

    if not results:
        logger.warning("  ⚠️ Нет LLM-результатов для построения отчёта.")
        return None

    logger.info("  🔎 Найдено региональных результатов: %d", len(results))

    # 2. Собрать структуру отчёта
    document = builder.build(
        ctx=ctx,
        results=results,
    )

    logger.info(
        "  🧱 Структура отчёта собрана | регионов: %d | постов: %d",
        document.regions_total,
        document.posts_total,
    )

    # 3. Рендер в Markdown
    document = renderer.render(document)

    # 4. Сохранение
    output_path = exporter.save_docx(
        ctx=ctx, document=document,
        filename="report.docx",
    )

    logger.info("✅ Отчёт готов: %s", output_path)

    return output_path