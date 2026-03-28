# Доступ к серверу AI-лаборатории

## Подключение

```bash
ssh ai-lab
```

Алиас `ai-lab` настроен в `~/.ssh/config`.

## Параметры подключения

| Параметр | Значение |
|---|---|
| Хост | `212.24.45.138` |
| Порт | `16380` |
| Пользователь | `aiadmin` |
| Hostname сервера | `gravitel-ai-lab` |
| SSH-ключ | `~/.ssh/id_ed25519_ailab` (без passphrase) |
| ОС | Ubuntu 24.04 (OpenSSH 9.6) |

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
| Docker | — | Для Open WebUI |
| Open WebUI | latest | Docker, порт 3080 |

## Мониторинг (Prometheus)

### Сервисы на сервере

| Сервис | Порт | systemd unit | Статус |
|---|---|---|---|
| node_exporter | `9100` | `prometheus-node-exporter` | Установлен, active |
| nvidia_gpu_exporter | `9835` | `nvidia_gpu_exporter` | Установлен (v1.4.1, .deb), active |
| pipeline metrics | `8000` | — (поднимается пайплайном) | При запуске `python -m src.pipeline` |
| Ollama metrics | `11434` | — | Не поддерживается в v0.17.7, порт зарезервирован |
| Open WebUI | `8091` | Docker container `open-webui` | `docker compose up -d` из `~/01_LLM_GR` |

### Маппинг портов MikroTik → сервер

| Внешний порт | → Внутренний порт | Сервис |
|---|---|---|
| `42363` | → `9100` | node_exporter |
| `42364` | → `9835` | nvidia_gpu_exporter |
| `42365` | → `8000` | pipeline metrics |
| `42366` | → `11434` | Ollama metrics (зарезервирован) |
| `42367` | → `8080` | AI Lab Web (FastAPI) |
| `42368` | → `8090` | TTS API (venv_tts, модель 1.7B) |
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

- IP статический (`212.24.45.138`).
- Парольный доступ: `sshpass -p '<пароль>' ssh -p 16380 -o PreferredAuthentications=password aiadmin@<IP>` (использовать только если ключ не работает).
- На сервере в `authorized_keys` два ключа: `id_ed25519` (с passphrase, личный) и `id_ed25519_ailab` (без passphrase, для автоматизации).
- CDN PyTorch (`download-r2.pytorch.org`) таймаутит с сервера. Для обновления PyTorch — скачивать wheel локально на Mac и передавать по SCP.
- GigaAM v3 при установке из GitHub требует `--no-deps` (ограничение `torch<2.9` не совместимо с nightly).
