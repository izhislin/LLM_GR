"""Тесты модуля фильтрации звонков."""

import pytest

from src.call_filter import filter_call
from src.domain_config import CallFilters


SAMPLE_CALL = {
    "duration": 120,
    "direction": "in",
    "result": "success",
    "record_url": "https://records.aicall.ru/test/abc.mp3",
}


class TestFilterCall:
    """Тесты функции filter_call."""

    def test_call_passes_all_filters(self):
        """Звонок проходит все фильтры."""
        filters = CallFilters()
        passed, reason = filter_call(SAMPLE_CALL, filters)
        assert passed is True
        assert reason is None

    def test_call_too_short(self):
        """Звонок слишком короткий."""
        call = {**SAMPLE_CALL, "duration": 15}
        filters = CallFilters()
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "too short" in reason

    def test_call_too_long(self):
        """Звонок слишком длинный."""
        call = {**SAMPLE_CALL, "duration": 1800}
        filters = CallFilters()
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "too long" in reason

    def test_call_no_record(self):
        """Звонок без записи (record_url=None)."""
        call = {**SAMPLE_CALL, "record_url": None}
        filters = CallFilters()
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "no record" in reason

    def test_call_empty_record(self):
        """Звонок с пустой записью (record_url='')."""
        call = {**SAMPLE_CALL, "record_url": ""}
        filters = CallFilters()
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "no record" in reason

    def test_call_wrong_result(self):
        """Звонок с неподходящим результатом."""
        call = {**SAMPLE_CALL, "result": "missed"}
        filters = CallFilters()
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "result: missed" in reason

    def test_call_wrong_type(self):
        """Звонок с неподходящим типом."""
        call = {**SAMPLE_CALL, "direction": "out"}
        filters = CallFilters(call_types=["in"])
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "type: out" in reason

    def test_call_zero_duration(self):
        """Звонок с нулевой длительностью."""
        call = {**SAMPLE_CALL, "duration": 0}
        filters = CallFilters()
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "too short" in reason

    def test_call_none_duration(self):
        """Звонок с duration=None."""
        call = {**SAMPLE_CALL, "duration": None}
        filters = CallFilters()
        passed, reason = filter_call(call, filters)
        assert passed is False
        assert "too short" in reason
