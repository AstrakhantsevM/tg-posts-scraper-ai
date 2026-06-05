"""
scripts/process.py — этап LLM/AI-обработки собранных данных.

Единственная публичная функция:
    run(ctx)

Скрипт:
    1. Берёт контекст запуска.
    2. Для каждого региона ищет данные через llm_inference.searcher.
    3. Делит найденные посты/ответы на батчи через llm_inference.batcher.
    4. Передаёт батчи в llm_inference.inference.
    5. Если батч один — сохраняет прямой результат.
    6. Если батчей несколько:
        - делает summary по каждому батчу;
        - затем делает финальное summary по всем batch-summary.
    7. Сохраняет результат в JSON.

Ожидаемый путь сохранения:
    data/<output_label>/<YYYY-MM-DD>/<region>/llm_results.json

Ожидаемая структура результата::

    {
      "preset": "birth_support_check",
      "region": "Москва",
      "processed_at": "2026-04-27T12:00:00+00:00",
      "posts_total": 120,
      "batches_total": 3,
      "mode": "multi_batch_summary",
      "results": [
        {
          "batch_index": 0,
          "model_used": "openai-key-1",
          "success": true,
          "response": "...",
          "error": null
        }
      ],
      "final_summary": {
        "model_used": "openai-key-2",
        "success": true,
        "response": "...",
        "error": null
      },
      "errors": []
    }
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _01_01_core.run_context import RunContext

# Эти модули допишем отдельно.
# Здесь фиксируем ожидаемую архитектуру и точки интеграции.
from _03_04_llm_inference._1_searcher import LLMDataSearcher
from _03_04_llm_inference._2_batcher import LLMDataBatcher
from _03_04_llm_inference._3_models import LLMInferenceResult, LLMProcessResult
from _03_04_llm_inference.inference import LLMInferencePool

from _03_04_llm_inference._7_prompt_renderer import render_stage_prompt

logger = logging.getLogger(__name__)

def run(ctx: RunContext, target_date=None) -> None:
    """
    Запустить LLM-обработку для всех регионов из контекста.

    Синхронная обёртка над async-логикой, чтобы main.py мог оставаться
    синхронным.

    :param ctx: Контекст запуска.
    """
    asyncio.run(_run_async(ctx, target_date))

async def _run_async(ctx: RunContext, target_date) -> None:
    """
    Основной пайплайн LLM-обработки.

    Логика:
        - searcher подтягивает данные;
        - batcher режет данные на батчи;
        - inference_pool выполняет запросы к LLM с ротацией клиентов;
        - если батчей несколько, дополнительно выполняется финальное summary.
    """

    searcher = LLMDataSearcher()
    batcher = LLMDataBatcher(
        token_limit=ctx.preset.token_limit
    )

    inference_pool = LLMInferencePool.from_context(ctx)

    async with inference_pool:
        for region in ctx.region_channels:
            logger.info("▶ LLM-обработка региона: %s", region)

            # 1. Поиск данных для обработки
            items = searcher.find_items(ctx=ctx, region=region, target_date=target_date)

            if not items:
                logger.warning("  ⚠️ Нет данных для «%s», пропускаем.", region)
                continue

            logger.info("  🔎 Найдено объектов для обработки: %d", len(items))

            # 2. Подготовка текстов
            texts = [_item_to_text(item) for item in items]

            # 3. Нарезка на батчи
            batches = batcher.make_batches(texts)

            if not batches:
                logger.warning("  ⚠️ Не удалось сформировать батчи для «%s».", region)
                continue

            logger.info(
                "  📦 Батчей: %d | объектов: %d",
                len(batches),
                len(items),
            )

            # 4. LLM-обработка
            if len(batches) == 1:
                process_result = await _process_single_batch(
                    ctx=ctx,
                    region=region,
                    posts_total=len(items),
                    batch=batches[0],
                    inference_pool=inference_pool,
                )
            else:
                process_result = await _process_multiple_batches(
                    ctx=ctx,
                    region=region,
                    posts_total=len(items),
                    batches=batches,
                    inference_pool=inference_pool,
                )

            # 5. Сохранение
            _save_region(ctx, process_result)

            ok = sum(1 for r in process_result.results if r.success)
            err = len(process_result.errors)

            logger.info(
                "  ✅ %s: OK %d/%d батч(а) | ошибок %d",
                region,
                ok,
                process_result.batches_total,
                err,
            )

async def _process_single_batch(
    *,
    ctx: RunContext,
    region: str,
    posts_total: int,
    batch: Any,
    inference_pool: LLMInferencePool,
) -> LLMProcessResult:
    """
    Обработка региона, если все данные помещаются в один батч.

    В этом режиме нет промежуточных summary — батч сразу отправляется
    на основной промпт из ctx.prompt и системную инструкцию из ctx.system_instruction.
    """

    prompt = render_stage_prompt(
        ctx=ctx,
        stage="single_batch",
        region=region,
    )

    result = await inference_pool.infer(
        batch=batch,
        prompt=prompt,
        system_instruction=ctx.system_instruction,
        batch_index=0,
        role="single_batch",

    )

    errors = []
    if not result.success and result.error:
        errors.append(result.error)

    return LLMProcessResult(
        region=region,
        posts_total=posts_total,
        batches_total=1,
        mode="single_batch",
        results=[result],
        final_summary=None,
        errors=errors,
    )

async def _process_multiple_batches(
    *,
    ctx: RunContext,
    region: str,
    posts_total: int,
    batches: list[Any],
    inference_pool: LLMInferencePool,
) -> LLMProcessResult:
    """
    Обработка региона, если данных больше, чем помещается в один батч.

    Логика:
        1. Каждый батч отдельно отправляется на LLM.
        2. Для каждого батча просим сделать промежуточное summary.
        3. Затем все успешные batch-summary собираются в финальный батч.
        4. Финальный батч отправляется на итоговое summary.
    """

    concurrency = getattr(ctx.preset, "concurrency", 2)
    semaphore = asyncio.Semaphore(concurrency)

    async def _process_one_batch(index: int, batch: Any) -> LLMInferenceResult:
        async with semaphore:
            prompt = render_stage_prompt(
                ctx=ctx,
                stage="batch_summary",
                region=region,
                batch_index=index,
                batches_total=len(batches),
            )

            return await inference_pool.infer(
                batch=batch,
                prompt=prompt,
                system_instruction=ctx.system_instruction,
                batch_index=index,
                role="batch_summary",
            )

    tasks = [
        _process_one_batch(index=i, batch=batch)
        for i, batch in enumerate(batches)
    ]

    batch_results = await asyncio.gather(*tasks)

    successful_summaries = [
        result.response
        for result in batch_results
        if result.success and result.response
        and json.loads(result.response).get("found") is True
    ]

    errors = [
        result.error
        for result in batch_results
        if not result.success and result.error
    ]

    final_summary = None

    if successful_summaries:
        final_summary = await _make_final_summary(
            ctx=ctx,
            region=region,
            summaries=successful_summaries,
            inference_pool=inference_pool,
        )

        if not final_summary.success and final_summary.error:
            errors.append(final_summary.error)
    else:
        logger.error(
            "  ❌ Не удалось получить ни одного успешного batch-summary для «%s».",
            region,
        )

    return LLMProcessResult(
        region=region,
        posts_total=posts_total,
        batches_total=len(batches),
        mode="multi_batch_summary",
        results=batch_results,
        final_summary=final_summary,
        errors=errors,
    )

async def _make_final_summary(
    *,
    ctx: RunContext,
    region: str,
    summaries: list[str],
    inference_pool: LLMInferencePool,
) -> LLMInferenceResult:
    """
    Сделать итоговое summary по результатам обработки нескольких батчей.
    """

    prompt = render_stage_prompt(
        ctx=ctx,
        stage="final_summary",
        region=region,
        batches_total=len(summaries),
    )

    return await inference_pool.infer(
        batch=summaries,
        prompt=prompt,
        system_instruction=ctx.system_instruction,
        batch_index=-1,
        role="final_summary",
    )

def _item_to_text(item: Any) -> str:
    """
    Универсальное приведение объекта из searcher к тексту.

    Поддерживаем несколько вариантов будущей модели данных:
        - объект с методом to_plain_text();
        - объект с методом to_llm_text();
        - dict;
        - обычная строка;
        - любой другой объект через str().
    """

    if hasattr(item, "to_llm_text"):
        return item.to_llm_text()

    if hasattr(item, "to_plain_text"):
        return item.to_plain_text()

    if isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False)

    if isinstance(item, str):
        return item

    return str(item)

def _save_region(ctx: RunContext, result: LLMProcessResult) -> None:
    """
    Сохранить результаты LLM-обработки в:
        data/<output_label>/<YYYY-MM-DD>/<region>/llm_results.json
    """

    region_dir = ctx.data_dir / _safe_dir_name(result.region)
    region_dir.mkdir(parents=True, exist_ok=True)

    output_path = region_dir / "llm_results.json"

    payload = {
        "preset": getattr(ctx.preset, "output_label", None) or "default",
        "region": result.region,
        "processed_at": datetime.now(tz=timezone.utc).isoformat(),
        "posts_total": result.posts_total,
        "batches_total": result.batches_total,
        "mode": result.mode,
        "results": [
            _serialize_inference_result(item)
            for item in result.results
        ],
        "final_summary": (
            _serialize_inference_result(result.final_summary)
            if result.final_summary
            else None
        ),
        "errors": result.errors,
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("  💾 LLM-результат сохранён → %s", output_path)

def _serialize_inference_result(result: LLMInferenceResult) -> dict[str, Any]:
    """
    Привести результат инференса к JSON-compatible dict.
    """

    return {
        "batch_index": result.batch_index,
        "role": getattr(result, "role", None),
        "model_used": result.model_used,
        "success": result.success,
        "response": result.response,
        "error": result.error,
    }

def _safe_dir_name(name: str) -> str:
    """
    Безопасное имя директории для региона.
    """

    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
    return cleaned or "_unknown_region"