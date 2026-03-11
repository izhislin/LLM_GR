# Тестовый стенд транскрибации — План реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Собрать работающий пайплайн: аудиофайл (stereo) → транскрипция (GigaAM-v3) → LLM-анализ (Qwen3-8B через Ollama) → JSON-результат.

**Architecture:** Последовательный пайплайн из 4 модулей (audio_splitter → transcriber → dialogue_builder → llm_analyzer), связанных оркестратором pipeline.py. ASR работает через PyTorch/GigaAM напрямую, LLM — через Ollama REST API. Промпты хранятся в файлах `prompts/*.md`.

**Tech Stack:** Python 3.10, GigaAM-v3 (PyTorch), Ollama + Qwen3-8B, ffmpeg, pytest.

**Дизайн-документ:** `docs/plans/2026-03-11-transcription-stand-design.md`

---

### Task 1: Скаффолдинг проекта

**Files:**
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `requirements.txt`
- Create: `data/input/.gitkeep`
- Create: `data/transcripts/.gitkeep`
- Create: `data/results/.gitkeep`
- Create: `prompts/.gitkeep`

**Step 1: Создать директории**

```bash
mkdir -p src tests data/input data/transcripts data/results prompts
```

**Step 2: Создать `src/config.py`**

```python
"""Конфигурация пайплайна."""

from pathlib import Path

# Корень проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Директории данных
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
RESULTS_DIR = DATA_DIR / "results"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# GigaAM
GIGAAM_MODEL = "v3_e2e_rnnt"
GIGAAM_DEVICE = None  # None = auto (CUDA if available)

# Ollama
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_TIMEOUT = 120  # секунд на один вызов LLM

# Аудио
SAMPLE_RATE = 16000  # GigaAM ожидает 16kHz
```

**Step 3: Создать `src/__init__.py` и `tests/__init__.py`**

Пустые файлы.

**Step 4: Создать `tests/conftest.py`**

```python
"""Общие фикстуры для тестов."""

import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR
```

**Step 5: Создать `requirements.txt`**

```
# ASR
gigaam[longform]

# LLM client
requests>=2.28

# Testing
pytest>=7.0

# Utilities (уже в составе gigaam, но фиксируем)
torch>=2.0
torchaudio>=2.0
```

**Step 6: Создать .gitkeep файлы и `tests/fixtures/`**

```bash
touch src/__init__.py tests/__init__.py
touch data/input/.gitkeep data/transcripts/.gitkeep data/results/.gitkeep prompts/.gitkeep
mkdir -p tests/fixtures
touch tests/fixtures/.gitkeep
```

**Step 7: Commit**

```bash
git add src/ tests/ data/ prompts/ requirements.txt
git commit -m "feat: scaffold project structure with config, tests, and data directories"
```

---

### Task 2: Скрипт настройки сервера

**Files:**
- Create: `setup_server.sh`

**Step 1: Создать `setup_server.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Настройка Ubuntu 22.04 для тестового стенда транскрибации
# RTX 5060 Ti 16GB + GigaAM-v3 + Ollama (Qwen3-8B)
# ============================================================

echo "=== 1. Системные зависимости ==="
sudo apt update && sudo apt install -y \
    build-essential \
    ffmpeg \
    git \
    curl \
    python3-venv \
    python3-pip

echo "=== 2. NVIDIA Driver + CUDA Toolkit ==="
echo "Проверяем наличие nvidia-smi..."
if ! command -v nvidia-smi &> /dev/null; then
    echo "NVIDIA драйвер не найден. Устанавливаем..."
    # Добавляем CUDA-репозиторий NVIDIA для Ubuntu 22.04
    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
    sudo dpkg -i cuda-keyring_1.1-1_all.deb
    rm cuda-keyring_1.1-1_all.deb
    sudo apt update
    # Устанавливаем CUDA Toolkit (включает драйвер)
    sudo apt install -y cuda-toolkit-12-8 cuda-drivers
    echo ""
    echo "!!! ВАЖНО: Перезагрузите сервер после установки драйвера !!!"
    echo "После перезагрузки запустите этот скрипт ещё раз."
    exit 0
else
    echo "NVIDIA драйвер найден:"
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
fi

echo "=== 3. Python virtual environment ==="
VENV_DIR="$HOME/venv_transcribe"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

echo "=== 4. Python зависимости ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 5. Ollama ==="
if ! command -v ollama &> /dev/null; then
    echo "Устанавливаем Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "Загружаем модель Qwen3-8B..."
ollama pull qwen3:8b

echo "=== 6. Проверка ==="
echo ""
echo "--- GPU ---"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv
echo ""
echo "--- Python ---"
python3 -c "import torch; print(f'PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}')"
echo ""
echo "--- ffmpeg ---"
ffmpeg -version | head -1
echo ""
echo "--- Ollama ---"
ollama --version
echo ""
echo "=== Готово! ==="
echo "Активируйте окружение: source $VENV_DIR/bin/activate"
echo "Запустите пайплайн: python3 src/pipeline.py data/input/your_file.wav"
```

