"""Pydantic request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    affiliation: str | None = None
    avatar_color: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    mode: str = "quick"
    scope_type: str = "all"
    scope_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None
    auto_approve_writes: bool = False


class PaperUpdate(BaseModel):
    title: str | None = None
    authors: str | None = None
    year: int | None = None
    venue: str | None = None
    tags: list[str] | None = None
    favorite: bool | None = None
    note: str | None = None


class AnnotationCreate(BaseModel):
    paper_id: str
    page: int = Field(ge=1)
    color: str = "yellow"
    quote: str = ""
    rects: list[dict] = Field(default_factory=list)
    note: str | None = None
    tags: list[str] = Field(default_factory=list)


class AnnotationUpdate(BaseModel):
    color: str | None = None
    note: str | None = None
    tags: list[str] | None = None
    favorite: bool | None = None


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    color: str = "#2F6F62"


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    goal: str | None = None
    color: str = "#2F6F62"


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    goal: str | None = None
    status: str | None = None
    progress: int | None = None
    color: str | None = None


class ProjectItemCreate(BaseModel):
    kind: str = "note"
    ref_id: str | None = None
    title: str = ""
    content: str | None = None
    meta: dict = Field(default_factory=dict)


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=400)
    content: str = ""
    kind: str = "note"
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    source_paper_id: str | None = None
    source_page: int | None = None
    source_quote: str | None = None
    source_chunk_id: str | None = None
    force: bool = False


class KnowledgeUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    project_id: str | None = None


class LinkCreate(BaseModel):
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation: str = "related"
    note: str | None = None


class SummaryRequest(BaseModel):
    mode: str = "abstract"


class TranslateRequest(BaseModel):
    text: str | None = None
    page: int | None = None
    section_id: str | None = None
    target_language: str | None = None
    style: str | None = None


class CompareRequest(BaseModel):
    paper_ids: list[str] = Field(min_length=2, max_length=8)
    focus: str = ""
    fragments: list[dict] = Field(default_factory=list)


class GapRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    collection_id: str | None = None


class ExtractRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)
    paper_ids: list[str] = Field(default_factory=list)
    collection_id: str | None = None


class SingleExtractRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)


class ExportRequest(BaseModel):
    kind: str = "report"
    format: str = "md"
    title: str = "PaperLens report"
    content: str | None = None
    paper_id: str | None = None
    knowledge_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None


class SettingsUpdate(BaseModel):
    theme: str | None = None
    language: str | None = None
    reading_font_size: int | None = None
    reading_width: str | None = None
    default_summary_mode: str | None = None
    translation_language: str | None = None
    translation_style: str | None = None
    model_provider: str | None = None
    model_base_url: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    onboarding_completed: bool | None = None
    privacy: dict | None = None


class ModelKeyRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=400)
    base_url: str | None = None
    model_name: str | None = None
    temperature: float | None = None


class ConfirmActionRequest(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class FigureUpdate(BaseModel):
    note: str | None = None
    saved: bool | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    archived: bool | None = None


class AccountDeleteRequest(BaseModel):
    password: str
    confirm: str

class EvidenceCreate(BaseModel):
    paper_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    section: str | None = None
    quote: str = ""
    claim: str | None = None
    evidence_type: str = "direct"
    confidence: float | None = None
    source_type: str = "manual"
    source_id: str | None = None
    analysis_id: str | None = None
    meta: dict = Field(default_factory=dict)


class EvidenceUpdate(BaseModel):
    evidence_type: str | None = None
    claim: str | None = None
    confidence: float | None = None

class PaperSetRequest(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=8)
    force: bool = False


class GapValidateRequest(BaseModel):
    claim: str = Field(min_length=2, max_length=2000)
    paper_ids: list[str] = Field(min_length=1, max_length=8)

class IntelligenceRequest(BaseModel):
    scope_type: str = "all"
    scope_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    force: bool = False

class AgentTaskPlanRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    mode: str = "quick"
    scope_type: str = "all"
    scope_ids: list[str] = Field(default_factory=list)


class AgentTaskPlanUpdate(BaseModel):
    plan: list[dict] = Field(min_length=1, max_length=8)

class KnowledgeRollbackRequest(BaseModel):
    note: str | None = None

class KnowledgeMergeRequest(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=20)
    note: str | None = None

class ArtifactGenerateRequest(BaseModel):
    kind: str
    scope_type: str = "all"
    scope_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    title: str | None = None


class ArtifactExportRequest(BaseModel):
    format: str = "md"
