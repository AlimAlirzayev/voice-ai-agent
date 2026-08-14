# n8n integration

Bu qovluqdakı workflow-lar Docker Compose ilə avtomatik import olunur:

- `Voice AI Agent Chat Webhook`: JSON mesajını backend `/chat` endpointinə ötürür,
  `status: pending_approval` üçün ikinci bir webhook-la (`/chat/resume`) tam işlək
  HITL round-trip təmin edir (bax aşağı: "HITL: Koroğlu təsdiqi").
- `Voice AI Agent Voice Webhook`: multipart audio faylını backend `/voice`
  endpointinə ötürür, `segments` massivini olduğu kimi qaytarır və eyni HITL
  `resume` addımı üçün ikinci webhook təmin edir.
- `Voice AI Agent Telegram Voice`: Telegram-dan səs mesajını qəbul edir, backend
  `/voice` endpointinə göndərir, **hər danışan üzv üçün ayrı bir Telegram səsli
  mesaj** göndərir (`bot.py`-dəki `_send_voice_segments` ilə eyni məntiq) və
  Koroğlu təsdiqi lazım olanda mətn əmrləri ilə `/voice/resume` çağırır.

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

## HITL: Koroğlu təsdiqi n8n-də necə işləyir

Backend Koroğlu danışanda `/chat` və `/voice`-dan `status: "pending_approval"`
(və ya ekvivalent) qaytarır — bax [`chat.py`](../apps/voice-ai-agent/app/api/chat.py),
[`voice.py`](../apps/voice-ai-agent/app/api/voice.py). Bunu həll edən
`POST /chat/resume` / `POST /voice/resume` çağırışı **ayrı, gec gələ biləcək
bir insan qərarı** tələb edir — n8n-in tək `Webhook -> HTTP Request -> Respond`
icra dövrü bunu sinxron gözləyə bilməz (icra saatlarla asılı qala bilməzdi).
Ona görə hər üç workflow bunu **iki ayrı tetikleyici** kimi modelləşdirir,
tam olaraq `bot.py`-nin Telegram düymə + callback-query handler modelinə
paralel:

- **Mətn (`voice-ai-agent-chat.json`)** — `ChatResponse` backend-də artıq
  `status` və `approval` sahələrini daşıyır (bax
  [`schemas.py`](../apps/voice-ai-agent/app/models/schemas.py)), ona görə bu
  workflow **tam işlək, iki addımlı** bir axındır:
  1. `POST /webhook/voice-ai-agent-chat` -> `/chat` -> cavab. Cavab
     `status: "pending_approval"` olduqda, `approval` obyekti (advisor,
     draft, question) **olduğu kimi** ötürülür və üstünə aydınlıq üçün
     `resume_hint` sahəsi əlavə olunur — çağıran tərəf `approval`-ı heç vaxt
     yekun cavab kimi qəbul edə bilməz, çünki `status` açıq şəkildə görünür.
  2. Qərar gələndə: `POST /webhook/voice-ai-agent-chat-resume`
     `{"thread_id": "...", "decision": "approve|reject|edit", "text": "..."}`
     -> `/chat/resume` -> yekun cavab (eyni formatda, `Format Chat Response`
     node-u vasitəsilə).

- **Səs (`voice-ai-agent-voice.json`, `voice-ai-agent-telegram.json`)** —
  burada **real bir backend məhdudiyyəti var**: `VoiceResponse`
  (`schemas.py`) `ChatResponse`-dan fərqli olaraq **`status` və `approval`
  sahələrini ümumiyyətlə daşımır**. Yəni `/voice` və `/voice/resume`
  cavabından proqramatik şəkildə "bu, gözləyən təsdiqdir" deyə əmin olmaq
  mümkün deyil (bu, Python backend-ə toxunmadan bu iş çərçivəsində düzəldilə
  bilməyən bir gap-dır). Hər iki səs workflow-u bunun əvəzinə
  `approval_gate()`-in (bax
  [`builder.py`](../apps/voice-ai-agent/app/graph/builder.py)) həmişə
  qaytardığı **sabit sual mətni** üzərində mətn-əsaslı best-effort
  həssaslıq (`hitl_suspected` / `hitl_note`) istifadə edir. Bu, real bir
  siqnaldır (backend kodu dəyişməyənədək etibarlıdır), amma rəsmi bir
  kontrakt sahəsi deyil — bu barədə qeyd hər iki workflow-un `Format Voice
  Response` / `Prepare Voice Segments` node-larının şərhlərində var.
  - Generic webhook: ikinci tetikleyici `POST /webhook/voice-ai-agent-voice-resume`
    (form sahələri: `thread_id`, `decision`, `text`) `/voice/resume`-i çağırır
    və eyni `segments`/`hitl_suspected` formatını qaytarır.
  - Telegram: **inline-keyboard düymələri əvəzinə mətn əmrləri** istifadə
    olunur (`/tesdiqle`, `/imtina`, `/duzelis <yeni mətn>`). Bunun səbəbi
    prinsipial deyil, praktikidir: bu layihədə n8n-in canlı Telegram node
    versiyasına qoşulub `reply_markup`/inline-keyboard sxemini yoxlamaq
    mümkün olmadı, ona görə əl ilə yazılan, sənədləşdirilməmiş bir JSON
    formatı təxmin etmək əvəzinə, artıq bu faylda sınanmış `sendMessage`/
    `sendVoice` node-ları üzərində qurulan, doğrulana bilən bir mətn-əmr
    axını seçildi. Nəticə: **tam işlək** iki addımlı round-trip (düymə yox,
    amma silinməyən, real bir cavab yolu) — Telegram Trigger-in "message"
    axınının eyni "Is Voice Message" IF node-unun `false` qolu bu əmrləri
    tutur, `/voice/resume`-ə göndərir və nəticəni yenə seqment-seqment səsli
    mesaj kimi geri qaytarır.

  Əgər gələcəkdə `VoiceResponse`-a `status`/`approval` sahələri əlavə
  olunarsa (Python backend dəyişikliyi, bu iş çərçivəsindən kənar), yuxarıdakı
  mətn-əsaslı həssaslığı birbaşa `status === "pending_approval"` yoxlaması ilə
  əvəz etmək mümkün olacaq. İnline-keyboard dəstəyi lazım olarsa,
  canlı n8n instansında Telegram node-un `reply_markup` sxemini təsdiqləyib
  `bot.py`-dəki `_approval_keyboard`-a bənzər bir tətbiq əlavə etmək
  mümkündür — hazırda bu, sınanmamış olduğu üçün qəsdən edilməyib.