**Step 2: Сделать исполняемым и commit**

```bash
chmod +x setup_server.sh
git add setup_server.sh
git commit -m "feat: add server setup script for Ubuntu 22.04 + CUDA + Ollama"
```

---

### Task 3: Модуль разделения каналов (audio_splitter)

**Files:**
- Create: `tests/test_audio_splitter.py`
- Create: `src/audio_splitter.py`
- Create: `tests/fixtures/test_stereo.wav` (генерируется в тесте)

**Step 1: Написать тесты**

```python
"""Тесты для audio_splitter."""

import subprocess
import wave
import struct
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.audio_splitter import split_stereo_to_mono, get_audio_info


@pytest.fixture
def stereo_wav(tmp_path):
    """Создаёт минимальный стерео WAV-файл для тестов."""
    filepath = tmp_path / "test_stereo.wav"
    sample_rate = 16000
    duration = 1  # 1 секунда
    n_samples = sample_rate * duration

    with wave.open(str(filepath), "w") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        for i in range(n_samples):
            # Левый канал: синус 440Hz, правый: синус 880Hz
            left = int(32767 * 0.5 * __import__("math").sin(2 * 3.14159 * 440 * i / sample_rate))
            right = int(32767 * 0.5 * __import__("math").sin(2 * 3.14159 * 880 * i / sample_rate))
            wav_file.writeframes(struct.pack("<hh", left, right))

    return filepath


def test_split_stereo_creates_two_mono_files(stereo_wav, tmp_path):
    """split_stereo_to_mono должен создать два моно WAV-файла."""
    left, right = split_stereo_to_mono(stereo_wav, tmp_path)

    assert left.exists(), "Левый канал не создан"
    assert right.exists(), "Правый канал не создан"

    # Проверяем, что оба файла — моно
    with wave.open(str(left)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000

    with wave.open(str(right)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000


def test_split_stereo_file_naming(stereo_wav, tmp_path):
    """Файлы должны называться <имя>_operator.wav и <имя>_client.wav."""
    left, right = split_stereo_to_mono(stereo_wav, tmp_path)

    assert left.name == "test_stereo_operator.wav"
    assert right.name == "test_stereo_client.wav"


def test_get_audio_info(stereo_wav):
    """get_audio_info должен вернуть информацию о файле."""
    info = get_audio_info(stereo_wav)

    assert info["channels"] == 2
    assert info["sample_rate"] == 16000
    assert info["duration_sec"] == pytest.approx(1.0, abs=0.1)


def test_split_mono_raises_error(tmp_path):
    """Моно-файл должен вызывать ошибку."""
    mono_path = tmp_path / "mono.wav"
    with wave.open(str(mono_path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(struct.pack("<h", 0) * 16000)

    with pytest.raises(ValueError, match="stereo"):
        split_stereo_to_mono(mono_path, tmp_path)
```

**Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_audio_splitter.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.audio_splitter'`

