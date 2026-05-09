"""
llm_inference/batcher.py

Модуль нарезки данных на батчи для LLM-обработки.

Задача:
    - принять список текстов;
    - оценить размер каждого текста в токенах;
    - сгруппировать тексты так, чтобы каждый батч был не больше token_limit;
    - вернуть список LLMBatch.

Batcher не занимается:
    - поиском данных;
    - вызовом LLM;
    - промптами;
    - сохранением результатов.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class LLMBatch:
    """
    Один батч данных для LLM.

    Attributes:
        batch_index:
            Порядковый номер батча.

        texts:
            Список текстов внутри батча.

        tokens_estimated:
            Примерная оценка количества токенов в батче.

        items_count:
            Количество объектов внутри батча.

        oversized:
            True, если хотя бы один объект внутри батча сам по себе
            превышает token_limit.
    """

    batch_index: int
    texts: list[str]
    tokens_estimated: int
    items_count: int
    oversized: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """
        Текстовое представление батча.
        """

        return self.to_plain_text()

    def to_plain_text(self) -> str:
        """
        Склеить элементы батча в один текст для промпта.
        """

        parts = []

        for index, text in enumerate(self.texts, start=1):
            parts.append(
                f"--- ITEM {index} ---\n{text}"
            )

        return "\n\n".join(parts)


class LLMDataBatcher:
    """
    Делит список текстов на батчи по token_limit.

    Базовый вариант использует приблизительную оценку:
        1 токен ≈ 4 символа.

    Этого достаточно для первичной архитектуры.

    Позже можно заменить _estimate_tokens на tiktoken или tokenizer
    конкретной модели.
    """

    def __init__(
        self,
        *,
        token_limit: int,
        reserved_tokens: int = 1_500,
        min_token_limit: int = 1_000,
    ) -> None:
        """
        :param token_limit:
            Максимальный лимит токенов модели/пресета.

        :param reserved_tokens:
            Запас под system prompt, user prompt, JSON-структуру и ответ модели.
            Например, если token_limit=16000, а reserved_tokens=1500,
            то на сами данные останется 14500.

        :param min_token_limit:
            Минимальный допустимый лимит на данные.
            Нужен, чтобы не получить отрицательный или слишком маленький лимит.
        """

        if token_limit <= 0:
            raise ValueError("token_limit должен быть положительным числом")

        self.token_limit = token_limit
        self.reserved_tokens = max(0, reserved_tokens)
        self.payload_token_limit = max(
            min_token_limit,
            token_limit - self.reserved_tokens,
        )

    def make_batches(self, texts: list[str]) -> list[LLMBatch]:
        """
        Сформировать батчи из списка текстов.

        :param texts: Список строк для обработки.
        :return: Список LLMBatch.
        """

        normalized_texts = self._normalize_texts(texts)

        if not normalized_texts:
            return []

        batches: list[LLMBatch] = []

        current_texts: list[str] = []
        current_tokens = 0
        current_oversized = False

        for text in normalized_texts:
            text_tokens = self._estimate_tokens(text)

            # Если отдельный текст сам больше лимита,
            # он становится отдельным oversized-батчем.
            if text_tokens > self.payload_token_limit:
                if current_texts:
                    batches.append(
                        self._make_batch(
                            batch_index=len(batches),
                            texts=current_texts,
                            tokens_estimated=current_tokens,
                            oversized=current_oversized,
                        )
                    )

                    current_texts = []
                    current_tokens = 0
                    current_oversized = False

                logger.warning(
                    "Один объект превышает payload_token_limit: %d > %d. "
                    "Кладём его в отдельный oversized-батч.",
                    text_tokens,
                    self.payload_token_limit,
                )

                batches.append(
                    self._make_batch(
                        batch_index=len(batches),
                        texts=[text],
                        tokens_estimated=text_tokens,
                        oversized=True,
                    )
                )

                continue

            # Если добавление текста переполнит текущий батч,
            # закрываем текущий батч и начинаем новый.
            if current_texts and current_tokens + text_tokens > self.payload_token_limit:
                batches.append(
                    self._make_batch(
                        batch_index=len(batches),
                        texts=current_texts,
                        tokens_estimated=current_tokens,
                        oversized=current_oversized,
                    )
                )

                current_texts = [text]
                current_tokens = text_tokens
                current_oversized = False

                continue

            current_texts.append(text)
            current_tokens += text_tokens

        if current_texts:
            batches.append(
                self._make_batch(
                    batch_index=len(batches),
                    texts=current_texts,
                    tokens_estimated=current_tokens,
                    oversized=current_oversized,
                )
            )

        logger.info(
            "LLMDataBatcher: сформировано батчей: %d | payload_token_limit: %d",
            len(batches),
            self.payload_token_limit,
        )

        return batches

    def _make_batch(
        self,
        *,
        batch_index: int,
        texts: list[str],
        tokens_estimated: int,
        oversized: bool,
    ) -> LLMBatch:
        """
        Создать объект LLMBatch.
        """

        return LLMBatch(
            batch_index=batch_index,
            texts=texts,
            tokens_estimated=tokens_estimated,
            items_count=len(texts),
            oversized=oversized,
            metadata={
                "token_limit": self.token_limit,
                "reserved_tokens": self.reserved_tokens,
                "payload_token_limit": self.payload_token_limit,
            },
        )

    def _normalize_texts(self, texts: list[str]) -> list[str]:
        """
        Очистить входные тексты.

        Убираем:
            - None;
            - пустые строки;
            - строки из одних пробелов.
        """

        result: list[str] = []

        for item in texts:
            if item is None:
                continue

            text = str(item).strip()

            if not text:
                continue

            result.append(text)

        return result

    def _estimate_tokens(self, text: str) -> int:
        """
        Примерно оценить количество токенов.

        Базовая эвристика:
            1 токен ≈ 4 символа.

        Для русского языка оценка может быть неидеальной, но для первой
        версии пайплайна этого достаточно.

        Позже сюда можно подключить tiktoken.
        """

        if not text:
            return 0

        return max(1, len(text) // 4)