**Qısa nəticə**: Koroğlu ilə bağlı sənaryolar artıq n8n-in hər üç kanalında da
(mətn, generic səs, Telegram) real, işlək bir cavaba çatır — heç bir halda
gözləyən tövsiyə yekun cavab kimi göstərilmir və sual havada asılı qalmır.
`bot.py` yenə də ən zəngin UX-i (Telegram inline düymələr) təqdim edir və
xüsusilə Telegram inline-keyboard təcrübəsi üstünlük təşkil edirsə tövsiyə
olunur, amma bu artıq n8n-in "yeganə yol"u olduğu üçün deyil.

## Telegram voice workflow

`Voice AI Agent Telegram Voice` workflow-unda hər Telegram node-a eyni
`Telegram API` credential-ını qoşun. Telegram Trigger node-unda
`Download Images/Files` aktiv qalmalıdır; bu, gələn audio-nu `data` binary
field-ə yerləşdirir. Workflow-u aktiv etdikdən sonra `telegram-bot` servisindən ayrıca polling
istifadə etməyin: eyni bot tokeni üçün yalnız bir Telegram update consumer
işləməlidir. Eyni səbəbdən standalone `bot.py` və n8n Telegram Trigger-i
paralel işlətmək olmaz.

Bu workflow yalnız kanal, binary-data orchestration və (yuxarıda izah olunan)
mətn-əmr əsaslı HITL round-trip-i idarə edir. Whisper, LangGraph memory, LLM
və TTS yenə FastAPI backend-də qalır. Beləliklə n8n vizual orchestration
qatıdır, agentin AI mühəndisliyi məntiqi isə bir yerdə saxlanılır.

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

Koroğlu tövsiyəsi (HITL) test — mətn webhook:

```bash
curl -X POST http://localhost:5678/webhook/voice-ai-agent-chat \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"n8n-demo","message":"Bu riskli addımı atmalıyammı?"}'
# -> {"status":"pending_approval","approval":{...},"resume_hint":"..."}

curl -X POST http://localhost:5678/webhook/voice-ai-agent-chat-resume \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"n8n-demo","decision":"approve"}'
# decision: approve | reject | edit (edit üçün "text" sahəsi də göndərin)
```

Səs workflow-u üçün `data` adlı binary audio field göndərilməlidir. Məsələn:

```bash
curl -X POST http://localhost:5678/webhook/voice-ai-agent-voice \
  -F 'file=@voice.ogg;type=audio/ogg' \
  -F 'thread_id=n8n-voice'
```

Səsli HITL davam etdirmək üçün:

```bash
curl -X POST http://localhost:5678/webhook/voice-ai-agent-voice-resume \
  -d 'thread_id=n8n-voice' -d 'decision=approve'
```

Webhook workflow-larının cavabında `transcript`, `reply`, `audio_base64`,
`audio_mime`, `tts_provider`, `history_length`, `turn_id` və **`segments`**
(hər danışan üzv üçün ayrı audio + mətn + advisor adı) sahələri görünür. Mətn
workflow-unun cavabında əlavə olaraq `status`, `approval` (backend-dən
olduğu kimi) və `pending_approval` halında `resume_hint` var. Səs
workflow-larının cavabında isə backend-in öz məhdudiyyətinə görə (yuxarıya
bax) `hitl_suspected` / `hitl_note` — best-effort həssaslıq sahələri — var.

Telegram workflow-u isə audio cavabını avtomatik olaraq hər seqment üçün ayrı
bir Telegram voice message kimi göndərir, əvvəlcə transkripsiyanı ayrı mətn
mesajı kimi göndərir və Koroğlu təsdiqi gözlənəndə mətn əmrləri (yuxarı bax)
üçün təlimat göndərir.

## İstifadəçi rəyi (feedback) — n8n-də hələ əlavə olunmayıb

Hər tamamlanmış cavab (`/chat`, `/chat/resume`, `/voice`, `/voice/resume`)
bir `turn_id` daşıyır və bunu `POST /feedback`
`{"turn_id","thread_id","kind":"up|down|correction","text?"}` ilə
qiymətləndirmək mümkündür (bax kök [`README.md`](../README.md) bölmə 1,
[`bot.py`](../apps/voice-ai-agent/bot.py) `_feedback_keyboard`/`on_feedback`).
Bu workflow-lara qəsdən əlavə edilməyib: `turn_id` bütün cavablarda artıq
görünür, ona görə istəyən inteqrator öz `/feedback` HTTP Request node-unu
asanlıqla əlavə edə bilər, amma bunu bu üç faylın "əsas" HITL/segments
düzəlişinə qatmaq süni mürəkkəblik yaradardı — bu, backend-in dəstəklədiyi,
lakin hazırkı workflow-ların formasına təbii uymayan, tamamilə opsional bir
genişləndirmədir.
