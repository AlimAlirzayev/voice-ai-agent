# n8n integration

Bu qovluqdakı iki workflow Docker Compose ilə avtomatik import olunur:

- `Voice AI Agent Chat Webhook`: JSON mesajını backend `/chat` endpointinə ötürür.
- `Voice AI Agent Voice Webhook`: multipart audio faylını backend `/voice` endpointinə ötürür.

Başlatmaq:

```bash
docker compose --profile n8n up --build
```

Telegram botla birlikdə:

```bash
docker compose --profile telegram --profile n8n up --build
```

n8n UI:

```text
http://localhost:5678
```

Webhook test:

```bash
curl -X POST http://localhost:5678/webhook/voice-ai-agent-chat \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"n8n-demo","message":"Salam"}'
```

Səs workflow-u üçün `data` adlı binary audio field göndərilməlidir. Məsələn:

```bash
curl -X POST http://localhost:5678/webhook/voice-ai-agent-voice \
  -F 'file=@voice.ogg;type=audio/ogg' \
  -F 'thread_id=n8n-voice'
```

Workflow cavabında `transcript`, `reply`, `audio_base64`, `audio_mime` və
`history_length` sahələri görünür. n8n audio cavabını Telegram-a göndərmir;
Telegram üçün əsas işlək yol `telegram-bot` servisidir.
