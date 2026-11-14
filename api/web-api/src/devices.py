"""IoT device registration and 3-float telemetry store (PocketBase + local JSON fallback)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DeviceStore:
    """Persist IoT devices and their 3-float sensor readings (`soil_moisture`, `humidity`, `temperature`)."""

    def __init__(
        self,
        pb_url: str | None = None,
        local_path: str | Path | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.pb_url = (pb_url or os.getenv("PB_URL", "http://127.0.0.1:8090")).rstrip("/")
        default_local = Path(__file__).resolve().parent.parent / "pb_data" / "devices_fallback.json"
        self.local_path = Path(local_path) if local_path else default_local
        self._client = http_client

    async def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=8.0)

    def _load_local(self) -> dict[str, Any]:
        if not self.local_path.exists():
            return {"devices": {}, "readings": []}
        try:
            data = json.loads(self.local_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("devices", {})
                data.setdefault("readings", [])
                return data
        except Exception:
            pass
        return {"devices": {}, "readings": []}

    def _save_local(self, data: dict[str, Any]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def register_device(
        self,
        *,
        device_id: str,
        farm_id: str,
        plot_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        clean_id = device_id.strip()
        now = _utc_iso()
        payload: dict[str, Any] = {
            "device_id": clean_id,
            "farm_id": farm_id,
            "plot_id": plot_id,
            "name": (name or clean_id).strip(),
            "last_seen": now,
        }

        if self.pb_url:
            close_after = self._client is None
            http = await self._http()
            try:
                existing = await http.get(
                    f"{self.pb_url}/api/collections/devices/records",
                    params={"filter": f'device_id="{clean_id}"', "perPage": 1},
                )
                if existing.status_code == 200:
                    items = existing.json().get("items") or []
                    if items:
                        pb_id = items[0]["id"]
                        upd = await http.patch(
                            f"{self.pb_url}/api/collections/devices/records/{pb_id}",
                            json=payload,
                        )
                        if upd.status_code == 200:
                            return upd.json()
                    else:
                        crt = await http.post(
                            f"{self.pb_url}/api/collections/devices/records",
                            json=payload,
                        )
                        if crt.status_code in (200, 201):
                            return crt.json()
            except Exception:
                pass
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        prev = local["devices"].get(clean_id, {})
        record = {**prev, **payload}
        local["devices"][clean_id] = record
        self._save_local(local)
        return record

    async def record_reading(
        self,
        *,
        device_id: str,
        soil_moisture: float,
        humidity: float,
        temperature: float,
    ) -> dict[str, Any]:
        clean_id = device_id.strip()
        now = _utc_iso()
        reading_payload: dict[str, Any] = {
            "device_id": clean_id,
            "ts": now,
            "soil_moisture": round(float(soil_moisture), 2),
            "humidity": round(float(humidity), 2),
            "temperature": round(float(temperature), 2),
        }

        if self.pb_url:
            close_after = self._client is None
            http = await self._http()
            try:
                dev_resp = await http.get(
                    f"{self.pb_url}/api/collections/devices/records",
                    params={"filter": f'device_id="{clean_id}"', "perPage": 1},
                )
                if dev_resp.status_code == 200:
                    items = dev_resp.json().get("items") or []
                    if items:
                        dev = items[0]
                        reading_payload["farm_id"] = dev.get("farm_id", "")
                        reading_payload["plot_id"] = dev.get("plot_id", "")
                        await http.patch(
                            f"{self.pb_url}/api/collections/devices/records/{dev['id']}",
                            json={"last_seen": now, "latest_reading": reading_payload},
                        )
                    crt = await http.post(
                        f"{self.pb_url}/api/collections/device_readings/records",
                        json=reading_payload,
                    )
                    if crt.status_code in (200, 201):
                        return crt.json()
            except Exception:
                pass
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        dev = local["devices"].get(clean_id)
        if dev:
            reading_payload["farm_id"] = dev.get("farm_id", "")
            reading_payload["plot_id"] = dev.get("plot_id", "")
            dev["last_seen"] = now
            dev["latest_reading"] = reading_payload
        local["readings"].append(reading_payload)
        local["readings"] = local["readings"][-500:]
        self._save_local(local)
        return reading_payload

    async def list_plot_devices(self, plot_id: str) -> list[dict[str, Any]]:
        if self.pb_url:
            close_after = self._client is None
            http = await self._http()
            try:
                resp = await http.get(
                    f"{self.pb_url}/api/collections/devices/records",
                    params={"filter": f'plot_id="{plot_id}"', "perPage": 100},
                )
                if resp.status_code == 200:
                    return resp.json().get("items") or []
            except Exception:
                pass
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        return [d for d in local["devices"].values() if d.get("plot_id") == plot_id]

    async def get_device_readings(
        self, device_id: str, limit: int = 60
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        clean_id = device_id.strip()
        if self.pb_url:
            close_after = self._client is None
            http = await self._http()
            try:
                dev_resp = await http.get(
                    f"{self.pb_url}/api/collections/devices/records",
                    params={"filter": f'device_id="{clean_id}"', "perPage": 1},
                )
                rd_resp = await http.get(
                    f"{self.pb_url}/api/collections/device_readings/records",
                    params={
                        "filter": f'device_id="{clean_id}"',
                        "sort": "-ts",
                        "perPage": max(1, min(limit, 200)),
                    },
                )
                if dev_resp.status_code == 200 and rd_resp.status_code == 200:
                    devs = dev_resp.json().get("items") or []
                    readings = list(reversed(rd_resp.json().get("items") or []))
                    return (devs[0] if devs else None, readings)
            except Exception:
                pass
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        dev = local["devices"].get(clean_id)
        readings = [r for r in local["readings"] if r.get("device_id") == clean_id][-limit:]
        return dev, readings
