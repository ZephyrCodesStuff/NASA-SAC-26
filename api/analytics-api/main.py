"""
Main FastAPI Application for Field Ingestion, 3-Year Plan Optimization & Gemini Advisory API.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from projection_api.api.parser_routes import router as parser_router
from projection_api.api.projection_routes import projection_router
from projection_api.config import API_HOST, API_PORT, DEBUG

app = FastAPI(
    title="Agricultural Ingestion, 3-Year Plan Optimization & Gemini Advisory API",
    description=(
        "Standardized agricultural ingestion and multi-objective 3-year planting plan solver. "
        "Ingests raw NASA Earth observations, dated in-situ sensors, elevation maps, and input prices. "
        "Simulates year-by-year physical ground impact (NPK balances, Henin-Dupuis SOC %, ASAE compaction PSI, "
        "FAO-56 ETc deficits, RUSLE erosion) and generates 5 distinct farmer strategies: "
        "Most Income, Best Soil Health, Least Effort, Highest ROI %, and Least Risk, "
        "accompanied by grounded Google Gemini 3.8 Flash AI advisory."
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

# Include API routes
app.include_router(parser_router)
app.include_router(projection_router)


@app.get("/", tags=["General"])
def root_info():
    """Returns high-level API metadata and quickstart endpoints."""
    return {
        "title": "Agricultural Ingestion, 3-Year Plan Optimization & Gemini Advisory API",
        "version": "1.0.0",
        "documentation": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "ingest": "POST /api/parser/ingest",
            "validate": "POST /api/parser/validate",
            "seed_templates": "GET /api/parser/seed-templates",
            "soil_types": "GET /api/parser/soil-types",
            "plan_3year": "POST /api/projections/plan-3year",
            "crops_catalog": "GET /api/projections/crops-catalog",
            "soil_profiles": "GET /api/projections/soil-profiles"
        },
        "supported_strategies": [
            "most_income",
            "best_soil_health",
            "least_effort",
            "highest_roi",
            "least_crop_loss_risk"
        ],
        "ai_advisory": "Google Gemini 3.8 Flash via official google-genai SDK (with deterministic offline fallback)"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("projection_api.main:app", host=API_HOST, port=API_PORT, reload=DEBUG)
