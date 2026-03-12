"""CLI-просмотрщик результатов обработки звонков.

Использование:
    python -m src.viewer              — таблица всех звонков
    python -m src.viewer <файл>       — детали одного звонка
    python -m src.viewer --sort score — сортировка по оценке качества
    python -m src.viewer --sort date  — сортировка по дате обработки
    python -m src.viewer --sort dur   — сортировка по длительности
"""

import json
import sys
import textwrap
from pathlib import Path

from src.config import RESULTS_DIR


def load_results(results_dir: Path | None = None) -> list[dict]:
    """Загрузить все JSON-результаты из директории."""
    results_dir = Path(results_dir or RESULTS_DIR)
    results = []
    for f in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠ Ошибка чтения {f.name}: {e}", file=sys.stderr)
    return results


def format_duration(sec: float) -> str:
    """Форматировать секунды в MM:SS."""
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def quality_bar(score: int, max_score: int = 10) -> str:
    """Визуальная шкала качества."""
    filled = round(score * 10 / max_score)
    return "█" * filled + "░" * (10 - filled)


def print_table(results: list[dict], sort_key: str = "file") -> None:
    """Вывести таблицу всех звонков."""
    if not results:
        print("Нет результатов в", RESULTS_DIR)
        return

    # Сортировка
    sort_funcs = {
        "file": lambda r: r.get("file", ""),
        "date": lambda r: r.get("processed_at", ""),
        "score": lambda r: r.get("quality_score", {}).get("total", 0),
        "dur": lambda r: r.get("duration_sec", 0),
    }
    key_fn = sort_funcs.get(sort_key, sort_funcs["file"])
    reverse = sort_key in ("score", "dur", "date")
    results = sorted(results, key=key_fn, reverse=reverse)

    # Шапка
    print(f"\n{'#':>3}  {'Файл':<50} {'Длит':>5} {'Оценка':>6}  {'Качество':<12} {'Тема'}")
    print("─" * 120)

    for i, r in enumerate(results, 1):
        fname = r.get("file", "?")
        dur = format_duration(r.get("duration_sec", 0))
        score = r.get("quality_score", {}).get("total", 0)
        bar = quality_bar(score)
        topic = r.get("summary", {}).get("topic", "—")
        # Обрезаем тему если длинная
        if len(topic) > 45:
            topic = topic[:42] + "..."
        print(f"{i:>3}  {fname:<50} {dur:>5} {score:>5}/10  {bar}  {topic}")

    # Итого
    total_dur = sum(r.get("duration_sec", 0) for r in results)
    avg_score = sum(r.get("quality_score", {}).get("total", 0) for r in results) / len(results)
    print("─" * 120)
    print(f"     Всего: {len(results)} звонков, {format_duration(total_dur)} общая длительность, средняя оценка: {avg_score:.1f}/10")
    print()


def print_detail(result: dict) -> None:
    """Вывести детали одного звонка."""
    print()
    print("=" * 80)
    print(f"  📞 {result.get('file', '?')}")
    print("=" * 80)

    # Мета
    print(f"\n  Обработан: {result.get('processed_at', '?')}")
    print(f"  Длительность: {format_duration(result.get('duration_sec', 0))}")

    # Оценка качества
    qs = result.get("quality_score", {})
    total = qs.get("total", 0)
    print(f"\n  ⭐ Оценка качества: {total}/10  {quality_bar(total)}")

    criteria = qs.get("criteria", {})
    if criteria:
        print()
        for name, info in criteria.items():
            labels = {
                "greeting": "Приветствие",
                "listening": "Слушание",
                "solution": "Решение",
                "politeness": "Вежливость",
                "closing": "Завершение",
            }
            label = labels.get(name, name)
            s = info.get("score", 0)
            comment = info.get("comment", "")
            print(f"    {label:<14} {s:>2}/10  {quality_bar(s)}  {comment}")

    # Резюме
    summary = result.get("summary", {})
    if summary:
        print(f"\n  📋 Тема: {summary.get('topic', '—')}")
        print(f"  📋 Итог: {summary.get('outcome', '—')}")
        kp = summary.get("key_points", [])
        if kp:
            print("  📋 Ключевые моменты:")
            for p in kp:
                wrapped = textwrap.fill(p, width=70, initial_indent="     • ", subsequent_indent="       ")
                print(wrapped)

    # Извлечённые данные
    ed = result.get("extracted_data", {})
    if ed:
        print("\n  📦 Извлечённые данные:")
        if ed.get("client_name"):
            print(f"     Клиент: {ed['client_name']}")
        if ed.get("contract_number"):
            print(f"     Договор: {ed['contract_number']}")
        if ed.get("phone_number"):
            print(f"     Телефон: {ed['phone_number']}")
        issues = ed.get("issues", [])
        if issues:
            print("     Проблемы:")
            for issue in issues:
                print(f"       - {issue}")
        agreements = ed.get("agreements", [])
        if agreements:
            print("     Договорённости:")
            for a in agreements:
                print(f"       - {a}")
        if ed.get("callback_needed"):
            print("     ⚠ Требуется перезвонить!")
        steps = ed.get("next_steps", [])
        if steps:
            print("     Следующие шаги:")
            for s in steps:
                print(f"       - {s}")

    # Транскрипт
    transcript = result.get("transcript", "")
    if transcript:
        print("\n  💬 Транскрипт:")
        print("  " + "─" * 76)
        for line in transcript.split("\n"):
            if line.strip():
                wrapped = textwrap.fill(line, width=74, initial_indent="    ", subsequent_indent="    ")
                print(wrapped)
        print("  " + "─" * 76)

    print()


def find_result(query: str, results: list[dict]) -> dict | None:
    """Найти результат по имени файла (частичное совпадение)."""
    query_lower = query.lower()
    for r in results:
        if query_lower in r.get("file", "").lower():
            return r
    return None


def main():
    """CLI-точка входа."""
    args = sys.argv[1:]
    sort_key = "file"

    # Парсинг аргументов
    if "--sort" in args:
        idx = args.index("--sort")
        if idx + 1 < len(args):
            sort_key = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            print("Ошибка: --sort требует аргумент (file, date, score, dur)")
            sys.exit(1)

    results = load_results()

    if args:
        # Детальный просмотр
        r = find_result(args[0], results)
        if r:
            print_detail(r)
        else:
            print(f"Файл не найден: {args[0]}")
            print("Доступные файлы:")
            for r in results:
                print(f"  {r.get('file', '?')}")
            sys.exit(1)
    else:
        # Таблица
        print_table(results, sort_key)


if __name__ == "__main__":
    main()
