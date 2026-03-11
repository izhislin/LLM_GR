"""Тесты для audio_splitter."""

import subprocess
import wave
import struct
import math
import pytest
from pathlib import Path

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
            left = int(32767 * 0.5 * math.sin(2 * math.pi * 440 * i / sample_rate))
            right = int(32767 * 0.5 * math.sin(2 * math.pi * 880 * i / sample_rate))
            wav_file.writeframes(struct.pack("<hh", left, right))

    return filepath


def test_split_stereo_creates_two_mono_files(stereo_wav, tmp_path):
    """split_stereo_to_mono должен создать два моно WAV-файла."""
    left, right = split_stereo_to_mono(stereo_wav, tmp_path)

    assert left.exists(), "Левый канал не создан"
    assert right.exists(), "Правый канал не создан"

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
