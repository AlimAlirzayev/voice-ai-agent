# Voice AI Agent

FastAPI + LangGraph voice assistant with persistent SQLite conversation memory.

## Run locally

Create `apps/voice-ai-agent/.env` from `.env.example`, then add `OPENAI_API_KEY`.

```bash
cd apps/voice-ai-agent
uv sync
uv run uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` and call `POST /chat`:

```json
{"message": "Salam, mənim adım Alimdir", "thread_id": "demo"}
```

Send another request with the same `thread_id` to continue the conversation.

## Run with Docker

```bash
docker build -t voice-ai-agent apps/voice-ai-agent
docker run --rm -p 8000:8000 --env-file apps/voice-ai-agent/.env voice-ai-agent
```

The `POST /voice` endpoint accepts an audio upload, transcribes it with Whisper,
runs the same agent, and returns a base64-encoded spoken response. ElevenLabs
is preferred for speech synthesis when `ELEVENLABS_API_KEY` is configured; OpenAI
TTS is used as the fallback.

## Telegram bot

Start the API first, set `TELEGRAM_BOT_TOKEN`, then run:

```bash
uv run python bot.py
```# Voice AI Agent app

Bu qovluq layihənin əsas Python tətbiqidir.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

Əsas endpoint-lər:

- `GET /`
- `POST /chat`
- `POST /voice`

Telegram bot:

```bash
python bot.py
```

Test:

```bash
pytest
```

Chat provider:

- `LLM_PROVIDER=auto` — `GROQ_API_KEY` varsa Groq, yoxdursa OpenAI.
- `LLM_PROVIDER=groq` — Groq-u məcburi istifadə edir.
- `LLM_PROVIDER=openai` — OpenAI chat modelini məcburi istifadə edir.
