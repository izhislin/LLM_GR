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

    # Извлекаем левый канал (оператор) через pan filter
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-af", "pan=mono|c0=c0",
            "-ar", "16000",
            str(operator_path),
        ],
        capture_output=True, check=True,
    )

    # Извлекаем правый канал (клиент) через pan filter
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-af", "pan=mono|c0=c1",
            "-ar", "16000",
            str(client_path),
        ],
        capture_output=True, check=True,
    )

    return operator_path, client_path
