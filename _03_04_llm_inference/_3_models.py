"""
llm_inference/models.py

Модели данных для LLM-инференса.
"""

from dataclasses import dataclass


@dataclass
class LLMModelConfig:
    """
    Конфигурация одной LLM-модели из preset.preferred_models.
    """

    provider: str
    model: str


@dataclass
class LLMInferenceResult:
    """
    Результат одного вызова LLM.
    """

    batch_index: int
    role: str
    model_used: str | None
    provider_used: str | None
    success: bool
    response: str | None
    error: str | None


@dataclass
class LLMProcessResult:
    """
    Результат обработки одного региона.
    Использует результаты вызова
    """

    region: str
    posts_total: int
    batches_total: int
    mode: str
    results: list[LLMInferenceResult]
    final_summary: LLMInferenceResult | None
    errors: list[str]