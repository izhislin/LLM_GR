"""Тесты HTTP-клиента Gravitel API."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from src.gravitel_api import GravitelClient


@pytest.fixture
def client():
    """Создаёт экземпляр GravitelClient для тестов."""
    return GravitelClient(domain="test.aicall.ru", api_key="test-secret-key")


def _make_response(status_code: int, *, json=None, content=None, method="GET", url="https://example.com"):
    """Вспомогательная функция: создать httpx.Response с нужными параметрами."""
    kwargs = {"status_code": status_code, "request": httpx.Request(method, url)}
    if json is not None:
        kwargs["json"] = json
    if content is not None:
        kwargs["content"] = content
    return httpx.Response(**kwargs)


# ── fetch_history ──────────────────────────────────────────────────────────


class TestFetchHistory:
    """Тесты метода fetch_history."""

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        """fetch_history возвращает список записей."""
        mock_data = [{"id": 1, "caller": "+79001234567"}]
        mock_resp = _make_response(200, json=mock_data, method="POST")

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.fetch_history(period="today")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_auth_header_passed(self, client):
        """X-API-KEY заголовок передаётся в запросе."""
        mock_resp = _make_response(200, json=[], method="POST")

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await client.fetch_history(period="today")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("X-API-KEY") == "test-secret-key"

    @pytest.mark.asyncio
    async def test_request_body_parameters(self, client):
        """Параметры period, call_type, limit передаются в теле запроса."""
        mock_resp = _make_response(200, json=[], method="POST")

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await client.fetch_history(period="today", call_type="in", limit=50)

        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body["period"] == "today"
        assert body["type"] == "in"
        assert body["limit"] == 50

    @pytest.mark.asyncio
    async def test_start_end_parameters(self, client):
        """Параметры start и end передаются вместо period."""
        mock_resp = _make_response(200, json=[], method="POST")

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await client.fetch_history(start="2026-03-01", end="2026-03-13")

        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body["start"] == "2026-03-01"
        assert body["end"] == "2026-03-13"
        assert "period" not in body


# ── fetch_accounts ─────────────────────────────────────────────────────────


class TestFetchAccounts:
    """Тесты метода fetch_accounts."""

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        """fetch_accounts возвращает список аккаунтов."""
        mock_data = [{"id": 10, "name": "Оператор 1"}]
        mock_resp = _make_response(200, json=mock_data)

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.fetch_accounts()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "Оператор 1"

    @pytest.mark.asyncio
    async def test_auth_header(self, client):
        """X-API-KEY передаётся в GET-запросе fetch_accounts."""
        mock_resp = _make_response(200, json=[])

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.fetch_accounts()

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("X-API-KEY") == "test-secret-key"


# ── fetch_groups ───────────────────────────────────────────────────────────


class TestFetchGroups:
    """Тесты метода fetch_groups."""

    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        """fetch_groups возвращает список групп."""
        mock_data = [{"id": 5, "name": "Отдел продаж"}]
        mock_resp = _make_response(200, json=mock_data)

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.fetch_groups()

        assert isinstance(result, list)
        assert result[0]["name"] == "Отдел продаж"

    @pytest.mark.asyncio
    async def test_auth_header(self, client):
        """X-API-KEY передаётся в GET-запросе fetch_groups."""
        mock_resp = _make_response(200, json=[])

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.fetch_groups()

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("X-API-KEY") == "test-secret-key"


# ── download_record ────────────────────────────────────────────────────────


class TestDownloadRecord:
    """Тесты метода download_record."""

    @pytest.mark.asyncio
    async def test_saves_bytes_to_file(self, client, tmp_path):
        """download_record сохраняет байты ответа в файл."""
        audio_bytes = b"\x00\x01\x02\x03RIFF_fake_audio"
        mock_resp = _make_response(200, content=audio_bytes)

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            save_path = tmp_path / "records" / "call_001.wav"
            result = await client.download_record(
                record_url="https://storage.example.com/rec/001.wav",
                save_path=save_path,
            )

        assert result == save_path
        assert save_path.exists()
        assert save_path.read_bytes() == audio_bytes

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, client, tmp_path):
        """download_record создаёт родительские директории."""
        mock_resp = _make_response(200, content=b"data")

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            save_path = tmp_path / "deep" / "nested" / "dir" / "file.wav"
            await client.download_record(
                record_url="https://storage.example.com/rec/002.wav",
                save_path=save_path,
            )

        assert save_path.parent.exists()
        assert save_path.exists()


# ── Ошибки ─────────────────────────────────────────────────────────────────


class TestErrorHandling:
    """Тесты обработки ошибок."""

    @pytest.mark.asyncio
    async def test_401_raises_http_status_error(self, client):
        """401 Unauthorized вызывает HTTPStatusError."""
        mock_resp = _make_response(401, json={"error": "unauthorized"}, method="POST")

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_history(period="today")

    @pytest.mark.asyncio
    async def test_500_raises_http_status_error(self, client):
        """500 Server Error вызывает HTTPStatusError."""
        mock_resp = _make_response(500, json={"error": "internal"})

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_accounts()
