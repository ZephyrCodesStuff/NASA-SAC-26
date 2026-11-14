"""
Main FastAPI Application for Field Input Ingestion & Parser API.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from projection_api.api.parser_routes import router as parser_router
from projection_api.config import API_HOST, API_PORT, DEBUG

app = FastAPI(
    title="Field Ingestion & Input Parser API",
    description=(
        "Standardized agricultural ingestion API. "
        "Normalizes parcel info, 1-5 year historical harvest records, economic input prices, "
        "seed characteristics (Greenhouse Need & Extreme Event Resistances), NASA Earth observations, "
        "long-term weather projections, local user telemetry, and elevation maps."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include parser API routes
app.include_router(parser_router)


@app.get("/", tags=["General"])
def root_info():
    """Returns high-level API metadata and quickstart endpoints."""
    return {
        "title": "Field Ingestion & Input Parser API",
        "version": "1.0.0",
        "documentation": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "ingest": "POST /api/parser/ingest",
            "validate": "POST /api/parser/validate",
            "seed_templates": "GET /api/parser/seed-templates",
            "soil_types": "GET /api/parser/soil-types"
        },
        "domains_supported": [
            "Parcel Info & Soil Type",
            "Last 1-5 Years Harvest & Crop History",
            "Seed / Water / Oil Prices & Seed Characteristics (Greenhouse Need & Extreme Event Resistance)",
            "NASA Earth Observations (11 datasets)",
            "Long-Term Weather Projections",
            "Local User Telemetry (In-situ sensors, soil override, tillage, irrigation)",
            "Elevation Maps (DEM, slope, aspect, waterlogging)"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("projection_api.main:app", host=API_HOST, port=API_PORT, reload=DEBUG)
