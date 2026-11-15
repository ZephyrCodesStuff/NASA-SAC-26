#!/usr/bin/env python3
"""Seed realistic ESP32 IoT sensor telemetry calibrated to Cascina Bricco 01 (44.8590°N, 7.6976°E).

Usage:
  python3 scripts/seed_iot_bricco.py --base-url https://your-ceres-domain.com/api
  python3 scripts/seed_iot_bricco.py --base-url http://127.0.0.1:8081 --sn CERES-BRICCO-01
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

# Calibrated to Cascina Bricco 01 (mid-November Po Valley, Loam topsoil, 236m,
# 28 mm rain over last 7 days, 1 dry day, SMAP 38% wetness drying, 6.7°C / 92% RH).
READINGS = [
    {"soil_moisture": 23.8, "humidity": 95.2, "temperature": 4.8},
    {"soil_moisture": 23.2, "humidity": 93.8, "temperature": 5.4},
    {"soil_moisture": 22.7, "humidity": 90.5, "temperature": 6.3},
    {"soil_moisture": 22.1, "humidity": 86.4, "temperature": 7.5},
    {"soil_moisture": 21.6, "humidity": 88.1, "temperature": 8.1},
    {"soil_moisture": 21.2, "humidity": 91.8, "temperature": 6.9},
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed realistic IoT readings for Cascina Bricco 01")
    parser.add_argument("--base-url", default="http://127.0.0.1:8081", help="web-api base URL (e.g. http://127.0.0.1:8081 or https://host/api)")
    parser.add_argument("--sn", default="CERES-BRICCO-01", help="ESP32 board serial number (X-NASA-Board-SN)")
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/devices/ingest"
    print(f"Seeding {len(READINGS)} readings for {args.sn} -> {url}")

    for idx, r in enumerate(READINGS, 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(r).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-NASA-Board-SN": args.sn,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                print(f"  [{idx}/{len(READINGS)}] {resp.status} -> {r} | {body[:120]}")
        except urllib.error.HTTPError as exc:
            print(f"  [{idx}/{len(READINGS)}] HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
            raise SystemExit(1)
        time.sleep(0.25)

    print(f"\nDone! Now claim serial '{args.sn}' inside Cascina Bricco 01's IoT sensor panel.")


if __name__ == "__main__":
    main()
