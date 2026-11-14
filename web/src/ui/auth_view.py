"""Login & registration view with browser-side PBKDF2-SHA256 key derivation."""

from __future__ import annotations

import json

from nicegui import app, ui

from src.auth import (
    DEMO_USERS,
    PBKDF2_ITERATIONS,
    PBKDF2_SALT_SUFFIX,
    AuthError,
    AuthService,
)

PBKDF2_BROWSER_SCRIPT = f"""
<script>
window.deriveClientPasswordHash = async function(email, password) {{
    const enc = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
        'raw',
        enc.encode(password),
        'PBKDF2',
        false,
        ['deriveBits']
    );
    const salt = enc.encode(email.trim().toLowerCase() + ':{PBKDF2_SALT_SUFFIX}');
    const bits = await crypto.subtle.deriveBits(
        {{ name: 'PBKDF2', salt: salt, iterations: {PBKDF2_ITERATIONS}, hash: 'SHA-256' }},
        keyMaterial,
        256
    );
    return Array.from(new Uint8Array(bits))
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('');
}};
</script>
"""


async def _derive_in_browser(email: str, password: str) -> str:
    """Run PBKDF2-SHA256 inside the user's browser so plaintext passwords stay client-side."""
    result = await ui.run_javascript(
        f"return await window.deriveClientPasswordHash({json.dumps(email)}, {json.dumps(password)});",
        timeout=5.0,
    )
    if not isinstance(result, str) or len(result) < 32:
        raise AuthError("Browser PBKDF2 key derivation failed.")
    return result


def build_auth_view(auth_service: AuthService) -> None:
    """Render a centered Login / Register card with one-click demo accounts."""
    ui.add_head_html(PBKDF2_BROWSER_SCRIPT)

    with ui.column().classes("w-full min-h-[calc(100vh-80px)] items-center justify-center p-4 bg-slate-50"):
        with ui.card().classes("w-full max-w-md p-6 shadow-lg gap-3"):
            ui.label("Turin Crop Rotation Planner").classes("text-xl font-bold text-primary")
            ui.label(
                "Sign in or create an account. Passwords are PBKDF2-derived in your browser "
                "and stored with Argon2id in PocketBase."
            ).classes("text-xs text-gray-600")

            error_label = ui.label("").classes("text-xs text-negative font-medium")
            error_label.visible = False

            with ui.tabs().classes("w-full") as tabs:
                login_tab = ui.tab("Sign In")
                register_tab = ui.tab("Register")

            with ui.tab_panels(tabs, value=login_tab).classes("w-full"):
                # --- Sign In ---
                with ui.tab_panel(login_tab).classes("p-0 pt-3 gap-3"):
                    login_email = ui.input("Email", placeholder="marco@turinfarm.it").props("outlined dense").classes("w-full")
                    login_pw = ui.input("Password", password=True, password_toggle_button=True).props("outlined dense").classes("w-full")

                    async def do_login() -> None:
                        error_label.visible = False
                        email = (login_email.value or "").strip()
                        pw = login_pw.value or ""
                        if not email or not pw:
                            error_label.set_text("Please enter email and password.")
                            error_label.visible = True
                            return
                        try:
                            client_hash = await _derive_in_browser(email, pw)
                            user = await auth_service.login(email, client_hash)
                        except AuthError as exc:
                            error_label.set_text(str(exc))
                            error_label.visible = True
                            return
                        app.storage.user["user"] = user
                        ui.navigate.to("/")

                    ui.button("Sign In", on_click=do_login, icon="login").props("color=primary").classes("w-full")

                # --- Register ---
                with ui.tab_panel(register_tab).classes("p-0 pt-3 gap-3"):
                    reg_name = ui.input("Full Name", placeholder="Lucia Ferrero").props("outlined dense").classes("w-full")
                    reg_email = ui.input("Email", placeholder="lucia@farm.it").props("outlined dense").classes("w-full")
                    reg_role = ui.select(
                        options={"farm_admin": "Farm Admin (Can edit plots)", "viewer": "Viewer (Read-only)"},
                        value="farm_admin",
                        label="Role",
                    ).props("outlined dense").classes("w-full")
                    reg_pw = ui.input("Password (min 6 chars)", password=True, password_toggle_button=True).props("outlined dense").classes("w-full")

                    async def do_register() -> None:
                        error_label.visible = False
                        name = (reg_name.value or "").strip()
                        email = (reg_email.value or "").strip()
                        pw = reg_pw.value or ""
                        if len(pw) < 6:
                            error_label.set_text("Password must be at least 6 characters.")
                            error_label.visible = True
                            return
                        try:
                            client_hash = await _derive_in_browser(email, pw)
                            user = await auth_service.register(
                                email=email,
                                name=name,
                                client_hash=client_hash,
                                role=str(reg_role.value or "viewer"),
                            )
                        except AuthError as exc:
                            error_label.set_text(str(exc))
                            error_label.visible = True
                            return
                        app.storage.user["user"] = user
                        ui.navigate.to("/")

                    ui.button("Create Account", on_click=do_register, icon="person_add").props("color=primary").classes("w-full")

            ui.separator().classes("my-1")
            ui.label("Quick Demo Accounts").classes("text-xs font-semibold text-gray-500 uppercase tracking-wide")

            with ui.column().classes("w-full gap-2"):
                for demo in DEMO_USERS:
                    async def _demo_login(d=demo) -> None:
                        error_label.visible = False
                        try:
                            client_hash = await _derive_in_browser(d.email, d.password)
                            user = await auth_service.login(d.email, client_hash)
                        except AuthError as exc:
                            error_label.set_text(str(exc))
                            error_label.visible = True
                            return
                        app.storage.user["user"] = user
                        ui.navigate.to("/")

                    role_label = "Farm Admin" if demo.role == "farm_admin" else "Viewer"
                    ui.button(
                        f"{demo.name} ({role_label}) — {demo.email}",
                        on_click=_demo_login,
                        icon="bolt",
                    ).props("outline dense no-caps").classes("w-full text-xs")
