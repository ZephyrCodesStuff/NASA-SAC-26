"""API tests with the data sources stubbed out (no network)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

SAMPLE = (Path(__file__).parent / "fixtures" / "catasto_modena.xml").read_bytes()


class _Ok:
    @staticmethod
    def fetch(parcel, q):
        return {"status": "ok", "values": {"lat": parcel.centroid[0], "history": q.history}}


class _Boom:
    @staticmethod
    def fetch(parcel, q):
        raise RuntimeError("ClientResponseError 403 Forbidden url=https://data.gesdisc.earthdata.nasa.gov/x")


@pytest.fixture
def client(monkeypatch):
    from app import core

    core._mem.clear()  # results are cached per (source, shape, query); keep tests independent
    sources = {n: (_Ok, t, d) for n, (_, t, d) in main.SOURCES.items()}
    sources["rainfall"] = (_Boom, 5, "boom")
    monkeypatch.setattr(main, "SOURCES", sources)
    with TestClient(main.app) as c:
        yield c


def test_parcel_returns_every_dataset_per_parcel(client):
    r = client.post("/parcel", content=SAMPLE, headers={"Content-Type": "application/xml"})
    assert r.status_code == 200
    body = r.json()
    assert [p["parcel"]["id"] for p in body["parcels"]] == ["F257_025400.121", "F257_025400.124"]
    ds = body["parcels"][0]["datasets"]
    assert set(main.SOURCES) <= set(ds) and "crop_type" in ds
    assert ds["weather"]["status"] == "ok"


def test_failing_source_does_not_break_response_and_gesdisc_hint(client):
    ds = client.post("/parcel", content=SAMPLE).json()["parcels"][0]["datasets"]
    assert ds["rainfall"]["status"] == "unavailable"
    assert "GESDISC" in ds["rainfall"]["note"]


def test_dataset_filter_and_history_flag(client):
    body = client.post("/parcel?datasets=weather,soil&history=true", content=SAMPLE).json()
    ds = body["parcels"][0]["datasets"]
    assert set(ds) == {"weather", "soil"}
    assert ds["weather"]["values"]["history"] is True
    assert body["query"]["window"] is not None


def test_bad_inputs(client):
    assert client.post("/parcel", content=b"").status_code == 400
    assert client.post("/parcel", content=b"<x/>").status_code == 422
    assert client.post("/parcel?datasets=nope", content=SAMPLE).status_code == 422
    assert client.get("/point?lat=100&lon=0").status_code == 422


def test_point(client):
    r = client.get("/point?lat=44.6&lon=11.0&datasets=weather")
    assert r.status_code == 200
    assert abs(r.json()["parcels"][0]["datasets"]["weather"]["values"]["lat"] - 44.6) < 1e-6


def test_geojson_endpoint(client):
    poly = {"type": "Polygon", "coordinates": [[[11.0, 44.6], [11.001, 44.6], [11.001, 44.601], [11.0, 44.601], [11.0, 44.6]]]}
    r = client.post("/geojson?datasets=weather", json={"type": "Feature", "id": "f1", "geometry": poly, "properties": {}})
    assert r.status_code == 200
    assert r.json()["parcels"][0]["parcel"]["id"] == "f1"
    assert client.post("/geojson", content=b"nope").status_code == 400
    assert client.post("/geojson", json={"type": "Point", "coordinates": [0, 0]}).status_code == 422
