"""IoT device claim/unclaim and X-NASA-Board-SN telemetry store (PocketBase + local JSON fallback)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DeviceConflictError(Exception):
    """Raised when attempting to claim a serial number already assigned to another plot."""


class DeviceStore:
    """Persist claimed devices (1 plot at a time) and ingested 3-float sensor readings."""

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

    async def ingest_reading(
        self,
        *,
        serial_number: str,
        soil_moisture: float,
        humidity: float,
        temperature: float,
    ) -> dict[str, Any]:
        """Store a 3-float reading from a board identified only by `X-NASA-Board-SN`."""
        clean_sn = serial_number.strip()
        now = _utc_iso()
        reading_payload: dict[str, Any] = {
            "device_id": clean_sn,
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
                    params={"filter": f'device_id="{clean_sn}"', "perPage": 1},
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
        dev = local["devices"].get(clean_sn)
        if dev:
            reading_payload["farm_id"] = dev.get("farm_id", "")
            reading_payload["plot_id"] = dev.get("plot_id", "")
            dev["last_seen"] = now
            dev["latest_reading"] = reading_payload
        local["readings"].append(reading_payload)
        local["readings"] = local["readings"][-1000:]
        self._save_local(local)
        return reading_payload

    async def claim_device(
        self,
        *,
        serial_number: str,
        farm_id: str,
        plot_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Claim a device S/N onto `(farm_id, plot_id)`. Rejects if already assigned to another plot."""
        clean_sn = serial_number.strip()
        now = _utc_iso()

        if self.pb_url:
            close_after = self._client is None
            http = await self._http()
            try:
                existing = await http.get(
                    f"{self.pb_url}/api/collections/devices/records",
                    params={"filter": f'device_id="{clean_sn}"', "perPage": 1},
                )
                rd_resp = await http.get(
                    f"{self.pb_url}/api/collections/device_readings/records",
                    params={"filter": f'device_id="{clean_sn}"', "sort": "-ts", "perPage": 1},
                )
                latest = None
                if rd_resp.status_code == 200:
                    rd_items = rd_resp.json().get("items") or []
                    if rd_items:
                        latest = rd_items[0]

                if existing.status_code == 200:
                    items = existing.json().get("items") or []
                    if items:
                        cur = items[0]
                        cur_plot = str(cur.get("plot_id") or "")
                        if cur_plot and cur_plot != plot_id:
                            raise DeviceConflictError(
                                f"Device {clean_sn} is already assigned to another plot. Remove it there first."
                            )
                        upd_payload: dict[str, Any] = {
                            "farm_id": farm_id,
                            "plot_id": plot_id,
                            "name": (name or cur.get("name") or clean_sn).strip(),
                        }
                        if latest:
                            upd_payload["latest_reading"] = latest
                            upd_payload["last_seen"] = latest.get("ts") or now
                        upd = await http.patch(
                            f"{self.pb_url}/api/collections/devices/records/{cur['id']}",
                            json=upd_payload,
                        )
                        if upd.status_code == 200:
                            return upd.json()
                    else:
                        create_payload: dict[str, Any] = {
                            "device_id": clean_sn,
                            "farm_id": farm_id,
                            "plot_id": plot_id,
                            "name": (name or clean_sn).strip(),
                            "last_seen": latest.get("ts") if latest else now,
                            "latest_reading": latest,
                        }
                        crt = await http.post(
                            f"{self.pb_url}/api/collections/devices/records",
                            json=create_payload,
                        )
                        if crt.status_code in (200, 201):
                            return crt.json()
            except DeviceConflictError:
                raise
            except Exception:
                pass
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        cur = local["devices"].get(clean_sn)
        if cur and cur.get("plot_id") and cur.get("plot_id") != plot_id:
            raise DeviceConflictError(
                f"Device {clean_sn} is already assigned to another plot. Remove it there first."
            )
        matching_readings = [r for r in local["readings"] if r.get("device_id") == clean_sn]
        latest = matching_readings[-1] if matching_readings else None
        record = {
            "device_id": clean_sn,
            "farm_id": farm_id,
            "plot_id": plot_id,
            "name": (name or (cur or {}).get("name") or clean_sn).strip(),
            "last_seen": latest.get("ts") if latest else now,
            "latest_reading": latest,
        }
        local["devices"][clean_sn] = record
        self._save_local(local)
        return record

    async def unclaim_device(self, *, serial_number: str, plot_id: str) -> bool:
        """Remove a device from `plot_id` so its S/N can be claimed on another plot."""
        clean_sn = serial_number.strip()
        if self.pb_url:
            close_after = self._client is None
            http = await self._http()
            try:
                existing = await http.get(
                    f"{self.pb_url}/api/collections/devices/records",
                    params={"filter": f'device_id="{clean_sn}" && plot_id="{plot_id}"', "perPage": 1},
                )
                if existing.status_code == 200:
                    items = existing.json().get("items") or []
                    if not items:
                        return False
                    del_resp = await http.delete(
                        f"{self.pb_url}/api/collections/devices/records/{items[0]['id']}"
                    )
                    return del_resp.status_code in (200, 204)
            except Exception:
                pass
            finally:
                if close_after:
                    await http.aclose()

        local = self._load_local()
        cur = local["devices"].get(clean_sn)
        if not cur or cur.get("plot_id") != plot_id:
            return False
        del local["devices"][clean_sn]
        self._save_local(local)
        return True

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
        self, serial_number: str, limit: int = 60
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        clean_sn = serial_number.strip()
        if self.pb_url:
            close_after = self._client is None
            http = await self._http()
            try:
                dev_resp = await http.get(
                    f"{self.pb_url}/api/collections/devices/records",
                    params={"filter": f'device_id="{clean_sn}"', "perPage": 1},
                )
                rd_resp = await http.get(
                    f"{self.pb_url}/api/collections/device_readings/records",
                    params={
                        "filter": f'device_id="{clean_sn}"',
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
        dev = local["devices"].get(clean_sn)
        readings = [r for r in local["readings"] if r.get("device_id") == clean_sn][-limit:]
        return dev, readings
