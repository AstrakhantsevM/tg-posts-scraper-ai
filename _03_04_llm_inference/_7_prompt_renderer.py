# _03_04_llm_inference/_7_prompt_renderer.py

from __future__ import annotations

from typing import Any

from _01_01_core.run_context import RunContext
from _01_02_configs.settings import settings


def render_stage_prompt(
    *,
    ctx: RunContext,
    stage: str,
    region: str,
    batch_index: int | None = None,
    batches_total: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    stage_config = ctx.preset.prompt_stages.get(stage)

    if not stage_config:
        raise ValueError(f"В preset не настроен prompt_stages.{stage}")

    template_path = settings.PROMPTS_DIR / stage_config.template_file

    if not template_path.exists():
        raise FileNotFoundError(f"Prompt-template не найден: {template_path}")

    variables: dict[str, Any] = {
        "base_prompt": ctx.prompt.strip(),
        "region": region,
        "stage": stage,
        "batch_index": "" if batch_index is None else batch_index,
        "batches_total": "" if batches_total is None else batches_total,
    }

    if extra:
        variables.update(extra)

    template = template_path.read_text(encoding="utf-8")
    return _render_template(template, variables)


def _render_template(template: str, variables: dict[str, Any]) -> str:
    result = template

    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", str(value))

    return result.strip()