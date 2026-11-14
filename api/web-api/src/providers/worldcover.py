"""ESA WorldCover 2021 (10m) land-cover provider via direct S3 COG HTTP Range requests.

Reads Cloud-Optimized GeoTIFF (COG) tiles directly from the public AWS S3 bucket
(`s3://esa-worldcover/v200/2021/map/`) using `httpx` HTTP `Range` requests and
Python's standard-library `struct` + `zlib` — no GDAL or rasterio required.

Each 3°×3° tile is 36,000×36,000 uint8 pixels (~10 m resolution) tiled into
1024×1024 DEFLATE-compressed blocks. Fetching a single block (~20-90 KB) covers
~9.5 km × 6.7 km at Turin's latitude (45°N), classifying hundreds of cadastral
parcels in microseconds once cached.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import httpx

from src.providers.catasto import _feature_bbox, point_in_geojson_geometry

WORLDCOVER_S3_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
WORLDCOVER_ATTRIBUTION = "ESA WorldCover 2021 (10m, CC BY 4.0)"

WORLDCOVER_CLASSES: dict[int, str] = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

FARMLAND_CLASS_IDS: frozenset[int] = frozenset({30, 40})  # Grassland & Cropland
DEFAULT_CACHE_DIR = Path(
    os.getenv("WORLDCOVER_CACHE_DIR", str(Path(__file__).resolve().parents[3] / ".cache" / "worldcover"))
)

# TIFF tag IDs used in WorldCover COGs
_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_TILE_WIDTH = 322
_TAG_TILE_LENGTH = 323
_TAG_TILE_OFFSETS = 324
_TAG_TILE_BYTE_COUNTS = 325
_TAG_MODEL_PIXEL_SCALE = 33550
_TAG_MODEL_TIEPOINT = 33922

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 12: 8}
_TYPE_FORMATS = {1: "B", 3: "H", 4: "I", 12: "d"}


@dataclass(frozen=True, slots=True)
class CogHeader:
    """Parsed GeoTIFF IFD metadata for a 3°×3° ESA WorldCover COG."""

    tile_id: str
    width: int
    height: int
    tile_width: int
    tile_height: int
    origin_lon: float
    origin_lat: float
    scale_lon: float
    scale_lat: float
    tile_offsets: list[int]
    tile_byte_counts: list[int]

    @property
    def tiles_per_row(self) -> int:
        return (self.width + self.tile_width - 1) // self.tile_width


_HEADER_CACHE: dict[str, CogHeader] = {}
_TILE_CACHE: dict[tuple[str, int], bytes] = {}
_HEADER_LOCKS: dict[str, asyncio.Lock] = {}
_TILE_LOCKS: dict[tuple[str, int], asyncio.Lock] = {}


def worldcover_tile_id(lat: float, lon: float) -> str:
    """Return the 3°×3° ESA WorldCover tile ID (e.g. 'N45E006') for (lat, lon)."""
    lat_base = math.floor(lat / 3.0) * 3
    lon_base = math.floor(lon / 3.0) * 3
    ns = "N" if lat_base >= 0 else "S"
    ew = "E" if lon_base >= 0 else "W"
    return f"{ns}{abs(lat_base):02d}{ew}{abs(lon_base):03d}"


def worldcover_cog_url(tile_id: str) -> str:
    """Return the public HTTPS S3 URL for an ESA WorldCover 2021 10m Map COG."""
    return f"{WORLDCOVER_S3_BASE}/ESA_WorldCover_10m_2021_v200_{tile_id}_Map.tif"


def parse_cog_header(data: bytes, tile_id: str) -> CogHeader:
    """Parse GeoTIFF IFD0 tags and tile index arrays from the first 32+ KB of a COG."""
    if len(data) < 8:
        raise ValueError("COG header too short")
    endian = "<" if data[:2] == b"II" else ">" if data[:2] == b"MM" else ""
    if not endian:
        raise ValueError("Invalid TIFF byte order marker")

    version, ifd_offset = struct.unpack(endian + "HI", data[2:8])
    if version != 42:
        raise ValueError(f"Unsupported TIFF version: {version}")

    num_entries = struct.unpack(endian + "H", data[ifd_offset : ifd_offset + 2])[0]
    tags: dict[int, tuple[int, int, int, bytes]] = {}
    for i in range(num_entries):
        off = ifd_offset + 2 + i * 12
        tag, typ, count, raw_val_or_off = struct.unpack(endian + "HHII", data[off : off + 12])
        tags[tag] = (typ, count, raw_val_or_off, data[off + 8 : off + 12])

    def _read_values(tag_id: int) -> list[Any]:
        typ, count, offset_or_val, inline_bytes = tags[tag_id]
        fmt_char = _TYPE_FORMATS[typ]
        elem_size = _TYPE_SIZES[typ]
        total_bytes = count * elem_size
        if total_bytes <= 4:
            buf = inline_bytes[:total_bytes]
        else:
            buf = data[offset_or_val : offset_or_val + total_bytes]
        return list(struct.unpack(endian + f"{count}{fmt_char}", buf))

    width = int(_read_values(_TAG_IMAGE_WIDTH)[0])
    height = int(_read_values(_TAG_IMAGE_LENGTH)[0])
    tile_width = int(_read_values(_TAG_TILE_WIDTH)[0])
    tile_height = int(_read_values(_TAG_TILE_LENGTH)[0])
    scale = _read_values(_TAG_MODEL_PIXEL_SCALE)
    tiepoint = _read_values(_TAG_MODEL_TIEPOINT)
    tile_offsets = [int(v) for v in _read_values(_TAG_TILE_OFFSETS)]
    tile_byte_counts = [int(v) for v in _read_values(_TAG_TILE_BYTE_COUNTS)]

    return CogHeader(
        tile_id=tile_id,
        width=width,
        height=height,
        tile_width=tile_width,
        tile_height=tile_height,
        origin_lon=float(tiepoint[3]),
        origin_lat=float(tiepoint[4]),
        scale_lon=float(scale[0]),
        scale_lat=float(scale[1]),
        tile_offsets=tile_offsets,
        tile_byte_counts=tile_byte_counts,
    )


def _sample_points_for_feature(feature: dict[str, Any], max_grid: int = 3) -> list[tuple[float, float]]:
    """Return interior (lat, lon) sample points inside a parcel polygon."""
    geom = feature.get("geometry")
    if not geom:
        return []

    points: list[tuple[float, float]] = []
    props = feature.get("properties") or {}
    centroid = props.get("centroid")
    if centroid and len(centroid) == 2:
        clat, clon = float(centroid[0]), float(centroid[1])
        if point_in_geojson_geometry(clat, clon, geom):
            points.append((clat, clon))

    bbox = _feature_bbox(geom)
    if bbox is not None:
        min_lat, min_lon, max_lat, max_lon = bbox
        for r in range(1, max_grid + 1):
            for c in range(1, max_grid + 1):
                lat = min_lat + (max_lat - min_lat) * (r / (max_grid + 1))
                lon = min_lon + (max_lon - min_lon) * (c / (max_grid + 1))
                if point_in_geojson_geometry(lat, lon, geom):
                    points.append((lat, lon))

    if not points and centroid and len(centroid) == 2:
        points.append((float(centroid[0]), float(centroid[1])))
    return points


class WorldCoverClient:
    """Async ESA WorldCover 2021 10m pixel sampler backed by S3 COG Range requests."""

    def __init__(
        self,
        cache_dir: Path | str | None = DEFAULT_CACHE_DIR,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = timeout
        self._external_client = client
        self._client: httpx.AsyncClient | None = client

    async def __aenter__(self) -> WorldCoverClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _get_header(self, tile_id: str) -> CogHeader:
        if tile_id in _HEADER_CACHE:
            return _HEADER_CACHE[tile_id]

        lock = _HEADER_LOCKS.setdefault(tile_id, asyncio.Lock())
        async with lock:
            if tile_id in _HEADER_CACHE:
                return _HEADER_CACHE[tile_id]

            if self.cache_dir is not None:
                hdr_path = self.cache_dir / f"{tile_id}_header.json"
                if hdr_path.exists():
                    try:
                        raw = json.loads(hdr_path.read_text(encoding="utf-8"))
                        hdr = CogHeader(**raw)
                        _HEADER_CACHE[tile_id] = hdr
                        return hdr
                    except Exception:
                        pass

            http = await self._http()
            url = worldcover_cog_url(tile_id)
            resp = await http.get(url, headers={"Range": "bytes=0-32767"})
            resp.raise_for_status()
            hdr = parse_cog_header(resp.content, tile_id)
            _HEADER_CACHE[tile_id] = hdr

            if self.cache_dir is not None:
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    (self.cache_dir / f"{tile_id}_header.json").write_text(
                        json.dumps(
                            {
                                "tile_id": hdr.tile_id,
                                "width": hdr.width,
                                "height": hdr.height,
                                "tile_width": hdr.tile_width,
                                "tile_height": hdr.tile_height,
                                "origin_lon": hdr.origin_lon,
                                "origin_lat": hdr.origin_lat,
                                "scale_lon": hdr.scale_lon,
                                "scale_lat": hdr.scale_lat,
                                "tile_offsets": hdr.tile_offsets,
                                "tile_byte_counts": hdr.tile_byte_counts,
                            }
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
            return hdr

    async def _get_tile_bytes(self, hdr: CogHeader, tile_idx: int) -> bytes:
        key = (hdr.tile_id, tile_idx)
        if key in _TILE_CACHE:
            return _TILE_CACHE[key]

        lock = _TILE_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            if key in _TILE_CACHE:
                return _TILE_CACHE[key]

            if self.cache_dir is not None:
                tile_path = self.cache_dir / f"{hdr.tile_id}_t{tile_idx}.bin"
                if tile_path.exists():
                    raw = tile_path.read_bytes()
                    _TILE_CACHE[key] = raw
                    return raw

            off = hdr.tile_offsets[tile_idx]
            cnt = hdr.tile_byte_counts[tile_idx]
            if cnt == 0:
                raw = bytes(hdr.tile_width * hdr.tile_height)
                _TILE_CACHE[key] = raw
                return raw

            http = await self._http()
            url = worldcover_cog_url(hdr.tile_id)
            resp = await http.get(url, headers={"Range": f"bytes={off}-{off + cnt - 1}"})
            resp.raise_for_status()
            raw = zlib.decompress(resp.content)
            _TILE_CACHE[key] = raw

            if self.cache_dir is not None:
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    (self.cache_dir / f"{hdr.tile_id}_t{tile_idx}.bin").write_bytes(raw)
                except Exception:
                    pass
            return raw

    async def sample_point(self, lat: float, lon: float) -> int:
        """Return the ESA WorldCover 2021 class ID (e.g. 40=Cropland, 50=Built-up) at (lat, lon)."""
        tile_id = worldcover_tile_id(lat, lon)
        hdr = await self._get_header(tile_id)
        px = max(0, min(hdr.width - 1, int((lon - hdr.origin_lon) / hdr.scale_lon)))
        py = max(0, min(hdr.height - 1, int((hdr.origin_lat - lat) / hdr.scale_lat)))
        tc = px // hdr.tile_width
        tr = py // hdr.tile_height
        tile_idx = tr * hdr.tiles_per_row + tc
        raw = await self._get_tile_bytes(hdr, tile_idx)
        local_x = px % hdr.tile_width
        local_y = py % hdr.tile_height
        return raw[local_y * hdr.tile_width + local_x]

    async def classify_parcel(self, feature: dict[str, Any]) -> dict[str, Any]:
        """Sample WorldCover pixels inside a parcel and attach land-cover & farmland flags."""
        props = feature.setdefault("properties", {})
        if "worldcover_class" in props and "is_farmland" in props:
            return feature

        points = _sample_points_for_feature(feature)
        if not points:
            props.update(
                {
                    "worldcover_class": None,
                    "worldcover_label": "Unknown",
                    "is_farmland": False,
                    "farmland_ratio": 0.0,
                }
            )
            return feature

        samples: list[int] = []
        for lat, lon in points:
            val = await self.sample_point(lat, lon)
            if val > 0:
                samples.append(val)

        if not samples:
            props.update(
                {
                    "worldcover_class": None,
                    "worldcover_label": "No data",
                    "is_farmland": False,
                    "farmland_ratio": 0.0,
                }
            )
            return feature

        counts: dict[int, int] = {}
        for s in samples:
            counts[s] = counts.get(s, 0) + 1
        majority_cls = max(counts, key=lambda k: counts[k])
        farmland_hits = sum(1 for s in samples if s in FARMLAND_CLASS_IDS)
        farmland_ratio = round(farmland_hits / len(samples), 2)

        props.update(
            {
                "worldcover_class": majority_cls,
                "worldcover_label": WORLDCOVER_CLASSES.get(majority_cls, f"Class {majority_cls}"),
                "is_farmland": majority_cls in FARMLAND_CLASS_IDS or farmland_ratio >= 0.5,
                "farmland_ratio": farmland_ratio,
            }
        )
        return feature

    async def classify_parcels(self, features: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Classify a batch of parcel GeoJSON features concurrently (reusing cached COG blocks)."""
        unclassified = [
            f for f in features
            if "worldcover_class" not in (f.get("properties") or {})
        ]
        if unclassified:
            # Prime unique COG headers/blocks first, then sample all parcels
            await asyncio.gather(*(self.classify_parcel(f) for f in unclassified))
        return list(features)
