"""
llm_inference/inference.py

LLMInferencePool — пул LLM-агентов с round-robin ротацией и fallback.

Этот файл отвечает только за:
    - порядок выбора агента;
    - выполнение запроса;
    - fallback на следующего агента при ошибке;
    - возврат LLMInferenceResult.

Он не занимается:
    - созданием конкретных агентов;
    - чтением API-ключей;
    - нормализацией batch;
    - чтением prompt-файлов.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from _01_01_core.run_context import RunContext

from _03_04_llm_inference._3_models import LLMInferenceResult
from _03_04_llm_inference._4_agent_slot import AgentSlot
from _03_04_llm_inference._5_agent_factory import LLMAgentFactory
from _03_04_llm_inference._6_batch_payload import BatchPayloadBuilder

logger = logging.getLogger(__name__)

class LLMInferencePool:
    """
    Пул LLM-агентов.

    Ротация:
        preferred_models = [mistral, groq]

        1 запрос -> mistral
        2 запрос -> groq
        3 запрос -> mistral
        4 запрос -> groq

    Fallback:
        если выбранный агент упал, пробуем следующего.
        если упали все, возвращаем success=False.
    """

    def __init__(
        self,
        *,
        agents: list[AgentSlot],
        max_attempts_per_request: int | None = None,
        require_json: bool = True,
    ) -> None:
        if not agents:
            raise ValueError("LLMInferencePool требует хотя бы одного агента.")

        self._agents = agents
        self._cursor = 0
        self._lock = asyncio.Lock()
        self._max_attempts_per_request = max_attempts_per_request or len(agents)
        self._require_json = require_json

    @classmethod
    def from_context(cls, ctx: RunContext) -> "LLMInferencePool":
        preferred_models = getattr(ctx.preset, "preferred_models", None)
        if not preferred_models:
            raise ValueError(
                "В preset не задан preferred_models. "
                "Нужно указать хотя бы одну модель."
            )
        temperature = getattr(ctx.preset, "temperature", 0.1)
        require_json = getattr(ctx.preset, "require_json", True)

        agents = LLMAgentFactory.build_slots(
            preferred_models=preferred_models,
            temperature=temperature,
        )
        logger.info(
            "LLMInferencePool собран | агентов: %d | модели: %s | require_json: %s",
            len(agents),
            ", ".join(slot.label for slot in agents),
            require_json,
        )
        return cls(agents=agents, require_json=require_json)  # ← пробрасываем

    async def __aenter__(self) -> "LLMInferencePool":
        logger.debug("LLMInferencePool открыт.")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        logger.debug("LLMInferencePool закрыт.")

    async def infer(
        self,
        *,
        batch: Any,
        prompt: str,
        system_instruction: str | None,
        batch_index: int,
        role: str,
    ) -> LLMInferenceResult:
        """
        Выполнить один LLM-запрос.

        :param batch: Данные батча.
        :param prompt: Пользовательский промпт.
        :param system_instruction: Системная инструкция.
        :param batch_index: Индекс батча.
        :param role: Роль обработки: single_batch, batch_summary, final_summary.
        """

        if not prompt or not prompt.strip():
            raise ValueError("prompt не может быть пустым.")

        data = BatchPayloadBuilder.to_data(batch)

        if not data:
            return self._empty_batch_result(
                batch_index=batch_index,
                role=role,
            )

        start_index = await self._next_start_index()

        return await self._try_agents(
            start_index=start_index,
            prompt=prompt,
            data=data,
            system_instruction=system_instruction,
            batch_index=batch_index,
            role=role,
        )

    async def infer_all(
        self,
        batches: list[Any],
        *,
        prompt: str,
        system_instruction: str | None,
        role: str = "batch_processing",
        concurrency: int = 1
    ) -> list[LLMInferenceResult]:
        """
        Обработать список батчей параллельно.
        """

        semaphore = asyncio.Semaphore(concurrency)

        async def _run_one(index: int, batch: Any) -> LLMInferenceResult:
            async with semaphore:
                return await self.infer(
                    batch=batch,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    batch_index=index,
                    role=role,
                )

        tasks = [
            _run_one(index, batch)
            for index, batch in enumerate(batches)
        ]

        return await asyncio.gather(*tasks)

    async def _try_agents(
        self,
        *,
        start_index: int,
        prompt: str,
        data: list[str],
        system_instruction: str | None,
        batch_index: int,
        role: str,
    ) -> LLMInferenceResult:
        """
        Попробовать агентов по очереди, начиная со start_index.
        """

        errors: list[str] = []

        for attempt_offset in range(self._max_attempts_per_request):
            agent_index = (start_index + attempt_offset) % len(self._agents)
            slot = self._agents[agent_index]

            try:
                response = await self._call_agent(
                    slot=slot,
                    prompt=prompt,
                    data=data,
                    system_instruction=system_instruction,
                    batch_index=batch_index,
                    role=role,
                    attempt=attempt_offset + 1,
                )

                if self._require_json:
                    response = self._extract_json(response)

                return LLMInferenceResult(
                    batch_index=batch_index,
                    role=role,
                    provider_used=slot.provider,
                    model_used=slot.model,
                    success=True,
                    response=response,
                    error=None,
                )

            except Exception as exc:
                error_message = self._format_agent_error(
                    slot=slot,
                    exc=exc,
                    batch_index=batch_index,
                    role=role,
                )

                logger.exception("  ❌ %s", error_message)
                errors.append(error_message)

        return LLMInferenceResult(
            batch_index=batch_index,
            role=role,
            provider_used=None,
            model_used=None,
            success=False,
            response=None,
            error="Все LLM-агенты упали: " + " | ".join(errors),
        )

    async def _call_agent(
        self,
        *,
        slot: AgentSlot,
        prompt: str,
        data: list[str],
        system_instruction: str | None,
        batch_index: int,
        role: str,
        attempt: int,
    ) -> str:
        """
        Вызвать конкретного агента.

        Агенты синхронные, поэтому запускаем их через asyncio.to_thread().
        """

        logger.info(
            "  🤖 LLM запрос | role=%s | batch=%s | agent=%s | attempt=%d/%d",
            role,
            batch_index,
            slot.label,
            attempt,
            self._max_attempts_per_request,
        )

        return await asyncio.to_thread(
            slot.agent.process,
            prompt=prompt,
            data=data,
            system_instruction=system_instruction,
        )

    async def _next_start_index(self) -> int:
        """
        Получить стартового агента для следующего запроса.

        Lock нужен, потому что infer может вызываться параллельно.
        """

        async with self._lock:
            index = self._cursor
            self._cursor = (self._cursor + 1) % len(self._agents)
            return index

    def _empty_batch_result(
        self,
        *,
        batch_index: int,
        role: str,
    ) -> LLMInferenceResult:
        return LLMInferenceResult(
            batch_index=batch_index,
            role=role,
            provider_used=None,
            model_used=None,
            success=False,
            response=None,
            error="Пустой batch: нечего отправлять в LLM.",
        )

    @staticmethod
    def _format_agent_error(
        *,
        slot: AgentSlot,
        exc: Exception,
        batch_index: int,
        role: str,
    ) -> str:
        return (
            f"{slot.label} failed for role={role}, "
            f"batch={batch_index}: {type(exc).__name__}: {exc}"
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """
        Извлечь и валидировать JSON из ответа модели.
        Поддерживает:
            - чистый JSON;
            - ```json ... ``` блоки;
            - JSON внутри произвольного текста (ищет первый { или [).
        Возвращает нормализованную JSON-строку.
        Бросает ValueError, если JSON не найден или невалиден.
        """
        import json, re

        stripped = text.strip()

        # Вариант 1: уже чистый JSON
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass

        # Вариант 2: обёрнут в ```json ... ``` или просто ``` ... ```
        fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", stripped)
        if fence_match:
            candidate = fence_match.group(1).strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Найден code-блок, но внутри невалидный JSON: {exc}"
                ) from exc

        # Вариант 3: JSON где-то в тексте — ищем первый { или [
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start = stripped.find(start_char)
            if start == -1:
                continue
            # ищем последний соответствующий закрывающий символ
            end = stripped.rfind(end_char)
            if end <= start:
                continue
            candidate = stripped[start:end + 1]
            try:
                json.loads(candidate)
                logger.warning(
                    "JSON извлечён из «грязного» ответа (обрезан мусор до/после)."
                )
                return candidate
            except json.JSONDecodeError:
                continue

        raise ValueError(
            f"Ответ модели не содержит валидного JSON. "
            f"Первые 200 символов: {stripped[:200]!r}"
        )