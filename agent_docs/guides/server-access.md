# Доступ к серверу AI-лаборатории

## Подключение

```bash
ssh ai-lab
```

Алиас `ai-lab` настроен в `~/.ssh/config`.

## Параметры подключения

| Параметр | Значение |
|---|---|
| Хост (внешний) | `212.24.45.138` |
| Порт (внешний SSH) | `16380` |
| Внутренний IP (LAN) | `192.168.1.190` |
| MAC (eno1) | `60:CF:84:62:59:2C` |
| Пользователь | `aiadmin` |
| Hostname сервера | `gravitel-ai-lab` |
| SSH-ключ | `~/.ssh/id_ed25519_ailab` (без passphrase) |
| ОС | Ubuntu 24.04 (OpenSSH 9.6) |

### Фиксация внутреннего IP

Внутренний IP `192.168.1.190` прибит **static DHCP lease** на MikroTik за MAC-адресом сервера. Это исключает смену IP при перезагрузках / power-loss: `IP → DHCP Server → Leases` содержит запись `60:CF:84:62:59:2C → 192.168.1.190` в статусе `static`.

Если IP когда-либо изменится снова, **все DNAT-правила в таблице ниже станут нерабочими одновременно** — симптом будет «ICMP до `212.24.45.138` идёт, но все TCP-порты в таймаут». Проверка: `ip -br a` на сервере, затем `IP → DHCP Server → Leases` в MikroTik.

## SSH-конфиг (`~/.ssh/config`)

```
Host ai-lab
    HostName 212.24.45.138
    Port 16380
    User aiadmin
    IdentityFile ~/.ssh/id_ed25519_ailab
    IdentitiesOnly yes
```

## Выполнение команд из агента

```bash
ssh ai-lab "команда"
```

Для многострочных скриптов:

```bash
ssh ai-lab 'bash -s' <<'EOF'
команда1
команда2
EOF
```

## Установленное ПО

| Компонент | Версия | Примечание |
|---|---|---|
| GPU | RTX 5060 Ti 16GB | Blackwell (sm_120), драйвер 590.48 |
| PyTorch | 2.12.0.dev+cu128 (nightly) | Стабильные не поддерживают sm_120 |
| GigaAM | 0.1.0 (из GitHub) | PyPI-версия не содержит v3 |
| Ollama | 0.17.7 | systemd-сервис, модель qwen3:8b |
| Python | 3.12.3 | venv: `~/venv_transcribe` |
| ffmpeg | 6.1.1 | |
| CUDA | 13.1 (driver) / 12.8 (PyTorch runtime) | |
| node_exporter | 1.7.0 | apt, systemd: `prometheus-node-exporter` |
| nvidia_gpu_exporter | 1.4.1 | .deb, systemd: `nvidia_gpu_exporter` |
| Docker | 28.2.2 | apt, `docker compose` v2 |
| Open WebUI | 0.8.12 | Docker, порт 8091, `WEBUI_NAME=Gravitel AI` |

## Мониторинг (Prometheus)

### Сервисы на сервере

| Сервис | Порт | systemd unit | Статус |
|---|---|---|---|
| node_exporter | `9100` | `prometheus-node-exporter` | Установлен, active |
| nvidia_gpu_exporter | `9835` | `nvidia_gpu_exporter` | Установлен (v1.4.1, .deb), active |
| pipeline metrics | `8000` | — (поднимается пайплайном) | При запуске `python -m src.pipeline` |
| Ollama metrics | `11434` | — | Не поддерживается в v0.17.7, порт зарезервирован |
| AI Lab Web (FastAPI) | `8080` | `ai-lab-web.service` (user) | Active, `uvicorn src.web.app:app` |
| TTS API (Qwen3-TTS 1.7B) | `8090` | `tts-api.service` (user) | Active, venv_tts |
| Open WebUI | `8091` | Docker container `open-webui` | `docker compose up -d` из `~/01_LLM_GR` |
| ByVoice Portal (Next.js) | `3200` | `byvoice-portal.service` (user) | Active, Next.js 15 + Auth.js v5 |

### Маппинг портов MikroTik → сервер

Все правила DNAT имеют `to-addresses=192.168.1.190`. При смене внутреннего IP правила надо обновлять одновременно во всех строках.

