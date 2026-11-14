"""NiceGUI entrypoint for NASA Space Apps Challenge 2026."""

import os

import httpx
from nicegui import app, ui

from src.auth import AuthService
from src.providers.catasto import CatastoClient
from src.providers.worldcover import WorldCoverClient
from src.ui.auth_view import build_auth_view
from src.ui.map_picker import build_catasto_map_picker

PB_URL = os.getenv("PB_URL", "http://127.0.0.1:8090").rstrip("/")
PB_PUBLIC_URL = os.getenv("PB_PUBLIC_URL", PB_URL).rstrip("/")
PORT = int(os.getenv("PORT", "8080"))
RELOAD = os.getenv("RELOAD", "1") == "1"
STORAGE_SECRET = os.getenv("STORAGE_SECRET") or "nasa-space-apps-2026-dev-secret"

catasto_client = CatastoClient(pb_url=PB_URL)
worldcover_client = WorldCoverClient()
auth_service = AuthService(pb_url=PB_URL)


async def check_pocketbase() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{PB_URL}/api/health")
            if resp.status_code == 200:
                return True, "PB Connected"
            return False, f"PB HTTP {resp.status_code}"
    except Exception:
        return False, "PB Offline (local cache/auth)"


@ui.page("/")
async def index() -> None:
    ui.colors(primary="#0b3d91", secondary="#fc3d21")
    current_user = app.storage.user.get("user")

    with ui.header().classes("items-center justify-between bg-primary text-white py-2 px-4"):
        with ui.row().classes("items-center gap-3"):
            ui.label("NASA Space Apps 2026 — Turin Catasto").classes("text-base font-bold")
            pb_badge = ui.badge("Checking PB...", color="grey")

        with ui.row().classes("items-center gap-3"):
            if current_user:
                ui.label(f"{current_user.get('name')} ({current_user.get('role')})").classes("text-xs font-medium")

                def sign_out() -> None:
                    app.storage.user.pop("user", None)
                    ui.navigate.to("/")

                ui.button("Sign out", on_click=sign_out, icon="logout").props("flat dense color=white size=sm")

            ui.link("PocketBase Admin", f"{PB_PUBLIC_URL}/_/", new_tab=True).classes(
                "text-white underline text-xs"
            )

    async def _update_pb_status() -> None:
        ok, msg = await check_pocketbase()
        pb_badge.set_text(msg)
        pb_badge.props(f"color={'positive' if ok else 'warning'}")

    ui.timer(0.05, _update_pb_status, once=True)

    if not current_user:
        build_auth_view(auth_service)
        return

    await build_catasto_map_picker(
        catasto_client=catasto_client,
        worldcover_client=worldcover_client,
    )


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=PORT,
        title="NASA Space Apps 2026",
        reload=RELOAD,
        storage_secret=STORAGE_SECRET,
    )
