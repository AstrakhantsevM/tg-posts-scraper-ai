"""
llm_inference/searcher.py

Модуль поиска данных для LLM-обработки.

Задача:
    - получить контекст запуска;
    - определить дату обработки;
    - найти папку региона;
    - подтянуть посты/ответы/цепочки данных;
    - вернуть список объектов, которые дальше пойдут в батчер.

Searcher не занимается:
    - подсчётом токенов;
    - нарезкой на батчи;
    - вызовом LLM;
    - сохранением результатов.
"""

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from _01_01_core.run_context import RunContext

logger = logging.getLogger(__name__)

class LLMDataSearcher:
    """
    Поисковик данных для LLM-обработки.

    Основной публичный метод:
        find_items(ctx, region, target_date=None)

    Если target_date не передан, searcher сам берёт самую свежую дату,
    доступную внутри директории данных.
    """

    DEFAULT_INPUT_FILENAMES = (
        "posts.json",
        "messages.json",
        "data.json",
        "raw_posts.json",
    )

    def find_items(
        self,
        *,
        ctx: RunContext,
        region: str,
        target_date: str | date | None = None,
    ) -> list[Any]:
        """
        Найти данные для LLM-обработки по региону.

        :param ctx: Контекст запуска.
        :param region: Регион, например "Москва".
        :param target_date: Дата обработки. Если None — берём самую свежую.
        :return: Список объектов для дальнейшей обработки.
        """

        base_dir = self._resolve_base_dir(ctx)

        resolved_date = self._resolve_target_date(
            base_dir=base_dir,
            target_date=target_date,
        )

        if resolved_date is None:
            logger.warning("Не удалось определить дату обработки в %s", base_dir)
            return []

        region_dir = base_dir / resolved_date / self._safe_dir_name(region)

        if not region_dir.exists():
            logger.warning(
                "Папка региона не найдена: %s",
                region_dir,
            )
            return []

        input_path = self._find_input_file(region_dir)

        if input_path is None:
            logger.warning(
                "Не найден входной JSON-файл для региона «%s» в %s",
                region,
                region_dir,
            )
            return []

        logger.info(
            "  🔎 LLMDataSearcher: читаем данные из %s",
            input_path,
        )

        raw_payload = self._read_json(input_path)

        if raw_payload is None:
            return []

        items = self._extract_items(raw_payload)

        logger.info(
            "  🔎 LLMDataSearcher: найдено объектов: %d",
            len(items),
        )

        return items

    def _resolve_base_dir(self, ctx: RunContext) -> Path:
        """
        Определить базовую директорию с данными.

        В текущей архитектуре ожидается, что ctx.data_dir уже указывает на:

            data/<output_label>

        либо на:

            data/<output_label>/<YYYY-MM-DD>

        Чтобы searcher мог работать устойчиво, проверяем оба варианта.
        """

        data_dir = Path(ctx.data_dir)

        if self._looks_like_date_dir(data_dir.name):
            return data_dir.parent

        return data_dir

    def _resolve_target_date(
        self,
        *,
        base_dir: Path,
        target_date: str | date | None,
    ) -> str | None:
        """
        Определить дату обработки.

        Если target_date передан — нормализуем его к YYYY-MM-DD.
        Если None — берём самую свежую папку с датой внутри base_dir.
        """

        if target_date is not None:
            return self._normalize_date(target_date)

        return self._find_latest_date_dir(base_dir)

    def _normalize_date(self, value: str | date) -> str:
        """
        Привести дату к строке YYYY-MM-DD.
        """

        if isinstance(value, date):
            return value.isoformat()

        value = str(value).strip()

        # Уже нормальный формат
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value

        # Пробуем распарсить ISO datetime/date
        try:
            return datetime.fromisoformat(value).date().isoformat()
        except ValueError as exc:
            raise ValueError(
                f"Некорректный target_date: {value!r}. "
                f"Ожидается формат YYYY-MM-DD или ISO datetime."
            ) from exc

    def _find_latest_date_dir(self, base_dir: Path) -> str | None:
        """
        Найти самую свежую директорию с именем YYYY-MM-DD.
        """

        if not base_dir.exists():
            logger.warning("Базовая директория данных не найдена: %s", base_dir)
            return None

        date_dirs: list[str] = []

        for child in base_dir.iterdir():
            if child.is_dir() and self._looks_like_date_dir(child.name):
                date_dirs.append(child.name)

        if not date_dirs:
            logger.warning(
                "В директории %s нет папок с датами формата YYYY-MM-DD",
                base_dir,
            )
            return None

        return max(date_dirs)

    def _looks_like_date_dir(self, name: str) -> bool:
        """
        Проверить, похоже ли имя директории на дату YYYY-MM-DD.
        """

        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", name))

    def _find_input_file(self, region_dir: Path) -> Path | None:
        """
        Найти JSON-файл с исходными данными в папке региона.

        Сначала проверяем известные имена файлов.
        Потом fallback — берём первый JSON, который не похож на результат
        AI/LLM-обработки.
        """

        for filename in self.DEFAULT_INPUT_FILENAMES:
            candidate = region_dir / filename
            if candidate.exists() and candidate.is_file():
                return candidate

        json_files = sorted(region_dir.glob("*.json"))

        ignored_names = {
            "ai_results.json",
            "llm_results.json",
            "process_results.json",
        }

        for path in json_files:
            if path.name not in ignored_names:
                return path

        return None

    def _read_json(self, path: Path) -> Any | None:
        """
        Безопасно прочитать JSON.
        """

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.exception("Ошибка парсинга JSON-файла: %s", path)
            return None
        except OSError:
            logger.exception("Ошибка чтения JSON-файла: %s", path)
            return None

    def _extract_items(self, payload: Any) -> list[Any]:
        """
        Извлечь список объектов из JSON.

        Поддерживаем несколько возможных форматов scraper output:

        1. Прямой список:
            [
              {...},
              {...}
            ]

        2. Обёртка с posts:
            {
              "posts": [...]
            }

        3. Обёртка с messages:
            {
              "messages": [...]
            }

        4. Обёртка с items:
            {
              "items": [...]
            }

        5. Обёртка с results:
            {
              "results": [...]
            }

        Если формат неизвестен, возвращаем весь payload одним объектом.
        """

        if isinstance(payload, list):
            return payload

        if isinstance(payload, dict):
            for key in ("posts", "messages", "items", "results", "data"):
                value = payload.get(key)

                if isinstance(value, list):
                    return value

            return [payload]

        return [payload]

    def _safe_dir_name(self, name: str) -> str:
        """
        Безопасное имя директории региона.

        Должно совпадать с логикой сохранения scraper/process.
        """

        cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
        return cleaned or "_unknown_region"