"""Тесты модуля базы данных (SQLite)."""

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from src.db import (
    get_call,
    get_calls_count,
    get_operator_name,
    get_pending_calls,
    get_processing,
    get_retryable_calls,
    init_db,
    insert_call,
    insert_processing,
    list_calls,
    list_departments,
    list_operators,
    reopen_processing,
    update_call_from_polling,
    update_domain_poll_time,
    update_processing_status,
    upsert_department,
    upsert_operator,
)


# ── Фикстуры ────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Инициализированная in-memory БД для каждого теста."""
    conn = init_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def sample_call():
    """Пример данных звонка."""
    return {
        "id": "call-001",
        "domain": "example.gravitel.ru",
        "direction": "in",
        "result": "success",
        "duration": 120,
        "wait": 5,
        "started_at": "2026-03-10T10:00:00+00:00",
        "client_number": "+79001234567",
        "operator_extension": "101",
        "operator_name": "Иванов Иван",
        "phone": "+74951234567",
        "record_url": "https://cdn.example.com/rec/call-001.mp3",
        "source": "api",
        "received_at": "2026-03-10T10:05:00+00:00",
    }


@pytest.fixture
def sample_call_2():
    """Второй пример звонка (другой домен и направление)."""
    return {
        "id": "call-002",
        "domain": "other.gravitel.ru",
        "direction": "out",
        "result": "missed",
        "duration": 30,
        "wait": 0,
        "started_at": "2026-03-11T14:00:00+00:00",
        "client_number": "+79009876543",
        "operator_extension": "202",
        "operator_name": "Петров Пётр",
        "phone": "+74959876543",
        "record_url": "https://cdn.example.com/rec/call-002.mp3",
        "source": "api",
        "received_at": "2026-03-11T14:05:00+00:00",
    }


# ── init_db ──────────────────────────────────────────────────────────────────


class TestInitDb:
    """Тесты инициализации БД."""

    def test_creates_all_tables(self, db):
        """init_db создаёт все необходимые таблицы."""
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        assert "calls" in tables
        assert "processing" in tables
        assert "operators" in tables
        assert "departments" in tables
        assert "domains" in tables

    def test_creates_indexes(self, db):
        """init_db создаёт индексы."""
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_calls_domain" in indexes
        assert "idx_calls_started" in indexes
        assert "idx_processing_status" in indexes

    def test_row_factory_is_row(self, db):
        """row_factory установлен в sqlite3.Row."""
        assert db.row_factory == sqlite3.Row

    def test_idempotent(self, tmp_path):
        """Повторный вызов init_db не вызывает ошибок."""
        db_path = str(tmp_path / "test.db")
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        conn2.close()


# ── insert_call / get_call ───────────────────────────────────────────────────


class TestInsertGetCall:
    """Тесты вставки и получения звонков."""

    def test_insert_and_get(self, db, sample_call):
        """Вставка и получение звонка возвращают корректные данные."""
        result = insert_call(db, sample_call)
        assert result is True

        call = get_call(db, "call-001")
        assert call is not None
        assert call["id"] == "call-001"
        assert call["domain"] == "example.gravitel.ru"
        assert call["direction"] == "in"
        assert call["duration"] == 120
        assert call["client_number"] == "+79001234567"
        assert call["operator_name"] == "Иванов Иван"
        assert call["record_url"] == "https://cdn.example.com/rec/call-001.mp3"

    def test_duplicate_ignored(self, db, sample_call):
        """Повторная вставка того же звонка игнорируется (INSERT OR IGNORE)."""
        assert insert_call(db, sample_call) is True
        assert insert_call(db, sample_call) is False

        # Только одна запись в таблице
        cursor = db.execute("SELECT COUNT(*) as cnt FROM calls")
        assert cursor.fetchone()["cnt"] == 1

    def test_get_nonexistent_returns_none(self, db):
        """Получение несуществующего звонка возвращает None."""
        assert get_call(db, "nonexistent") is None


# ── list_calls ───────────────────────────────────────────────────────────────


