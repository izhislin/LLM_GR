"""Генератор HTML-отчёта по результатам обработки звонков.

Использование:
    python -m src.report_generator                  — отчёт в data/report.html
    python -m src.report_generator -o my_report.html — указать путь
"""

import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from src.config import RESULTS_DIR, DATA_DIR


def load_results(results_dir: Path | None = None) -> list[dict]:
    """Загрузить все JSON-результаты."""
    results_dir = Path(results_dir or RESULTS_DIR)
    results = []
    for f in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return results


def _score_color(score: int) -> str:
    """CSS-цвет для оценки."""
    if score >= 8:
        return "#22c55e"
    if score >= 5:
        return "#eab308"
    return "#ef4444"


def _format_duration(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _format_transcript_html(transcript: str) -> str:
    """Форматировать транскрипт в HTML с подсветкой ролей."""
    lines = []
    for line in transcript.split("\n"):
        line = line.strip()
        if not line:
            continue
        escaped = escape(line)
        if "Оператор:" in escaped:
            escaped = escaped.replace("Оператор:", '<span class="role-op">Оператор:</span>')
        if "Клиент:" in escaped:
            escaped = escaped.replace("Клиент:", '<span class="role-cl">Клиент:</span>')
        lines.append(f"<div class='transcript-line'>{escaped}</div>")
    return "\n".join(lines)


def _criteria_html(criteria: dict) -> str:
    """HTML для критериев качества."""
    labels = {
        "greeting": "Приветствие",
        "listening": "Слушание",
        "solution": "Решение",
        "politeness": "Вежливость",
        "closing": "Завершение",
    }
    rows = []
    for name, info in criteria.items():
        label = labels.get(name, name)
        score = info.get("score", 0)
        comment = escape(info.get("comment", ""))
        color = _score_color(score)
        pct = score * 10
        rows.append(f"""
            <div class="criteria-row">
                <span class="criteria-label">{label}</span>
                <div class="criteria-bar-bg">
                    <div class="criteria-bar" style="width:{pct}%;background:{color}"></div>
                </div>
                <span class="criteria-score" style="color:{color}">{score}/10</span>
                <span class="criteria-comment">{comment}</span>
            </div>""")
    return "\n".join(rows)


def _card_html(r: dict, idx: int) -> str:
    """HTML-карточка одного звонка."""
    fname = escape(r.get("file", "?"))
    dur = _format_duration(r.get("duration_sec", 0))
    dur_sec = r.get("duration_sec", 0)
    processed = r.get("processed_at", "")[:19].replace("T", " ")

    qs = r.get("quality_score", {})
    total = qs.get("total", 0)
    color = _score_color(total)
    criteria = qs.get("criteria", {})

    summary = r.get("summary", {})
    topic = escape(summary.get("topic", "—"))
    outcome = escape(summary.get("outcome", "—"))
    key_points = summary.get("key_points", [])
    kp_html = "\n".join(f"<li>{escape(p)}</li>" for p in key_points)

    ed = r.get("extracted_data", {})
    client_name = escape(ed.get("client_name") or "—")
    contract = escape(ed.get("contract_number") or "—")
    phone = escape(ed.get("phone_number") or "—")
    callback = "⚠️ Да" if ed.get("callback_needed") else "Нет"
    issues = ed.get("issues", [])
    issues_html = ", ".join(escape(i) for i in issues) if issues else "—"
    agreements = ed.get("agreements", [])
    agreements_html = ", ".join(escape(a) for a in agreements) if agreements else "—"

    transcript = _format_transcript_html(r.get("transcript", ""))

    return f"""
    <div class="card" data-score="{total}" data-dur="{dur_sec}" data-file="{fname}">
        <div class="card-header" onclick="toggleCard({idx})">
            <div class="card-title">
                <span class="card-num">#{idx+1}</span>
                <span class="card-file">{fname}</span>
            </div>
            <div class="card-meta">
                <span class="badge">{dur}</span>
                <span class="badge score-badge" style="background:{color}">{total}/10</span>
                <span class="card-topic">{topic[:60]}{'...' if len(topic) > 60 else ''}</span>
                <span class="expand-icon" id="icon-{idx}">▶</span>
            </div>
        </div>
        <div class="card-body" id="body-{idx}" style="display:none">
            <div class="section">
                <h3>📋 Резюме</h3>
                <p><strong>Тема:</strong> {topic}</p>
                <p><strong>Итог:</strong> {outcome}</p>
                <ul>{kp_html}</ul>
            </div>
            <div class="section">
                <h3>⭐ Оценка качества — <span style="color:{color}">{total}/10</span></h3>
                {_criteria_html(criteria)}
            </div>
            <div class="section">
                <h3>📦 Извлечённые данные</h3>
                <table class="data-table">
                    <tr><td>Клиент</td><td>{client_name}</td></tr>
                    <tr><td>Договор</td><td>{contract}</td></tr>
                    <tr><td>Телефон</td><td>{phone}</td></tr>
                    <tr><td>Проблемы</td><td>{issues_html}</td></tr>
                    <tr><td>Договорённости</td><td>{agreements_html}</td></tr>
                    <tr><td>Перезвонить</td><td>{callback}</td></tr>
                </table>
            </div>
            <div class="section">
                <h3>💬 Транскрипт</h3>
                <div class="transcript">{transcript}</div>
            </div>
            <div class="section meta-footer">
                Обработано: {processed}
            </div>
        </div>
    </div>"""


def generate_report(
    results_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Сгенерировать HTML-отчёт.

    Returns:
        Путь к сгенерированному файлу.
    """
    results = load_results(results_dir)
    output_path = Path(output_path or DATA_DIR / "report.html")

    if not results:
        output_path.write_text("<h1>Нет результатов</h1>", encoding="utf-8")
        return output_path

    # Статистика
    total_calls = len(results)
    total_dur = sum(r.get("duration_sec", 0) for r in results)
    avg_score = sum(r.get("quality_score", {}).get("total", 0) for r in results) / total_calls
    min_score = min(r.get("quality_score", {}).get("total", 0) for r in results)
    max_score = max(r.get("quality_score", {}).get("total", 0) for r in results)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Карточки
    cards = "\n".join(_card_html(r, i) for i, r in enumerate(results))

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Отчёт — Обработка звонков</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f172a; color:#e2e8f0; padding:20px; }}
.container {{ max-width:1100px; margin:0 auto; }}
h1 {{ font-size:1.6em; margin-bottom:4px; color:#f8fafc; }}
.subtitle {{ color:#94a3b8; margin-bottom:20px; font-size:0.9em; }}

.stats {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px,1fr)); gap:12px; margin-bottom:24px; }}
.stat-card {{ background:#1e293b; border-radius:10px; padding:16px; text-align:center; }}
.stat-value {{ font-size:1.8em; font-weight:700; color:#f8fafc; }}
.stat-label {{ font-size:0.8em; color:#94a3b8; margin-top:4px; }}

.controls {{ display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; }}
.controls button {{ background:#1e293b; border:1px solid #334155; color:#e2e8f0; padding:8px 16px; border-radius:6px; cursor:pointer; font-size:0.85em; }}
.controls button:hover {{ background:#334155; }}
.controls button.active {{ background:#3b82f6; border-color:#3b82f6; }}
.search-input {{ background:#1e293b; border:1px solid #334155; color:#e2e8f0; padding:8px 14px; border-radius:6px; flex:1; min-width:200px; font-size:0.85em; }}
.search-input::placeholder {{ color:#64748b; }}

.card {{ background:#1e293b; border-radius:10px; margin-bottom:8px; overflow:hidden; border:1px solid #334155; }}
.card-header {{ padding:14px 18px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; gap:12px; }}
.card-header:hover {{ background:#243044; }}
.card-title {{ display:flex; align-items:center; gap:10px; min-width:0; }}
.card-num {{ color:#64748b; font-size:0.8em; flex-shrink:0; }}
.card-file {{ font-weight:500; font-size:0.85em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.card-meta {{ display:flex; align-items:center; gap:8px; flex-shrink:0; }}
.card-topic {{ color:#94a3b8; font-size:0.8em; max-width:300px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:none; }}
@media(min-width:800px) {{ .card-topic {{ display:inline; }} }}
.badge {{ padding:3px 10px; border-radius:20px; font-size:0.75em; font-weight:600; background:#334155; white-space:nowrap; }}
.score-badge {{ color:#fff; }}
.expand-icon {{ color:#64748b; font-size:0.7em; transition:transform 0.2s; }}
.expand-icon.open {{ transform:rotate(90deg); }}

.card-body {{ padding:0 18px 18px; }}
.section {{ margin-top:16px; }}
.section h3 {{ font-size:0.95em; margin-bottom:8px; color:#f8fafc; }}
.section p {{ font-size:0.85em; margin-bottom:4px; line-height:1.5; }}
.section ul {{ font-size:0.85em; margin-left:20px; line-height:1.6; }}

.criteria-row {{ display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:0.85em; }}
.criteria-label {{ width:100px; flex-shrink:0; color:#94a3b8; }}
.criteria-bar-bg {{ width:120px; height:8px; background:#334155; border-radius:4px; flex-shrink:0; overflow:hidden; }}
.criteria-bar {{ height:100%; border-radius:4px; transition:width 0.3s; }}
.criteria-score {{ width:40px; flex-shrink:0; font-weight:600; font-size:0.85em; }}
.criteria-comment {{ color:#94a3b8; font-size:0.8em; }}

.data-table {{ width:100%; font-size:0.85em; }}
.data-table td {{ padding:4px 8px; border-bottom:1px solid #1e293b; }}
.data-table td:first-child {{ color:#94a3b8; width:130px; }}

.transcript {{ background:#0f172a; border-radius:8px; padding:14px; font-size:0.82em; line-height:1.7; max-height:400px; overflow-y:auto; }}
.transcript-line {{ margin-bottom:4px; }}
.role-op {{ color:#3b82f6; font-weight:600; }}
.role-cl {{ color:#22c55e; font-weight:600; }}

.meta-footer {{ font-size:0.75em; color:#64748b; margin-top:12px; padding-top:8px; border-top:1px solid #334155; }}

footer {{ text-align:center; color:#475569; font-size:0.75em; margin-top:30px; padding:10px; }}
</style>
</head>
<body>
<div class="container">
    <h1>📞 Отчёт по обработке звонков</h1>
    <p class="subtitle">Сгенерировано: {generated} · Gravitel AI Lab</p>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{total_calls}</div>
            <div class="stat-label">Звонков</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{_format_duration(total_dur)}</div>
            <div class="stat-label">Общая длительность</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color:{_score_color(int(avg_score))}">{avg_score:.1f}</div>
            <div class="stat-label">Средняя оценка</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{min_score}–{max_score}</div>
            <div class="stat-label">Мин–Макс оценка</div>
        </div>
    </div>

    <div class="controls">
        <input type="text" class="search-input" id="search" placeholder="🔍 Поиск по файлу или теме..." oninput="filterCards()">
        <button onclick="sortCards('file')" id="btn-file" class="active">По имени</button>
        <button onclick="sortCards('score')" id="btn-score">По оценке</button>
        <button onclick="sortCards('dur')" id="btn-dur">По длительности</button>
        <button onclick="expandAll()" id="btn-expand">Развернуть все</button>
    </div>

    <div id="cards">
        {cards}
    </div>

    <footer>Gravitel AI Lab · GigaAM-v3 + Qwen3-8B · {generated}</footer>
</div>

<script>
function toggleCard(idx) {{
    const body = document.getElementById('body-' + idx);
    const icon = document.getElementById('icon-' + idx);
    if (body.style.display === 'none') {{
        body.style.display = 'block';
        icon.classList.add('open');
    }} else {{
        body.style.display = 'none';
        icon.classList.remove('open');
    }}
}}

let allExpanded = false;
function expandAll() {{
    allExpanded = !allExpanded;
    document.querySelectorAll('.card-body').forEach(b => b.style.display = allExpanded ? 'block' : 'none');
    document.querySelectorAll('.expand-icon').forEach(i => {{
        if (allExpanded) i.classList.add('open'); else i.classList.remove('open');
    }});
    document.getElementById('btn-expand').textContent = allExpanded ? 'Свернуть все' : 'Развернуть все';
}}

function sortCards(key) {{
    const container = document.getElementById('cards');
    const cards = [...container.querySelectorAll('.card')];
    cards.sort((a, b) => {{
        if (key === 'score') return parseFloat(b.dataset.score) - parseFloat(a.dataset.score);
        if (key === 'dur') return parseFloat(b.dataset.dur) - parseFloat(a.dataset.dur);
        return a.dataset.file.localeCompare(b.dataset.file);
    }});
    cards.forEach(c => container.appendChild(c));
    document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-' + key)?.classList.add('active');
}}

function filterCards() {{
    const q = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('.card').forEach(c => {{
        const text = c.textContent.toLowerCase();
        c.style.display = text.includes(q) ? '' : 'none';
    }});
}}
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main():
    """CLI-точка входа."""
    output_path = None
    args = sys.argv[1:]
    if "-o" in args:
        idx = args.index("-o")
        if idx + 1 < len(args):
            output_path = Path(args[idx + 1])

    path = generate_report(output_path=output_path)
    print(f"Отчёт сгенерирован: {path}")


if __name__ == "__main__":
    main()
