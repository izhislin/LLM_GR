"""Конфигурация доменов клиентов.

Загружает настройки доменов из YAML-файла (config/domains.yaml).
Каждый домен — компания-клиент Гравител с собственными параметрами
поллинга и фильтрации звонков.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.config import PROJECT_ROOT


@dataclass
class CallFilters:
    """Фильтры звонков для домена."""

    min_duration_sec: int = 20
    max_duration_sec: int = 1500
    call_types: list[str] = field(default_factory=lambda: ["in", "out"])
    only_with_record: bool = True
    results: list[str] = field(default_factory=lambda: ["success"])


@dataclass
class DomainConfig:
    """Конфигурация одного домена клиента."""

    api_key_env: str
    webhook_key_env: str = ""
    profile: str | None = None
    enabled: bool = True
    polling_interval_min: int = 10
    filters: CallFilters = field(default_factory=CallFilters)


def load_domains_config(config_path: Path | None = None) -> dict[str, DomainConfig]:
    """Загрузить конфигурацию доменов из YAML-файла.

    Args:
        config_path: путь к YAML-файлу. По умолчанию — PROJECT_ROOT / config / domains.yaml.

    Returns:
        Словарь {имя_домена: DomainConfig}.

    Raises:
        FileNotFoundError: если файл не найден.
    """
    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "domains.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Файл конфигурации не найден: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    domains: dict[str, DomainConfig] = {}
    for domain_name, domain_data in raw.get("domains", {}).items():
        # Создаём CallFilters с дефолтами для недостающих полей
        filters_data = domain_data.get("filters", {})
        filters = CallFilters(**filters_data)

        domains[domain_name] = DomainConfig(
            api_key_env=domain_data["api_key_env"],
            webhook_key_env=domain_data.get("webhook_key_env", ""),
            profile=domain_data.get("profile"),
            enabled=domain_data.get("enabled", True),
            polling_interval_min=domain_data.get("polling_interval_min", 10),
            filters=filters,
        )

    return domains