**Step 3: Написать реализацию `src/audio_splitter.py`**

```python
"""Разделение стерео-аудио на два моно-канала через ffmpeg."""

import json
import subprocess
from pathlib import Path


def get_audio_info(audio_path: Path) -> dict:
    """Получить информацию об аудиофайле через ffprobe."""
    audio_path = Path(audio_path)
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    audio_stream = next(
        s for s in data["streams"] if s["codec_type"] == "audio"
    )
    return {
        "channels": int(audio_stream["channels"]),
        "sample_rate": int(audio_stream["sample_rate"]),
        "duration_sec": float(audio_stream.get("duration", 0)),
    }


def split_stereo_to_mono(
    audio_path: Path, output_dir: Path
) -> tuple[Path, Path]:
    """Разделить стерео WAV на два моно-файла (оператор = левый, клиент = правый).

    Returns:
        (operator_path, client_path)
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    info = get_audio_info(audio_path)
    if info["channels"] < 2:
        raise ValueError(
            f"Файл должен быть stereo (2 канала), получен: {info['channels']} канал(ов)"
        )

    stem = audio_path.stem
    operator_path = output_dir / f"{stem}_operator.wav"
    client_path = output_dir / f"{stem}_client.wav"

    # Извлекаем левый канал (оператор)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-map_channel", "0.0.0",
            "-ar", "16000",
            "-ac", "1",
            str(operator_path),
        ],
        capture_output=True, check=True,
    )

    # Извлекаем правый канал (клиент)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-map_channel", "0.0.1",
            "-ar", "16000",
            "-ac", "1",
            str(client_path),
        ],
        capture_output=True, check=True,
    )

    return operator_path, client_path
```

**Step 4: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_audio_splitter.py -v
```

Expected: 4 PASSED

**Step 5: Commit**

```bash
git add src/audio_splitter.py tests/test_audio_splitter.py
git commit -m "feat: add audio_splitter module with ffmpeg stereo-to-mono splitting"
```

---

### Task 4: Модуль транскрибации (transcriber)

**Files:**
- Create: `tests/test_transcriber.py`
- Create: `src/transcriber.py`

**Важно:** GigaAM требует GPU. Тесты используют моки для локального запуска, интеграционный тест — на сервере.

**Step 1: Написать тесты**

```python
"""Тесты для transcriber (с моками GigaAM)."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.transcriber import transcribe_channel, Utterance


def _mock_utterances():
    """Имитация ответа GigaAM transcribe_longform."""
    return [
        {"transcription": "Добрый день, компания Гравител.", "boundaries": (0.0, 2.5)},
        {"transcription": "Меня зовут Анна.", "boundaries": (2.5, 4.0)},
    ]


@patch("src.transcriber._get_model")
def test_transcribe_channel_returns_utterances(mock_get_model, tmp_path):
    """transcribe_channel должен вернуть список Utterance."""
    mock_model = MagicMock()
    mock_model.transcribe_longform.return_value = _mock_utterances()
    mock_get_model.return_value = mock_model

    fake_audio = tmp_path / "test.wav"
    fake_audio.touch()

    result = transcribe_channel(fake_audio)

    assert len(result) == 2
    assert isinstance(result[0], Utterance)
    assert result[0].text == "Добрый день, компания Гравител."
    assert result[0].start == 0.0
    assert result[0].end == 2.5


@patch("src.transcriber._get_model")
def test_transcribe_channel_empty_audio(mock_get_model, tmp_path):
    """Пустое аудио должно вернуть пустой список."""
    mock_model = MagicMock()
    mock_model.transcribe_longform.return_value = []
    mock_get_model.return_value = mock_model

    fake_audio = tmp_path / "empty.wav"
    fake_audio.touch()

    result = transcribe_channel(fake_audio)
    assert result == []
```

**Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_transcriber.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.transcriber'`

**Step 3: Написать реализацию `src/transcriber.py`**

```python
"""Транскрибация аудио через GigaAM-v3."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.config import GIGAAM_MODEL, GIGAAM_DEVICE

