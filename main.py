import logging
from _01_02_configs.presets import load_preset
from _01_01_core.run_context import RunContext

from _05_01_scripts import scrape, process

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main(preset_name: str) -> None:
    logger.info("=== Запуск | пресет: %s ===", preset_name)

    preset = load_preset(preset_name)
    ctx = RunContext.from_preset(preset)

    # Парсим посты из каналов
    #scrape.run(ctx)

    # Анализруем посты с ИИ. YYYY-MM-DD или
    # target_date=None -> свежайшая дата
    process.run(ctx, target_date=None)

    # Формируем отчет. target_path=None -> на рабочий стол
    #report.run(ctx, target_path=None)

    logger.info("=== Готово | пресет: %s ===", preset_name)

if __name__ == "__main__":
    preset = "test"
    main(preset_name=preset)