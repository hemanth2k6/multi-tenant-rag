"""Authentication and Tenant schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    """Schema for tenant registration."""

    name: str = Field(..., min_length=1, max_length=255)
    plan: str = Field(default="free", pattern="^(free|premium)$")


class TenantResponse(BaseModel):
    """Schema returned for tenant representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    plan: str
    created_at: datetime


class ApiKeyCreate(BaseModel):
    """Schema for requesting a new API key."""

    tenant_id: uuid.UUID


class ApiKeyResponse(BaseModel):
    """Schema returned when an API key is created (raw_key shown only once)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    prefix: str
    raw_key: str | None = None
    created_at: datetime
