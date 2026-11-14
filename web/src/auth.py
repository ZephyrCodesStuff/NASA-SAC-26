"""Authentication service using PocketBase storage, PBKDF2 (client), and Argon2id (backend)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

PBKDF2_SALT_SUFFIX = "nasa-space-apps-2026"
PBKDF2_ITERATIONS = 100_000
PBKDF2_DKLEN = 32

# Explicit Argon2id configuration
_ARGON2 = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


@dataclass(frozen=True, slots=True)
class DemoUserSpec:
    """Built-in demo user account always available for testing/demos."""

    email: str
    name: str
    role: str
    password: str


DEMO_USERS: tuple[DemoUserSpec, ...] = (
    DemoUserSpec(
        email="marco@turinfarm.it",
        name="Marco Rossi",
        role="farm_admin",
        password="demo-farmer-2026",
    ),
    DemoUserSpec(
        email="elena@agronomy.it",
        name="Elena Bianchi",
        role="viewer",
        password="demo-agro-2026",
    ),
)

VALID_ROLES: frozenset[str] = frozenset({"farm_admin", "viewer"})


def is_farm_owner(farm_record: dict[str, Any] | None, user: dict[str, Any] | None) -> bool:
    """Return True if the logged-in user is a `farm_admin` who owns `farm_record`."""
    if not farm_record or not user:
        return False
    return (
        user.get("role") == "farm_admin"
        and bool(user.get("user_id") or user.get("id"))
        and farm_record.get("owner") in {user.get("user_id"), user.get("id")}
    )


class AuthError(ValueError):
    """Raised on invalid credentials, duplicate registration, or malformed input."""


def derive_pbkdf2_client_hash(email: str, password: str) -> str:
    """Mirror the browser Web Crypto PBKDF2-SHA256 derivation (for demo seeding & tests)."""
    norm_email = email.strip().lower()
    salt = f"{norm_email}:{PBKDF2_SALT_SUFFIX}".encode("utf-8")
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=PBKDF2_DKLEN,
    )
    return dk.hex()


def hash_password_argon2id(client_hash: str) -> str:
    """Hash a PBKDF2-derived client hash with Argon2id on the backend."""
    if not client_hash or len(client_hash) < 32:
        raise AuthError("Invalid client-derived password hash.")
    return _ARGON2.hash(client_hash)


def verify_password_argon2id(stored_hash: str, client_hash: str) -> bool:
    """Verify a PBKDF2-derived client hash against a stored Argon2id hash."""
    if not stored_hash or not client_hash:
        return False
    try:
        return _ARGON2.verify(stored_hash, client_hash)
    except (VerifyMismatchError, InvalidHashError):
        return False


class AuthService:
    """User registration & login backed by PocketBase `app_users` + Argon2id."""

    def __init__(
        self,
        pb_url: str | None = None,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.pb_url = (pb_url if pb_url is not None else os.getenv("PB_URL", "http://127.0.0.1:8090")).rstrip("/")
        self.timeout = timeout
        self._client = client
        self._fallback_users: dict[str, dict[str, Any]] = {}
        self._demo_seeded_in_memory = False

    def _ensure_fallback_demos(self) -> None:
        if self._demo_seeded_in_memory:
            return
        for demo in DEMO_USERS:
            email = demo.email.lower()
            if email not in self._fallback_users:
                client_hash = derive_pbkdf2_client_hash(email, demo.password)
                self._fallback_users[email] = {
                    "id": f"demo_{email.split('@')[0]}",
                    "email": email,
                    "name": demo.name,
                    "role": demo.role,
                    "password_hash": hash_password_argon2id(client_hash),
                    "is_demo": True,
                }
        self._demo_seeded_in_memory = True

    async def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=self.timeout)

    async def _pb_create_auth_user(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """Create a user in PocketBase `users` Auth collection. Returns `(record, error_msg)`."""
        if not self.pb_url:
            return None, None
        close_after = self._client is None
        http = await self._http()
        try:
            resp = await http.post(
                f"{self.pb_url}/api/collections/users/records",
                json=payload,
            )
            if resp.status_code in (200, 201):
                return resp.json(), None
            if resp.status_code == 400:
                return None, "exists"
            return None, None
        except Exception:
            return None, None
        finally:
            if close_after:
                await http.aclose()

    async def _pb_auth_with_password(self, email: str, client_hash: str) -> tuple[dict[str, Any] | None, str | None, bool]:
        """Authenticate against PocketBase `users` Auth collection.

        Returns `(record, token, pb_reachable)`.
        """
        if not self.pb_url:
            return None, None, False
        close_after = self._client is None
        http = await self._http()
        try:
            resp = await http.post(
                f"{self.pb_url}/api/collections/users/auth-with-password",
                json={"identity": email, "password": client_hash},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("record") or {}, data.get("token"), True
            return None, None, True
        except Exception:
            return None, None, False
        finally:
            if close_after:
                await http.aclose()

    async def ensure_demo_users(self) -> None:
        """Ensure the built-in demo users exist in PocketBase `users` (and fallback store)."""
        self._ensure_fallback_demos()
        if not self.pb_url:
            return
        for demo in DEMO_USERS:
            email = demo.email.lower()
            client_hash = derive_pbkdf2_client_hash(email, demo.password)
            rec, _, reachable = await self._pb_auth_with_password(email, client_hash)
            if not reachable:
                return
            if rec is None:
                await self._pb_create_auth_user(
                    {
                        "email": email,
                        "password": client_hash,
                        "passwordConfirm": client_hash,
                        "name": demo.name,
                        "role": demo.role,
                        "password_hash": hash_password_argon2id(client_hash),
                        "is_demo": True,
                        "emailVisibility": True,
                    }
                )

    @staticmethod
    def _public_user(
        record: dict[str, Any],
        backend: str,
        pb_user_id: str | None = None,
        pb_token: str | None = None,
    ) -> dict[str, Any]:
        uid = pb_user_id or record.get("id")
        role = record.get("role")
        if role not in VALID_ROLES:
            role = "viewer"
        return {
            "id": uid,
            "user_id": uid,
            "token": pb_token,
            "email": record.get("email"),
            "name": record.get("name"),
            "role": role,
            "is_demo": bool(record.get("is_demo", False)),
            "backend": backend,
        }

    async def register(
        self,
        email: str,
        name: str,
        client_hash: str,
        role: str = "viewer",
    ) -> dict[str, Any]:
        """Register a new user using a PBKDF2-derived client hash, stored as Argon2id."""
        norm_email = email.strip().lower()
        clean_name = name.strip()
        clean_role = role.strip() if role.strip() in VALID_ROLES else "viewer"
        if "@" not in norm_email or "." not in norm_email.split("@")[-1]:
            raise AuthError("Please enter a valid email address.")
        if not clean_name:
            raise AuthError("Please enter your name.")

        await self.ensure_demo_users()

        if norm_email in self._fallback_users:
            raise AuthError("An account with this email already exists.")

        argon2_hash = hash_password_argon2id(client_hash)
        pb_payload = {
            "email": norm_email,
            "password": client_hash,
            "passwordConfirm": client_hash,
            "name": clean_name,
            "role": clean_role,
            "password_hash": argon2_hash,
            "is_demo": False,
            "emailVisibility": True,
        }

        created, err = await self._pb_create_auth_user(pb_payload)
        if err == "exists":
            raise AuthError("An account with this email already exists.")
        if created is not None:
            rec, pb_tok, _ = await self._pb_auth_with_password(norm_email, client_hash)
            return self._public_user(
                rec or created,
                backend="pocketbase",
                pb_user_id=(rec or created).get("id"),
                pb_token=pb_tok,
            )

        local_rec = {
            "id": f"local_{len(self._fallback_users) + 1}",
            "email": norm_email,
            "name": clean_name,
            "role": clean_role,
            "password_hash": argon2_hash,
            "is_demo": False,
        }
        self._fallback_users[norm_email] = local_rec
        return self._public_user(local_rec, backend="local_fallback")

    async def login(self, email: str, client_hash: str) -> dict[str, Any]:
        """Authenticate a user against PocketBase `users` (PBKDF2 + Argon2id)."""
        norm_email = email.strip().lower()
        if not norm_email or not client_hash:
            raise AuthError("Email and password are required.")

        await self.ensure_demo_users()

        record, pb_tok, reachable = await self._pb_auth_with_password(norm_email, client_hash)
        if reachable:
            if record is None:
                raise AuthError("Invalid email or password.")
            if record.get("password_hash") and not verify_password_argon2id(record["password_hash"], client_hash):
                raise AuthError("Invalid email or password.")
            return self._public_user(
                record,
                backend="pocketbase",
                pb_user_id=record.get("id"),
                pb_token=pb_tok,
            )

        fallback = self._fallback_users.get(norm_email)
        if fallback is None or not verify_password_argon2id(fallback.get("password_hash", ""), client_hash):
            raise AuthError("Invalid email or password.")
        return self._public_user(fallback, backend="local_fallback")
