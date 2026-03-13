"""Фильтрация звонков по параметрам домена.

Проверяет звонок на соответствие фильтрам домена (наличие записи,
длительность, результат, тип). Используется перед отправкой звонка
в пайплайн обработки.
"""

from src.domain_config import CallFilters


def filter_call(call: dict, filters: CallFilters) -> tuple[bool, str | None]:
    """Проверить звонок на соответствие фильтрам.

    Проверки выполняются последовательно:
    1. Наличие записи (only_with_record)
    2. Минимальная длительность
    3. Максимальная длительность
    4. Допустимый результат
    5. Допустимый тип звонка

    Args:
        call: словарь с данными звонка (duration, direction, result, record_url).
        filters: фильтры домена.

    Returns:
        (True, None) — звонок прошёл все фильтры.
        (False, reason) — звонок отфильтрован с указанием причины.
    """
    # 1. Наличие записи
    if filters.only_with_record and not call.get("record_url"):
        return False, "no record"

    # 2. Длительность слишком мала
    duration = call.get("duration") or 0
    if duration < filters.min_duration_sec:
        return False, f"too short ({duration}s < {filters.min_duration_sec}s)"

    # 3. Длительность слишком велика
    if duration > filters.max_duration_sec:
        return False, f"too long ({duration}s > {filters.max_duration_sec}s)"

    # 4. Неподходящий результат
    result = call.get("result")
    if result not in filters.results:
        return False, f"result: {result}"

    # 5. Неподходящий тип звонка
    direction = call.get("direction")
    if "all" not in filters.call_types and direction not in filters.call_types:
        return False, f"type: {direction}"

    return True, None
