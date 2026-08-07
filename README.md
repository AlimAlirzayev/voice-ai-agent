# Voice AI Agent

FastAPI, LangGraph memory, OpenAI speech-to-text, optional ElevenLabs text-to-speech və Telegram bot ilə işləyən səsli AI agent.

Bu repo artıq köhnə n8n starter template deyil. Real entrypoint `apps/voice-ai-agent` altındakı Python tətbiqidir.

## Nə edir?

- `GET /` — health və aktiv inteqrasiyaları göstərir.
- `POST /chat` — eyni `thread_id` ilə yaddaşlı mətn söhbəti aparır.
- `POST /voice` — audio faylı transcribe edir, agent cavab verir və cavabı audio kimi qaytarır.
- `bot.py` — Telegram-da mətnə mətn, səsə səs cavabı verir.
- n8n workflow-ları — mətn və audio webhook-ları ilə backend endpointlərini çağırır.
- SQLite checkpoint-lər — söhbət yaddaşını restart-dan sonra saxlayır.
- LangSmith — LangGraph node-larının trace-lərini göstərir.

## Lokal işə salma

```bash
cd apps/voice-ai-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

`.env` faylında ən azı bunu doldur:

```bash
OPENAI_API_KEY=sk-...
```

Chat modeli üçün `LLM_PROVIDER=auto` default-dur: `GROQ_API_KEY` varsa Groq, yoxdursa OpenAI istifadə edir. Səs transkripsiyası və OpenAI TTS fallback üçün yenə `OPENAI_API_KEY` lazımdır.

API-ni başlat:

```bash
uvicorn app.main:app --reload
```

Yoxlama:

```bash
curl http://127.0.0.1:8000/
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"demo","message":"Salam, mənim adım Alimdir."}'
```

Qeyd: `OPENAI_API_KEY` boş olsa belə health endpoint açılır. `/chat` və `/voice` isə açar tələb edir və aydın xəta qaytarır.

## Əsas istifadə ssenarisi: Telegram səs agenti

BotFather-dan bot yaradıb `.env` faylına tokeni əlavə et. API lokalda işləyirsə:

```bash
TELEGRAM_BOT_TOKEN=123456:...
BACKEND_URL=http://api:8000
```

Docker ilə backend və botu birlikdə başlat:

```bash
docker compose --profile telegram up --build
```

Sonra Telegram botuna voice message göndər. Bot audio faylını `/voice` endpointinə
ötürür, Whisper transcript yaradır, LangGraph cavabı hazırlayır və cavabı yenidən
Telegram voice message kimi göndərir. `/reset` həmin Telegram chat-i üçün yeni
LangGraph thread açır.

Lokal proseslərlə işlətmək istəsən, backend terminalında `uvicorn app.main:app`
işlədikdən sonra app qovluğunda ikinci terminaldan `python bot.py` çalışdır və
`BACKEND_URL=http://127.0.0.1:8000` istifadə et.

## Docker ilə

Root qovluqda:

```bash
cp .env.example .env
docker compose up --build
```

Host-da `8000` məşğuldursa `.env` içində `API_PORT=8011` kimi dəyiş.

Telegram botu da konteynerdə işlətmək üçün:

```bash
docker compose --profile telegram up --build
```

n8n-i də paralel qaldırmaq üçün:

```bash
docker compose --profile telegram --profile n8n up --build
```

n8n açılır: `http://localhost:5678`. Import olunan workflow webhook-u:

```bash
curl -X POST http://localhost:5678/webhook/voice-ai-agent-chat \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"n8n-demo","message":"Salam, n8n-dən gəlirəm"}'
```

Audio webhook-u ilə:

```bash
curl -X POST http://localhost:5678/webhook/voice-ai-agent-voice \
  -F 'file=@voice.ogg;type=audio/ogg' \
  -F 'thread_id=n8n-voice'
```

Bu workflow n8n-də audio input-u, backend request-ini və JSON nəticəsini bir
axında göstərir. Telegram bot isə real istifadəçi kanalıdır.

## LangSmith tracing

LangGraph tracing-i aktiv etmək üçün `.env`-də bunları doldur:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=voice-ai-agent
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

API və botu restart etdikdən sonra Telegram-dan səs göndər. LangGraph agent
çağırışı LangSmith-də `voice-ai-agent` project-i altında görünəcək. Orada
`agent` node-un input history-sini, system prompt-u, model cavabını və latency-ni
yoxlamaq mümkündür. `LANGSMITH_API_KEY` boşdursa tətbiq işləməyə davam edir, sadəcə
trace göndərilmir.

## Kod axını

1. `bot.py:on_voice` Telegram audio-sunu yükləyir və `/voice` endpointinə multipart
   request göndərir.
2. `app/api/voice.py` audio-nu `transcribe` edir, `run_turn` ilə agenti çağırır və
   `synthesize` ilə audio cavab yaradır.
3. `app/graph/builder.py` LangGraph state-ini SQLite checkpointer ilə `thread_id`
   üzrə saxlayır.
4. `app/services/voice.py` Whisper, ElevenLabs və OpenAI audio klientlərini idarə edir.
5. `app/core/config.py` LangSmith dəyişənlərini process environment-a ötürür; buna
   görə LangChain tracing konfiqurasiyanı görür.

## Əsas env dəyişənləri

| Dəyişən | Məna |
|---|---|
| `LLM_PROVIDER` | `auto`, `openai` və ya `groq` |
| `GROQ_API_KEY` | Groq chat provider üçün açar |
| `GROQ_MODEL` | Groq modeli, default `llama-3.1-8b-instant` |
| `OPENAI_API_KEY` | Chat, Whisper və OpenAI TTS üçün tələb olunur |
| `OPENAI_MODEL` | Chat modeli, default `gpt-4.1-mini` |
| `OPENAI_STT_MODEL` | Speech-to-text modeli, default `whisper-1` |
| `ELEVENLABS_API_KEY` | Optional TTS provider; yoxdursa OpenAI TTS istifadə olunur |
| `TELEGRAM_BOT_TOKEN` | Telegram bot üçün token |
| `BACKEND_URL` | Botun API-yə qoşulduğu URL |
| `SQLITE_PATH` | LangGraph checkpoint SQLite faylı |
| `LANGSMITH_API_KEY` | Optional tracing |

## Testlər

```bash
cd apps/voice-ai-agent
pytest
```

## Struktur

```text
apps/voice-ai-agent/
  app/
    api/        FastAPI endpoint-ləri
    graph/      LangGraph agent və memory flow
    memory/     SQLite checkpointer
    services/   OpenAI, ElevenLabs və LLM klientləri
  bot.py        Telegram bot entrypoint
  pyproject.toml
docker-compose.yml
```
