"""Тесты модуля конфигурации доменов."""

import pytest
import yaml
from pathlib import Path

from src.domain_config import CallFilters, DomainConfig, load_domains_config


# ── CallFilters ─────────────────────────────────────────────────────────────

class TestCallFilters:
    """Тесты датакласса CallFilters."""

    def test_default_values(self):
        """Значения по умолчанию корректны."""
        f = CallFilters()
        assert f.min_duration_sec == 20
        assert f.max_duration_sec == 1500
        assert f.call_types == ["in", "out"]
        assert f.only_with_record is True
        assert f.results == ["success"]

    def test_custom_values(self):
        """Можно задать кастомные значения."""
        f = CallFilters(
            min_duration_sec=10,
            max_duration_sec=600,
            call_types=["in"],
            only_with_record=False,
            results=["success", "missed"],
        )
        assert f.min_duration_sec == 10
        assert f.max_duration_sec == 600
        assert f.call_types == ["in"]
        assert f.only_with_record is False
        assert f.results == ["success", "missed"]

    def test_list_defaults_are_independent(self):
        """Дефолтные списки не разделяются между экземплярами."""
        f1 = CallFilters()
        f2 = CallFilters()
        f1.call_types.append("internal")
        assert "internal" not in f2.call_types


# ── DomainConfig ────────────────────────────────────────────────────────────

class TestDomainConfig:
    """Тесты датакласса DomainConfig."""

    def test_all_fields(self):
        """Все поля заполняются корректно."""
        filters = CallFilters(min_duration_sec=30)
        dc = DomainConfig(
            api_key_env="MY_KEY",
            profile="gravitel",
            enabled=True,
            polling_interval_min=5,
            filters=filters,
        )
        assert dc.api_key_env == "MY_KEY"
        assert dc.profile == "gravitel"
        assert dc.enabled is True
        assert dc.polling_interval_min == 5
        assert dc.filters.min_duration_sec == 30

    def test_profile_none(self):
        """Профиль может быть None."""
        dc = DomainConfig(
            api_key_env="KEY",
            profile=None,
            enabled=True,
            polling_interval_min=10,
            filters=CallFilters(),
        )
        assert dc.profile is None


# ── load_domains_config ─────────────────────────────────────────────────────

