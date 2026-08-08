# n8n integration

Bu qovluqdakı workflow-lar Docker Compose ilə avtomatik import olunur:

- `Voice AI Agent Chat Webhook`: JSON mesajını backend `/chat` endpointinə ötürür.
- `Voice AI Agent Voice Webhook`: multipart audio faylını backend `/voice` endpointinə ötürür.
- `Voice AI Agent Telegram Voice`: Telegram-dan səs mesajını qəbul edir, backend
  `/voice` endpointinə göndərir, base64 cavabını binary audio-ya çevirir və cavabı
  Telegram-a səsli mesaj kimi qaytarır.

Başlatmaq:

```bash
docker compose --profile n8n up --build
```

Əgər `5678` portu başqa n8n instansı tərəfindən istifadə olunursa, layihə n8n-ni
məsələn `5679` portunda başladın:

```bash
N8N_HOST_PORT=5679 N8N_WEBHOOK_URL=http://127.0.0.1:5679/ \
  docker compose --profile n8n up --build -d
```

Telegram botla birlikdə:

```bash
docker compose --profile telegram --profile n8n up --build
```

### Mövcud n8n storage haqqında

`n8n-import` yalnız storage boş olduqda workflow import edir. Mövcud
`n8n_storage` volume-da artıq workflow olduqda yeni JSON faylı avtomatik import
olunmur. Bu halda n8n UI-də **Import from File** seçib
`workflows/voice-ai-agent-telegram.json` faylını ayrıca import edin.

CLI ilə import olunan workflow-lar default olaraq inactive ola bilər. Webhook
ünvanlarını test etməzdən əvvəl n8n UI-də workflow-u açıb **Activate** edin.

## Telegram voice workflow

`Voice AI Agent Telegram Voice` workflow-unda hər iki Telegram node-a eyni
`Telegram API` credential-ını qoşun. Telegram Trigger node-unda
`Download Images/Files` aktiv qalmalıdır; bu, gələn audio-nu `data` binary
field-ə yerləşdirir. Workflow-u aktiv etdikdən sonra `telegram-bot` servisindən ayrıca polling
istifadə etməyin: eyni bot tokeni üçün yalnız bir Telegram update consumer
işləməlidir. Eyni səbəbdən standalone `bot.py` və n8n Telegram Trigger-i
paralel işlətmək olmaz.

Bu workflow yalnız kanal və binary-data orchestration edir. Whisper, LangGraph
memory, LLM və TTS yenə FastAPI backend-də qalır. Beləliklə n8n vizual
orchestration qatıdır, agentin AI mühəndisliyi məntiqi isə bir yerdə saxlanılır.

n8n UI (standart port):

```text
http://localhost:5678
```

Alternativ port nümunəsi:

```text
http://localhost:5679
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

Webhook workflow-larının cavabında `transcript`, `reply`, `audio_base64`,
`audio_mime` və `history_length` sahələri görünür. Telegram workflow-u isə
audio cavabını avtomatik olaraq Telegram voice message kimi göndərir.
