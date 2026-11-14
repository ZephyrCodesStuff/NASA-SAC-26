import math

from app.core import clean


def test_clean_drops_fill_values_and_nan():
    assert clean(-999.0) is None
    assert clean(-9999) is None
    assert clean(math.nan) is None
    assert clean(None) is None
    assert clean(-12.345678, 2) == -12.35
    assert clean(0) == 0


def test_ttl_cache_single_flight():
    import threading
    import time

    from app.core import ttl_cache

    calls = []

    @ttl_cache(60)
    def slow(x):
        calls.append(x)
        time.sleep(0.2)
        return x * 2

    out = []
    ts = [threading.Thread(target=lambda: out.append(slow(3))) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == [6] * 5 and calls == [3]


def test_stac_search_uses_bbox_not_full_polygon(monkeypatch):
    from app import core

    sent = []

    class R:
        def __init__(self, data):
            self._d = data

        def raise_for_status(self):
            return self

        def json(self):
            return self._d

    pages = [{"features": [{"properties": {"datetime": "2026-01-02"}}],
              "links": [{"rel": "next", "href": "https://cmr.example/next?page=2", "method": "GET"}]},
             {"features": [{"properties": {"datetime": "2026-01-01"}}], "links": []}]

    monkeypatch.setattr(core._http, "post", lambda url, json: sent.append(("POST", json)) or R(pages[0]))
    monkeypatch.setattr(core._http, "get", lambda url: sent.append(("GET", url)) or R(pages[1]))
    ring = [[11 + i * 1e-5, 44.6 + (i % 2) * 1e-5] for i in range(500)] + [[11, 44.6]]
    out = core.stac_search(["X"], {"type": "Polygon", "coordinates": [ring]}, core.date(2026, 1, 1), core.date(2026, 1, 3))
    assert [f["properties"]["datetime"] for f in out] == ["2026-01-01", "2026-01-02"]
    assert "intersects" not in sent[0][1] and len(sent[0][1]["bbox"]) == 4
    assert sent[1] == ("GET", "https://cmr.example/next?page=2")


def test_ttl_cache_survives_restart(tmp_path, monkeypatch):
    """Values written to the disk layer are found again after the in-memory layer is gone."""
    from app import core

    monkeypatch.setattr(core, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(core, "_db", None)
    monkeypatch.setattr(core, "DISK_CACHE", True)
    calls = []

    @core.ttl_cache(60)
    def fetch(x):
        calls.append(x)
        return {("clay", "0-5cm"): {"mean": x}}  # tuple keys: needs pickle, not JSON

    assert fetch(7) == {("clay", "0-5cm"): {"mean": 7}}
    core._mem.clear()  # simulate a container restart
    monkeypatch.setattr(core, "_db", None)
    assert fetch(7) == {("clay", "0-5cm"): {"mean": 7}}
    assert calls == [7]


def test_ttl_cache_does_not_cache_errors(tmp_path, monkeypatch):
    import pytest

    from app import core

    monkeypatch.setattr(core, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(core, "_db", None)
    n = []

    @core.ttl_cache(60)
    def flaky():
        n.append(1)
        if len(n) == 1:
            raise RuntimeError("503")
        return "ok"

    with pytest.raises(RuntimeError):
        flaky()
    assert flaky() == "ok"