class TestListCalls:
    """Тесты списка звонков с фильтрами и пагинацией."""

    def _insert_calls_with_processing(self, db, sample_call, sample_call_2):
        """Вставляет два звонка с обработкой для тестов."""
        insert_call(db, sample_call)
        insert_call(db, sample_call_2)
        insert_processing(db, "call-001", status="done")
        insert_processing(db, "call-002", status="pending")

    def test_list_all(self, db, sample_call, sample_call_2):
        """Список всех звонков без фильтров."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db)
        assert len(calls) == 2

    def test_order_by_started_at_desc(self, db, sample_call, sample_call_2):
        """Звонки отсортированы по started_at DESC (новые первыми)."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db)
        assert calls[0]["id"] == "call-002"  # 2026-03-11 > 2026-03-10
        assert calls[1]["id"] == "call-001"

    def test_filter_by_domain(self, db, sample_call, sample_call_2):
        """Фильтр по домену."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db, domain="example.gravitel.ru")
        assert len(calls) == 1
        assert calls[0]["id"] == "call-001"

    def test_filter_by_direction(self, db, sample_call, sample_call_2):
        """Фильтр по направлению звонка."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db, direction="out")
        assert len(calls) == 1
        assert calls[0]["id"] == "call-002"

    def test_filter_by_status(self, db, sample_call, sample_call_2):
        """Фильтр по статусу обработки."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db, status="done")
        assert len(calls) == 1
        assert calls[0]["id"] == "call-001"

    def test_filter_by_date_range(self, db, sample_call, sample_call_2):
        """Фильтр по диапазону дат."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db, date_from="2026-03-11", date_to="2026-03-12")
        assert len(calls) == 1
        assert calls[0]["id"] == "call-002"

    def test_filter_by_operator(self, db, sample_call, sample_call_2):
        """Фильтр по добавочному оператора."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db, operator="101")
        assert len(calls) == 1
        assert calls[0]["id"] == "call-001"

    def test_pagination(self, db, sample_call, sample_call_2):
        """Пагинация: per_page=1, page=1 и page=2."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)

        page1 = list_calls(db, page=1, per_page=1)
        assert len(page1) == 1
        assert page1[0]["id"] == "call-002"  # первая страница — новейший

        page2 = list_calls(db, page=2, per_page=1)
        assert len(page2) == 1
        assert page2[0]["id"] == "call-001"

    def test_pagination_empty_page(self, db, sample_call):
        """Пустая страница при выходе за пределы."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001")
        calls = list_calls(db, page=100, per_page=10)
        assert calls == []

    def test_combined_filters(self, db, sample_call, sample_call_2):
        """Комбинация нескольких фильтров."""
        self._insert_calls_with_processing(db, sample_call, sample_call_2)
        calls = list_calls(db, domain="example.gravitel.ru", status="done")
        assert len(calls) == 1
        assert calls[0]["id"] == "call-001"


# ── get_calls_count ──────────────────────────────────────────────────────────


class TestGetCallsCount:
    """Тесты подсчёта звонков."""

    def test_count_all(self, db, sample_call, sample_call_2):
        """Подсчёт всех звонков."""
        insert_call(db, sample_call)
        insert_call(db, sample_call_2)
        insert_processing(db, "call-001", status="done")
        insert_processing(db, "call-002", status="pending")
        assert get_calls_count(db) == 2

    def test_count_by_domain(self, db, sample_call, sample_call_2):
        """Подсчёт звонков по домену."""
        insert_call(db, sample_call)
        insert_call(db, sample_call_2)
        insert_processing(db, "call-001")
        insert_processing(db, "call-002")
        assert get_calls_count(db, domain="example.gravitel.ru") == 1

    def test_count_by_status(self, db, sample_call, sample_call_2):
        """Подсчёт звонков по статусу обработки."""
        insert_call(db, sample_call)
        insert_call(db, sample_call_2)
        insert_processing(db, "call-001", status="done")
        insert_processing(db, "call-002", status="pending")
        assert get_calls_count(db, status="done") == 1
        assert get_calls_count(db, status="pending") == 1

    def test_count_empty(self, db):
        """Пустая БД — 0 звонков."""
        assert get_calls_count(db) == 0


# ── processing CRUD ──────────────────────────────────────────────────────────


class TestProcessingCrud:
    """Тесты CRUD для таблицы processing."""

    def test_insert_and_get_processing(self, db, sample_call):
        """Вставка и получение записи обработки."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001")

        proc = get_processing(db, "call-001")
        assert proc is not None
        assert proc["call_id"] == "call-001"
        assert proc["status"] == "pending"
        assert proc["retry_count"] == 0

    def test_insert_with_skip_reason(self, db, sample_call):
        """Вставка с причиной пропуска."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001", status="skipped", skip_reason="Слишком короткий")

        proc = get_processing(db, "call-001")
        assert proc["status"] == "skipped"
        assert proc["skip_reason"] == "Слишком короткий"

    def test_get_nonexistent_processing(self, db):
        """Получение несуществующей записи обработки."""
        assert get_processing(db, "nonexistent") is None


# ── update_processing_status ─────────────────────────────────────────────────


class TestUpdateProcessingStatus:
    """Тесты обновления статуса обработки."""

    def test_set_processing_sets_started_at(self, db, sample_call):
        """Статус 'processing' устанавливает started_at."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001")
        update_processing_status(db, "call-001", "processing")

        proc = get_processing(db, "call-001")
        assert proc["status"] == "processing"
        assert proc["started_at"] is not None

    def test_set_done_sets_completed_at(self, db, sample_call):
        """Статус 'done' устанавливает completed_at и result_json."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001")
        result = json.dumps({"summary": "Тест"})
        update_processing_status(
            db, "call-001", "done",
            result_json=result,
            processing_time_sec=5.2,
        )

        proc = get_processing(db, "call-001")
        assert proc["status"] == "done"
        assert proc["completed_at"] is not None
        assert proc["result_json"] == result
        assert proc["processing_time_sec"] == pytest.approx(5.2)

    def test_set_error_increments_retry_count(self, db, sample_call):
        """Статус 'error' инкрементирует retry_count и ставит completed_at."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001")

        update_processing_status(db, "call-001", "error", error_message="Timeout")
        proc = get_processing(db, "call-001")
        assert proc["retry_count"] == 1
        assert proc["error_message"] == "Timeout"
        assert proc["completed_at"] is not None

        update_processing_status(db, "call-001", "error", error_message="Timeout 2")
        proc = get_processing(db, "call-001")
        assert proc["retry_count"] == 2

    def test_set_audio_path(self, db, sample_call):
        """Можно установить audio_path при обновлении статуса."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001")
        update_processing_status(
            db, "call-001", "processing",
            audio_path="/data/audio/call-001.wav",
        )

        proc = get_processing(db, "call-001")
        assert proc["audio_path"] == "/data/audio/call-001.wav"


# ── get_pending_calls / get_retryable_calls ──────────────────────────────────


class TestPendingAndRetryable:
    """Тесты получения звонков для обработки."""

    def test_get_pending_calls(self, db, sample_call, sample_call_2):
        """Получение звонков со статусом pending."""
        insert_call(db, sample_call)
        insert_call(db, sample_call_2)
        insert_processing(db, "call-001", status="pending")
        insert_processing(db, "call-002", status="done")

        pending = get_pending_calls(db)
        assert len(pending) == 1
        assert pending[0]["call_id"] == "call-001"

    def test_get_pending_limit(self, db):
        """Лимит на количество возвращаемых pending."""
        for i in range(5):
            call = {
                "id": f"call-{i:03d}",
                "domain": "test.ru",
                "direction": "in",
                "source": "api",
                "received_at": "2026-03-10T10:00:00+00:00",
            }
            insert_call(db, call)
            insert_processing(db, f"call-{i:03d}", status="pending")

        pending = get_pending_calls(db, limit=3)
        assert len(pending) == 3

    def test_get_retryable_calls(self, db, sample_call, sample_call_2):
        """Получение звонков с ошибкой и retry_count < max."""
        insert_call(db, sample_call)
        insert_call(db, sample_call_2)
        insert_processing(db, "call-001", status="pending")
        insert_processing(db, "call-002", status="pending")

        # call-001: ошибка с retry_count=1
        update_processing_status(db, "call-001", "error", error_message="Err")
        # call-002: ошибка с retry_count=3 (max)
        for _ in range(3):
            update_processing_status(db, "call-002", "error", error_message="Err")

        retryable = get_retryable_calls(db, max_retries=3)
        assert len(retryable) == 1
        assert retryable[0]["call_id"] == "call-001"

    def test_get_retryable_excludes_non_error(self, db, sample_call):
        """Retryable не включает не-error статусы."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001", status="pending")

        retryable = get_retryable_calls(db)
        assert len(retryable) == 0


