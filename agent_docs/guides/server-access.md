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

## Примечания

- IP статический (`212.24.45.138`).
- Парольный доступ: `sshpass -p '<пароль>' ssh -p 16380 -o PreferredAuthentications=password aiadmin@<IP>` (использовать только если ключ не работает).
- На сервере в `authorized_keys` два ключа: `id_ed25519` (с passphrase, личный) и `id_ed25519_ailab` (без passphrase, для автоматизации).
- CDN PyTorch (`download-r2.pytorch.org`) таймаутит с сервера. Для обновления PyTorch — скачивать wheel локально на Mac и передавать по SCP.
- GigaAM v3 при установке из GitHub требует `--no-deps` (ограничение `torch<2.9` не совместимо с nightly).
