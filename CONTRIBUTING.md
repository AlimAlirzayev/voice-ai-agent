# Contributing

Bu repo Voice AI Agent layihəsidir: FastAPI backend, LangGraph yaddaş, səs emalı və Telegram bot.

## Lokal yoxlama

```bash
cd apps/voice-ai-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

## PR qaydası

- Bir PR bir məsələni həll etsin.
- Secret-ləri commit etmə: `.env`, token, API key və runtime SQLite faylları Git-dən kənarda qalmalıdır.
- API davranışı dəyişirsə README-ni də yenilə.
- Mümkündürsə test əlavə et.
