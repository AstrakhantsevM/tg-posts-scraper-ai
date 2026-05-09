import logging
from typing import Optional
from mistralai.client import Mistral

logger = logging.getLogger(__name__)

class MistralAgent:
    """
    Агент для взаимодействия с LLM-моделями через API Mistral AI.

    Отвечает за одну задачу: принять промпт + данные → вернуть ответ модели.
    Логика отказоустойчивости (retry, circuit-breaker и т.п.) намеренно вынесена
    наружу и не является ответственностью этого класса — используйте ``tenacity``
    или аналог на уровне вызывающего кода.

    Параметр ``temperature`` оставлен здесь (в отличие от GroqAgent), потому что
    Mistral SDK принимает его непосредственно в вызове ``chat.complete`` и он
    является частью контракта на генерацию, а не инфраструктурной настройкой.

    Пример использования::

        agent = MistralAgent(
            api_key="...",
            model="mistral-small-latest",
            temperature=0.1,
        )
        result = agent.process(
            prompt="Выдели ключевые темы.",
            data=["Пост 1...", "Пост 2..."],
            system_instruction="Ты аналитик социальных сетей.",
        )
        print(result)
    """

    #: Разделитель между элементами списка ``data`` при склейке в единый запрос.
    DATA_SEPARATOR = "\n---\n"

    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest",
        timeout: int = 30,
        temperature: float = 0.1,
    ) -> None:
        """
        Инициализация агента.

        :param api_key:     Секретный ключ Mistral API. Передаётся извне — хардкод запрещён.
        :param model:       Идентификатор модели. Варианты:
                            ``"mistral-small-latest"`` — быстрая и дешёвая,
                            ``"mistral-large-latest"`` — мощная,
                            ``"open-mistral-nemo"`` — open-source.
                            По умолчанию ``"mistral-small-latest"``.
        :param timeout:     Таймаут HTTP-запроса в секундах. По умолчанию 30.
                            Передаётся в ``httpx``-транспорт внутри SDK.
        :param temperature: Степень случайности генерации (от 0.0 до 1.0).
                            Значения ближе к 0 дают детерминированные ответы —
                            рекомендуется для аналитических задач.
                            По умолчанию 0.1.
        """
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self._client = Mistral(api_key=api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        prompt: str,
        data: list[str],
        system_instruction: Optional[str] = None,
    ) -> str:
        """
        Отправить запрос к модели и вернуть её ответ.

        Метод формирует список сообщений в формате ChatML, объединяет переданные
        данные через :attr:`DATA_SEPARATOR` и делает **один** вызов к API.
        При ошибке исключение пробрасывается вызывающему коду без перехвата —
        за retry-логику отвечает внешний слой (tenacity, celery и т.д.).

        :param prompt:             Инструкция для модели (например, содержимое файла
                                   из папки ``prompts/``).
        :param data:               Список строк для анализа (посты, документы и т.п.).
                                   Не может быть пустым.
        :param system_instruction: Опциональная системная роль (``role: system``).
                                   Если ``None`` — системное сообщение не добавляется.
        :return:                   Текст ответа модели (stripped).
        :raises ValueError:        Если ``data`` пуст.
        :raises mistralai.SDKError: При любой ошибке на стороне Mistral API
                                    (сетевые ошибки, rate-limit, невалидный ключ и т.п.).
        """
        if not data:
            raise ValueError("`data` не может быть пустым списком.")

        messages = self._build_messages(prompt, data, system_instruction)

        logger.debug(
            "Запрос к модели %s | temperature=%.2f | сообщений: %d | элементов данных: %d",
            self.model,
            self.temperature,
            len(messages),
            len(data),
        )

        response = self._client.chat.complete(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )

        content: str = response.choices[0].message.content.strip()
        logger.debug("Модель %s вернула %d символов.", self.model, len(content))
        return content

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        prompt: str,
        data: list[str],
        system_instruction: Optional[str],
    ) -> list[dict]:
        """
        Собрать список сообщений ChatML.

        Порядок сообщений:
        1. ``system`` — если передан ``system_instruction``.
        2. ``user``   — промпт + данные, разделённые :attr:`DATA_SEPARATOR`.

        Mistral рекомендует передавать системную инструкцию именно через роль
        ``system``, а не встраивать её в ``user``-сообщение — это повышает
        точность следования инструкции.

        :param prompt:             Инструкция пользователя.
        :param data:               Список строк для анализа.
        :param system_instruction: Системная установка или ``None``.
        :return:                   Список словарей ``{"role": ..., "content": ...}``.
        """
        messages = []

        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        formatted_data = self.DATA_SEPARATOR.join(data)
        user_content = f"{prompt}\n\nПОСТЫ ДЛЯ АНАЛИЗА:\n{formatted_data}"
        messages.append({"role": "user", "content": user_content})

        return messages