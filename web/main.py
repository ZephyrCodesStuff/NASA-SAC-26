"""NiceGUI entrypoint for NASA Space Apps Challenge 2026."""

import os

import httpx
from nicegui import ui

from src.providers.catasto import CatastoClient
from src.ui.map_picker import build_catasto_map_picker

PB_URL = os.getenv("PB_URL", "http://127.0.0.1:8090").rstrip("/")
PB_PUBLIC_URL = os.getenv("PB_PUBLIC_URL", PB_URL).rstrip("/")
PORT = int(os.getenv("PORT", "8080"))
RELOAD = os.getenv("RELOAD", "1") == "1"

catasto_client = CatastoClient(pb_url=PB_URL)


async def check_pocketbase() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{PB_URL}/api/health")
            if resp.status_code == 200:
                return True, f"PB Connected"
            return False, f"PB HTTP {resp.status_code}"
    except Exception:
        return False, "PB Offline (disk cache active)"


@ui.page("/")
async def index() -> None:
    ui.colors(primary="#0b3d91", secondary="#fc3d21")

    with ui.header().classes("items-center justify-between bg-primary text-white py-2 px-4"):
        with ui.row().classes("items-center gap-3"):
            ui.label("NASA Space Apps 2026 — Turin Catasto").classes("text-base font-bold")
            pb_badge = ui.badge("Checking PB...", color="grey")
        ui.link("PocketBase Admin", f"{PB_PUBLIC_URL}/_/", new_tab=True).classes(
            "text-white underline text-xs"
        )

    ok, msg = await check_pocketbase()
    pb_badge.set_text(msg)
    pb_badge.props(f"color={'positive' if ok else 'warning'}")

    await build_catasto_map_picker(catasto_client=catasto_client)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=PORT,
        title="NASA Space Apps 2026",
        reload=RELOAD,
    )
