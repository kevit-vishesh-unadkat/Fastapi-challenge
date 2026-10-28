"""Bootstrap the first admin (register only makes attendees, and /users needs an admin).

    ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='...at least 12 chars...' python -m app.scripts.create_admin
"""
import asyncio
import getpass
import os
import sys

from pydantic import TypeAdapter, ValidationError

from app.common.types import Email
from app.core.config import get_settings
from app.core.database import create_client, ensure_indexes
from app.core.errors import ConflictError
from app.core.security import hash_password
from app.repositories.user_repository import UserRepository


async def main() -> None:
    raw_email = os.environ.get("ADMIN_EMAIL") or input("Admin email: ")
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password (min 12 chars): ")
    name = os.environ.get("ADMIN_NAME", "Administrator")
    try:
        email = TypeAdapter(Email).validate_python(raw_email.strip())
    except ValidationError:
        sys.exit("Invalid email address")
    if not 12 <= len(password) <= 128:
        sys.exit("Password must be 12-128 characters")

    settings = get_settings()
    client = create_client(settings)
    try:
        db = client[settings.mongodb_db]
        await ensure_indexes(db)
        try:
            await UserRepository(db.users).insert(
                {
                    "email": email,
                    "name": name,
                    "role": "admin",
                    "is_active": True,
                    "password_hash": await hash_password(password),
                }
            )
        except ConflictError:
            sys.exit(f"A user with email {email} already exists")
        print(f"Admin created: {email}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
