"""Тесты модуля коррекции транскриптов."""

import pytest
from pathlib import Path

from src.text_corrector import correct_text, load_profile, _compile_profile


# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_TRANSCRIPT = (
    "[00:00:00] Оператор: Здравствуйте, компания Гривитал.\n"
    "[00:00:05] Клиент: Добрый день, у меня проблема с ватс.\n"
    "[00:00:10] Оператор: Давайте проверим ваш сип-транк.\n"
    "[00:00:15] Клиент: Мне нужно настроить ай пи телефон."
)

GRAVITEL_PROFILE = {
    "company": {
        "name": "Гравител",
        "patterns": [
            [r"[Гг]р[иеа][вб][ие]?[тс][еи]?[лл]+", "Гравител"],
            [r"[Гг]р[ае]в[иа][сф][ие][тбп]", "Гравител"],
        ],
    },
    "terms": [
        [r"[Гг]рави.?фон", "Грави-фон"],
    ],
    "llm_context": "Звонок в компании Гравител.",
}


# ── Общий слой ───────────────────────────────────────────────────────────────

class TestCommonCorrections:
    """Тесты общего слоя коррекции."""

    def test_gravitel_variants(self):
        """Известные искажения «Гравител» исправляются."""
        variants = [
            "Гривитал",
            "Грибителл",
            "Гривителл",
            "Грависит",
            "Грейсипе",
        ]
        for v in variants:
            result = correct_text(f"Компания {v} приветствует вас")
            assert "Гравител" in result, f"Не исправлено: {v} → {result}"

    def test_telecom_terms(self):
        """Телефонные термины нормализуются."""
        assert "SIP" in correct_text("настройте сип транк")
        assert "IP" in correct_text("ай пи телефон")
        assert "ВАТС" in correct_text("виртуальная ватс")
        assert "АТС" in correct_text("подключите атээс")
        assert "IVR" in correct_text("настройте айвиар")
        assert "CRM" in correct_text("интеграция с црм")

    def test_capitalized_terms(self):
        """Термины с заглавной буквы тоже исправляются."""
        assert "SIP" in correct_text("Сип-телефон")
        assert "ВАТС" in correct_text("Ватс настроена")
        assert "АТС" in correct_text("Атээс работает")

    def test_full_transcript(self):
        """Комплексный тест на реалистичном транскрипте."""
        result = correct_text(SAMPLE_TRANSCRIPT)
        assert "Гравител" in result
        assert "ВАТС" in result
        assert "SIP" in result
        assert "IP" in result

    def test_no_profile_works(self):
        """Без профиля работает только общий слой."""
        result = correct_text("Компания Гривителл, сип-телефония", profile=None)
        assert "Гравител" in result
        assert "SIP" in result


# ── Профиль клиента ──────────────────────────────────────────────────────────

class TestProfileCorrections:
    """Тесты профильного слоя коррекции."""

    def test_profile_company_patterns(self):
        """Паттерны из профиля применяются."""
        result = correct_text("Звоните в Гривитал", profile=GRAVITEL_PROFILE)
        assert "Гравител" in result

    def test_profile_terms(self):
        """Доменные термины из профиля применяются."""
        result = correct_text("Установите гравифон", profile=GRAVITEL_PROFILE)
        assert "Грави-фон" in result

    def test_profile_staff(self):
        """Имена сотрудников из профиля исправляются."""
        profile = {
            "company": {"name": "Тест", "patterns": []},
            "staff": [
                [r"Пертов", "Петров"],
                [r"Иванав", "Иванов"],
            ],
            "terms": [],
        }
        result = correct_text("Доктор Пертов примет вас", profile=profile)
        assert "Петров" in result

    def test_null_replacement_skipped(self):
        """Паттерны с null-заменой игнорируются."""
        profile = {
            "company": {"name": "Тест", "patterns": []},
            "terms": [[r"тестовое", None]],
        }
        result = correct_text("Это тестовое слово", profile=profile)
        assert "тестовое" in result

    def test_compile_profile_empty(self):
        """Пустой профиль не ломает компиляцию."""
        compiled = _compile_profile({})
        assert compiled == []


# ── False positives ──────────────────────────────────────────────────────────

class TestFalsePositives:
    """Проверка отсутствия ложных срабатываний."""

    def test_gracia_not_changed(self):
        """'грация' не превращается в 'Гравител'."""
        result = correct_text("Это была грация движений")
        assert "грация" in result
        assert "Гравител" not in result

    def test_integration_not_changed(self):
        """'интеграция' не затрагивается."""
        result = correct_text("интеграция с CRM системой")
        assert "интеграция" in result

    def test_simple_words_preserved(self):
        """Обычные слова не искажаются."""
        text = "Клиент позвонил и спросил про тарифы"
        assert correct_text(text) == text

    def test_timestamps_preserved(self):
        """Таймкоды не ломаются."""
        text = "[00:01:30] Оператор: Здравствуйте"
        result = correct_text(text)
        assert "[00:01:30]" in result


# ── load_profile ─────────────────────────────────────────────────────────────

class TestLoadProfile:
    """Тесты загрузки профилей."""

    def test_load_none(self):
        """None возвращает None."""
        assert load_profile(None) is None

    def test_load_nonexistent(self):
        """Несуществующий профиль возвращает None."""
        assert load_profile("nonexistent_profile_xyz") is None

    def test_load_gravitel(self):
        """Реальный профиль gravitel загружается."""
        profile = load_profile("gravitel")
        assert profile is not None
        assert profile["company"]["name"] == "Гравител"
        assert len(profile["company"]["patterns"]) > 0
        assert "llm_context" in profile

    def test_load_custom_dir(self, tmp_path):
        """Загрузка из кастомной директории."""
        # Создаём временный профиль
        profile_content = "company:\n  name: Test\n  patterns: []\nterms: []\n"
        (tmp_path / "test.yaml").write_text(profile_content, encoding="utf-8")
        profile = load_profile("test", profiles_dir=tmp_path)
        assert profile is not None
        assert profile["company"]["name"] == "Test"
