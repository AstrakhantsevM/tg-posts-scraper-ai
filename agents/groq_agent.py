import logging
from typing import Optional
from groq import Groq

logger = logging.getLogger(__name__)

class GroqAgent:
    """
    Агент для взаимодействия с LLM-моделями через API Groq.

    Отвечает за одну задачу: принять промпт + данные → вернуть ответ модели.
    Вся логика отказоустойчивости (retry, circuit-breaker и т.п.) вынесена наружу
    и не является ответственностью этого класса.

    Пример использования::

        agent = GroqAgent(api_key="gsk_...", model="llama-3.1-8b-instant")
        result = agent.process(
            prompt="Выдели ключевые темы.",
            data=["Пост 1...", "Пост 2..."],
            system_instruction="Ты аналитик социальных сетей.",
        )
        print(result)
    """

    #: Разделитель между элементами списка data при склейке в единый запрос.
    DATA_SEPARATOR = "\n---\n"

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        timeout: int = 30,
    ) -> None:
        """
        Инициализация агента.

        :param api_key:  Секретный ключ Groq API. Передаётся извне — хардкод запрещён.
        :param model:    Идентификатор модели. По умолчанию llama-3.1-8b-instant.
        :param timeout:  Таймаут HTTP-запроса в секундах. По умолчанию 30.
        """
        self.model = model
        self.timeout = timeout
        self._client = Groq(api_key=api_key)

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
        за retry-логику отвечает внешний слой.

        :param prompt:             Инструкция для модели (например, содержимое файла
                                   из папки ``prompts/``).
        :param data:               Список строк для анализа (посты, документы и т.п.).
                                   Не может быть пустым.
        :param system_instruction: Опциональная системная роль (``role: system``).
                                   Если ``None`` — системное сообщение не добавляется.
        :return:                   Текст ответа модели (stripped).
        :raises ValueError:        Если ``data`` пуст.
        :raises groq.APIError:     При любой ошибке на стороне Groq API.
        """
        if not data:
            raise ValueError("`data` не может быть пустым списком.")

        messages = self._build_messages(prompt, data, system_instruction)

        logger.debug(
            "Запрос к модели %s | сообщений: %d | элементов данных: %d",
            self.model,
            len(messages),
            len(data),
        )

        response = self._client.chat.completions.create(
            messages=messages,
            model=self.model,
            timeout=self.timeout,
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