logger = logging.getLogger(__name__)

# Ленивая загрузка модели (singleton)
_model = None


@dataclass
class Utterance:
    """Одна фраза с таймкодами."""
    text: str
    start: float  # секунды
    end: float    # секунды


def _get_model():
    """Загрузить модель GigaAM (singleton, первый вызов скачивает модель)."""
    global _model
    if _model is None:
        import gigaam
        logger.info("Загружаю GigaAM модель %s...", GIGAAM_MODEL)
        _model = gigaam.load_model(
            GIGAAM_MODEL,
            fp16_encoder=True,
            device=GIGAAM_DEVICE,
        )
        logger.info("GigaAM загружена.")
    return _model


def transcribe_channel(audio_path: Path) -> list[Utterance]:
    """Транскрибировать моно-аудиофайл.

    Args:
        audio_path: Путь к моно WAV-файлу (16kHz).

    Returns:
        Список Utterance с текстом и таймкодами.
    """
    audio_path = Path(audio_path)
    model = _get_model()

    raw_utterances = model.transcribe_longform(str(audio_path))

    utterances = []
    for item in raw_utterances:
        start, end = item["boundaries"]
        utterances.append(Utterance(
            text=item["transcription"],
            start=start,
            end=end,
        ))

    logger.info(
        "Транскрибировано %d фраз из %s", len(utterances), audio_path.name
    )
    return utterances


def reset_model():
    """Выгрузить модель из памяти (для тестов и переключения моделей)."""
    global _model
    _model = None
```

**Step 4: Запустить тесты**

```bash
pytest tests/test_transcriber.py -v
```

Expected: 2 PASSED

**Step 5: Commit**

```bash
git add src/transcriber.py tests/test_transcriber.py
git commit -m "feat: add transcriber module wrapping GigaAM-v3 with lazy model loading"
```

---

### Task 5: Модуль сборки диалога (dialogue_builder)

**Files:**
- Create: `tests/test_dialogue_builder.py`
- Create: `src/dialogue_builder.py`

Это чистая логика без внешних зависимостей — полностью тестируемо.

**Step 1: Написать тесты**

```python
"""Тесты для dialogue_builder."""

import pytest
from src.dialogue_builder import build_dialogue, DialogueTurn
from src.transcriber import Utterance


def test_build_dialogue_interleaves_speakers():
    """Фразы из двух каналов должны чередоваться по времени."""
    operator = [
        Utterance(text="Добрый день.", start=0.0, end=1.5),
        Utterance(text="Чем могу помочь?", start=3.0, end=4.5),
    ]
    client = [
        Utterance(text="Здравствуйте.", start=1.5, end=2.8),
        Utterance(text="У меня вопрос по тарифу.", start=5.0, end=7.0),
    ]

    dialogue = build_dialogue(operator, client)

    assert len(dialogue) == 4
    assert dialogue[0].speaker == "Оператор"
    assert dialogue[0].text == "Добрый день."
    assert dialogue[1].speaker == "Клиент"
    assert dialogue[1].text == "Здравствуйте."
    assert dialogue[2].speaker == "Оператор"
    assert dialogue[3].speaker == "Клиент"


def test_build_dialogue_empty_channels():
    """Пустые каналы — пустой диалог."""
    dialogue = build_dialogue([], [])
    assert dialogue == []


def test_build_dialogue_one_channel_empty():
    """Если один канал пуст — диалог из одного спикера."""
    operator = [Utterance(text="Алло?", start=0.0, end=1.0)]

    dialogue = build_dialogue(operator, [])

    assert len(dialogue) == 1
    assert dialogue[0].speaker == "Оператор"


def test_build_dialogue_formats_to_text():
    """Диалог должен форматироваться в читаемый текст."""
    operator = [Utterance(text="Добрый день.", start=0.0, end=1.5)]
    client = [Utterance(text="Привет.", start=2.0, end=3.0)]

    dialogue = build_dialogue(operator, client)
    text = "\n".join(str(turn) for turn in dialogue)

    assert "[00:00:00]" in text
    assert "Оператор:" in text
    assert "Клиент:" in text


