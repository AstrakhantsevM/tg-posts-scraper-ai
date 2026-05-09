from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта — два уровня вверх от этого файла.
BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Общая конфигурация .env — определяется ОДИН раз, применяется ко всем.
# ---------------------------------------------------------------------------

_ENV_CONFIG = SettingsConfigDict(
    env_file=BASE_DIR / ".env",
    env_file_encoding="utf-8",
    extra="ignore",
)


# ---------------------------------------------------------------------------
# Группы настроек
# ---------------------------------------------------------------------------


class APISettings(BaseSettings):
    """
    Ключи внешних AI-сервисов.

    Все значения — ``SecretStr``: они не попадают в repr/логи.
    Получить значение: ``settings.api.mistral_key.get_secret_value()``.

    Переменные в .env:
        M1KEY   — Mistral API key
        O1KEY   — OpenRouter API key
        G1KEY   — Groq основной ключ
        G2KEY   — Groq резервный ключ (необязателен)
    """

    model_config = _ENV_CONFIG

    mistral_key: SecretStr = Field(alias="M1KEY")
    openrouter_key: SecretStr = Field(alias="O1KEY")
    groq_main: SecretStr = Field(alias="G1KEY")
    groq_reserve: Optional[SecretStr] = Field(default=None, alias="G2KEY")


class TelegramSettings(BaseSettings):
    """
    Учётные данные Telegram MTProto API (Telethon / Pyrogram).

    Переменные в .env:
        TG_API_ID   — числовой идентификатор приложения
        TG_API_HASH — хеш приложения
    """

    model_config = _ENV_CONFIG

    api_id: int = Field(alias="TG_API_ID")
    api_hash: str = Field(alias="TG_API_HASH")
    session_path: str = "sessions/default_session"


class ReportSettings(BaseSettings):
    """
    Параметры генерации .docx-отчётов.

    Все пути абсолютны (через ``BASE_DIR``), поэтому скрипт корректно
    работает независимо от рабочей директории при запуске.

    Переопределить через .env::

        DATA_ROOT=/mnt/nas/data
        REPORT_OUTPUT_DIR=/home/user/reports
    """

    model_config = _ENV_CONFIG

    # Пути
    DATA_ROOT: Path = BASE_DIR / "data"
    REPORT_OUTPUT_DIR: Path = Path.home() / "Desktop"

    # Оформление
    REPORT_FONT: str = "Arial"
    REPORT_LANG: str = "ru"

    # Поведение парсера
    RAW_POSTS_SCAN_LIMIT: int = 200

    @model_validator(mode="after")
    def _create_output_dir(self) -> "ReportSettings":
        """
        Создать директорию для отчётов после валидации всех полей.

        Используется ``model_validator`` вместо ``field_validator``, потому что
        создание файловой системы — это side-effect, который должен произойти
        **после** того, как модель полностью собрана и валидна.
        """
        self.REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        return self


# ---------------------------------------------------------------------------
# Главный класс настроек
# ---------------------------------------------------------------------------


class AppSettings(BaseSettings):
    """
    Единая точка входа для всей конфигурации приложения.

    Pydantic читает ``.env`` **один раз** и распределяет значения по вложенным
    моделям через ``model_validator``.  Прямое инстанцирование подклассов
    внутри ``AppSettings`` намеренно исключено — это предотвращает повторное
    чтение файла и скрытую инициализацию при импорте.

    Использование::

        from config import settings

        key = settings.api.mistral_key.get_secret_value()
        level = settings.LOG_LEVEL       # "INFO"
        path = settings.PROMPTS_DIR / "analyze.txt"
    """

    model_config = _ENV_CONFIG

    # Общие флаги
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    BASE_DIR: Path = BASE_DIR
    PROMPTS_DIR: Path = BASE_DIR / "prompts"
    MODULES_DIR: Path = BASE_DIR / "modules"

    # Пути (абсолютные)
    PROMPTS_DIR: Path = BASE_DIR / "prompts"
    MODULES_DIR: Path = BASE_DIR / "modules"

    # Вложенные группы — объявляем как Optional, заполняем в model_validator
    api: Optional[APISettings] = None
    tg: Optional[TelegramSettings] = None
    report: Optional[ReportSettings] = None

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """
        Привести LOG_LEVEL к верхнему регистру и проверить допустимость.

        Используем ``logging.getLevelName`` вместо ручного списка — стандартная
        библиотека уже знает все валидные уровни.

        :raises ValueError: Если значение не является стандартным уровнем логирования.
        """
        normalised = str(value).upper()
        if logging.getLevelName(normalised) == f"Level {normalised}":
            raise ValueError(
                f"Недопустимый уровень логирования: {value!r}. "
                f"Допустимые: DEBUG, INFO, WARNING, ERROR, CRITICAL."
            )
        return normalised

    @model_validator(mode="after")
    def _init_sub_settings(self) -> "AppSettings":
        """
        Инициализировать вложенные группы настроек после сборки ``AppSettings``.

        Подклассы создаются здесь, внутри Pydantic-жизненного цикла, — это
        гарантирует, что ошибки их инициализации будут пойманы и обёрнуты
        в стандартное ``ValidationError`` вместо «сырого» исключения при импорте.
        """
        self.api = APISettings()
        self.tg = TelegramSettings()
        self.report = ReportSettings()
        return self


# ---------------------------------------------------------------------------
# Синглтон — создаётся один раз при импорте модуля.
# Если .env отсутствует или содержит ошибки — падаем сразу, не в рантайме.
# ---------------------------------------------------------------------------

settings = AppSettings()