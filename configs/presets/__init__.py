import json
from pathlib import Path

from configs.presets.preset_model import Preset

_PRESETS_DIR = Path(__file__).parent


def load_preset(name: str) -> Preset:
    """
    Загрузить и валидировать пресет по имени.

    :param name: Имя пресета = имя JSON-файла без расширения.
    :return:     Валидированный объект :class:`Preset`.
    :raises FileNotFoundError: Если файл не найден.
    :raises ValidationError:   Если JSON не соответствует схеме.
    """
    path = _PRESETS_DIR / f"{name}.json"
    if not path.exists():
        available = [p.stem for p in _PRESETS_DIR.glob("*.json")]
        raise FileNotFoundError(
            f"Пресет '{name}' не найден. "
            f"Доступные: {available if available else '(нет JSON-файлов)'}"
        )
    return Preset.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_presets() -> list[str]:
    """Вернуть имена всех доступных пресетов."""
    return sorted(p.stem for p in _PRESETS_DIR.glob("*.json"))