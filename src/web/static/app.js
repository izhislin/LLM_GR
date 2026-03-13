/* AI Lab — Анализ звонков: JS */

const API = '/api';
let currentPage = 1;
const perPage = 50;
let autoRefreshTimer = null;

// ── Helpers ─────────────────────────────────────────────────────────────────

function qs(sel) { return document.querySelector(sel); }

function formatDuration(sec) {
    if (!sec && sec !== 0) return '—';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
}

function formatTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatTimeFull(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}

function getScore(qs) {
    if (!qs) return null;
    return qs.total ?? qs.rounded_score ?? qs.average_score ?? null;
}

function scoreClass(score) {
    if (score >= 7) return 'score-high';
    if (score >= 5) return 'score-mid';
    return 'score-low';
}

function statusBadge(status) {
    const labels = { done: 'Готово', pending: 'Ожидает', processing: 'Обработка', error: 'Ошибка', skipped: 'Пропущен' };
    return `<span class="status status-${status || 'pending'}">${labels[status] || status || '—'}</span>`;
}

function dirBadge(dir) {
    if (dir === 'in') return '<span class="dir-in">&#x2193; Вх</span>';
    if (dir === 'out') return '<span class="dir-out">&#x2191; Исх</span>';
    return dir || '—';
}

function escHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Stats bar ───────────────────────────────────────────────────────────────

async function loadStats() {
    try {
        const resp = await fetch(`${API}/stats`);
        const data = await resp.json();
        const bar = qs('#stats-bar');
        if (bar) {
            bar.innerHTML = `
                <span class="stat-item">Всего: <span class="stat-value">${data.total_calls}</span></span>
                <span class="stat-item">Готово: <span class="stat-value">${data.done}</span></span>
                <span class="stat-item">В очереди: <span class="stat-value">${data.pending}</span></span>
                <span class="stat-item">Ошибки: <span class="stat-value">${data.error}</span></span>
            `;
        }
    } catch (e) { console.error('Stats error:', e); }
}

// ── Domains filter ──────────────────────────────────────────────────────────

async function loadDomains() {
    try {
        const resp = await fetch(`${API}/domains`);
        const domains = await resp.json();
        const sel = qs('#filter-domain');
        if (!sel) return;
        domains.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.domain;
            opt.textContent = `${d.domain} (${d.total_calls})`;
            sel.appendChild(opt);
        });
    } catch (e) { console.error('Domains error:', e); }
}

// ── Calls list ──────────────────────────────────────────────────────────────

function buildQuery() {
    const params = new URLSearchParams();
    const domain = qs('#filter-domain')?.value;
    const direction = qs('#filter-direction')?.value;
    const status = qs('#filter-status')?.value;
    const dateFrom = qs('#filter-date-from')?.value;
    const dateTo = qs('#filter-date-to')?.value;

    if (domain) params.set('domain', domain);
    if (direction) params.set('direction', direction);
    if (status) params.set('status', status);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    params.set('page', currentPage);
    params.set('per_page', perPage);
    return params.toString();
}

async function loadCalls() {
    const body = qs('#calls-body');
    if (!body) return;

    try {
        const resp = await fetch(`${API}/calls?${buildQuery()}`);
        const data = await resp.json();

        if (!data.calls.length) {
            body.innerHTML = '<tr><td colspan="7" class="loading">Нет звонков</td></tr>';
            return;
        }

        body.innerHTML = data.calls.map(c => {
            let scoreHtml = '—';
            if (c.processing_status === 'done' && c.result_json) {
                try {
                    const res = JSON.parse(c.result_json || '{}');
                    const total = getScore(res.quality_score);
                    if (total != null) {
                        scoreHtml = `<span class="score ${scoreClass(total)}">${total}/10</span>`;
                    }
                } catch (e) {}
            }

            return `<tr class="clickable" onclick="location.href='/call/${c.id}'">
                <td>${formatTime(c.started_at)}</td>
                <td>${dirBadge(c.direction)}</td>
                <td>${c.client_number || '—'}</td>
                <td>${c.operator_name || c.operator_extension || '—'}</td>
                <td>${formatDuration(c.duration)}</td>
                <td>${scoreHtml}</td>
                <td>${statusBadge(c.processing_status)}</td>
            </tr>`;
        }).join('');

        renderPagination(data.total, data.page, data.per_page);
    } catch (e) {
        body.innerHTML = '<tr><td colspan="7" class="loading">Ошибка загрузки</td></tr>';
        console.error('Calls error:', e);
    }
}

