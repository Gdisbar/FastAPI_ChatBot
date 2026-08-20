from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


def _normalize_confidence(v):
    """LLMs return 0.95 or 95 or 95.0 — all should become int 0-100."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if 0 < v <= 1:           # 0.95 -> 95
            return round(v * 100)
        if v > 100:              # 150 -> 100 (cap)
            return 100
        return round(v)          # 95.4 -> 95, 95 -> 95
    return v


class MessageIn(BaseModel):
    session_id: str
    content: str = Field(..., min_length=1)


class TranscriptMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class TranscriptIn(BaseModel):
    session_id: Optional[str] = None
    messages: List[TranscriptMessage]

class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    role: str
    content: str
    intent: Optional[str] = None
    dialogue_stage: Optional[str] = None
    confidence: Optional[int] = None
    raw_llm_response: Optional[dict] = None
    created_at: datetime

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v):
        return _normalize_confidence(v)



class ChatMetadata(BaseModel):
    intent: str
    dialogue_stage: str
    confidence: int
    reasoning: str

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v):
        return _normalize_confidence(v)


class TranscriptAnalysisOut(BaseModel):
    session_id: str
    filename: Optional[str] = None
    overall_flow: List[str]
    per_turn: List[dict]


class ConversationUpdate(BaseModel):
    intent: Optional[str] = None
    dialogue_stage: Optional[str] = None
    confidence: Optional[int] = None
    content: Optional[str] = None