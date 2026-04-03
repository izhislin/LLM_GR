"""Оркестратор пайплайна обработки звонков."""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.analytics.conversation_metrics import compute_metrics
from src.audio_splitter import split_stereo_to_mono, get_audio_info
from src.transcriber import transcribe_channel
from src.dialogue_builder import build_dialogue, dialogue_to_text
from src.llm_analyzer import analyze_dialogue
from src.text_corrector import load_profile, correct_text
from src.config import INPUT_DIR, TRANSCRIPTS_DIR, RESULTS_DIR, PROMPTS_DIR, DEFAULT_PROFILE
from src.metrics import (
    PROMETHEUS_AVAILABLE,
    start_metrics_server,
    track_stage,
)

if PROMETHEUS_AVAILABLE:
    from src.metrics import PROCESSING_SECONDS, PIPELINE_RTF, FILES_TOTAL

logger = logging.getLogger(__name__)


def process_audio_file(
    audio_path: Path,
    output_dir: Path | None = None,
    prompts_dir: Path | None = None,
    profile_name: str | None = DEFAULT_PROFILE,
) -> dict:
    """Обработать один аудиофайл через весь пайплайн.

    Args:
        audio_path: Путь к стерео аудиофайлу.
        output_dir: Куда сохранить результат (по умолчанию — data/results/).
        prompts_dir: Директория с промптами (по умолчанию — prompts/).
        profile_name: Имя профиля коррекции (без .yaml) или None.

    Returns:
        Словарь с полным результатом анализа.
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir or RESULTS_DIR)
    prompts_dir = Path(prompts_dir or PROMPTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = load_profile(profile_name)

    logger.info("=== Обработка: %s ===", audio_path.name)
    pipeline_start = time.monotonic()

    # 1. Информация об аудио
    info = get_audio_info(audio_path)
    logger.info(
        "Аудио: %.1f сек, %d каналов, %d Hz",
        info["duration_sec"], info["channels"], info["sample_rate"],
    )

    # 2. Разделение каналов
    logger.info("Разделение каналов...")
    transcripts_dir = output_dir.parent / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    with track_stage("split"):
        operator_path, client_path = split_stereo_to_mono(audio_path, transcripts_dir)

    # 3. Транскрибация
    logger.info("Транскрибация оператора...")
    with track_stage("transcribe_operator"):
        operator_utterances = transcribe_channel(operator_path)

    logger.info("Транскрибация клиента...")
    with track_stage("transcribe_client"):
        client_utterances = transcribe_channel(client_path)

    # 4. Сборка диалога
    dialogue = build_dialogue(operator_utterances, client_utterances)
    dialogue_text = dialogue_to_text(dialogue)

    # 4.5. Коррекция транскрипта
    with track_stage("correct"):
        dialogue_text = correct_text(dialogue_text, profile)

    # Build structured segments with corrected text
    transcript_segments = [
        {"speaker": t.speaker, "text": correct_text(t.text, profile), "start": t.start, "end": t.end}
        for t in dialogue
    ]

    # 4.6. Conversation metrics (из таймкодов, без LLM)
    conversation_metrics = compute_metrics(transcript_segments)

    # Сохраняем транскрипт (уже после коррекции)
    transcript_file = transcripts_dir / f"{audio_path.stem}.txt"
    transcript_file.write_text(dialogue_text, encoding="utf-8")
    logger.info("Транскрипт сохранён: %s", transcript_file)

    # 5. LLM-анализ
    llm_context = profile.get("llm_context") if profile else None
    logger.info("LLM-анализ...")
    with track_stage("llm_analyze"):
        analysis = analyze_dialogue(dialogue_text, prompts_dir, llm_context=llm_context, profile=profile)

    # 6. Метрики обработки
    processing_time = time.monotonic() - pipeline_start
    if PROMETHEUS_AVAILABLE:
        PROCESSING_SECONDS.observe(processing_time)
        if info["duration_sec"] > 0:
            PIPELINE_RTF.set(processing_time / info["duration_sec"])
        FILES_TOTAL.labels(status="ok").inc()

    # 7. Сборка результата
    result = {
        "file": audio_path.name,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "duration_sec": info["duration_sec"],
        "transcript": dialogue_text,
        "transcript_segments": transcript_segments,
        "conversation_metrics": conversation_metrics,
        **analysis,
    }

    # 8. Сохранение JSON
    result_file = output_dir / f"{audio_path.stem}.json"
    result_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Результат сохранён: %s (%.1f сек)", result_file, processing_time)

    return result


def main():
    """CLI-точка входа."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Обработка аудиофайла звонка")
    parser.add_argument("audio", help="Путь к стерео аудиофайлу")
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help="Имя профиля коррекции (без .yaml)")
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"Файл не найден: {audio_path}")
        sys.exit(1)

    start_metrics_server()
    result = process_audio_file(audio_path, profile_name=args.profile)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
