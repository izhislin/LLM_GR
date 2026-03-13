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
PROFILES_DIR = PROJECT_ROOT / "profiles"
DEFAULT_PROFILE = "gravitel"  # имя профиля (без .yaml) или None

# GigaAM
GIGAAM_MODEL = "v3_e2e_rnnt"
GIGAAM_DEVICE = None  # None = auto (CUDA if available)

# Ollama
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_TIMEOUT = 120  # секунд на один вызов LLM

# Аудио
SAMPLE_RATE = 16000  # GigaAM ожидает 16kHz

# Prometheus
METRICS_PORT = 8000
