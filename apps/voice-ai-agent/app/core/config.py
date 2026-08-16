"""Application settings.

Everything is read from `.env` (see `.env.example`). Nothing here has a secret
default, so the app is safe to run with an empty environment - it will simply
report which capabilities are unavailable on `GET /`.
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/voice-ai-agent - the project root, so the app can be started from
# anywhere (repo root, IDE, or the app folder) and still find .env / the db.
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # --- LLM (Lesson 31) ---
    # "auto" uses Groq when GROQ_API_KEY is present, otherwise OpenAI.
    LLM_PROVIDER: str = "auto"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # --- Speech to text: Whisper (Lesson 26) ---
    # Hosted Whisper, so the demo needs no torch/ffmpeg install on macOS.
    OPENAI_STT_MODEL: str = "whisper-1"

    # --- Text to speech: ElevenLabs, with OpenAI as fallback (Lesson 26) ---
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "JBFqnCBsd6RMkjVDRZzb"
    ELEVENLABS_MODEL: str = "eleven_v3"  # supports Azerbaijani (aze); multilingual_v2 does not
    # 1.0 = "robust": measured 2026-08-15, lower values let v3 drift the clone
    # into Turkish phonetics mid-sentence; eleven_v3 rejects language_code=aze,
    # so stability is the only consistency lever we have.
    ELEVENLABS_STABILITY: float = 1.0
    # Shared secret for mutating Voice Lab endpoints (dictionary/retrain);
    # empty disables the check (local dev). Set it on any public deployment.
    VOICELAB_TOKEN: str = ""
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TTS_VOICE: str = "alloy"

    # --- Divan council: one distinct real voice per legendary advisor.
    # Designed 2026-08-15 via ElevenLabs Voice Design (text-to-voice), one
    # in-character description per advisor, then saved permanently to the
    # account - replaces the earlier generic English premade voices. ---
    ELEVENLABS_VOICE_ID_NESREDDIN: str = "upFQswkYdMAgtWgjZXkL"  # warm wry folk storyteller
    ELEVENLABS_VOICE_ID_KOROGLU: str = "o0yt6WKWDl2XhHqGDcxJ"  # deep heroic warrior
    ELEVENLABS_VOICE_ID_SIMURG: str = "0veO3zcg0atchaW6fibk"  # ethereal mythical bird
    ELEVENLABS_VOICE_ID_NESIMI: str = "F3jd2648HUXkUl5m169e"  # intense mystic poet
    ELEVENLABS_VOICE_ID_DEDEQORQUD: str = "t9lFw8Q0LywmkFAU7PfJ"  # ancient wise elder
    ELEVENLABS_VOICE_ID_NIZAMI: str = "D19FXtjmMLZnfSG9IkSO"  # refined poet-philosopher
    OPENAI_TTS_VOICE_NESREDDIN: str = "onyx"
    OPENAI_TTS_VOICE_KOROGLU: str = "echo"
    OPENAI_TTS_VOICE_SIMURG: str = "nova"
    OPENAI_TTS_VOICE_NESIMI: str = "fable"
    OPENAI_TTS_VOICE_DEDEQORQUD: str = "onyx"
    OPENAI_TTS_VOICE_NIZAMI: str = "shimmer"

    # --- Observability (Lesson 30) ---
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_TRACING: bool = True
    LANGSMITH_PROJECT: str = "voice-ai-agent"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    # --- Entry point ---
    TELEGRAM_BOT_TOKEN: str = ""
    BACKEND_URL: str = "http://127.0.0.1:8000"

    # --- Memory (Lesson 31) ---
    SQLITE_PATH: str = "database/checkpoints.sqlite"
    MAX_HISTORY_MESSAGES: int = 12

    # --- User feedback (Lesson 11.2) ---
    FEEDBACK_PATH: str = "database/feedback.sqlite"

    # --- Safety guardrail (not a course lesson - baseline for any public AI product) ---
    # Deliberately generic and number-free by default: a wrong crisis hotline
    # number is worse than none. Override with a real, currently-verified
    # local resource before a public deployment.
    CRISIS_RESPONSE_TEXT: str = (
        "Dediklərin mənə çox ağır gəldi və bunu tək daşımamalısan. Divan bunun "
        "üçün doğru yer deyil. Zəhmət olmasa dərhal təcili tibbi yardımla "
        "əlaqə saxla və ya yanındakı etibar etdiyin bir insana - ailə üzvünə, "
        "dostuna və ya həkiminə - bunu de. Sən dəyərlisən və kömək almağa "
        "layiqsən."
    )

    # --- Abuse protection: per-IP rate limiting (not a course lesson -
    # baseline for any publicly-reachable AI product) ---
    # Single-process, in-memory limiter (see `app/core/rate_limit.py`): this
    # app runs as one container with no horizontal scaling (see
    # docker-compose.yml), so no shared store (e.g. Redis) is needed yet.
    # `/chat` and `/voice` share one budget per IP - both trigger the same
    # costly council (+ TTS) pipeline. `/feedback` gets its own, more
    # generous budget: cheap to serve, but still worth capping against spam.
    RATE_LIMIT_PER_MINUTE: int = 20
    RATE_LIMIT_FEEDBACK_PER_MINUTE: int = 60
    RATE_LIMIT_WINDOW_SECONDS: float = 60.0

    # --- Secondary safety net: OpenAI moderation (not a course lesson -
    # defense in depth alongside the deterministic self-harm check in
    # `app/graph/guardrails.py`) ---
    # Deliberately narrow: only categories the moderation model is actually
    # built to classify (hate/threatening, harassment/threatening, illicit
    # activity, graphic violence, sexual content involving minors). See
    # `app/services/moderation.py` for why impersonation of real people is
    # deliberately NOT handled here.
    MODERATION_ENABLED: bool = True
    MODERATION_MODEL: str = "omni-moderation-latest"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        extra="ignore",
    )

    @property
    def sqlite_file(self) -> Path:
        path = Path(self.SQLITE_PATH)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def rag_index_file(self) -> Path:
        return self.sqlite_file.parent / "rag" / "index.json"

    @property
    def feedback_file(self) -> Path:
        path = Path(self.FEEDBACK_PATH)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.LANGSMITH_TRACING and self.LANGSMITH_API_KEY)

    @property
    def tts_provider(self) -> str:
        return "elevenlabs" if self.ELEVENLABS_API_KEY else "openai"

    def elevenlabs_voice_for(self, advisor: str | None) -> str:
        return {
            "nesreddin": self.ELEVENLABS_VOICE_ID_NESREDDIN,
            "koroglu": self.ELEVENLABS_VOICE_ID_KOROGLU,
            "simurg": self.ELEVENLABS_VOICE_ID_SIMURG,
            "nesimi": self.ELEVENLABS_VOICE_ID_NESIMI,
            "dedeqorqud": self.ELEVENLABS_VOICE_ID_DEDEQORQUD,
            "nizami": self.ELEVENLABS_VOICE_ID_NIZAMI,
        }.get(advisor or "", self.ELEVENLABS_VOICE_ID)

    def openai_voice_for(self, advisor: str | None) -> str:
        return {
            "nesreddin": self.OPENAI_TTS_VOICE_NESREDDIN,
            "koroglu": self.OPENAI_TTS_VOICE_KOROGLU,
            "simurg": self.OPENAI_TTS_VOICE_SIMURG,
            "nesimi": self.OPENAI_TTS_VOICE_NESIMI,
            "dedeqorqud": self.OPENAI_TTS_VOICE_DEDEQORQUD,
            "nizami": self.OPENAI_TTS_VOICE_NIZAMI,
        }.get(advisor or "", self.OPENAI_TTS_VOICE)

    @property
    def chat_provider(self) -> str:
        provider = self.LLM_PROVIDER.lower().strip()
        if provider == "auto":
            return "groq" if self.GROQ_API_KEY else "openai"
        if provider not in {"openai", "groq"}:
            return "openai"
        return provider

    @property
    def chat_model(self) -> str:
        return self.GROQ_MODEL if self.chat_provider == "groq" else self.OPENAI_MODEL

    @property
    def llm_ready(self) -> bool:
        if self.chat_provider == "groq":
            return bool(self.GROQ_API_KEY)
        return bool(self.OPENAI_API_KEY)


settings = Settings()


def apply_tracing_env() -> None:
    """Publish LangSmith settings into os.environ.

    LangChain's tracer reads os.environ directly, not our Settings object, so
    values that only live in `.env` would be silently ignored without this.
    """
    if settings.tracing_enabled:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
        os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
        os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
    else:
        os.environ["LANGSMITH_TRACING"] = "false"


apply_tracing_env()
