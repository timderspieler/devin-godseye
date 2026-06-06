"""SQLAlchemy ORM models."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IssueStatus(enum.StrEnum):
    """Lifecycle of an issue inside the automation service."""

    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"  # approved, session being created
    DECLINED = "declined"
    RUNNING = "running"  # a Devin session is actively working
    COMPLETED = "completed"  # session finished successfully (PR or finished)
    FAILED = "failed"  # session errored / expired / blocked


# Devin session statuses that we treat as terminal-success vs terminal-failure.
# v1 used "finished"/"expired"; v3 uses "exit"/"suspended".
SUCCESS_STATUSES = {"finished", "exit"}
FAILURE_STATUSES = {"expired", "suspended"}


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("repo", "number", name="uq_issue_repo_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo: Mapped[str] = mapped_column(String(255), index=True)
    number: Mapped[int] = mapped_column(Integer, index=True)
    github_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(1024))
    body: Mapped[str] = mapped_column(Text, default="")
    html_url: Mapped[str] = mapped_column(String(1024))
    labels: Mapped[str] = mapped_column(String(1024), default="")
    trigger_label: Mapped[str] = mapped_column(String(255), default="")

    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus, native_enum=False, length=32),
        default=IssueStatus.PENDING_APPROVAL,
        index=True,
    )
    auto_approved: Mapped[bool] = mapped_column(default=False)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    session: Mapped[FixSession | None] = relationship(
        "FixSession",
        back_populates="issue",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def label_list(self) -> list[str]:
        return [label for label in self.labels.split(",") if label]


class FixSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), unique=True, index=True
    )
    devin_session_id: Mapped[str] = mapped_column(String(255), index=True)
    devin_session_url: Mapped[str] = mapped_column(String(1024), default="")

    # Last known Devin status_enum (working/blocked/expired/finished/...).
    status: Mapped[str] = mapped_column(String(64), default="working")
    pr_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pr_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    issue: Mapped[Issue] = relationship("Issue", back_populates="session")
