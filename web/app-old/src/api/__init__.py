"""FastAPI backend router & standalone app factory."""

from src.api.app import create_api_router, create_fastapi_app

__all__ = ["create_api_router", "create_fastapi_app"]
