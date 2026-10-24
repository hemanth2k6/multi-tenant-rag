"""Tenant model for multi-tenant isolation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.api_key import ApiKey
    from app.db.models.chunk import Chunk
    from app.db.models.document import Document


class Tenant(Base):
    """Represents an isolated SaaS customer/organization."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    api_keys: Mapped[list[ApiKey]] = relationship(
        "ApiKey",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
