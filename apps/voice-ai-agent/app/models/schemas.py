"""Request and response bodies for the API."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, examples=["Mənim adım Alim."])
    thread_id: str = Field(
        "demo",
        description="Conversation id. The same thread_id continues the same memory.",
    )


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    history_length: int = Field(
        ..., description="Messages currently kept in this thread's checkpoint."
    )


class VoiceResponse(BaseModel):
    thread_id: str
    transcript: str = Field(..., description="What Whisper heard.")
    reply: str = Field(..., description="What the agent answered.")
    audio_base64: str = Field(..., description="The spoken reply, base64 encoded.")
    audio_mime: str
    tts_provider: str = Field(..., description="Which engine actually spoke: elevenlabs or openai.")
    history_length: int
