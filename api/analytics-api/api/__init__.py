"""API routes package initialization."""
from projection_api.api.parser_routes import router as parser_router
from projection_api.api.projection_routes import projection_router

__all__ = ["parser_router", "projection_router"]
