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

function parseTranscriptSegments(text, segments) {
    // If structured segments available, use them
    if (segments && segments.length) {
        return segments.map(s => ({
            speaker: s.speaker, text: s.text,
            start: s.start, end: s.end,
        }));
    }
    // Fallback: parse [HH:MM:SS] from transcript text
    if (!text) return [];
    return text.split('\n').filter(l => l.trim()).map(line => {
        const m = line.match(/^\[(\d{2}):(\d{2}):(\d{2})\]\s*(Оператор|Клиент):\s*(.*)$/);
        if (!m) return null;
        const [, h, min, s, speaker, content] = m;
        return { speaker, text: content,
            start: parseInt(h)*3600 + parseInt(min)*60 + parseInt(s), end: null };
    }).filter(Boolean);
}

function fillEndTimes(segments, duration) {
    const safeDur = (duration && isFinite(duration)) ? duration : Infinity;
    for (let i = 0; i < segments.length; i++) {
        if (segments[i].end == null)
            segments[i].end = (i+1 < segments.length) ? segments[i+1].start : safeDur;
    }
    return segments;
}

function formatTimestamp(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${m}:${String(s).padStart(2,'0')}`;
}

function renderTranscript(text, segments, callId) {
    const parsed = parseTranscriptSegments(text, segments);
    if (!parsed.length) return '';

    const linesHtml = parsed.map((seg, i) => {
        const cls = seg.speaker === 'Оператор' ? 't-operator' : 't-client';
        const ts = formatTimestamp(seg.start);
        return `<div class="t-line ${cls}" data-index="${i}" data-start="${seg.start}" data-end="${seg.end || ''}">`
            + `<span class="t-time">[${ts}]</span> <strong>${escHtml(seg.speaker)}:</strong> ${escHtml(seg.text)}`
            + `</div>`;
    }).join('');

    return `
        <div class="call-card" id="player-card">
            <h2>Запись и транскрипт</h2>
            <div class="audio-player-wrap">
                <audio id="call-audio" preload="metadata" src="/api/audio/${encodeURIComponent(callId)}"></audio>
                <div class="player-controls">
                    <button id="play-btn" class="btn-play" title="Play/Pause">&#9654;</button>
                    <span id="current-time" class="player-time">0:00</span>
                    <div class="progress-bar-wrap" id="progress-wrap">
                        <div class="progress-bar" id="progress-bar"></div>
                    </div>
                    <span id="total-time" class="player-time">0:00</span>
                    <select id="speed-select" class="speed-select">
                        <option value="0.75">0.75x</option>
                        <option value="1" selected>1x</option>
                        <option value="1.25">1.25x</option>
                        <option value="1.5">1.5x</option>
                        <option value="2">2x</option>
                    </select>
                </div>
            </div>
            <div class="transcript" id="transcript-box">${linesHtml}</div>
        </div>`;
}

function initAudioPlayer(segments) {
    const audio = document.getElementById('call-audio');
    const playBtn = document.getElementById('play-btn');
    const progressWrap = document.getElementById('progress-wrap');
    const progressBar = document.getElementById('progress-bar');
    const currentTimeEl = document.getElementById('current-time');
    const totalTimeEl = document.getElementById('total-time');
    const speedSelect = document.getElementById('speed-select');
    const transcriptBox = document.getElementById('transcript-box');

    if (!audio || !playBtn) return;

    // Fill end times when duration is known
    audio.addEventListener('loadedmetadata', () => {
        totalTimeEl.textContent = formatTimestamp(audio.duration);
        fillEndTimes(segments, audio.duration);
    });

    // Play/Pause
    playBtn.addEventListener('click', () => {
        if (audio.paused) { audio.play(); playBtn.innerHTML = '&#9646;&#9646;'; }
        else { audio.pause(); playBtn.innerHTML = '&#9654;'; }
    });

    // Progress bar update + transcript highlight
    audio.addEventListener('timeupdate', () => {
        const t = audio.currentTime;
        const pct = audio.duration ? (t / audio.duration) * 100 : 0;
        progressBar.style.width = pct + '%';
        currentTimeEl.textContent = formatTimestamp(t);

        // Highlight current segment
        const lines = transcriptBox.querySelectorAll('.t-line');
        let activeIdx = -1;
        for (let i = 0; i < segments.length; i++) {
            if (t >= segments[i].start && (segments[i].end == null || t < segments[i].end)) {
                activeIdx = i;
                break;
            }
        }
        lines.forEach((el, i) => {
            el.classList.toggle('t-active', i === activeIdx);
        });

        // Auto-scroll to active line
        if (activeIdx >= 0 && lines[activeIdx]) {
            const line = lines[activeIdx];
            const box = transcriptBox;
            const lineTop = line.offsetTop - box.offsetTop;
            const boxScroll = box.scrollTop;
            const boxHeight = box.clientHeight;
            if (lineTop < boxScroll || lineTop > boxScroll + boxHeight - line.offsetHeight) {
                box.scrollTop = lineTop - boxHeight / 3;
            }
        }
    });

    // Click on progress bar to seek
    progressWrap.addEventListener('click', (e) => {
        const rect = progressWrap.getBoundingClientRect();
        const pct = (e.clientX - rect.left) / rect.width;
        audio.currentTime = pct * audio.duration;
    });

    // Click on transcript line to seek
    transcriptBox.addEventListener('click', (e) => {
        const line = e.target.closest('.t-line');
        if (!line) return;
        const start = parseFloat(line.dataset.start);
        if (!isNaN(start)) {
            audio.currentTime = start;
            if (audio.paused) { audio.play(); playBtn.innerHTML = '&#9646;&#9646;'; }
        }
    });

    // Speed control
    speedSelect.addEventListener('change', () => {
        audio.playbackRate = parseFloat(speedSelect.value);
    });

    // Audio ended
    audio.addEventListener('ended', () => {
        playBtn.innerHTML = '&#9654;';
    });

    // Handle audio load error
    audio.addEventListener('error', () => {
        const wrap = document.querySelector('.audio-player-wrap');
        if (wrap) wrap.innerHTML = '<div class="player-no-audio">Аудиозапись недоступна</div>';
    });
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
            ${renderTranscript(result.transcript, result.transcript_segments, callId)}

            ${proc.error_message ? `
            <div class="call-card">
                <h2>Ошибка</h2>
                <pre style="color:#721c24">${escHtml(proc.error_message)}</pre>
            </div>` : ''}
        `;

        // Initialize audio player
        const segments = parseTranscriptSegments(result.transcript, result.transcript_segments);
        if (result.duration_sec) fillEndTimes(segments, result.duration_sec);
        initAudioPlayer(segments);
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