# ── operators ────────────────────────────────────────────────────────────────


class TestOperators:
    """Тесты CRUD для операторов."""

    def test_upsert_and_list(self, db):
        """Вставка и получение списка операторов."""
        upsert_operator(db, "test.ru", "101", "Иванов Иван")
        upsert_operator(db, "test.ru", "102", "Петров Пётр")

        ops = list_operators(db, "test.ru")
        assert len(ops) == 2
        names = {op["name"] for op in ops}
        assert "Иванов Иван" in names
        assert "Петров Пётр" in names

    def test_upsert_updates_existing(self, db):
        """Повторный upsert обновляет имя оператора."""
        upsert_operator(db, "test.ru", "101", "Иванов")
        upsert_operator(db, "test.ru", "101", "Иванов Иван Иваныч")

        ops = list_operators(db, "test.ru")
        assert len(ops) == 1
        assert ops[0]["name"] == "Иванов Иван Иваныч"

    def test_get_operator_name(self, db):
        """Получение имени оператора по домену и добавочному."""
        upsert_operator(db, "test.ru", "101", "Иванов Иван")
        assert get_operator_name(db, "test.ru", "101") == "Иванов Иван"

    def test_get_operator_name_unknown(self, db):
        """Несуществующий оператор возвращает None."""
        assert get_operator_name(db, "test.ru", "999") is None

    def test_list_operators_other_domain(self, db):
        """Операторы другого домена не возвращаются."""
        upsert_operator(db, "test.ru", "101", "Иванов")
        upsert_operator(db, "other.ru", "201", "Сидоров")

        ops = list_operators(db, "test.ru")
        assert len(ops) == 1
        assert ops[0]["extension"] == "101"


