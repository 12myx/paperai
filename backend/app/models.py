"""SQLAlchemy ORM models for PaperLens AI.

Every user-owned row carries a `user_id` so that data isolation can be
enforced in a single place (see `app.deps.owned_or_404`).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    affiliation: Mapped[str | None] = mapped_column(String(255))
    avatar_color: Mapped[str] = mapped_column(String(16), default="#2F6F62")
    plan: Mapped[str] = mapped_column(String(32), default="researcher")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    papers = relationship("Paper", back_populates="user", cascade="all, delete-orphan")


class Paper(Base, TimestampMixin):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(600), default="Untitled paper")
    authors: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(300))
    doi: Mapped[str | None] = mapped_column(String(200))
    abstract: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="en")
    filename: Mapped[str] = mapped_column(String(400))
    stored_path: Mapped[str] = mapped_column(String(600))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="processing", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    user = relationship("User", back_populates="papers")
    pages = relationship("PaperPage", back_populates="paper", cascade="all, delete-orphan")
    sections = relationship("Section", back_populates="paper", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="paper", cascade="all, delete-orphan")
    figures = relationship("Figure", back_populates="paper", cascade="all, delete-orphan")
    annotations = relationship("Annotation", back_populates="paper", cascade="all, delete-orphan")


class PaperPage(Base):
    __tablename__ = "paper_pages"
    __table_args__ = (UniqueConstraint("paper_id", "page_number", name="uq_paper_page"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[float] = mapped_column(Float, default=0)
    height: Mapped[float] = mapped_column(Float, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)

    paper = relationship("Paper", back_populates="pages")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(400), default="Untitled section")
    level: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    page_start: Mapped[int] = mapped_column(Integer, default=1)
    page_end: Mapped[int] = mapped_column(Integer, default=1)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)

    paper = relationship("Paper", back_populates="sections")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_paper_order", "paper_id", "order_index"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))
    section_title: Mapped[str] = mapped_column(String(400), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    page_start: Mapped[int] = mapped_column(Integer, default=1)
    page_end: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    bbox: Mapped[dict] = mapped_column(JSON, default=dict)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    kind: Mapped[str] = mapped_column(String(32), default="paragraph")

    paper = relationship("Paper", back_populates="chunks")
    section = relationship("Section")


class Figure(Base):
    __tablename__ = "figures"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    image_path: Mapped[str | None] = mapped_column(String(600))
    caption: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24), default="figure")
    width: Mapped[float] = mapped_column(Float, default=0)
    height: Mapped[float] = mapped_column(Float, default=0)
    bbox: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_explanation: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    table_markdown: Mapped[str | None] = mapped_column(Text)
    detected_kind: Mapped[str] = mapped_column(String(24), default="unclassified", index=True)
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    caption_confidence: Mapped[float] = mapped_column(Float, default=0)
    is_page_snapshot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_status: Mapped[str] = mapped_column(String(16), default="auto")
    visual_status: Mapped[str] = mapped_column(String(16), default="unavailable")

    paper = relationship("Paper", back_populates="figures")


class Annotation(Base, TimestampMixin):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[str] = mapped_column(String(16), default="yellow")
    quote: Mapped[str] = mapped_column(Text, default="")
    rects: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    paper = relationship("Paper", back_populates="annotations")


class Collection(Base, TimestampMixin):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(16), default="#2F6F62")


class CollectionPaper(Base):
    __tablename__ = "collection_papers"
    __table_args__ = (UniqueConstraint("collection_id", "paper_id", name="uq_collection_paper"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="active")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str] = mapped_column(String(16), default="#2F6F62")


class ProjectItem(Base):
    __tablename__ = "project_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="note")
    ref_id: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(400), default="")
    content: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KnowledgeItem(Base, TimestampMixin):
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="note", index=True)
    source_paper_id: Mapped[str | None] = mapped_column(String(32), index=True)
    source_chunk_id: Mapped[str | None] = mapped_column(String(32))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)




class KnowledgeMeta(Base):
    """P7 enrichment: auto tags, cluster, duplicate and current version."""

    __tablename__ = "knowledge_meta"
    __table_args__ = (UniqueConstraint("item_id", name="uq_knowledge_meta_item"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True)
    auto_tags: Mapped[list] = mapped_column(JSON, default=list)
    cluster_key: Mapped[str] = mapped_column(String(80), default="")
    cluster_label: Mapped[str] = mapped_column(String(120), default="")
    duplicate_of: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class KnowledgeVersion(Base):
    """Append-only snapshot for knowledge history / rollback."""

    __tablename__ = "knowledge_versions"
    __table_args__ = (UniqueConstraint("item_id", "version", name="uq_knowledge_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(400), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="note")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    changed_fields: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KnowledgeLink(Base):
    __tablename__ = "knowledge_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(32))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(32))
    relation: Mapped[str] = mapped_column(String(64), default="related")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(300), default="New research thread")
    mode: Mapped[str] = mapped_column(String(32), default="quick")
    scope_type: Mapped[str] = mapped_column(String(24), default="all")
    scope_ids: Mapped[list] = mapped_column(JSON, default=list)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    project_id: Mapped[str | None] = mapped_column(String(32))

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(32), default="quick")
    model: Mapped[str | None] = mapped_column(String(120))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    agent_run_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation = relationship("Conversation", back_populates="messages")






class ProcessingJob(Base):
    """Durable paper-ingestion job for the in-process worker queue."""

    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    paper_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(80), default="等待处理")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AcademicArtifact(Base):
    """P8 evidence-backed academic artifact (review, proposal, plan, ...)."""

    __tablename__ = "academic_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(400), default="")
    scope_type: Mapped[str] = mapped_column(String(24), default="all")
    scope_ids: Mapped[list] = mapped_column(JSON, default=list)
    paper_ids: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    evidence_table: Mapped[list] = mapped_column(JSON, default=list)
    scope_statement: Mapped[str] = mapped_column(Text, default="")
    local: Mapped[bool] = mapped_column(Boolean, default=True)
    model: Mapped[str | None] = mapped_column(String(120))
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    quality_status: Mapped[str] = mapped_column(String(16), default="unchecked")
    knowledge_item_ids: Mapped[list] = mapped_column(JSON, default=list)
    knowledge_saved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ActionRequest(Base):
    """Persistent, user-bound confirmation token for agent write actions."""

    __tablename__ = "action_requests"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    args_json: Mapped[str] = mapped_column(Text, default="{}")
    args_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    result_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class ArtifactQualityReport(Base):
    __tablename__ = "artifact_quality_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("academic_artifacts.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="warning")
    score: Mapped[int] = mapped_column(Integer, default=0)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResourceUsage(Base):
    """Lifecycle ledger for resources included/read/referenced in an agent run."""

    __tablename__ = "resource_usage"
    __table_args__ = (UniqueConstraint("run_id", "resource_type", "resource_id", "stage", name="uq_resource_usage_stage"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    message_id: Mapped[str | None] = mapped_column(String(32))
    resource_type: Mapped[str] = mapped_column(String(24), index=True)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    resource_name: Mapped[str] = mapped_column(String(400), default="")
    stage: Mapped[str] = mapped_column(String(16), index=True)
    selection_source: Mapped[str] = mapped_column(String(24), default="auto")
    retrieval_reason: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32))
    message_id: Mapped[str | None] = mapped_column(String(32))
    goal: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(32), default="quick")
    status: Mapped[str] = mapped_column(String(24), default="running")
    provider: Mapped[str] = mapped_column(String(32), default="local")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)




class AgentTask(Base):
    """P6 task state machine: plan, execution, pause/resume/cancel, self-check."""

    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), index=True)
    run_id: Mapped[str | None] = mapped_column(String(32))
    user_message_id: Mapped[str | None] = mapped_column(String(32))
    result_message_id: Mapped[str | None] = mapped_column(String(32))
    goal: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(32), default="quick")
    scope_type: Mapped[str] = mapped_column(String(24), default="all")
    scope_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    plan: Mapped[list] = mapped_column(JSON, default=list)
    plan_source: Mapped[str] = mapped_column(String(24), default="local")
    plan_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(240))
    self_check: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32), default="local")
    rerun_of: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(32), default="tool")
    tool_name: Mapped[str | None] = mapped_column(String(80))
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class ExportRecord(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="report")
    title: Mapped[str] = mapped_column(String(300), default="")
    format: Mapped[str] = mapped_column(String(16), default="md")
    filename: Mapped[str] = mapped_column(String(400), default="")
    path: Mapped[str] = mapped_column(String(600), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)




class ResearchAnalysis(Base):
    """A persisted AI research output (summary, comparison, gap, ...).

    Analyses are stored so that evidence can reference the exact output that
    produced a claim, and so Research Intelligence can reuse results later.
    """

    __tablename__ = "research_analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(400), default="")
    scope_type: Mapped[str] = mapped_column(String(24), default="papers")
    scope_ids: Mapped[list] = mapped_column(JSON, default=list)
    paper_ids: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    local: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Evidence(Base, TimestampMixin):
    """A verifiable evidence record linking a claim to a paper location.

    Types:
      direct       - verbatim evidence from one paper
      shared       - the same finding is supported by multiple papers
      inferred     - an AI inference drawn from cited evidence
      hypothesis   - an AI-proposed hypothesis, not yet verified
      insufficient - no sufficient evidence was found
      external     - requires external literature / data to verify
    """

    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_evidence_fingerprint"),
        Index("ix_evidence_source", "source_type", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    paper_id: Mapped[str | None] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), index=True
    )
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_analyses.id", ondelete="CASCADE"), index=True
    )
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(400))
    quote: Mapped[str] = mapped_column(Text, default="")
    claim: Mapped[str | None] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(String(24), default="direct", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_note: Mapped[str | None] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(24), default="manual", index=True)
    source_id: Mapped[str | None] = mapped_column(String(32), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)




class PaperFacet(Base, TimestampMixin):
    """Structured, evidence-backed profile of a paper for multi-paper research."""

    __tablename__ = "paper_facets"
    __table_args__ = (UniqueConstraint("user_id", "paper_id", name="uq_paper_facet"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    local: Mapped[bool] = mapped_column(Boolean, default=True)
    model: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ResearchInsight(Base):
    """Cached structured multi-paper output (matrix, conflicts, evolution, ...)."""

    __tablename__ = "research_insights"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(400), default="")
    scope_type: Mapped[str] = mapped_column(String(24), default="papers")
    paper_ids: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    local: Mapped[bool] = mapped_column(Boolean, default=True)
    model: Mapped[str | None] = mapped_column(String(120))
    analysis_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)




class IntelligenceReport(Base):
    """Cached Research Intelligence output scoped to library/project/collection."""

    __tablename__ = "intelligence_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    scope_type: Mapped[str] = mapped_column(String(24), default="all")
    scope_id: Mapped[str | None] = mapped_column(String(32), index=True)
    scope_label: Mapped[str] = mapped_column(String(300), default="")
    paper_ids: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    local: Mapped[bool] = mapped_column(Boolean, default=True)
    model: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserSettings(Base, TimestampMixin):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme: Mapped[str] = mapped_column(String(16), default="light")
    language: Mapped[str] = mapped_column(String(16), default="zh")
    reading_font_size: Mapped[int] = mapped_column(Integer, default=16)
    reading_width: Mapped[str] = mapped_column(String(16), default="wide")
    default_summary_mode: Mapped[str] = mapped_column(String(32), default="abstract")
    translation_language: Mapped[str] = mapped_column(String(32), default="简体中文")
    translation_style: Mapped[str] = mapped_column(String(32), default="academic")
    model_provider: Mapped[str] = mapped_column(String(32), default="deepseek")
    model_base_url: Mapped[str | None] = mapped_column(String(400))
    model_name: Mapped[str | None] = mapped_column(String(120))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Float, default=0.3)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2400)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy: Mapped[dict] = mapped_column(JSON, default=dict)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(48))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)