"""Farm & plot management store (PocketBase `farms` + `user_plots` with local fallback) and geometry helpers."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Sequence

import httpx

logger = logging.getLogger(__name__)


class PocketBaseError(Exception):
    """Raised when PocketBase is configured (`pb_url` set) and a request fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

from src.providers.catasto import (
    _feature_bbox,
    compute_geometry_area_ha,
    compute_geometry_centroid,
    point_in_geojson_geometry,
)

DEFAULT_STORE_PATH = Path(
    os.getenv("FARMS_STORE_PATH", str(Path(__file__).resolve().parents[2] / ".cache" / "farms_store.json"))
)


# ---------------------------------------------------------------------------
# Pure-Python polygon intersection & Leaflet draw:created extraction
# ---------------------------------------------------------------------------


def _extract_rings(geometry: dict[str, Any]) -> list[list[Sequence[float]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return [coords] if coords else []
    if gtype == "MultiPolygon":
        return [poly for poly in coords if poly]
    return []


def _segments_intersect(
    p1: Sequence[float],
    p2: Sequence[float],
    q1: Sequence[float],
    q2: Sequence[float],
) -> bool:
    """Return True if closed 2D segments p1-p2 and q1-q2 intersect."""

    def _orient(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def _on_seg(a: Sequence[float], b: Sequence[float], p: Sequence[float]) -> bool:
        return (
            min(a[0], b[0]) - 1e-12 <= p[0] <= max(a[0], b[0]) + 1e-12
            and min(a[1], b[1]) - 1e-12 <= p[1] <= max(a[1], b[1]) + 1e-12
        )

    o1 = _orient(p1, p2, q1)
    o2 = _orient(p1, p2, q2)
    o3 = _orient(q1, q2, p1)
    o4 = _orient(q1, q2, p2)

    if ((o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0)) and (
        (o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0)
    ):
        return True
    if abs(o1) <= 1e-12 and _on_seg(p1, p2, q1):
        return True
    if abs(o2) <= 1e-12 and _on_seg(p1, p2, q2):
        return True
    if abs(o3) <= 1e-12 and _on_seg(q1, q2, p1):
        return True
    if abs(o4) <= 1e-12 and _on_seg(q1, q2, p2):
        return True
    return False


def polygons_intersect(geom_a: dict[str, Any], geom_b: dict[str, Any]) -> bool:
    """Return True if two GeoJSON Polygon/MultiPolygon geometries overlap or touch."""
    bbox_a = _feature_bbox(geom_a)
    bbox_b = _feature_bbox(geom_b)
    if bbox_a is None or bbox_b is None:
        return False
    if (
        bbox_a[2] < bbox_b[0]
        or bbox_b[2] < bbox_a[0]
        or bbox_a[3] < bbox_b[1]
        or bbox_b[3] < bbox_a[1]
    ):
        return False

    polys_a = _extract_rings(geom_a)
    polys_b = _extract_rings(geom_b)

    for poly in polys_a:
        for pt in poly[0]:
            if point_in_geojson_geometry(pt[1], pt[0], geom_b):
                return True
    for poly in polys_b:
        for pt in poly[0]:
            if point_in_geojson_geometry(pt[1], pt[0], geom_a):
                return True

    for poly_a in polys_a:
        ring_a = poly_a[0]
        for poly_b in polys_b:
            ring_b = poly_b[0]
            for i in range(len(ring_a) - 1):
                for j in range(len(ring_b) - 1):
                    if _segments_intersect(ring_a[i], ring_a[i + 1], ring_b[j], ring_b[j + 1]):
                        return True
    return False


def extract_drawn_geojson(event_args: Any) -> dict[str, Any] | None:
    """Convert a NiceGUI Leaflet `draw:created` event payload into a GeoJSON Feature."""
    if not isinstance(event_args, dict):
        return None
    layer = event_args.get("layer") or {}
    raw_latlngs = layer.get("_latlngs")
    if not raw_latlngs:
        return None

    # Leaflet polygon/rectangle `_latlngs` is usually [[{lat, lng}, ...]]
    ring_raw = raw_latlngs[0] if isinstance(raw_latlngs[0], list) else raw_latlngs
    if not isinstance(ring_raw, list) or len(ring_raw) < 3:
        return None

    ring: list[list[float]] = []
    for pt in ring_raw:
        if isinstance(pt, dict) and "lat" in pt and "lng" in pt:
            ring.append([float(pt["lng"]), float(pt["lat"])])
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    geometry = {"type": "Polygon", "coordinates": [ring]}
    centroid = compute_geometry_centroid(geometry)
    return {
        "type": "Feature",
        "id": f"drawn_{uuid.uuid4().hex[:10]}",
        "geometry": geometry,
        "properties": {
            "cadastral_ref": None,
            "area_ha": compute_geometry_area_ha(geometry),
            "centroid": list(centroid) if centroid else None,
            "is_custom_drawn": True,
        },
    }


def merge_catasto_features_into_plot(
    features: list[dict[str, Any]],
    *,
    label: str = "",
    crop: str = "Maize",
    use_catasto_names: bool = False,
    fallback_index: int = 1,
) -> dict[str, Any]:
    """Combine one or more GeoJSON parcel features into a single `user_plots` payload.

    Custom drawn areas produce a single `Polygon` plot; multi-parcel Catasto selections
    are unified into a single `MultiPolygon` plot with `sub_plots` metadata preserved.
    """
    polygons: list[Any] = []
    sub_plots: list[dict[str, Any]] = []
    refs: list[str] = []
    total_area_ha = 0.0
    weighted_lat = 0.0
    weighted_lon = 0.0
    centroid_weight = 0.0

    for feat in features:
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon" and coords:
            polygons.append(coords)
        elif gtype == "MultiPolygon" and coords:
            polygons.extend(coords)

        props = feat.get("properties") or {}
        area = float(props.get("area_ha") or 0.0)
        total_area_ha += area
        c_ref = str(props.get("national_ref") or props.get("cadastral_ref") or "").strip()
        if c_ref:
            refs.append(c_ref)

        c_raw = props.get("centroid")
        c_obj: dict[str, float] | None = None
        if isinstance(c_raw, list) and len(c_raw) == 2:
            c_obj = {"lat": float(c_raw[0]), "lon": float(c_raw[1])}
        elif isinstance(c_raw, dict) and "lat" in c_raw and "lon" in c_raw:
            c_obj = {"lat": float(c_raw["lat"]), "lon": float(c_raw["lon"])}

        if c_obj is not None:
            w = area if area > 0 else 1.0
            weighted_lat += c_obj["lat"] * w
            weighted_lon += c_obj["lon"] * w
            centroid_weight += w

        if use_catasto_names or len(features) > 1:
            sub_plots.append(
                {
                    "cadastral_ref": c_ref,
                    "area_ha": round(area, 4),
                    "centroid": c_obj,
                    "administrative_unit": props.get("administrative_unit"),
                    "foglio": props.get("foglio"),
                    "particella": props.get("particella"),
                    "inspire_id": props.get("inspire_id"),
                    "worldcover_class": props.get("worldcover_class"),
                    "worldcover_label": props.get("worldcover_label"),
                }
            )

    if len(polygons) == 1:
        merged_geometry: dict[str, Any] = {"type": "Polygon", "coordinates": polygons[0]}
    else:
        merged_geometry = {"type": "MultiPolygon", "coordinates": polygons}

    centroid_obj = (
        {"lat": round(weighted_lat / centroid_weight, 6), "lon": round(weighted_lon / centroid_weight, 6)}
        if centroid_weight > 0
        else None
    )

    first_props = (features[0].get("properties") or {}) if features else {}
    if len(refs) <= 1:
        cadastral_ref = refs[0] if refs else ""
    elif len(refs) <= 3:
        cadastral_ref = ", ".join(refs)
    else:
        cadastral_ref = f"{', '.join(refs[:3])} (+{len(refs) - 3} more)"

    clean_label = label.strip()
    if clean_label:
        final_label = clean_label
    elif use_catasto_names and len(refs) == 1:
        final_label = f"Parcel {refs[0]}"
    elif use_catasto_names and len(features) > 1:
        final_label = f"Catasto Plot ({len(features)} parcels)"
    else:
        final_label = f"Drawn Field {fallback_index}"

    return {
        "cadastral_ref": cadastral_ref,
        "administrative_unit": first_props.get("administrative_unit") if len(features) == 1 else None,
        "foglio": first_props.get("foglio") if len(features) == 1 else None,
        "particella": first_props.get("particella") if len(features) == 1 else None,
        "inspire_id": first_props.get("inspire_id") if len(features) == 1 else None,
        "label": final_label,
        "area_ha": round(total_area_ha, 4),
        "centroid": centroid_obj,
        "geometry": merged_geometry,
        "sub_plots": sub_plots if sub_plots else None,
        "baseline_rotation": [crop],
        "worldcover_class": first_props.get("worldcover_class"),
        "worldcover_label": first_props.get("worldcover_label") or ("Custom Area" if not use_catasto_names else "Farmland"),
    }


def compute_geometry_bounds(geometry: dict[str, Any] | None) -> list[list[float]] | None:
    """Return Leaflet `[[min_lat, min_lon], [max_lat, max_lon]]` bounds for a GeoJSON geometry."""
    if not geometry or not isinstance(geometry, dict):
        return None
    rings = _extract_rings(geometry)
    pts = [pt for poly in rings for ring in poly for pt in ring if len(pt) >= 2]
    if not pts:
        return None
    lons = [float(pt[0]) for pt in pts]
    lats = [float(pt[1]) for pt in pts]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


# ---------------------------------------------------------------------------
# Pre-seeded Turin demo farms & plots
# ---------------------------------------------------------------------------


def _default_demo_seed(owner_id: str) -> dict[str, Any]:
    farm_1_id = "demo_farm_cascina_san_giorgio"
    farm_2_id = "demo_farm_tenuta_stura"

    p1_geom = {
        "type": "Polygon",
        "coordinates": [
            [
                [7.7158, 44.8464],
                [7.7172, 44.8464],
                [7.7172, 44.8473],
                [7.7158, 44.8473],
                [7.7158, 44.8464],
            ]
        ],
    }
    p2_geom = {
        "type": "Polygon",
        "coordinates": [
            [
                [7.7175, 44.8465],
                [7.7191, 44.8465],
                [7.7191, 44.8475],
                [7.7175, 44.8475],
                [7.7175, 44.8465],
            ]
        ],
    }
    p3_geom = {
        "type": "Polygon",
        "coordinates": [
            [
                [7.7145, 45.1178],
                [7.7168, 45.1178],
                [7.7168, 45.1192],
                [7.7145, 45.1192],
                [7.7145, 45.1178],
            ]
        ],
    }

    return {
        "farms": [
            {
                "id": farm_1_id,
                "name": "Cascina San Giorgio (Carmagnola)",
                "owner": owner_id,
                "viewers": [],
                "is_public_demo": True,
                "constraints": {"irrigation": True, "no_till_drill": False},
            },
            {
                "id": farm_2_id,
                "name": "Tenuta Stura (Torino Nord)",
                "owner": owner_id,
                "viewers": [],
                "is_public_demo": True,
                "constraints": {"irrigation": False, "no_till_drill": True},
            },
        ],
        "user_plots": [
            {
                "id": "demo_plot_csg_1",
                "farm": farm_1_id,
                "cadastral_ref": "B791_011500.1",
                "label": "South Clay Parcel",
                "area_ha": compute_geometry_area_ha(p1_geom),
                "centroid": {"lat": 44.84685, "lon": 7.7165},
                "geometry": p1_geom,
                "baseline_rotation": ["Maize", "Maize", "Winter Wheat"],
                "worldcover_class": 40,
                "worldcover_label": "Cropland",
            },
            {
                "id": "demo_plot_csg_2",
                "farm": farm_1_id,
                "cadastral_ref": "B791_011500.10",
                "label": "East Irrigated Field",
                "area_ha": compute_geometry_area_ha(p2_geom),
                "centroid": {"lat": 44.8470, "lon": 7.7183},
                "geometry": p2_geom,
                "baseline_rotation": ["Soybean", "Winter Wheat", "Maize"],
                "worldcover_class": 40,
                "worldcover_label": "Cropland",
            },
            {
                "id": "demo_plot_stura_1",
                "farm": farm_2_id,
                "cadastral_ref": "L219_104400.211",
                "label": "Stura North Pasture",
                "area_ha": compute_geometry_area_ha(p3_geom),
                "centroid": {"lat": 45.1185, "lon": 7.71565},
                "geometry": p3_geom,
                "baseline_rotation": ["Alfalfa", "Alfalfa", "Barley"],
                "worldcover_class": 30,
                "worldcover_label": "Grassland",
            },
        ],
    }


# ---------------------------------------------------------------------------
# FarmStore (PocketBase REST + local JSON fallback)
# ---------------------------------------------------------------------------


class FarmStore:
    """Manages `farms` and `user_plots` in PocketBase with local JSON fallback."""

    def __init__(
        self,
        pb_url: str | None = None,
        store_path: Path | str | None = DEFAULT_STORE_PATH,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.pb_url = (pb_url if pb_url is not None else os.getenv("PB_URL", "http://127.0.0.1:8090")).rstrip("/")
        self.store_path = Path(store_path) if store_path else None
        self.timeout = timeout
        self._client = client

    def _load_local(self) -> dict[str, Any]:
        if self.store_path and self.store_path.exists():
            try:
                return json.loads(self.store_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        data = _default_demo_seed("demo_marco")
        self._save_local(data)
        return data

    def _save_local(self, data: dict[str, Any]) -> None:
        if not self.store_path:
            return
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            self.store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _headers(token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=self.timeout)

    async def ensure_demo_farms_in_pb(self, user: dict[str, Any]) -> None:
        """Seed the 2 showcase Turin farms + plots into PocketBase if none exist yet."""
        uid = user.get("user_id") or user.get("id")
        token = user.get("token")
        if not self.pb_url or not token or not uid or user.get("role") != "farm_admin":
            return

        close_after = self._client is None
        http = await self._http()
        try:
            resp = await http.get(
                f"{self.pb_url}/api/collections/farms/records",
                params={"filter": "is_public_demo=true", "perPage": 1},
                headers=self._headers(token),
            )
            if resp.status_code != 200 or (resp.json().get("items") or []):
                return

            seed = _default_demo_seed(uid)
            id_map: dict[str, str] = {}
            for f in seed["farms"]:
                f_resp = await http.post(
                    f"{self.pb_url}/api/collections/farms/records",
                    json={
                        "name": f["name"],
                        "owner": uid,
                        "viewers": [],
                        "is_public_demo": True,
                        "constraints": f["constraints"],
                    },
                    headers=self._headers(token),
                )
                if f_resp.status_code in (200, 201):
                    id_map[f["id"]] = f_resp.json()["id"]

            for p in seed["user_plots"]:
                pb_farm_id = id_map.get(p["farm"])
                if not pb_farm_id:
                    continue
                await http.post(
                    f"{self.pb_url}/api/collections/user_plots/records",
                    json={
                        "farm": pb_farm_id,
                        "cadastral_ref": p["cadastral_ref"],
                        "label": p["label"],
                        "area_ha": p["area_ha"],
                        "centroid": p["centroid"],
                        "geometry": p["geometry"],
                        "baseline_rotation": p["baseline_rotation"],
                        "worldcover_class": p["worldcover_class"],
                        "worldcover_label": p["worldcover_label"],
                    },
                    headers=self._headers(token),
                )
        except Exception:
            pass
        finally:
            if close_after:
                await http.aclose()

    async def list_farms(self, user: dict[str, Any] | None) -> list[dict[str, Any]]:
        """List accessible farms (owned farms first, then shared/public demo farms)."""
        uid = (user or {}).get("user_id") or (user or {}).get("id")
        token = (user or {}).get("token")
        farms: list[dict[str, Any]] | None = None

        if self.pb_url and token:
            if user and user.get("role") == "farm_admin":
                await self.ensure_demo_farms_in_pb(user)
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.get(
                    f"{self.pb_url}/api/collections/farms/records",
                    params={"perPage": 100},
                    headers=self._headers(token),
                )
                if resp.status_code != 200:
                    logger.error("PocketBase list_farms failed (%s): %s", resp.status_code, resp.text)
                    raise PocketBaseError(
                        502 if resp.status_code >= 500 else resp.status_code,
                        f"PocketBase list_farms error ({resp.status_code}): {resp.text}",
                    )
                farms = resp.json().get("items") or []
            except PocketBaseError:
                raise
            except Exception as exc:
                logger.error("PocketBase list_farms unreachable: %s", exc)
                raise PocketBaseError(502, f"PocketBase unreachable: {exc}") from exc
            finally:
                if close_after:
                    await http.aclose()
        elif self.pb_url:
            raise PocketBaseError(401, "PocketBase requires an authenticated token to list farms")

        if farms is None:
            local = self._load_local()
            if user and user.get("email") == "marco@turinfarm.it" and uid:
                for f in local["farms"]:
                    if f.get("is_public_demo"):
                        f["owner"] = uid
                self._save_local(local)
            farms = [
                f
                for f in local["farms"]
                if f.get("is_public_demo") or f.get("owner") == uid or uid in (f.get("viewers") or [])
            ]

        return sorted(farms, key=lambda f: (0 if f.get("owner") == uid else 1, f.get("name") or ""))

    async def create_farm(
        self,
        name: str,
        user: dict[str, Any],
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = user.get("user_id") or user.get("id")
        token = user.get("token")
        payload = {
            "name": name.strip(),
            "owner": uid,
            "viewers": [],
            "is_public_demo": False,
            "constraints": constraints or {"irrigation": True, "no_till_drill": False},
        }

        if self.pb_url:
            if not token:
                raise PocketBaseError(401, "PocketBase requires an authenticated token to create a farm")
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.post(
                    f"{self.pb_url}/api/collections/farms/records",
                    json=payload,
                    headers=self._headers(token),
                )
                if resp.status_code in (200, 201):
                    return resp.json()
                logger.error("PocketBase create_farm failed (%s): %s", resp.status_code, resp.text)
                raise PocketBaseError(
                    502 if resp.status_code >= 500 else resp.status_code,
                    f"PocketBase create_farm error ({resp.status_code}): {resp.text}",
                )
            except PocketBaseError:
                raise
            except Exception as exc:
                logger.error("PocketBase create_farm unreachable: %s", exc)
                raise PocketBaseError(502, f"PocketBase unreachable: {exc}") from exc
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        rec = {"id": f"farm_{uuid.uuid4().hex[:10]}", **payload}
        local["farms"].append(rec)
        self._save_local(local)
        return rec

    async def list_plots(self, farm_id: str, user: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """List saved plots (`user_plots`) for a farm."""
        token = (user or {}).get("token")
        if self.pb_url:
            if not token:
                raise PocketBaseError(401, "PocketBase requires an authenticated token to list plots")
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.get(
                    f"{self.pb_url}/api/collections/user_plots/records",
                    params={"filter": f'farm="{farm_id}"', "perPage": 200},
                    headers=self._headers(token),
                )
                if resp.status_code == 200:
                    return resp.json().get("items") or []
                logger.error("PocketBase list_plots failed (%s): %s", resp.status_code, resp.text)
                raise PocketBaseError(
                    502 if resp.status_code >= 500 else resp.status_code,
                    f"PocketBase list_plots error ({resp.status_code}): {resp.text}",
                )
            except PocketBaseError:
                raise
            except Exception as exc:
                logger.error("PocketBase list_plots unreachable: %s", exc)
                raise PocketBaseError(502, f"PocketBase unreachable: {exc}") from exc
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        return [p for p in local["user_plots"] if p.get("farm") == farm_id]

    async def add_plot(
        self,
        farm_id: str,
        plot_data: dict[str, Any],
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a claimed plot (Catasto or custom drawn) into `user_plots`."""
        token = (user or {}).get("token")
        payload = {"farm": farm_id, **plot_data}

        if self.pb_url:
            if not token:
                raise PocketBaseError(401, "PocketBase requires an authenticated token to add plots")
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.post(
                    f"{self.pb_url}/api/collections/user_plots/records",
                    json=payload,
                    headers=self._headers(token),
                )
                if resp.status_code in (200, 201):
                    return resp.json()
                logger.error("PocketBase add_plot failed (%s): %s", resp.status_code, resp.text)
                raise PocketBaseError(
                    502 if resp.status_code >= 500 else resp.status_code,
                    f"PocketBase add_plot error ({resp.status_code}): {resp.text}",
                )
            except PocketBaseError:
                raise
            except Exception as exc:
                logger.error("PocketBase add_plot unreachable: %s", exc)
                raise PocketBaseError(502, f"PocketBase unreachable: {exc}") from exc
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        rec = {"id": f"plot_{uuid.uuid4().hex[:10]}", **payload}
        local["user_plots"].append(rec)
        self._save_local(local)
        return rec

    async def remove_plot(self, plot_id: str, user: dict[str, Any] | None = None) -> bool:
        """Delete a plot from `user_plots`."""
        token = (user or {}).get("token")
        if self.pb_url:
            if not token:
                raise PocketBaseError(401, "PocketBase requires an authenticated token to remove plots")
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.delete(
                    f"{self.pb_url}/api/collections/user_plots/records/{plot_id}",
                    headers=self._headers(token),
                )
                if resp.status_code in (200, 204):
                    return True
                if resp.status_code == 404:
                    return False
                logger.error("PocketBase remove_plot failed (%s): %s", resp.status_code, resp.text)
                raise PocketBaseError(
                    502 if resp.status_code >= 500 else resp.status_code,
                    f"PocketBase remove_plot error ({resp.status_code}): {resp.text}",
                )
            except PocketBaseError:
                raise
            except Exception as exc:
                logger.error("PocketBase remove_plot unreachable: %s", exc)
                raise PocketBaseError(502, f"PocketBase unreachable: {exc}") from exc
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        before = len(local["user_plots"])
        local["user_plots"] = [p for p in local["user_plots"] if p.get("id") != plot_id]
        self._save_local(local)
        return len(local["user_plots"]) < before

    async def update_plot(
        self,
        plot_id: str,
        patch: dict[str, Any],
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update fields (e.g. `nasa_snapshot`, `soil_override`, `active_plan`) on a plot."""
        token = (user or {}).get("token")
        if self.pb_url:
            if not token:
                raise PocketBaseError(401, "PocketBase requires an authenticated token to update plots")
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.patch(
                    f"{self.pb_url}/api/collections/user_plots/records/{plot_id}",
                    json=patch,
                    headers=self._headers(token),
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.error("PocketBase update_plot failed (%s): %s", resp.status_code, resp.text)
                raise PocketBaseError(
                    502 if resp.status_code >= 500 else resp.status_code,
                    f"PocketBase update_plot error ({resp.status_code}): {resp.text}",
                )
            except PocketBaseError:
                raise
            except Exception as exc:
                logger.error("PocketBase update_plot unreachable: %s", exc)
                raise PocketBaseError(502, f"PocketBase unreachable: {exc}") from exc
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        for idx, p in enumerate(local["user_plots"]):
            if p.get("id") == plot_id:
                updated = {**p, **patch}
                local["user_plots"][idx] = updated
                self._save_local(local)
                return updated
        return None

    async def get_plot_with_farm(
        self,
        plot_id: str,
        user: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Fetch a single plot and its parent farm (PocketBase first, local fallback second)."""
        token = (user or {}).get("token")
        if self.pb_url:
            if not token:
                raise PocketBaseError(401, "PocketBase requires an authenticated token to get plot")
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.get(
                    f"{self.pb_url}/api/collections/user_plots/records/{plot_id}",
                    params={"expand": "farm"},
                    headers=self._headers(token),
                )
                if resp.status_code == 404:
                    return None, None
                if resp.status_code != 200:
                    logger.error("PocketBase get_plot failed (%s): %s", resp.status_code, resp.text)
                    raise PocketBaseError(
                        502 if resp.status_code >= 500 else resp.status_code,
                        f"PocketBase get_plot error ({resp.status_code}): {resp.text}",
                    )
                plot_rec = resp.json()
                farm_rec = (plot_rec.get("expand") or {}).get("farm")
                if not farm_rec and plot_rec.get("farm"):
                    f_resp = await http.get(
                        f"{self.pb_url}/api/collections/farms/records/{plot_rec['farm']}",
                        headers=self._headers(token),
                    )
                    if f_resp.status_code == 200:
                        farm_rec = f_resp.json()
                return plot_rec, farm_rec
            except PocketBaseError:
                raise
            except Exception as exc:
                logger.error("PocketBase get_plot unreachable: %s", exc)
                raise PocketBaseError(502, f"PocketBase unreachable: {exc}") from exc
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        plot_rec = next((p for p in local["user_plots"] if p.get("id") == plot_id), None)
        if not plot_rec:
            return None, None
        farm_rec = next((f for f in local["farms"] if f.get("id") == plot_rec.get("farm")), None)
        return plot_rec, farm_rec
