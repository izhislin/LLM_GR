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
    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
    sudo dpkg -i cuda-keyring_1.1-1_all.deb
    rm cuda-keyring_1.1-1_all.deb
    sudo apt update
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
echo "Запустите пайплайн: python3 -m src.pipeline data/input/your_file.wav"
