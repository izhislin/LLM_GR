"""Двухуровневая коррекция транскриптов.

Уровень 1 — общий: телефонные термины, бренд Гравител.
Уровень 2 — профиль клиента: YAML-файл с доменной лексикой.
"""

import logging
import re
from pathlib import Path
from typing import Any

from src.config import PROFILES_DIR

logger = logging.getLogger(__name__)

# ── Общий слой (применяется всегда) ──────────────────────────────────────────

# (regex-паттерн, замена, флаги)
# Порядок важен: более специфичные паттерны идут первыми.
_COMMON_CORRECTIONS: list[tuple[str, str]] = [
    # Бренд «Гравител» — покрываем известные искажения GigaAM
    (r"\b[Гг]р[иеа][вб][ие]?[тс][еиа]?[лл]+\b", "Гравител"),
    (r"\b[Гг]р[ае]в[иа][сф][ие][тбп]\b", "Гравител"),
    (r"\b[Гг]рей[сц]ипе\b", "Гравител"),
    # Латинские варианты (LLM иногда транслитерирует)
    (r"\bGravital\b", "Гравител"),
    (r"\bgravital\b", "Гравител"),
    (r"\bGravitel\b", "Гравител"),

    # Телефонные / IT-термины
    (r"\bсип\b", "SIP"),
    (r"\bСип\b", "SIP"),
    (r"\bай[- ]?пи\b", "IP"),
    (r"\bАй[- ]?пи\b", "IP"),
    (r"\bватс\b", "ВАТС"),
    (r"\bВатс\b", "ВАТС"),
    (r"\bатээс\b", "АТС"),
    (r"\bАтээс\b", "АТС"),
    (r"\bайвиар\b", "IVR"),
    (r"\bАйвиар\b", "IVR"),
    (r"\bцрм\b", "CRM"),
    (r"\bЦрм\b", "CRM"),
    (r"\bсиар[- ]?эм\b", "CRM"),

    # Обрезанные слова (частые артефакты GigaAM)
    (r"\bштри\b", "штрих"),
    (r"\bШтри\b", "Штрих"),
    (r"\bдобавочн\b", "добавочный"),
    (r"\bДобавочн\b", "Добавочный"),
]

# Компилируем regex один раз при импорте модуля.
_COMPILED_COMMON: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern), replacement)
    for pattern, replacement in _COMMON_CORRECTIONS
]


def load_profile(profile_name: str | None, profiles_dir: Path | None = None) -> dict | None:
    """Загрузить YAML-профиль клиента.

    Args:
        profile_name: Имя профиля (без .yaml) или None.
        profiles_dir: Директория с профилями (по умолчанию — profiles/).

    Returns:
        Словарь профиля или None, если профиль не указан / не найден.
    """
    if not profile_name:
        return None

    profiles_dir = Path(profiles_dir or PROFILES_DIR)
    profile_path = profiles_dir / f"{profile_name}.yaml"

    if not profile_path.exists():
        logger.warning("Профиль не найден: %s", profile_path)
        return None

    import yaml
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    logger.info("Загружен профиль: %s", profile_name)
    return profile


def _compile_profile(profile: dict) -> list[tuple[re.Pattern, str]]:
    """Скомпилировать regex-паттерны из профиля."""
    compiled = []

    # company.patterns
    company = profile.get("company", {})
    for pair in company.get("patterns", []):
        if len(pair) == 2 and pair[1] is not None:
            compiled.append((re.compile(pair[0]), pair[1]))

    # terms
    for pair in profile.get("terms", []):
        if len(pair) == 2 and pair[1] is not None:
            compiled.append((re.compile(pair[0]), pair[1]))

    # staff
    for pair in profile.get("staff", []):
        if len(pair) == 2 and pair[1] is not None:
            compiled.append((re.compile(pair[0]), pair[1]))

    return compiled


def correct_text(text: str, profile: dict | None = None) -> str:
    """Применить коррекцию к тексту транскрипта.

    Порядок: общий слой → профиль клиента.

    Args:
        text: Текст транскрипта (формат dialogue_to_text).
        profile: Загруженный профиль (из load_profile) или None.

    Returns:
        Исправленный текст.
    """
    corrected = text
    replacements = 0

    # Уровень 1: общие замены
    for pattern, replacement in _COMPILED_COMMON:
        corrected, n = pattern.subn(replacement, corrected)
        replacements += n

    # Уровень 2: профиль клиента
    if profile:
        for pattern, replacement in _compile_profile(profile):
            corrected, n = pattern.subn(replacement, corrected)
            replacements += n

    if replacements > 0:
        logger.info("Коррекция текста: %d замен", replacements)

    return corrected
