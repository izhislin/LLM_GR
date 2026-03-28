# LLM API — инструкция

## 1. API-ключ (токен)

**Где хранится:** файл `.env` на сервере `~/01_LLM_GR/.env`, переменная `LLM_API_KEY`.

**Как сгенерировать новый:**
```bash
ssh ai-lab
cd ~/01_LLM_GR
# Сгенерировать новый ключ
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Вписать в .env
nano .env   # строка LLM_API_KEY=<новый_ключ>
# Перезапустить сервис
systemctl --user restart ai-lab-web
```

Если `LLM_API_KEY` не задан или пустой — авторизация отключена, API открыт всем.

## 2. Подключение

| Параметр | Значение |
|---|---|
| **Base URL** | `http://212.24.45.138:42367/v1` |
| **Auth** | `Authorization: Bearer <LLM_API_KEY>` |
| **Модель** | `qwen3:8b` |
| **Формат** | OpenAI Chat API |

Для OpenAI SDK (Python/JS/Go) — указать только `base_url` и `api_key`, всё остальное стандартное.

## 3. Основные команды

### Список моделей
```bash
curl -H "Authorization: Bearer $KEY" \
  http://212.24.45.138:42367/v1/models
```

### Запрос (синхронный)
```bash
curl http://212.24.45.138:42367/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [
      {"role": "system", "content": "Ты ассистент."},
      {"role": "user", "content": "Что такое SIP?"}
    ],
    "stream": false,
    "max_tokens": 500
  }'
```

### Запрос (стриминг)
```bash
curl http://212.24.45.138:42367/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Привет!"}],
    "stream": true
  }'
```
Ответ приходит чанками в формате SSE (`data: {...}`), завершается `data: [DONE]`.

## 4. Параметры запроса

| Параметр | Тип | Описание |
|---|---|---|
| `model` | string | Название модели (`qwen3:8b`) |
| `messages` | array | Массив `{role, content}`. Роли: `system`, `user`, `assistant` |
| `stream` | bool | `true` — SSE-поток, `false` — один JSON |
| `temperature` | float | Креативность, 0.0–1.0 (default: модельный) |
| `top_p` | float | Nucleus sampling, 0.0–1.0 |
| `max_tokens` | int | Лимит токенов ответа (**минимум 200** из-за thinking-блока Qwen3) |

## 5. Формат ответа

**Синхронный** (`stream: false`):
```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "qwen3:8b",
  "choices": [{
    "message": {"role": "assistant", "content": "Ответ"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 20, "completion_tokens": 150, "total_tokens": 170}
}
```

**Стриминг** (`stream: true`) — каждый чанк:
```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"токен"},"finish_reason":null}]}

data: [DONE]
```

## 6. Быстрая проверка

```bash
# Задать ключ
export KEY="<ваш LLM_API_KEY>"

# Проверить доступность
curl -s -H "Authorization: Bearer $KEY" http://212.24.45.138:42367/v1/models | python3 -m json.tool

# Тестовый запрос
curl -s http://212.24.45.138:42367/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"Скажи привет"}],"stream":false,"max_tokens":200}' \
  | python3 -m json.tool
```

## 7. Примеры на Python (OpenAI SDK)

```bash
pip install openai
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://212.24.45.138:42367/v1",
    api_key="<ваш LLM_API_KEY>"
)

# Простой запрос
response = client.chat.completions.create(
    model="qwen3:8b",
    messages=[
        {"role": "system", "content": "Ты полезный ассистент."},
        {"role": "user", "content": "Что такое ВАТС?"}
    ]
)
print(response.choices[0].message.content)

# Стриминг
stream = client.chat.completions.create(
    model="qwen3:8b",
    messages=[{"role": "user", "content": "Объясни кратко что такое SIP"}],
    stream=True
)
for chunk in stream:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)
```

## 8. Примечания

- **Qwen3 thinking:** Модель тратит ~100-150 токенов на скрытый `<think>` блок перед ответом. При `max_tokens < 200` ответ может быть пустым.
- **Многоходовый диалог:** Добавляйте предыдущие ответы в `messages` с `role: "assistant"` — модель видит всю историю.
- **System prompt:** Задаёт поведение модели на весь диалог. Полезно для специализации.
- **Совместимость:** API работает с LangChain, LlamaIndex, AutoGen и любыми фреймворками, поддерживающими OpenAI формат.
- **Реализация:** `src/web/routes/openai_compat.py` — прокси к Ollama.
