# История разработки

Правило: хранить только последние 10 записей. При добавлении новой переносить старые в
`agent_docs/development-history-archive.md`. Архив читать при необходимости.

---

Краткий журнал итераций проекта.

## Записи

### 2026-03-11 — Инициализация проекта и утверждение дизайна

- Определены требования: транскрибация двухканальных телефонных записей (русский) + LLM-обработка
- Выбран стек: GigaAM-v3 (ASR, Сбер) + Qwen3-8B (LLM через Ollama)
- GigaAM-v3 выбран вместо Whisper из-за 2-3x лучшего WER на русской телефонной речи
- Утверждён дизайн-документ: `docs/plans/2026-03-11-transcription-stand-design.md`
- Обновлён блок описания проекта в AGENTS.md

### 2026-03-11 — Audio splitter (Task 3)

- Создан `src/audio_splitter.py`: разделение стерео WAV на два моно-канала (оператор/клиент) через ffmpeg
- Функции: `get_audio_info()` (ffprobe), `split_stereo_to_mono()` (ffmpeg pan filter)
- Адаптация: `-map_channel` удалён в ffmpeg 8.x, заменён на `-af pan=mono|c0=c0/c1`
- Создан `tests/test_audio_splitter.py`: 4 теста (TDD), все проходят
- Создан `.venv` для запуска тестов (pytest)

### 2026-03-11 — Реализация всех модулей (Tasks 2, 4-8)

- `setup_server.sh`: скрипт настройки Ubuntu 22.04 (NVIDIA, CUDA, Ollama, Python deps)
- `src/transcriber.py`: обёртка GigaAM-v3 с lazy-загрузкой модели (singleton)
- `src/dialogue_builder.py`: склейка двух каналов в хронологический диалог
- `src/llm_analyzer.py`: клиент Ollama API с retry-логикой и JSON-парсингом
- `prompts/*.md`: промпты для суммаризации, оценки качества, извлечения данных
- `src/pipeline.py`: оркестратор пайплайна (CLI: `python -m src.pipeline <file>`)
- 16 тестов, все проходят (TDD, моки для GigaAM и Ollama)