# ── departments ──────────────────────────────────────────────────────────────


class TestDepartments:
    """Тесты CRUD для отделов."""

    def test_upsert_and_list(self, db):
        """Вставка и получение списка отделов."""
        upsert_department(db, "test.ru", 1, "100", "Продажи")
        upsert_department(db, "test.ru", 2, "200", "Поддержка")

        depts = list_departments(db, "test.ru")
        assert len(depts) == 2
        names = {d["name"] for d in depts}
        assert "Продажи" in names
        assert "Поддержка" in names

    def test_upsert_updates_existing(self, db):
        """Повторный upsert обновляет отдел."""
        upsert_department(db, "test.ru", 1, "100", "Продажи")
        upsert_department(db, "test.ru", 1, "100", "Отдел продаж")

        depts = list_departments(db, "test.ru")
        assert len(depts) == 1
        assert depts[0]["name"] == "Отдел продаж"

    def test_list_departments_other_domain(self, db):
        """Отделы другого домена не возвращаются."""
        upsert_department(db, "test.ru", 1, "100", "Продажи")
        upsert_department(db, "other.ru", 2, "200", "Поддержка")

        depts = list_departments(db, "test.ru")
        assert len(depts) == 1
        assert depts[0]["name"] == "Продажи"


# ── update_domain_poll_time ──────────────────────────────────────────────────


class TestDomainPollTime:
    """Тесты обновления времени поллинга домена."""

    def test_update_creates_domain(self, db):
        """Первый вызов создаёт запись домена."""
        update_domain_poll_time(db, "test.ru")
        cursor = db.execute("SELECT * FROM domains WHERE domain = ?", ("test.ru",))
        row = cursor.fetchone()
        assert row is not None
        assert row["domain"] == "test.ru"
        assert row["last_polled_at"] is not None

    def test_update_refreshes_timestamp(self, db):
        """Повторный вызов обновляет время."""
        update_domain_poll_time(db, "test.ru")
        cursor = db.execute("SELECT last_polled_at FROM domains WHERE domain = ?", ("test.ru",))
        ts1 = cursor.fetchone()["last_polled_at"]

        update_domain_poll_time(db, "test.ru")
        cursor = db.execute("SELECT last_polled_at FROM domains WHERE domain = ?", ("test.ru",))
        ts2 = cursor.fetchone()["last_polled_at"]

        # Временные метки должны быть разными (или как минимум не раньше)
        assert ts2 >= ts1