def test_dialogue_turn_str_format():
    """DialogueTurn.__str__ должен выдавать формат [HH:MM:SS] Спикер: Текст."""
    turn = DialogueTurn(speaker="Оператор", text="Добрый день.", start=65.5, end=67.0)
    assert str(turn) == "[00:01:05] Оператор: Добрый день."
```

**Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_dialogue_builder.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Написать реализацию `src/dialogue_builder.py`**

```python
"""Сборка хронологического диалога из двух каналов."""

from dataclasses import dataclass

from src.transcriber import Utterance


@dataclass
class DialogueTurn:
    """Одна реплика в диалоге."""
    speaker: str
    text: str
    start: float
    end: float

    def __str__(self) -> str:
        timestamp = _format_timestamp(self.start)
        return f"[{timestamp}] {self.speaker}: {self.text}"


def _format_timestamp(seconds: float) -> str:
    """Форматировать секунды в HH:MM:SS."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_dialogue(
    operator_utterances: list[Utterance],
    client_utterances: list[Utterance],
) -> list[DialogueTurn]:
    """Собрать хронологический диалог из двух каналов.

    Фразы из обоих каналов объединяются и сортируются по времени начала.

    Args:
        operator_utterances: Фразы оператора (левый канал).
        client_utterances: Фразы клиента (правый канал).

    Returns:
        Список DialogueTurn, отсортированный хронологически.
    """
    turns: list[DialogueTurn] = []

    for utt in operator_utterances:
        turns.append(DialogueTurn(
            speaker="Оператор", text=utt.text, start=utt.start, end=utt.end,
        ))

    for utt in client_utterances:
        turns.append(DialogueTurn(
            speaker="Клиент", text=utt.text, start=utt.start, end=utt.end,
        ))

    turns.sort(key=lambda t: t.start)
    return turns


def dialogue_to_text(dialogue: list[DialogueTurn]) -> str:
    """Преобразовать диалог в читаемый текст."""
    return "\n".join(str(turn) for turn in dialogue)
```

**Step 4: Запустить тесты**

```bash
pytest tests/test_dialogue_builder.py -v
```

Expected: 5 PASSED

**Step 5: Commit**

```bash
git add src/dialogue_builder.py tests/test_dialogue_builder.py
git commit -m "feat: add dialogue_builder for chronological merge of two channels"
```

---

### Task 6: Модуль LLM-анализа (llm_analyzer)

**Files:**
- Create: `tests/test_llm_analyzer.py`
- Create: `src/llm_analyzer.py`

**Step 1: Написать тесты**

```python
"""Тесты для llm_analyzer (с моками Ollama API)."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.llm_analyzer import call_llm, analyze_dialogue, load_prompt


@pytest.fixture
def sample_dialogue_text():
    return (
        "[00:00:00] Оператор: Добрый день, компания Гравител.\n"
        "[00:00:03] Клиент: Здравствуйте, хочу узнать про тариф.\n"
        "[00:00:08] Оператор: Конечно, какой тариф вас интересует?\n"
    )