| Внешний порт | → Внутренний порт | Сервис |
|---|---|---|
| `16380` | → `22` | SSH |
| `42363` | → `9100` | node_exporter |
| `42364` | → `9835` | nvidia_gpu_exporter |
| `42365` | → `8000` | pipeline metrics |
| `42366` | → `11434` | Ollama metrics (зарезервирован) |
| `42367` | → `8080` | AI Lab Web (FastAPI) |
| `42368` | → `8090` | TTS API (venv_tts, модель 1.7B) |
| `42370` | → `3200` | ByVoice Portal (Next.js) |
| `42371` | → `8091` | Open WebUI |

### Prometheus scrape config

```yaml
scrape_configs:
  - job_name: 'ai-lab-node'
    static_configs:
      - targets: ['212.24.45.138:42363']

  - job_name: 'ai-lab-gpu'
    static_configs:
      - targets: ['212.24.45.138:42364']

  - job_name: 'ai-lab-pipeline'
    scrape_interval: 15s
    static_configs:
      - targets: ['212.24.45.138:42365']
```

## OpenAI-compatible API

Прокси-слой поверх Ollama в формате OpenAI Chat API. Живёт в основном FastAPI-приложении.

| Параметр | Значение |
|---|---|
| Внутренний URL | `http://localhost:8080/v1/chat/completions` |
| Внешний URL | `http://212.24.45.138:42367/v1/chat/completions` |
| Auth | `Authorization: Bearer <LLM_API_KEY>` |
| Модель | `qwen3:8b` |
| Endpoints | `GET /v1/models`, `POST /v1/chat/completions` |

`LLM_API_KEY` задан в `~/01_LLM_GR/.env`. Поддерживает stream/sync, параметры `temperature`, `top_p`, `max_tokens`.

## Примечания

- Внешний IP статический (`212.24.45.138`). Внутренний LAN-IP прибит static lease (см. выше).
- Парольный доступ: `sshpass -p '<пароль>' ssh -p 16380 -o PreferredAuthentications=password aiadmin@<IP>` (использовать только если ключ не работает).
- На сервере в `authorized_keys` два ключа: `id_ed25519` (с passphrase, личный) и `id_ed25519_ailab` (без passphrase, для автоматизации).
- CDN PyTorch (`download-r2.pytorch.org`) таймаутит с сервера. Для обновления PyTorch — скачивать wheel локально на Mac и передавать по SCP.
- GigaAM v3 при установке из GitHub требует `--no-deps` (ограничение `torch<2.9` не совместимо с nightly).

## Восстановление после power-loss

После отключения питания сервер **не стартует автоматически** — нужна кнопка Power вручную. TODO: включить в BIOS `Restore on AC Power Loss = Power On`, после этого восстановление будет автоматическим.

При загрузке `FAILED openipmi.service` перекрывает `login:` prompt, создавая впечатление зависания. Это косметика — нажать Enter и вводить логин. Сам юнит замаскирован (`systemctl mask openipmi.service`), но сообщение в boot-логе остаётся.

Если после старта снаружи все TCP-порты в таймаут, а ICMP до `212.24.45.138` отвечает:
1. Локально на сервере: `ip -br a` — убедиться, что `eno1` = `192.168.1.190/24`. Если другой IP, см. следующий пункт.
2. На MikroTik: `IP → DHCP Server → Leases` — убедиться, что запись `60:CF:84:62:59:2C → 192.168.1.190` в статусе `static`. Если съехала, исправить и на сервере выполнить `sudo dhclient -r eno1 && sudo dhclient eno1` или `sudo reboot`.

## ByVoice Portal (`byvoice-portal`)

Next.js 15 + Auth.js v5, запущен user-systemd юнитом `byvoice-portal.service` из `~/byvoice-portal/web-client/`. Настройки — `.env.production`.

Ключевая деталь: **`NEXTAUTH_URL` должен быть закомментирован**, иначе Auth.js жёстко редиректит на указанный URL и доступ с LAN (`192.168.1.190:3200`) ломается — всех пользователей выкидывает на внешний `212.24.45.138:42370`. Вместо этого включён `AUTH_TRUST_HOST=true` — Auth.js использует заголовок `Host` из запроса, редиректы становятся относительными и работают с обоих origin-ов.

Ребилд (`npm run build`) при правке `.env.production` **не нужен** — server-side переменные читаются в рантайме, достаточно `systemctl --user restart byvoice-portal`.
