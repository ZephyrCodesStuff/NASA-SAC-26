"""FastAPI router & standalone app wrapping `auth`, `farms`, `catasto`, `worldcover`, and `data_api`."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.auth import AuthError, AuthService, derive_pbkdf2_client_hash, is_farm_owner
from src.devices import DeviceStore
from src.explainer import explain_plot_insights
from src.farms import (
    FarmStore,
    compute_geometry_bounds,
    merge_catasto_features_into_plot,
    polygons_intersect,
)
from src.formulas import evaluate_plot_strategies
from src.providers.catasto import CatastoClient, is_in_italy
from src.providers.data_api import (
    FAST_DATASETS,
    DataApiClient,
    build_analysis_payload,
    compute_soil_override_flags,
    extract_datasets,
    summarize_sensor_gaps,
)
from src.providers.worldcover import WorldCoverClient


class LoginRequest(BaseModel):
    email: str
    password: str | None = None
    client_hash: str | None = None


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str | None = None
    client_hash: str | None = None
    role: str = "viewer"


class CreateFarmRequest(BaseModel):
    name: str
    constraints: dict[str, Any] | None = None


class CreatePlotRequest(BaseModel):
    features: list[dict[str, Any]]
    label: str = ""
    crop: str = "Maize"
    use_catasto_names: bool = False


class UpdatePlotRequest(BaseModel):
    label: str | None = None
    soil_override: dict[str, Any] | None = None
    baseline_rotation: list[str] | None = None
    active_plan: dict[str, Any] | None = None


class CatastoDiscoverRequest(BaseModel):
    geometry: dict[str, Any]
    centroid: list[float] | None = Field(default=None, description="[lat, lon]")


class RegisterDeviceRequest(BaseModel):
    device_id: str
    farm_id: str
    plot_id: str
    name: str | None = None


class DeviceReadingRequest(BaseModel):
    soil_moisture: float
    humidity: float
    temperature: float


def create_api_router(
    *,
    auth_service: AuthService,
    farm_store: FarmStore,
    catasto_client: CatastoClient,
    worldcover_client: WorldCoverClient,
    data_api_client: DataApiClient,
    device_store: DeviceStore | None = None,
) -> APIRouter:
    """Build the FastAPI `APIRouter` for farms, plots, auth, Catasto, and telemetry."""
    router = APIRouter(tags=["api"])
    devices = device_store or DeviceStore(pb_url=auth_service.pb_url)

    async def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
        token = authorization.split(" ", 1)[1].strip()
        user = await auth_service.verify_token(token)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        return user

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "pb_url": auth_service.pb_url, "data_api_url": data_api_client.base_url}

    # --- Auth ---
    @router.post("/auth/login")
    async def login(body: LoginRequest) -> dict[str, Any]:
        ch = body.client_hash or (derive_pbkdf2_client_hash(body.email, body.password) if body.password else "")
        try:
            user = await auth_service.login(body.email, ch)
        except AuthError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        return {"user": user, "token": user.get("token")}

    @router.post("/auth/register", status_code=status.HTTP_201_CREATED)
    async def register(body: RegisterRequest) -> dict[str, Any]:
        ch = body.client_hash or (derive_pbkdf2_client_hash(body.email, body.password) if body.password else "")
        try:
            user = await auth_service.register(body.email, body.name, ch, role=body.role)
        except AuthError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"user": user, "token": user.get("token")}

    @router.get("/auth/me")
    async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        return {"user": user}

    # --- Farms ---
    @router.get("/farms")
    async def list_farms(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        farms = await farm_store.list_farms(user)
        return {"farms": farms}

    @router.post("/farms", status_code=status.HTTP_201_CREATED)
    async def create_farm(
        body: CreateFarmRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        if user.get("role") != "farm_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only farm_admin can create farms")
        farm = await farm_store.create_farm(body.name, user=user, constraints=body.constraints)
        return {"farm": farm}

    @router.get("/farms/{farm_id}/plots")
    async def list_plots(
        farm_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        plots = await farm_store.list_plots(farm_id, user=user)
        return {"plots": plots}

    @router.post("/farms/{farm_id}/plots", status_code=status.HTTP_201_CREATED)
    async def create_plot(
        farm_id: str,
        body: CreatePlotRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        farms = await farm_store.list_farms(user)
        farm = next((f for f in farms if f.get("id") == farm_id), None)
        if not farm or not is_farm_owner(farm, user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only farm owner can add plots")
        if not body.features:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one feature is required")

        existing_plots = await farm_store.list_plots(farm_id, user=user)
        plot_data = merge_catasto_features_into_plot(
            body.features,
            label=body.label,
            crop=body.crop,
            use_catasto_names=body.use_catasto_names,
            fallback_index=len(existing_plots) + 1,
        )
        created = await farm_store.add_plot(farm_id, plot_data, user=user)
        return {"plot": created}

    # --- Plots ---
    @router.get("/plots/{plot_id}")
    async def get_plot(
        plot_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        plot, farm = await farm_store.get_plot_with_farm(plot_id, user=user)
        if not plot or not farm:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plot not found")
        return {
            "plot": plot,
            "farm": farm,
            "is_owner": is_farm_owner(farm, user),
            "bounds": compute_geometry_bounds(plot.get("geometry")),
        }

    @router.patch("/plots/{plot_id}")
    async def update_plot(
        plot_id: str,
        body: UpdatePlotRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        plot, farm = await farm_store.get_plot_with_farm(plot_id, user=user)
        if not plot or not farm:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plot not found")
        if not is_farm_owner(farm, user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only farm owner can update plots")

        patch: dict[str, Any] = {}
        if body.label is not None:
            patch["label"] = body.label
        if body.baseline_rotation is not None:
            patch["baseline_rotation"] = body.baseline_rotation
        if body.active_plan is not None:
            patch["active_plan"] = body.active_plan
        if body.soil_override is not None:
            patch["soil_override"] = body.soil_override
            patch["overridden_fields"] = compute_soil_override_flags(body.soil_override)

        updated = await farm_store.update_plot(plot_id, patch, user=user)
        return {"plot": updated}

    @router.delete("/plots/{plot_id}")
    async def delete_plot(
        plot_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        plot, farm = await farm_store.get_plot_with_farm(plot_id, user=user)
        if not plot or not farm:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plot not found")
        if not is_farm_owner(farm, user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only farm owner can delete plots")
        ok = await farm_store.remove_plot(plot_id, user=user)
        return {"deleted": ok}

    @router.post("/plots/{plot_id}/telemetry/refresh")
    async def refresh_plot_telemetry(
        plot_id: str,
        datasets: str = FAST_DATASETS,
        history: bool = True,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        plot, farm = await farm_store.get_plot_with_farm(plot_id, user=user)
        if not plot or not farm:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plot not found")
        feature = {
            "type": "Feature",
            "id": plot.get("cadastral_ref") or plot.get("id"),
            "geometry": plot["geometry"],
            "properties": {"area_ha": plot.get("area_ha")},
        }
        try:
            snapshot = await data_api_client.fetch_plot_telemetry(feature, datasets=datasets, history=history)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"data-api error ({type(exc).__name__}): {exc}",
            ) from exc
        if is_farm_owner(farm, user):
            await farm_store.update_plot(plot_id, {"nasa_snapshot": snapshot}, user=user)
        return {"nasa_snapshot": snapshot}

    @router.get("/plots/{plot_id}/analysis-payload")
    async def get_analysis_payload(
        plot_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        plot, farm = await farm_store.get_plot_with_farm(plot_id, user=user)
        if not plot or not farm:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plot not found")
        payload = build_analysis_payload(plot)
        datasets = extract_datasets(plot.get("nasa_snapshot"))
        soil_override = plot.get("soil_override") if isinstance(plot.get("soil_override"), dict) else {}
        gaps = summarize_sensor_gaps(datasets, soil_override=soil_override)
        baseline_analysis = evaluate_plot_strategies(
            datasets=datasets,
            area_ha=float(plot.get("area_ha") or 1.0),
            baseline_rotation=plot.get("baseline_rotation"),
            soil_override=soil_override,
        )
        explained = explain_plot_insights(baseline_analysis, gaps, plot_label=str(plot.get("label") or "Plot"))
        return {
            "payload": payload,
            "baseline_preview": baseline_analysis,
            "explained": explained,
            "gaps": gaps,
        }

    # --- Catasto & WorldCover ---
    @router.post("/catasto/discover")
    async def catasto_discover(
        body: CatastoDiscoverRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        bounds = compute_geometry_bounds(body.geometry)
        if not bounds:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid GeoJSON geometry")
        (min_lat, min_lon), (max_lat, max_lon) = bounds
        mid_lat, mid_lon = (min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0
        if not is_in_italy(mid_lat, mid_lon):
            return {"parcels": []}  # the AdE cadastre only covers Italy

        # One WFS call around the drawn area, clamped under the AdE 2,000 m vertical-span limit
        half_lat = min(max((max_lat - min_lat) / 2.0, 0.001), 0.007)
        half_lon = min(max((max_lon - min_lon) / 2.0, 0.001), 0.009)
        try:
            fc = await catasto_client.fetch_parcels_in_bbox(
                mid_lat - half_lat, mid_lon - half_lon, mid_lat + half_lat, mid_lon + half_lon, count=150
            )
        except Exception as exc:  # noqa: BLE001 — upstream WFS errors/timeouts
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Catasto WFS unavailable: {type(exc).__name__}: {exc}",
            ) from exc

        intersecting = [p for p in fc.get("features") or [] if polygons_intersect(body.geometry, p["geometry"])]
        if not intersecting:
            return {"parcels": []}
        try:
            await worldcover_client.classify_parcels(intersecting)  # adds is_farmland / worldcover_* to properties
        except Exception:  # noqa: BLE001 — land-cover check is optional: return unfiltered parcels
            return {"parcels": intersecting}
        return {"parcels": [p for p in intersecting if (p.get("properties") or {}).get("is_farmland") is True]}

    # --- Unauthenticated IoT / ESP32 Hackathon Demo Endpoints ---
    @router.get("/public/farms-plots")
    async def public_farms_plots() -> dict[str, Any]:
        farms = await farm_store.list_farms(None)
        result: list[dict[str, Any]] = []
        for f in farms:
            fid = str(f.get("id") or "")
            plots = await farm_store.list_plots(fid, user=None)
            result.append(
                {
                    "id": fid,
                    "name": f.get("name"),
                    "plots": [
                        {
                            "id": p.get("id"),
                            "label": p.get("label"),
                            "cadastral_ref": p.get("cadastral_ref"),
                        }
                        for p in plots
                    ],
                }
            )
        return {"farms": result}

    @router.post("/devices/register", status_code=status.HTTP_201_CREATED)
    async def register_device(body: RegisterDeviceRequest) -> dict[str, Any]:
        if not body.device_id.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="device_id is required")
        dev = await devices.register_device(
            device_id=body.device_id,
            farm_id=body.farm_id,
            plot_id=body.plot_id,
            name=body.name,
        )
        return {"status": "registered", "device": dev}

    @router.post("/devices/{device_id}/readings", status_code=status.HTTP_201_CREATED)
    async def post_device_reading(device_id: str, body: DeviceReadingRequest) -> dict[str, Any]:
        reading = await devices.record_reading(
            device_id=device_id,
            soil_moisture=body.soil_moisture,
            humidity=body.humidity,
            temperature=body.temperature,
        )
        return {"ok": True, "reading": reading}

    @router.get("/plots/{plot_id}/devices")
    async def list_plot_devices(plot_id: str) -> dict[str, Any]:
        items = await devices.list_plot_devices(plot_id)
        return {"devices": items}

    @router.get("/devices/{device_id}/readings")
    async def get_device_readings(device_id: str, limit: int = 60) -> dict[str, Any]:
        dev, items = await devices.get_device_readings(device_id, limit=limit)
        return {"device": dev, "readings": items}

    return router


def create_fastapi_app(
    *,
    auth_service: AuthService | None = None,
    farm_store: FarmStore | None = None,
    catasto_client: CatastoClient | None = None,
    worldcover_client: WorldCoverClient | None = None,
    data_api_client: DataApiClient | None = None,
    device_store: DeviceStore | None = None,
) -> FastAPI:
    """Create a standalone FastAPI app (with CORS enabled for Next.js) and `/api` routes."""
    pb_url = os.getenv("PB_URL", "http://127.0.0.1:8090").rstrip("/")
    app = FastAPI(title="NASA Space Apps 2026 — Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    router = create_api_router(
        auth_service=auth_service or AuthService(pb_url=pb_url),
        farm_store=farm_store or FarmStore(pb_url=pb_url),
        catasto_client=catasto_client or CatastoClient(pb_url=pb_url),
        worldcover_client=worldcover_client or WorldCoverClient(),
        data_api_client=data_api_client or DataApiClient(),
        device_store=device_store or DeviceStore(pb_url=pb_url),
    )
    app.include_router(router, prefix="/api")
    return app
