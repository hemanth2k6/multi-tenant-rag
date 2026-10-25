"""Document model representing uploaded PDFs scoped to a tenant."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.chunk import Chunk
    from app.db.models.tenant import Tenant


class Document(Base):
    """Document uploaded by a tenant."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "file_hash", name="uq_tenant_file_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )
