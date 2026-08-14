"""Request and response bodies for the API."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, examples=["Mənim adım Alim."])
    thread_id: str = Field(
        "demo",
        description="Conversation id. The same thread_id continues the same memory.",
    )


class ResumeRequest(BaseModel):
    thread_id: str
    decision: str = Field(..., description="approve | reject | edit")
    text: str | None = Field(None, description="Replacement text when decision is 'edit'.")


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    history_length: int = Field(
        ..., description="Messages currently kept in this thread's checkpoint."
    )
    status: str = Field("ok", description="'ok' or 'pending_approval' (see /chat/resume).")
    approval: dict | None = Field(
        None, description="Present when status is 'pending_approval': the draft awaiting sign-off."
    )
    consulted: list[str] = Field(
        default_factory=list, description="Which Divan advisors were consulted for this turn."
    )
    turn_id: str = Field("", description="Reference this in POST /feedback to react to this reply.")
    narration: list[str] = Field(
        default_factory=list,
        description="Divanbəyi's own brief lines explaining what the graph did, in order.",
    )


class FeedbackRequest(BaseModel):
    turn_id: str = Field(..., min_length=1)
    thread_id: str = Field(..., min_length=1)
    kind: Literal["up", "down", "correction"]
    text: str | None = Field(None, description="Required for kind='correction': what the reply should have said.")
    advisor: str | None = Field(None, description="Advisor key the feedback targets, if known.")


class FeedbackResponse(BaseModel):
    id: int
    stored: bool = True


class VoiceSegment(BaseModel):
    advisor: str = Field("", description="Advisor key ('' for the Divan narrator voice).")
    name: str = Field(..., description="Display name, e.g. 'Koroğlu' or 'Divan'.")
    text: str
    audio_base64: str
    audio_mime: str
    tts_provider: str


class VoiceResponse(BaseModel):
    thread_id: str
    transcript: str = Field(..., description="What Whisper heard.")
    reply: str = Field(..., description="What the agent answered.")
    audio_base64: str = Field(..., description="The final segment's audio, base64 encoded (back-compat).")
    audio_mime: str
    tts_provider: str = Field(..., description="Which engine actually spoke: elevenlabs or openai.")
    history_length: int
    segments: list[VoiceSegment] = Field(
        default_factory=list,
        description="One clip per council member who actually spoke, each in their own voice.",
    )
    turn_id: str = Field("", description="Reference this in POST /feedback to react to this reply.")
    status: str = Field("ok", description="'ok' or 'pending_approval' (see /voice/resume).")
    approval: dict | None = Field(
        None, description="Present when status is 'pending_approval': the draft awaiting sign-off."
    )
    consulted: list[str] = Field(
        default_factory=list, description="Which Divan advisors were consulted for this turn."
    )
    narration: list[str] = Field(
        default_factory=list,
        description="Divanbəyi's own brief lines explaining what the graph did, in order.",
    )