@patch("src.llm_analyzer.requests.post")
def test_call_llm_returns_parsed_json(mock_post):
    """call_llm должен вернуть распарсенный JSON из ответа Ollama."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": '{"topic": "тариф", "outcome": "консультация"}'}
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    result = call_llm(
        system_prompt="Ты аналитик.",
        user_message="Текст диалога.",
        response_schema={"type": "object", "properties": {"topic": {"type": "string"}}},
    )

    assert result["topic"] == "тариф"


@patch("src.llm_analyzer.requests.post")
def test_call_llm_retries_on_invalid_json(mock_post):
    """При невалидном JSON должен быть повторный вызов."""
    bad_response = MagicMock()
    bad_response.json.return_value = {
        "message": {"content": "это не json"}
    }
    bad_response.raise_for_status = MagicMock()

    good_response = MagicMock()
    good_response.json.return_value = {
        "message": {"content": '{"topic": "тариф"}'}
    }
    good_response.raise_for_status = MagicMock()

    mock_post.side_effect = [bad_response, good_response]

    result = call_llm(
        system_prompt="Ты аналитик.",
        user_message="Текст.",
    )

    assert result["topic"] == "тариф"
    assert mock_post.call_count == 2


def test_load_prompt(tmp_path):
    """load_prompt должен загрузить текст промпта из файла."""
    prompt_file = tmp_path / "test_prompt.md"
    prompt_file.write_text("Ты аналитик колл-центра.\nАнализируй диалог.")

    result = load_prompt(prompt_file)

    assert "Ты аналитик колл-центра." in result
```

**Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_llm_analyzer.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Написать реализацию `src/llm_analyzer.py`**

```python
"""Клиент для Ollama API — отправка диалога на LLM-анализ."""

import json
import logging
from pathlib import Path

import requests

from src.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


def load_prompt(prompt_path: Path) -> str:
    """Загрузить текст промпта из файла."""
    return Path(prompt_path).read_text(encoding="utf-8").strip()


def call_llm(
    system_prompt: str,
    user_message: str,
    response_schema: dict | None = None,
) -> dict:
    """Отправить запрос в Ollama и получить JSON-ответ.

    Args:
        system_prompt: Системный промпт (роль, инструкции).
        user_message: Пользовательское сообщение (диалог).
        response_schema: JSON Schema для структурированного ответа.

    Returns:
        Распарсенный JSON-словарь.

    Raises:
        RuntimeError: Если не удалось получить валидный JSON после ретраев.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {"temperature": 0},
    }
    if response_schema:
        payload["format"] = response_schema

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Ollama вызов (попытка %d/%d)...", attempt, MAX_RETRIES)

        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()

        content = resp.json()["message"]["content"]

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning(
                "Попытка %d: невалидный JSON от LLM: %s", attempt, content[:200]
            )

    raise RuntimeError(
        f"Не удалось получить валидный JSON от LLM после {MAX_RETRIES} попыток"
    )


def analyze_dialogue(
    dialogue_text: str, prompts_dir: Path
) -> dict:
    """Выполнить полный анализ диалога: суммаризация, оценка, извлечение.

    Args:
        dialogue_text: Текст диалога с таймкодами и метками.
        prompts_dir: Директория с промпт-файлами.

    Returns:
        Словарь с ключами: summary, quality_score, extracted_data.
    """
    results = {}

    # 1. Суммаризация
    logger.info("Суммаризация...")
    summary_prompt = load_prompt(prompts_dir / "summarize.md")
    results["summary"] = call_llm(
        system_prompt=summary_prompt,
        user_message=dialogue_text,
    )

    # 2. Оценка качества
    logger.info("Оценка качества...")
    quality_prompt = load_prompt(prompts_dir / "quality_score.md")
    results["quality_score"] = call_llm(
        system_prompt=quality_prompt,
        user_message=dialogue_text,
    )

    # 3. Извлечение данных
    logger.info("Извлечение данных...")
    extract_prompt = load_prompt(prompts_dir / "extract_data.md")
    results["extracted_data"] = call_llm(
        system_prompt=extract_prompt,
        user_message=dialogue_text,
    )

    return results
```

**Step 4: Запустить тесты**

```bash
pytest tests/test_llm_analyzer.py -v
```

Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/llm_analyzer.py tests/test_llm_analyzer.py
git commit -m "feat: add llm_analyzer module with Ollama API client and retry logic"
```

---

### Task 7: Промпты для LLM

**Files:**
- Create: `prompts/summarize.md`
- Create: `prompts/quality_score.md`
- Create: `prompts/extract_data.md`

**Step 1: Создать `prompts/summarize.md`**

