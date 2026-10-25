"""Document request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentItem(BaseModel):
    """Schema for individual document metadata item."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    file_hash: str
    status: str
    created_at: datetime


class DocumentUploadResponse(BaseModel):
    """Schema returned after a successful PDF upload."""

    id: uuid.UUID
    filename: str
    status: str
    message: str


class DocumentListResponse(BaseModel):
    """Schema returned when listing tenant documents."""

    documents: list[DocumentItem]
    total: int
