"""
llm_inference/agent_slot.py

Описание одного агента внутри LLMInferencePool.
"""

from dataclasses import dataclass
from typing import Protocol

class LLMAgentProtocol(Protocol):
    """
    Минимальный интерфейс LLM-агента.

    Под него подходят GroqAgent и MistralAgent.
    """

    model: str

    def process(
        self,
        prompt: str,
        data: list[str],
        system_instruction: str | None = None,
    ) -> str:
        ...


@dataclass(frozen=True)
class AgentSlot:
    """
    Один агент внутри пула.
    """

    provider: str
    model: str
    agent: LLMAgentProtocol

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"