# ── update_call_from_polling ────────────────────────────────────────────────


class TestUpdateCallFromPolling:
    """Тесты обновления звонка данными из polling."""

    @pytest.fixture
    def webhook_call(self):
        """Звонок, созданный webhook-ом без записи."""
        return {
            "id": "call-wh-001",
            "domain": "example.gravitel.ru",
            "direction": "in",
            "result": "",
            "duration": 0,
            "wait": 0,
            "started_at": "2026-03-27T10:00:00+00:00",
            "client_number": "+79001234567",
            "operator_extension": "",
            "operator_name": None,
            "phone": "+74951234567",
            "record_url": "",
            "source": "webhook",
            "received_at": "2026-03-27T10:00:01+00:00",
        }

    @pytest.fixture
    def polling_data(self):
        """Данные из polling с record_url и duration."""
        return {
            "record_url": "https://records5.gravitel.ru/rec/call-wh-001.mp3",
            "duration": 120,
            "result": "success",
            "wait": 5,
            "operator_extension": "101",
            "operator_name": None,
        }

    def test_updates_empty_record_url(self, db, webhook_call, polling_data):
        """Обновляет звонок с пустым record_url."""
        insert_call(db, webhook_call)
        assert update_call_from_polling(db, "call-wh-001", polling_data) is True

        call = get_call(db, "call-wh-001")
        assert call["record_url"] == polling_data["record_url"]
        assert call["duration"] == 120
        assert call["result"] == "success"
        assert call["wait"] == 5
        assert call["operator_extension"] == "101"

    def test_skips_already_filled(self, db, sample_call, polling_data):
        """Не обновляет звонок с уже заполненным record_url."""
        insert_call(db, sample_call)  # sample_call имеет record_url
        assert update_call_from_polling(db, "call-001", polling_data) is False

        call = get_call(db, "call-001")
        # Оригинальный URL остался
        assert call["record_url"] == "https://cdn.example.com/rec/call-001.mp3"

    def test_nonexistent_call(self, db, polling_data):
        """Возвращает False для несуществующего звонка."""
        assert update_call_from_polling(db, "nonexistent", polling_data) is False

    def test_preserves_existing_extension(self, db, webhook_call, polling_data):
        """Сохраняет operator_extension, если polling отдаёт пустую строку."""
        webhook_call["operator_extension"] = "201"
        insert_call(db, webhook_call)

        polling_data["operator_extension"] = ""
        update_call_from_polling(db, "call-wh-001", polling_data)

        call = get_call(db, "call-wh-001")
        assert call["operator_extension"] == "201"


# ── reopen_processing ───────────────────────────────────────────────────────


class TestReopenProcessing:
    """Тесты перевода skipped → pending."""

    def test_reopens_skipped(self, db, sample_call):
        """Переводит skipped → pending и очищает skip_reason."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001", status="skipped", skip_reason="no record")

        assert reopen_processing(db, "call-001") is True

        proc = get_processing(db, "call-001")
        assert proc["status"] == "pending"
        assert proc["skip_reason"] is None

    def test_ignores_done(self, db, sample_call):
        """Не трогает звонки со статусом done."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001", status="done")

        assert reopen_processing(db, "call-001") is False

        proc = get_processing(db, "call-001")
        assert proc["status"] == "done"

    def test_ignores_error(self, db, sample_call):
        """Не трогает звонки со статусом error."""
        insert_call(db, sample_call)
        insert_processing(db, "call-001", status="pending")
        update_processing_status(db, "call-001", "error", error_message="fail")

        assert reopen_processing(db, "call-001") is False

    def test_nonexistent(self, db):
        """Возвращает False для несуществующего call_id."""
        assert reopen_processing(db, "nonexistent") is False
