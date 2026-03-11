"""Оркестратор пайплайна обработки звонков."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.audio_splitter import split_stereo_to_mono, get_audio_info
from src.transcriber import transcribe_channel
from src.dialogue_builder import build_dialogue, dialogue_to_text
from src.llm_analyzer import analyze_dialogue
from src.config import INPUT_DIR, TRANSCRIPTS_DIR, RESULTS_DIR, PROMPTS_DIR

logger = logging.getLogger(__name__)


def process_audio_file(
    audio_path: Path,
    output_dir: Path | None = None,
    prompts_dir: Path | None = None,
) -> dict:
    """Обработать один аудиофайл через весь пайплайн.

    Args:
        audio_path: Путь к стерео аудиофайлу.
        output_dir: Куда сохранить результат (по умолчанию — data/results/).
        prompts_dir: Директория с промптами (по умолчанию — prompts/).

    Returns:
        Словарь с полным результатом анализа.
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir or RESULTS_DIR)
    prompts_dir = Path(prompts_dir or PROMPTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Обработка: %s ===", audio_path.name)

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
    operator_path, client_path = split_stereo_to_mono(audio_path, transcripts_dir)

    # 3. Транскрибация
    logger.info("Транскрибация оператора...")
    operator_utterances = transcribe_channel(operator_path)

    logger.info("Транскрибация клиента...")
    client_utterances = transcribe_channel(client_path)

    # 4. Сборка диалога
    dialogue = build_dialogue(operator_utterances, client_utterances)
    dialogue_text = dialogue_to_text(dialogue)

    # Сохраняем транскрипт
    transcript_file = transcripts_dir / f"{audio_path.stem}.txt"
    transcript_file.write_text(dialogue_text, encoding="utf-8")
    logger.info("Транскрипт сохранён: %s", transcript_file)

    # 5. LLM-анализ
    logger.info("LLM-анализ...")
    analysis = analyze_dialogue(dialogue_text, prompts_dir)

    # 6. Сборка результата
    result = {
        "file": audio_path.name,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "duration_sec": info["duration_sec"],
        "transcript": dialogue_text,
        **analysis,
    }

    # 7. Сохранение JSON
    result_file = output_dir / f"{audio_path.stem}.json"
    result_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Результат сохранён: %s", result_file)

    return result


def main():
    """CLI-точка входа."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print("Использование: python -m src.pipeline <путь_к_аудиофайлу>")
        print(f"  или положите файлы в {INPUT_DIR}/")
        sys.exit(1)

    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        print(f"Файл не найден: {audio_path}")
        sys.exit(1)

    result = process_audio_file(audio_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