```markdown
Ты — аналитик колл-центра. Тебе предоставлен транскрипт телефонного разговора между оператором и клиентом.

Проанализируй диалог и верни JSON со следующей структурой:

{
  "topic": "Основная тема разговора (1 предложение)",
  "outcome": "Результат/итог разговора (1 предложение)",
  "key_points": ["Ключевой момент 1", "Ключевой момент 2", "..."]
}

Правила:
- key_points: от 2 до 5 пунктов, каждый — одно предложение
- Пиши на русском языке
- Будь конкретен, избегай общих фраз
- Верни ТОЛЬКО валидный JSON, без пояснений
```

**Step 2: Создать `prompts/quality_score.md`**

```markdown
Ты — супервизор колл-центра. Оцени качество работы оператора по транскрипту разговора.

Верни JSON со следующей структурой:

{
  "total": <средний балл от 1 до 10>,
  "criteria": {
    "greeting": {"score": <1-10>, "comment": "<пояснение>"},
    "listening": {"score": <1-10>, "comment": "<пояснение>"},
    "solution": {"score": <1-10>, "comment": "<пояснение>"},
    "politeness": {"score": <1-10>, "comment": "<пояснение>"},
    "closing": {"score": <1-10>, "comment": "<пояснение>"}
  }
}

Критерии оценки:
- greeting: Приветствие (представился ли, назвал ли компанию)
- listening: Активное слушание (переспрашивал, уточнял, не перебивал)
- solution: Решение вопроса (предложил решение, был ли полезен)
- politeness: Вежливость и тон (уважительное общение)
- closing: Завершение (подвёл итоги, попрощался, спросил есть ли вопросы)

total — среднее арифметическое всех критериев, округлённое до целого.

Правила:
- Пиши comment на русском, кратко (1 предложение)
- Верни ТОЛЬКО валидный JSON, без пояснений
```

**Step 3: Создать `prompts/extract_data.md`**

```markdown
Ты — аналитик данных. Извлеки структурированную информацию из транскрипта телефонного разговора.

Верни JSON со следующей структурой:

{
  "client_name": "<ФИО клиента или null если не упоминалось>",
  "contract_number": "<номер договора или null>",
  "phone_number": "<телефон клиента или null>",
  "agreements": ["<договорённость 1>", "<договорённость 2>"],
  "issues": ["<проблема/жалоба 1>"],
  "callback_needed": <true если нужен обратный звонок, иначе false>,
  "next_steps": ["<следующий шаг 1>"]
}

Правила:
- Извлекай только то, что явно упоминается в разговоре
- Если информация не упоминалась — ставь null для строк, [] для массивов, false для boolean
- Пиши на русском языке
- Верни ТОЛЬКО валидный JSON, без пояснений
```

**Step 4: Commit**

```bash
git add prompts/
git commit -m "feat: add LLM prompts for summarization, quality scoring, and data extraction"
```

---

### Task 8: Оркестратор пайплайна (pipeline)

**Files:**
- Create: `tests/test_pipeline.py`
- Create: `src/pipeline.py`

**Step 1: Написать тесты**

