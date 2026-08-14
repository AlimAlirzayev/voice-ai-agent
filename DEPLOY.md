# Divan — canlı server və iş davamlılığı bələdçisi

Bu sənəd layihənin harada işlədiyini, ona necə qoşulmağı və başqa kompüterdə işi
necə davam etdirməyi izah edir.

> **Heç bir parol, API açarı və ya bot tokeni bu fayla yazılmamalıdır.** Repo
> GitHub-dadır; buraya yazılan sirr dərhal ictimai sayılmalıdır. Sirrlər yalnız
> `.env` fayllarında yaşayır və `.gitignore` onları kənarda saxlayır.

## 1. Canlı ünvanlar

| Nə | Ünvan |
|---|---|
| Canlı demo səhifəsi | http://207.154.231.255/demo |
| Health / status | http://207.154.231.255/ |
| API sənədləri (Swagger) | http://207.154.231.255/docs |
| Telegram | botunuz serverdə işləyir, birbaşa yazın |

Server: DigitalOcean droplet, Ubuntu 24.04, Frankfurt (FRA1), `207.154.231.255`.
Tətbiq `/opt/voice-ai-agent` qovluğunda, Docker Compose ilə işləyir.

### ⚠️ Korporativ şəbəkə xəbərdarlığı

**İş kompüterinizin şəbəkəsi bu ünvanı bloklaya bilər.** Yoxlanılıb: həmin
şəbəkədən `example.com` açılır, amma xam IP ünvanlarına (bizim server daxil)
çıxış bağlıdır. Bu, serverin problemi deyil — dünyanın 7 fərqli nöqtəsindən
(Almaniya, Rusiya, Sinqapur, Türkiyə, Polşa, İsveç, Moldova) `HTTP 200 OK`
alındığı yoxlanılıb.

Şəxsi noutbukdan, telefon internetindən və ya kurs wifi-dan normal açılır.

## 2. Serverə qoşulmaq

```bash
ssh root@207.154.231.255
```

Parol DigitalOcean droplet yaradılanda verilən root paroludur (bu fayla
yazılmır — DigitalOcean panelindən və ya öz qeydlərinizdən götürün).

Hər dəfə parol yazmamaq üçün öz kompüterinizin açarını əlavə edin:

```bash
ssh-keygen -t ed25519 -C "macbook"      # açarınız yoxdursa
ssh-copy-id root@207.154.231.255        # bir dəfə parol soruşacaq, sonra lazım olmayacaq
```

## 3. MacBook-da (və ya yeni kompüterdə) işə başlamaq

```bash
git clone https://github.com/AlimAlirzayev/voice-ai-agent.git
cd voice-ai-agent
```

`.env` faylı Git-də **yoxdur** (içində API açarları var). Onu işləyən serverdən
gətirin — ən sürətli və səhvsiz yol budur:

```bash
scp root@207.154.231.255:/opt/voice-ai-agent/.env apps/voice-ai-agent/.env
```

Sonra lokal işə salın:

```bash
cd apps/voice-ai-agent
uv sync                                  # uv yoxdursa: brew install uv
uv run pytest -q                         # hər şeyin qaydasında olduğunu yoxlayır
uv run uvicorn app.main:app --reload     # http://127.0.0.1:8000/demo
```

> Telegram botunu **lokal işə salmayın** — serverdə artıq işləyir. Eyni tokenlə
> iki bot eyni vaxtda işləsə, Telegram mesajları ikisi arasında bölür və cavablar
> itir. Lokal sınamaq istəsəniz, əvvəlcə serverdəkini dayandırın:
> `ssh root@207.154.231.255 "cd /opt/voice-ai-agent && docker compose stop telegram-bot"`

## 4. Serverdə gündəlik əməliyyatlar

```bash
ssh root@207.154.231.255
cd /opt/voice-ai-agent

docker compose ps                        # nə işləyir
docker compose logs -f api               # API loqları (canlı)
docker compose logs -f telegram-bot      # bot loqları (canlı)
docker compose restart api               # yenidən başlat
```

### Yeni kodu serverə yaymaq (deploy)

```bash
ssh root@207.154.231.255
cd /opt/voice-ai-agent
git pull
docker compose --profile telegram up -d --build
```

`.env` faylı `git pull` zamanı toxunulmur — orada qalır.

### `.env`-i serverdə dəyişmək

```bash
nano /opt/voice-ai-agent/.env
docker compose --profile telegram up -d --force-recreate
```

> **Diqqət:** `.env`-ə sətir əlavə edəndə faylın sonunun yeni sətirlə bitdiyinə
> əmin olun. Əks halda yeni dəyər əvvəlki sətrin sonuna yapışır və o dəyəri
> səssizcə korlayır — bu, quraşdırma zamanı bir dəfə Telegram tokenini sındırdı.
> `printf '\nAÇAR=dəyər\n' >> .env` təhlükəsiz üsuldur.

## 5. Portlar

| Port | Vəziyyət | Qeyd |
|---|---|---|
| 22 | açıq | SSH |
| 80 | açıq | tətbiq (konteynerdə 8000 → hostda 80) |

Port `.env`-dəki `API_PORT` ilə idarə olunur. 80 seçilib ki, məhdud şəbəkələrdən
(kurs wifi, telefon) problemsiz açılsın və URL-də `:8000` görünməsin.

Firewall (UFW) yalnız 22 və 80-ə icazə verir:

```bash
ufw status
```

## 6. GitHub Actions ilə avtomatik deploy (hələ qurulmayıb)

Repoda `.github/workflows/deploy.yml` var, amma o, köhnə Hetzner serveri üçün
yazılıb və hazırda uğursuz olur (bu, layihə kodunun problemi deyil — sadəcə
secrets təyin edilməyib).

Avtomatlaşdırmaq istəsəniz, GitHub-da **Settings → Secrets and variables →
Actions** bölməsinə əlavə edin:

| Secret | Dəyər |
|---|---|
| `HOST` | `207.154.231.255` |
| `USERNAME` | `root` |
| `SSH_KEY` | serverə əlavə edilmiş açarın **private** hissəsi |

Ondan sonra hər `git push origin main` avtomatik deploy edəcək. Buna qədər
yuxarıdakı əl ilə deploy addımları işləyir.

## 7. Yeni Claude Code sessiyasına nə demək

Yeni kompüterdə söhbət tarixçəsi keçmir. İşi davam etdirmək üçün qısaca bunu
deyin:

> Bu layihə "Divan" adlı çoxagentli AI şurasıdır (LangGraph supervisor + 6
> tarixi Azərbaycan personajı, HITL təsdiq, hər personaj üçün ayrı ElevenLabs
> səsi, feedback loop, təhlükəsizlik qapısı). Kod GitHub-dadır, canlı server
> `207.154.231.255`-də işləyir. Ətraflı: `README.md` və `DEPLOY.md`.

Layihənin texniki izahı tam şəkildə [`README.md`](README.md)-dədir: qraf
topologiyası, HITL axını, hər personajın tarixi mənbəyi, API nümunələri və
test/eval əmrləri.

## 8. Sağlamlıq yoxlaması

Hər şeyin işlədiyini bir əmrlə yoxlamaq:

```bash
curl -s http://207.154.231.255/ | python3 -m json.tool
```

Gözlənilən cavabda `"status": "ok"`, `"llm"`, `"tts": "elevenlabs"` və
`"telegram_bot": true` olmalıdır.