class TestLoadDomainsConfig:
    """Тесты загрузки конфигурации доменов из YAML."""

    def _write_config(self, path: Path, data: dict) -> Path:
        """Вспомогательный метод: записать YAML-конфиг."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)
        return path

    def test_load_single_domain(self, tmp_path):
        """Один домен загружается корректно."""
        config_data = {
            "domains": {
                "example.com": {
                    "api_key_env": "EXAMPLE_API_KEY",
                    "profile": "example",
                    "enabled": True,
                    "polling_interval_min": 15,
                    "filters": {
                        "min_duration_sec": 30,
                        "max_duration_sec": 1000,
                        "call_types": ["in"],
                        "only_with_record": True,
                        "results": ["success"],
                    },
                }
            }
        }
        config_path = self._write_config(tmp_path / "domains.yaml", config_data)
        result = load_domains_config(config_path)

        assert "example.com" in result
        dc = result["example.com"]
        assert isinstance(dc, DomainConfig)
        assert dc.api_key_env == "EXAMPLE_API_KEY"
        assert dc.profile == "example"
        assert dc.enabled is True
        assert dc.polling_interval_min == 15
        assert isinstance(dc.filters, CallFilters)
        assert dc.filters.min_duration_sec == 30
        assert dc.filters.max_duration_sec == 1000
        assert dc.filters.call_types == ["in"]
        assert dc.filters.only_with_record is True
        assert dc.filters.results == ["success"]

    def test_load_multiple_domains(self, tmp_path):
        """Несколько доменов загружаются корректно."""
        config_data = {
            "domains": {
                "domain1.ru": {
                    "api_key_env": "KEY1",
                    "profile": "prof1",
                    "enabled": True,
                    "polling_interval_min": 5,
                    "filters": {
                        "min_duration_sec": 20,
                        "max_duration_sec": 1500,
                        "call_types": ["in", "out"],
                        "only_with_record": True,
                        "results": ["success"],
                    },
                },
                "domain2.ru": {
                    "api_key_env": "KEY2",
                    "profile": None,
                    "enabled": False,
                    "polling_interval_min": 30,
                    "filters": {
                        "min_duration_sec": 10,
                        "max_duration_sec": 600,
                        "call_types": ["in", "out", "internal"],
                        "only_with_record": False,
                        "results": ["success", "missed"],
                    },
                },
            }
        }
        config_path = self._write_config(tmp_path / "domains.yaml", config_data)
        result = load_domains_config(config_path)

        assert len(result) == 2
        assert "domain1.ru" in result
        assert "domain2.ru" in result

        # Проверяем второй домен
        dc2 = result["domain2.ru"]
        assert dc2.api_key_env == "KEY2"
        assert dc2.profile is None
        assert dc2.enabled is False
        assert dc2.polling_interval_min == 30
        assert dc2.filters.call_types == ["in", "out", "internal"]

    def test_enabled_disabled_filtering(self, tmp_path):
        """Фильтрация включённых/выключенных доменов."""
        config_data = {
            "domains": {
                "active.ru": {
                    "api_key_env": "KEY1",
                    "profile": "p1",
                    "enabled": True,
                    "polling_interval_min": 10,
                    "filters": {
                        "min_duration_sec": 20,
                        "max_duration_sec": 1500,
                        "call_types": ["in", "out"],
                        "only_with_record": True,
                        "results": ["success"],
                    },
                },
                "disabled.ru": {
                    "api_key_env": "KEY2",
                    "profile": "p2",
                    "enabled": False,
                    "polling_interval_min": 10,
                    "filters": {
                        "min_duration_sec": 20,
                        "max_duration_sec": 1500,
                        "call_types": ["in", "out"],
                        "only_with_record": True,
                        "results": ["success"],
                    },
                },
            }
        }
        config_path = self._write_config(tmp_path / "domains.yaml", config_data)
        result = load_domains_config(config_path)

        # Все домены загружены (фильтрация — ответственность вызывающего кода)
        assert len(result) == 2
        # Но можно отфильтровать по enabled
        enabled = {k: v for k, v in result.items() if v.enabled}
        disabled = {k: v for k, v in result.items() if not v.enabled}
        assert len(enabled) == 1
        assert "active.ru" in enabled
        assert len(disabled) == 1
        assert "disabled.ru" in disabled

    def test_file_not_found(self):
        """FileNotFoundError при отсутствующем файле."""
        with pytest.raises(FileNotFoundError):
            load_domains_config(Path("/nonexistent/path/domains.yaml"))

    def test_default_path_uses_project_root(self):
        """Путь по умолчанию — PROJECT_ROOT / config / domains.yaml."""
        # Загружаем реальный конфиг из проекта
        result = load_domains_config()
        assert "gravitel.aicall.ru" in result
        dc = result["gravitel.aicall.ru"]
        assert dc.api_key_env == "GRAVITEL_API_KEY"
        assert dc.profile == "gravitel"
        assert dc.enabled is True
        assert dc.polling_interval_min == 10

    def test_filters_defaults_when_partial(self, tmp_path):
        """Недостающие поля фильтров заполняются дефолтами."""
        config_data = {
            "domains": {
                "partial.ru": {
                    "api_key_env": "KEY",
                    "profile": None,
                    "enabled": True,
                    "polling_interval_min": 10,
                    "filters": {
                        "min_duration_sec": 60,
                    },
                }
            }
        }
        config_path = self._write_config(tmp_path / "domains.yaml", config_data)
        result = load_domains_config(config_path)

        dc = result["partial.ru"]
        assert dc.filters.min_duration_sec == 60  # явно задано
        assert dc.filters.max_duration_sec == 1500  # дефолт
        assert dc.filters.call_types == ["in", "out"]  # дефолт
        assert dc.filters.only_with_record is True  # дефолт
        assert dc.filters.results == ["success"]  # дефолт
