"""Unit tests for PBKDF2 + Argon2id + PocketBase authentication."""

import asyncio
import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.auth import (
    DEMO_USERS,
    AuthError,
    AuthService,
    derive_pbkdf2_client_hash,
    hash_password_argon2id,
    verify_password_argon2id,
)


class AuthTests(unittest.TestCase):
    def test_pbkdf2_and_argon2id_pipeline(self) -> None:
        h1 = derive_pbkdf2_client_hash("Marco@TurinFarm.it ", "demo-farmer-2026")
        h2 = derive_pbkdf2_client_hash("marco@turinfarm.it", "demo-farmer-2026")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

        stored_1 = hash_password_argon2id(h1)
        stored_2 = hash_password_argon2id(h1)
        self.assertTrue(stored_1.startswith("$argon2id$"))
        self.assertNotEqual(stored_1, stored_2)  # unique random salt per hash
        self.assertTrue(verify_password_argon2id(stored_1, h1))
        self.assertFalse(verify_password_argon2id(stored_1, "0" * 64))

    def test_demo_users_login_and_register_with_pocketbase_mock(self) -> None:
        pb_store: dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/collections/app_users/records":
                if request.method == "GET":
                    flt = request.url.params.get("filter", "")
                    email = flt.split('"')[1] if '"' in flt else ""
                    rec = pb_store.get(email)
                    return httpx.Response(200, json={"items": [rec] if rec else []})
                if request.method == "POST":
                    body = json.loads(request.content.decode("utf-8"))
                    rec = {"id": f"pb_{len(pb_store) + 1}", **body}
                    pb_store[body["email"]] = rec
                    return httpx.Response(201, json=rec)
            return httpx.Response(404)

        async def run_test() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                svc = AuthService(pb_url="http://pb.test", client=http)

                # Both demo users can log in and are seeded in PocketBase
                for demo in DEMO_USERS:
                    ch = derive_pbkdf2_client_hash(demo.email, demo.password)
                    user = await svc.login(demo.email, ch)
                    self.assertEqual(user["email"], demo.email)
                    self.assertEqual(user["backend"], "pocketbase")
                    self.assertTrue(user["is_demo"])

                self.assertIn("marco@turinfarm.it", pb_store)
                self.assertTrue(pb_store["marco@turinfarm.it"]["password_hash"].startswith("$argon2id$"))

                # Register a new user
                reg_ch = derive_pbkdf2_client_hash("lucia@farm.it", "secret-123")
                created = await svc.register("lucia@farm.it", "Lucia Ferrero", reg_ch, role="Farmer")
                self.assertEqual(created["email"], "lucia@farm.it")
                self.assertEqual(created["backend"], "pocketbase")
                self.assertFalse(created["is_demo"])

                # Log in with new user
                logged_in = await svc.login("lucia@farm.it", reg_ch)
                self.assertEqual(logged_in["name"], "Lucia Ferrero")

                # Duplicate email rejected
                with self.assertRaises(AuthError):
                    await svc.register("lucia@farm.it", "Lucia 2", reg_ch)

                # Wrong password rejected
                with self.assertRaises(AuthError):
                    await svc.login("lucia@farm.it", derive_pbkdf2_client_hash("lucia@farm.it", "wrong"))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
