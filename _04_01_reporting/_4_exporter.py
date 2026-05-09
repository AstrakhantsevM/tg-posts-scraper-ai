"""
_04_01_report/_4_exporter.py

Сохранение отчётов в файлы.
"""

import logging
from pathlib import Path

from _01_01_core.run_context import RunContext

logger = logging.getLogger(__name__)


class ReportExporter:
    """
    Сохраняет отчёты на диск.
    """

    def save_docx(
        self,
        *,
        ctx: RunContext,
        document,  # docx.Document
        filename: str | None = None,
    ) -> Path:
        """
        Сохранить Word-документ (.docx).

        :param ctx: Контекст запуска.
        :param document: Объект docx.Document, полученный из DocxReportRenderer.
        :param filename: Имя файла. По умолчанию строится из preset + даты.
        """
        from datetime import datetime, timezone

        if filename is None:
            preset = getattr(ctx.preset, "output_label", None) or "report"
            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            filename = f"МониторингСМИ_{date_str}_{preset}.docx"

        desktop_path = Path.home() / "Desktop"
        desktop_path.mkdir(parents=True, exist_ok=True)

        output_path = desktop_path / filename
        document.save(str(output_path))
        logger.info("  💾 Word-отчёт сохранён → %s", output_path)
        return output_path