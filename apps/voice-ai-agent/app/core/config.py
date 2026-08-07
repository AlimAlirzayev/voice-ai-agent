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
    ELEVENLABS_MODEL: str = "eleven_multilingual_v2"
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TTS_VOICE: str = "alloy"

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

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        extra="ignore",
    )

    @property
    def sqlite_file(self) -> Path:
        path = Path(self.SQLITE_PATH)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.LANGSMITH_TRACING and self.LANGSMITH_API_KEY)

    @property
    def tts_provider(self) -> str:
        return "elevenlabs" if self.ELEVENLABS_API_KEY else "openai"

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