function renderPagination(total, page, pp) {
    const pag = qs('#pagination');
    if (!pag) return;
    const pages = Math.ceil(total / pp);
    if (pages <= 1) { pag.innerHTML = ''; return; }

    let html = '';
    for (let i = 1; i <= Math.min(pages, 10); i++) {
        html += `<button class="${i === page ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }
    if (pages > 10) html += `<span>... (${pages})</span>`;
    pag.innerHTML = html;
}

function goToPage(p) { currentPage = p; loadCalls(); }

// ── Call detail ─────────────────────────────────────────────────────────────

function renderQualityScore(qs) {
    if (!qs) return '';
    const score = getScore(qs);
    if (score == null) return '';

    const criteriaLabels = {
        greeting: 'Приветствие',
        listening: 'Слушание',
        solution: 'Решение',
        politeness: 'Вежливость',
        closing: 'Завершение',
    };

    let barsHtml = '';
    for (const [key, label] of Object.entries(criteriaLabels)) {
        // Support both flat (greeting: 3) and nested (criteria.greeting.score: 8) formats
        let val = qs[key];
        let comment = '';
        if (val != null && typeof val === 'object') {
            comment = val.comment || '';
            val = val.score;
        }
        if (qs.criteria?.[key]) {
            const c = qs.criteria[key];
            val = c.score ?? c;
            comment = c.comment || '';
        }
        if (val == null) continue;
        const pct = (val / 10) * 100;
        barsHtml += `
            <div class="criteria-row">
                <span class="criteria-label">${label}</span>
                <div class="criteria-bar-bg">
                    <div class="criteria-bar ${scoreClass(val)}" style="width:${pct}%"></div>
                </div>
                <span class="criteria-value">${val}</span>
            </div>
            ${comment ? `<div class="criteria-comment">${escHtml(comment)}</div>` : ''}`;
    }

    const ivrNote = qs.is_ivr ? '<div class="ivr-badge">IVR / Автоответчик</div>' : '';

    return `
        <div class="call-card">
            <h2>Оценка качества</h2>
            ${ivrNote}
            <div class="score-hero">
                <span class="score-big ${scoreClass(score)}">${score}<span class="score-max">/10</span></span>
            </div>
            <div class="criteria-grid">${barsHtml}</div>
        </div>`;
}

function renderSummary(s) {
    if (!s) return '';

    const typeLabel = s.call_type || '';
    const topicHtml = s.topic ? `<p class="summary-topic">${escHtml(s.topic)}</p>` : '';
    const outcomeHtml = s.outcome ? `<div class="summary-section"><strong>Результат:</strong> ${escHtml(s.outcome)}</div>` : '';

    let keyPointsHtml = '';
    if (s.key_points?.length) {
        keyPointsHtml = `
            <div class="summary-section">
                <strong>Ключевые моменты:</strong>
                <ul>${s.key_points.map(p => `<li>${escHtml(p)}</li>`).join('')}</ul>
            </div>`;
    }

    let actionsHtml = '';
    if (s.action_items?.length) {
        actionsHtml = `
            <div class="summary-section">
                <strong>Дальнейшие действия:</strong>
                <ul>${s.action_items.map(a => `<li>${escHtml(a)}</li>`).join('')}</ul>
            </div>`;
    }

    return `
        <div class="call-card">
            <h2>Резюме ${typeLabel ? `<span class="call-type-badge">${escHtml(typeLabel)}</span>` : ''}</h2>
            ${topicHtml}
            ${outcomeHtml}
            ${keyPointsHtml}
            ${actionsHtml}
        </div>`;
}

function renderExtractedData(ed) {
    if (!ed) return '';

    const fields = [
        ['operator_name', 'Оператор'],
        ['client_name', 'Клиент'],
        ['department', 'Отдел'],
        ['contract_number', 'Договор'],
        ['phone_number', 'Телефон'],
    ];

    let fieldsHtml = '';
    for (const [key, label] of fields) {
        const val = ed[key];
        if (val != null && val !== '') {
            fieldsHtml += `<div class="ed-field"><span class="ed-label">${label}:</span> <span class="ed-value">${escHtml(String(val))}</span></div>`;
        }
    }

    const renderList = (arr, title) => {
        if (!arr?.length) return '';
        return `<div class="ed-list"><strong>${title}:</strong><ul>${arr.map(i => `<li>${escHtml(i)}</li>`).join('')}</ul></div>`;
    };

    const callbackHtml = ed.callback_needed ? '<div class="ed-callback">Требуется обратный звонок</div>' : '';

    return `
        <div class="call-card">
            <h2>Извлечённые данные</h2>
            ${fieldsHtml ? `<div class="ed-fields">${fieldsHtml}</div>` : ''}
            ${callbackHtml}
            ${renderList(ed.agreements, 'Договорённости')}
            ${renderList(ed.issues, 'Проблемы')}
            ${renderList(ed.next_steps, 'Следующие шаги')}
        </div>`;
}

function renderTranscript(text) {
    if (!text) return '';

    const lines = text.split('\n').map(line => {
        const escaped = escHtml(line);
        if (escaped.includes('Оператор:')) {
            return `<div class="t-line t-operator">${escaped}</div>`;
        } else if (escaped.includes('Клиент:')) {
            return `<div class="t-line t-client">${escaped}</div>`;
        }
        return `<div class="t-line">${escaped}</div>`;
    }).join('');

    return `
        <div class="call-card">
            <h2>Транскрипт</h2>
            <div class="transcript">${lines}</div>
        </div>`;
}

async function loadCallDetail() {
    const el = qs('#call-detail');
    if (!el) return;

    const callId = el.dataset.callId;
    try {
        const resp = await fetch(`${API}/calls/${callId}`);
        if (!resp.ok) { el.innerHTML = '<div class="loading">Звонок не найден</div>'; return; }
        const data = await resp.json();
        const proc = data.processing || {};
        let result = {};
        if (proc.result_json) {
            try { result = JSON.parse(proc.result_json); } catch (e) {}
        }

        el.innerHTML = `
            <div class="call-card">
                <h2>Метаданные</h2>
                <div class="meta-grid">
                    <div class="meta-item"><label>ID</label><span>${data.id}</span></div>
                    <div class="meta-item"><label>Домен</label><span>${data.domain}</span></div>
                    <div class="meta-item"><label>Дата</label><span>${formatTimeFull(data.started_at)}</span></div>
                    <div class="meta-item"><label>Направление</label><span>${dirBadge(data.direction)}</span></div>
                    <div class="meta-item"><label>Длительность</label><span>${formatDuration(data.duration)}</span></div>
                    <div class="meta-item"><label>Клиент</label><span>${data.client_number || '—'}</span></div>
                    <div class="meta-item"><label>Оператор</label><span>${data.operator_name || data.operator_extension || '—'}</span></div>
                    <div class="meta-item"><label>Статус</label>${statusBadge(proc.status)}</div>
                    <div class="meta-item"><label>Время обработки</label><span>${proc.processing_time_sec ? proc.processing_time_sec.toFixed(1) + ' сек' : '—'}</span></div>
                </div>
            </div>

            ${renderQualityScore(result.quality_score)}
            ${renderSummary(result.summary)}
            ${renderExtractedData(result.extracted_data)}
            ${renderTranscript(result.transcript)}

            ${proc.error_message ? `
            <div class="call-card">
                <h2>Ошибка</h2>
                <pre style="color:#721c24">${escHtml(proc.error_message)}</pre>
            </div>` : ''}
        `;
    } catch (e) {
        el.innerHTML = '<div class="loading">Ошибка загрузки</div>';
        console.error('Detail error:', e);
    }
}

// ── Sync button ─────────────────────────────────────────────────────────────

function setupSync() {
    const btn = qs('#btn-sync');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Syncing...';
        try {
            const domain = qs('#filter-domain')?.value;
            if (domain) {
                await fetch(`${API}/sync/${domain}`, { method: 'POST' });
            } else {
                const resp = await fetch(`${API}/domains`);
                const domains = await resp.json();
                for (const d of domains) {
                    await fetch(`${API}/sync/${d.domain}`, { method: 'POST' });
                }
            }
            await loadCalls();
            await loadStats();
        } catch (e) { console.error('Sync error:', e); }
        btn.disabled = false;
        btn.textContent = 'Sync';
    });
}

// ── Filters ─────────────────────────────────────────────────────────────────

function setupFilters() {
    ['#filter-domain', '#filter-direction', '#filter-status', '#filter-date-from', '#filter-date-to'].forEach(sel => {
        const el = qs(sel);
        if (el) el.addEventListener('change', () => { currentPage = 1; loadCalls(); });
    });
}

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadDomains();

    if (qs('#calls-table')) {
        loadCalls();
        setupFilters();
        setupSync();
        autoRefreshTimer = setInterval(() => { loadCalls(); loadStats(); }, 30000);
    }

    if (qs('#call-detail')) {
        loadCallDetail();
    }
});
