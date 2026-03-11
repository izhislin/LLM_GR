# Транскрибация и LLM-анализ телефонных звонков

Локальный стенд для транскрибации двухканальных телефонных аудиозаписей (русский язык) и их интеллектуальной обработки: суммаризация, оценка качества оператора, извлечение данных.

## Стек

- **ASR:** GigaAM-v3 (Сбер, MIT) — WER 8.4% на русском, ~1GB VRAM
- **LLM:** Qwen3-8B через Ollama — суммаризация, оценка, извлечение данных
- **Аудио:** ffmpeg — разделение стерео на моно-каналы
- **Язык:** Python 3.10+

## Требования к серверу

- NVIDIA GPU с 16+ GB VRAM (тестировалось на RTX 5060 Ti 16GB)
- Ubuntu 22.04 LTS
- 64GB RAM (рекомендуется)
- ~15GB диска на модели

## Быстрый старт

### 1. Настройка сервера

```bash
git clone <repo-url>
cd 01_LLM_GR
chmod +x setup_server.sh
./setup_server.sh
```

Скрипт установит NVIDIA-драйвер, CUDA, Python-зависимости, Ollama и загрузит модель Qwen3-8B. При первом запуске потребуется перезагрузка после установки драйвера.

### 2. Активация окружения

```bash
source ~/venv_transcribe/bin/activate
```

### 3. Обработка звонка

```bash
python -m src.pipeline data/input/your_call.wav
```

Результат сохраняется в `data/results/your_call.json`.

## Пайплайн

```
Аудиофайл (stereo WAV/MP3)
  → ffmpeg: разделение на оператор (L) и клиент (R)
  → GigaAM-v3: транскрипция каждого канала с таймкодами
  → Сборка хронологического диалога
  → Qwen3-8B: суммаризация → оценка качества → извлечение данных
  → JSON-результат
```

## Структура проекта

```
├── src/
│   ├── config.py             # Конфигурация (пути, модели, параметры)
│   ├── audio_splitter.py     # ffmpeg: stereo → 2x mono
│   ├── transcriber.py        # GigaAM-v3 обёртка
│   ├── dialogue_builder.py   # Склейка каналов в диалог
│   ├── llm_analyzer.py       # Ollama API клиент
│   └── pipeline.py           # Главный оркестратор
├── prompts/
│   ├── summarize.md          # Промпт суммаризации
│   ├── quality_score.md      # Промпт оценки качества
│   └── extract_data.md       # Промпт извлечения данных
├── tests/                    # Тесты (pytest)
├── data/
│   ├── input/                # Входные аудиофайлы
│   ├── transcripts/          # Транскрипты
│   └── results/              # JSON-результаты
├── setup_server.sh           # Скрипт настройки сервера
└── requirements.txt          # Python-зависимости
```

## Тесты

```bash
pytest tests/ -v
```

16 тестов покрывают все модули. Тесты работают без GPU (используют моки для GigaAM и Ollama).

## Документация

- `docs/plans/2026-03-11-transcription-stand-design.md` — дизайн-документ
- `agent_docs/index.md` — карта документации
