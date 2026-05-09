"""
llm_inference/agent_factory.py

Фабрика LLM-агентов.

Задача:
    - принять provider/model из конфига;
    - создать нужный агент;
    - вернуть AgentSlot.

Фабрика не занимается:
    - ротацией;
    - retry;
    - вызовом модели;
    - обработкой батчей.
"""

from typing import Any

from _01_02_configs.settings import settings

from _03_01_agents.groq_agent import GroqAgent
from _03_01_agents.mistral_agent import MistralAgent

from _03_04_llm_inference._4_agent_slot import AgentSlot

class LLMAgentFactory:
    """
    Создаёт LLM-агентов по provider/model.
    """

    @classmethod
    def build_slots(
        cls,
        *,
        preferred_models: list[Any],
        temperature: float = 0.1,
    ) -> list[AgentSlot]:
        """
        Создать список AgentSlot из preset.preferred_models.
        """

        if not preferred_models:
            raise ValueError(
                "preferred_models пуст. Нужно указать хотя бы одну LLM-модель."
            )

        slots: list[AgentSlot] = []

        for item in preferred_models:
            provider = cls._extract_provider(item)
            model = cls._extract_model(item)

            slot = cls.build_slot(
                provider=provider,
                model=model,
                temperature=temperature,
            )

            slots.append(slot)

        return slots

    @classmethod
    def build_slot(
        cls,
        *,
        provider: str,
        model: str,
        temperature: float = 0.1,
    ) -> AgentSlot:
        """
        Создать один AgentSlot.
        """

        provider = provider.lower().strip()
        model = model.strip()

        if provider == "mistral":
            agent = MistralAgent(
                api_key=settings.api.mistral_key.get_secret_value(),
                model=model,
                temperature=temperature,
            )

            return AgentSlot(
                provider=provider,
                model=model,
                agent=agent,
            )

        if provider == "groq":
            agent = GroqAgent(
                api_key=settings.api.groq_main.get_secret_value(),
                model=model,
            )

            return AgentSlot(
                provider=provider,
                model=model,
                agent=agent,
            )

        raise ValueError(f"Неподдерживаемый LLM provider: {provider!r}")

    @staticmethod
    def _extract_provider(item: Any) -> str:
        """
        Достать provider из dict или pydantic/dataclass-объекта.
        """

        if isinstance(item, dict):
            provider = item.get("provider")
        else:
            provider = getattr(item, "provider", None)

        if not provider:
            raise ValueError(f"У модели не указан provider: {item!r}")

        return str(provider)

    @staticmethod
    def _extract_model(item: Any) -> str:
        """
        Достать model из dict или pydantic/dataclass-объекта.
        """

        if isinstance(item, dict):
            model = item.get("model")
        else:
            model = getattr(item, "model", None)

        if not model:
            raise ValueError(f"У модели не указан model: {item!r}")

        return str(model)