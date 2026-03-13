"""HTTP-клиент Gravitel API.

Асинхронный клиент для работы с CRM API Гравител (crm.aicall.ru).
Используется для получения истории звонков, списка аккаунтов/групп
и скачивания записей разговоров.
"""

from pathlib import Path

import httpx

BASE_URL = "https://crm.aicall.ru"


class GravitelClient:
    """Асинхронный HTTP-клиент для Gravitel CRM API.

    Args:
        domain: домен компании-клиента в ВАТС (например, 'gravitel.aicall.ru').
        api_key: API-ключ для авторизации.
        timeout: таймаут HTTP-запросов в секундах.
    """

    def __init__(self, domain: str, api_key: str, timeout: float = 30.0) -> None:
        self._domain = domain
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        """Закрыть HTTP-клиент и освободить ресурсы."""
        await self._client.aclose()

    async def fetch_history(
        self,
        period: str | None = None,
        start: str | None = None,
        end: str | None = None,
        call_type: str = "all",
        limit: int | None = None,
    ) -> list[dict]:
        """Получить историю звонков домена.

        Args:
            period: предустановленный период ('today', 'yesterday' и т.д.).
            start: начало диапазона (ISO-дата), используется вместо period.
            end: конец диапазона (ISO-дата), используется вместо period.
            call_type: тип звонков ('all', 'in', 'out', 'internal').
            limit: максимальное количество записей.

        Returns:
            Список словарей с данными звонков.

        Raises:
            httpx.HTTPStatusError: при ошибке HTTP (4xx/5xx).
        """
        url = f"{BASE_URL}/v1/{self._domain}/history"
        body: dict = {"type": call_type}

        if period is not None:
            body["period"] = period
        if start is not None:
            body["start"] = start
        if end is not None:
            body["end"] = end
        if limit is not None:
            body["limit"] = limit

        resp = await self._client.post(
            url,
            headers={"X-API-KEY": self._api_key},
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch_accounts(self) -> list[dict]:
        """Получить список аккаунтов (операторов) домена.

        Returns:
            Список словарей с данными аккаунтов.

        Raises:
            httpx.HTTPStatusError: при ошибке HTTP (4xx/5xx).
        """
        url = f"{BASE_URL}/v1/{self._domain}/accounts"
        resp = await self._client.get(
            url,
            headers={"X-API-KEY": self._api_key},
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch_groups(self) -> list[dict]:
        """Получить список групп (отделов) домена.

        Returns:
            Список словарей с данными групп.

        Raises:
            httpx.HTTPStatusError: при ошибке HTTP (4xx/5xx).
        """
        url = f"{BASE_URL}/v1/{self._domain}/groups"
        resp = await self._client.get(
            url,
            headers={"X-API-KEY": self._api_key},
        )
        resp.raise_for_status()
        return resp.json()

    async def download_record(self, record_url: str, save_path: Path) -> Path:
        """Скачать запись разговора и сохранить в файл.

        Args:
            record_url: URL файла записи.
            save_path: путь для сохранения файла.

        Returns:
            Путь к сохранённому файлу.

        Raises:
            httpx.HTTPStatusError: при ошибке HTTP (4xx/5xx).
        """
        resp = await self._client.get(
            record_url,
            headers={"X-API-KEY": self._api_key},
        )
        resp.raise_for_status()

        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(resp.content)

        return save_path
