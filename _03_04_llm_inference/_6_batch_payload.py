"""
llm_inference/batch_payload.py

Нормализация batch-объекта к формату data: list[str],
который ожидают GroqAgent и MistralAgent.
"""

from typing import Any

class BatchPayloadBuilder:
    """
    Преобразует разные варианты batch в list[str].
    """

    @classmethod
    def to_data(cls, batch: Any) -> list[str]:
        """
        Поддерживаем:
            - LLMBatch с полем texts;
            - list[str];
            - tuple[str];
            - str;
            - объект с to_plain_text();
            - dict / любой объект через str().
        """

        if batch is None:
            return []

        if hasattr(batch, "texts"):
            return cls._normalize_list(batch.texts)

        if isinstance(batch, list | tuple):
            return cls._normalize_list(batch)

        if isinstance(batch, str):
            return cls._normalize_single(batch)

        if hasattr(batch, "to_plain_text"):
            return cls._normalize_single(batch.to_plain_text())

        return cls._normalize_single(str(batch))

    @staticmethod
    def _normalize_list(items: list | tuple) -> list[str]:
        result: list[str] = []

        for item in items:
            text = str(item).strip()

            if text:
                result.append(text)

        return result

    @staticmethod
    def _normalize_single(value: str) -> list[str]:
        text = str(value).strip()
        return [text] if text else []