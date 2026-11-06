"""User entity representing the authenticated tenant in the multi-tenant architecture."""

from __future__ import annotations

from app.db.models.tenant import Tenant

# In SaaS multi-tenancy architecture, User accounts map directly to isolated Tenants.
User = Tenant

__all__ = ["User"]

