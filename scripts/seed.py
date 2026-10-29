"""Seed script to create an initial tenant and generate an API key."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Ensure repo root is on sys.path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import generate_api_key
from app.db.models.api_key import ApiKey
from app.db.models.tenant import Tenant
from app.db.session import AsyncSessionLocal, engine


async def seed_tenant(name: str, plan: str) -> None:
    """Create a new tenant with an associated API key."""
    async with AsyncSessionLocal() as session:
        # 1. Create tenant
        tenant = Tenant(
            id=uuid.uuid4(),
            name=name,
            plan=plan,
        )
        session.add(tenant)
        await session.flush()

        # 2. Generate raw API key and hash
        raw_key, key_hash, prefix = generate_api_key()

        # 3. Store hashed key in database
        api_key = ApiKey(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            key_hash=key_hash,
            prefix=prefix,
        )
        session.add(api_key)
        await session.commit()

        print("\n" + "=" * 60)
        print("🎉 Tenant and API Key created successfully!")
        print("=" * 60)
        print(f" Tenant ID:   {tenant.id}")
        print(f" Name:        {tenant.name}")
        print(f" Plan:        {tenant.plan}")
        print(f" Key Prefix:  {prefix}")
        print("-" * 60)
        print(f" Raw API Key: {raw_key}")
        print("-" * 60)
        print("⚠️  SAVE THIS KEY! It is never stored and cannot be retrieved again.")
        print("\nExample curl query command:")
        print(
            f"curl -X POST http://localhost:8000/api/v1/query \\\n"
            f'  -H "Authorization: Bearer {raw_key}" \\\n'
            f'  -H "Content-Type: application/json" \\\n'
            f'  -d \'{{"question": "What is this document about?", "top_k": 3}}\'\n'
        )
        print("=" * 60 + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a tenant and API key")
    parser.add_argument(
        "--name",
        type=str,
        default="Acme Corp",
        help="Name of the organization/tenant (default: Acme Corp)",
    )
    parser.add_argument(
        "--plan",
        type=str,
        choices=["free", "premium"],
        default="free",
        help="Rate limit subscription plan: free or premium (default: free)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    try:
        await seed_tenant(name=args.name, plan=args.plan)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSeeding interrupted by user.")
        sys.exit(1)
