"""Standalone FastAPI entrypoint (e.g. `uvicorn api_main:app --host 0.0.0.0 --port 8081`)."""

from src.api import create_fastapi_app

app = create_fastapi_app()