```python
"""Тесты для pipeline (интеграция модулей с моками)."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.pipeline import process_audio_file


@pytest.fixture
def mock_prompts(tmp_path):
    """Создать минимальные промпт-файлы."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "summarize.md").write_text("Суммаризируй.")
    (prompts_dir / "quality_score.md").write_text("Оцени.")
    (prompts_dir / "extract_data.md").write_text("Извлеки.")
    return prompts_dir


@patch("src.pipeline.analyze_dialogue")
@patch("src.pipeline.transcribe_channel")
@patch("src.pipeline.split_stereo_to_mono")
@patch("src.pipeline.get_audio_info")
def test_process_audio_file_full_pipeline(
    mock_info, mock_split, mock_transcribe, mock_analyze, tmp_path, mock_prompts
):
    """process_audio_file должен пройти весь пайплайн и вернуть результат."""
    # Настраиваем моки
    mock_info.return_value = {"channels": 2, "sample_rate": 16000, "duration_sec": 30.0}

    operator_wav = tmp_path / "call_operator.wav"
    client_wav = tmp_path / "call_client.wav"
    operator_wav.touch()
    client_wav.touch()
    mock_split.return_value = (operator_wav, client_wav)

    from src.transcriber import Utterance
    mock_transcribe.side_effect = [
        [Utterance(text="Добрый день.", start=0.0, end=1.5)],
        [Utterance(text="Привет.", start=2.0, end=3.0)],
    ]

    mock_analyze.return_value = {
        "summary": {"topic": "тест", "outcome": "ок", "key_points": []},
        "quality_score": {"total": 8, "criteria": {}},
        "extracted_data": {"client_name": None},
    }

    audio_file = tmp_path / "call.wav"
    audio_file.touch()

    result = process_audio_file(
        audio_path=audio_file,
        output_dir=tmp_path / "results",
        prompts_dir=mock_prompts,
    )

    assert result["file"] == "call.wav"
    assert result["duration_sec"] == 30.0
    assert "transcript" in result
    assert "summary" in result
    assert "quality_score" in result
    assert "extracted_data" in result


@patch("src.pipeline.analyze_dialogue")
@patch("src.pipeline.transcribe_channel")
@patch("src.pipeline.split_stereo_to_mono")
@patch("src.pipeline.get_audio_info")
def test_process_audio_file_saves_json(
    mock_info, mock_split, mock_transcribe, mock_analyze, tmp_path, mock_prompts
):
    """Результат должен сохраниться в JSON-файл."""
    mock_info.return_value = {"channels": 2, "sample_rate": 16000, "duration_sec": 10.0}
    mock_split.return_value = (tmp_path / "op.wav", tmp_path / "cl.wav")
    (tmp_path / "op.wav").touch()
    (tmp_path / "cl.wav").touch()
    mock_transcribe.return_value = []
    mock_analyze.return_value = {
        "summary": {}, "quality_score": {}, "extracted_data": {},
    }

    audio_file = tmp_path / "test_call.wav"
    audio_file.touch()
    output_dir = tmp_path / "results"

    process_audio_file(audio_file, output_dir, mock_prompts)

    result_file = output_dir / "test_call.json"
    assert result_file.exists()
    data = json.loads(result_file.read_text())
    assert data["file"] == "test_call.wav"
```

**Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_pipeline.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Написать реализацию `src/pipeline.py`**

```python
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
```

**Step 4: Запустить тесты**

```bash
pytest tests/test_pipeline.py -v
```

Expected: 2 PASSED

**Step 5: Запустить все тесты проекта**

```bash
pytest tests/ -v
```

Expected: 12 PASSED (все тесты из Task 3-8)

**Step 6: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestrator tying all modules together"
```

---

### Task 9: Финальная интеграция и документация

**Files:**
- Modify: `README.md`
- Modify: `agent_docs/development-history.md`

**Step 1: Обновить README.md**

Заменить шаблонный README на описание проекта с инструкциями по запуску:

- Описание проекта
- Требования (железо, ОС)
- Быстрый старт: `setup_server.sh` → `python -m src.pipeline <file.wav>`
- Структура проекта

**Step 2: Обновить `agent_docs/development-history.md`**

Добавить запись о завершении реализации.

**Step 3: Commit**

```bash
git add README.md agent_docs/development-history.md
git commit -m "docs: update README and development history with project setup instructions"
```

---

## Порядок зависимостей задач

```
Task 1 (scaffolding)
  └─→ Task 2 (setup_server.sh)
  └─→ Task 3 (audio_splitter)
  └─→ Task 7 (prompts)
        Task 3 ─→ Task 4 (transcriber)
        Task 4 ─→ Task 5 (dialogue_builder)
        Task 5 + Task 6 ─→ Task 8 (pipeline)
        Task 3 ─→ Task 6 (llm_analyzer)
                  Task 8 ─→ Task 9 (docs)
```

Задачи 2, 3, 7 можно делать параллельно после Task 1. Задачи 4, 5, 6 зависят от 3. Task 8 требует все предыдущие модули. Task 9 — финальная.
