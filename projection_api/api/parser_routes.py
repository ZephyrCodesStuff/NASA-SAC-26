"""
FastAPI Routes for Field Input Parser & Ingestion Engine.
Exposes endpoints to ingest, validate, audit, and normalize:
- Parcel Info & Baseline Soil Type
- Flexible 1-5 Year Harvest History
- Seed / Water / Oil Prices & Seed Characteristics (Greenhouse Need & Extreme Event Resilience)
- NASA Earth Observations
- Long Term Weather Projections
- Local User Data (In-situ sensors, soil override, management constraints)
- Elevation Maps
"""

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from projection_api.models.input_parser_schemas import (
    FullFieldIngestionPayload,
    SeedDataInput,
    SoilTypeEnum
)
from projection_api.services.input_parser import (
    FieldIngestionParser,
    ParsedFieldNormalized,
    DEFAULT_SEED_PROFILES
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/parser", tags=["Field Input Ingestion & Parser"])


class ParserValidationReport(BaseModel):
    """Validation and summary report for raw field ingestion."""
    is_valid: bool = Field(..., description="True if payload passes all structural schema validations")
    parcel_id: str = Field(..., description="Parcel identifier")
    effective_soil_type: str = Field(..., description="Harmonized effective soil type")
    soil_type_source: str = Field(..., description="Source of soil type (Override, Declared, Satellite, Baseline)")
    historical_years_found: int = Field(..., description="Number of historical cultivation seasons parsed (max 5)")
    seed_varieties_count: int = Field(..., description="Number of seed varieties in the ingested catalog")
    greenhouse_compatible_crops: List[str] = Field(..., description="Crops that can be grown in greenhouse/tunnels")
    greenhouse_required_crops: List[str] = Field(..., description="Crops that strictly require protected greenhouse structures")
    open_field_only_crops: List[str] = Field(..., description="Broadacre crops requiring open-field cultivation")
    extreme_event_resilience_highlights: Dict[str, List[str]] = Field(
        ..., description="Crops with High/Very High resilience to drought, flood, wind, frost, heat"
    )
    data_completeness_score_pct: float = Field(..., ge=0.0, le=100.0, description="Completeness score (0-100%)")
    audit_messages: List[str] = Field(..., description="Step-by-step parser diagnostic notes")


class SoilTypeInfo(BaseModel):
    soil_type: str
    drainage_class: str
    available_water_capacity_mm_per_m: int
    compaction_vulnerability: str
    erosion_risk: str
    recommended_tillage: str


STANDARD_SOIL_PROPERTIES: List[SoilTypeInfo] = [
    SoilTypeInfo(
        soil_type="Clay",
        drainage_class="Poorly Drained / Slow Infiltration",
        available_water_capacity_mm_per_m=160,
        compaction_vulnerability="Very High (Smearing when wet)",
        erosion_risk="High (Surface runoff)",
        recommended_tillage="Controlled Traffic / Strip-Till (avoid wet tillage)"
    ),
    SoilTypeInfo(
        soil_type="Clay Loam",
        drainage_class="Moderately Well Drained",
        available_water_capacity_mm_per_m=190,
        compaction_vulnerability="High (Plowpan formation)",
        erosion_risk="Moderate",
        recommended_tillage="Strip-Till / Deep Bio-drills"
    ),
    SoilTypeInfo(
        soil_type="Silt Loam",
        drainage_class="Well Drained",
        available_water_capacity_mm_per_m=220,
        compaction_vulnerability="Moderate to High (Crusting)",
        erosion_risk="Very High (Wind & Water Detachment)",
        recommended_tillage="No-Till with Heavy Residue Cover"
    ),
    SoilTypeInfo(
        soil_type="Loam",
        drainage_class="Well Drained (Optimal Agronomic Tilth)",
        available_water_capacity_mm_per_m=200,
        compaction_vulnerability="Moderate",
        erosion_risk="Moderate",
        recommended_tillage="No-Till or Reduced Tillage"
    ),
    SoilTypeInfo(
        soil_type="Sandy Loam",
        drainage_class="Somewhat Excessively Drained",
        available_water_capacity_mm_per_m=130,
        compaction_vulnerability="Low to Moderate",
        erosion_risk="High (Wind Erosion)",
        recommended_tillage="Direct Seeding with Windbreak Strips"
    ),
    SoilTypeInfo(
        soil_type="Sand",
        drainage_class="Excessively Drained / Rapid Leaching",
        available_water_capacity_mm_per_m=80,
        compaction_vulnerability="Low",
        erosion_risk="Severe (Windblown drift)",
        recommended_tillage="Continuous Cover Cropping / Split N Fertigation"
    ),
    SoilTypeInfo(
        soil_type="Chernozem / Mollisol (Black Soil)",
        drainage_class="Well Drained with High Humus Capacity",
        available_water_capacity_mm_per_m=240,
        compaction_vulnerability="Moderate",
        erosion_risk="Moderate",
        recommended_tillage="Conservation Minimum Tillage"
    ),
    SoilTypeInfo(
        soil_type="Peat / Organic Muck",
        drainage_class="Very Poorly Drained (Requires Tile Drainage)",
        available_water_capacity_mm_per_m=280,
        compaction_vulnerability="Severe Subsidence Risk",
        erosion_risk="High (Oxidation loss)",
        recommended_tillage="Water Table Management / Zero Tillage"
    )
]


@router.post("/ingest", response_model=ParsedFieldNormalized)
def ingest_and_normalize_field(payload: FullFieldIngestionPayload) -> ParsedFieldNormalized:
    """
    Ingest, validate, harmonize units, and produce a normalized field profile.
    Processes:
    - Parcel Info & Baseline Soil Type
    - Flexible 1-5 Past Harvest Records
    - Seed Data: Greenhouse Need ('Open Field Only', 'Greenhouse Required', etc.) &
      Resistances to Extreme Events (Drought, Flood, High Wind, Frost, Heat)
    - Economic Input Prices (Diesel, Water, Electricity, NPK, Labor)
    - NASA Earth Observations (11 datasets)
    - Optional Long Term Climate Projections
    - Local User Data (In-Situ sensors & Soil override)
    - Elevation Maps (DEM, slope, aspect, waterlogging)
    """
    try:
        normalized = FieldIngestionParser.parse_and_validate(payload)
        return normalized
    except Exception as e:
        logger.error(f"Error parsing field ingestion payload: {str(e)}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Payload normalization failed: {str(e)}")


@router.post("/validate", response_model=ParserValidationReport)
def validate_field_payload(payload: FullFieldIngestionPayload) -> ParserValidationReport:
    """
    Lightweight validation endpoint checking payload structure, soil type resolution,
    greenhouse suitability, extreme weather resilience, and data completeness score.
    """
    try:
        normalized = FieldIngestionParser.parse_and_validate(payload)
        return ParserValidationReport(
            is_valid=True,
            parcel_id=normalized.parcel_id,
            effective_soil_type=normalized.soil_type,
            soil_type_source=normalized.soil_type_source,
            historical_years_found=normalized.history_years_count,
            seed_varieties_count=len(normalized.seed_catalog),
            greenhouse_compatible_crops=normalized.greenhouse_compatible_crops,
            greenhouse_required_crops=normalized.greenhouse_required_crops,
            open_field_only_crops=normalized.open_field_only_crops,
            extreme_event_resilience_highlights={
                "drought_resilient": normalized.drought_resilient_crops,
                "flood_resilient": normalized.flood_resilient_crops,
                "wind_resilient": normalized.wind_resilient_crops,
                "frost_resilient": normalized.frost_resilient_crops,
                "heat_resilient": normalized.heat_resilient_crops,
            },
            data_completeness_score_pct=normalized.data_completeness_score_pct,
            audit_messages=normalized.audit_messages
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")


@router.get("/seed-templates", response_model=List[SeedDataInput])
def get_seed_templates(
    crop_name: Optional[str] = Query(None, description="Filter template by crop name substring")
) -> List[SeedDataInput]:
    """
    Returns reference seed templates pre-configured with scientific greenhouse requirements
    and extreme event resistance parameters (drought, flood, wind, frost, heat).
    """
    results: List[SeedDataInput] = []
    for name, seed in DEFAULT_SEED_PROFILES.items():
        if crop_name:
            if crop_name.lower() in name.lower():
                results.append(seed)
        else:
            results.append(seed)
    return results


@router.get("/soil-types", response_model=List[SoilTypeInfo])
def get_supported_soil_types() -> List[SoilTypeInfo]:
    """
    Returns catalog of standard soil types with hydraulic properties,
    compaction vulnerability, erosion risk, and tillage recommendations.
    """
    return STANDARD_SOIL_PROPERTIES
