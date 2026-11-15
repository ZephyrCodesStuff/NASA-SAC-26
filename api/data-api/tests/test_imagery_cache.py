from app import imagery

WKT = "POLYGON ((7.70 44.86, 7.71 44.86, 7.71 44.87, 7.70 44.87, 7.70 44.86))"


def test_failed_group_is_retried_not_cached(monkeypatch):
    calls = {"hls": 0, "dem": 0}

    def hls(geometry, on):
        calls["hls"] += 1
        if calls["hls"] == 1:
            raise OSError("not recognized as being in a supported file format")  # e.g. Earthdata login page
        return {"status": "ok", "layers": {}}

    def dem(geometry, on):
        calls["dem"] += 1
        return {"status": "ok", "layers": {}}

    monkeypatch.setitem(imagery._GROUP_FNS, "hls", hls)
    monkeypatch.setitem(imagery._GROUP_FNS, "dem", dem)
    version = -12345  # cache key no other test uses

    first = imagery.render(WKT, None, ("hls", "dem"), version)
    assert first["groups"]["hls"]["status"] == "error"
    assert first["groups"]["dem"]["status"] == "ok"  # one failing group doesn't hide the others

    second = imagery.render(WKT, None, ("hls", "dem"), version)
    assert second["groups"]["hls"]["status"] == "ok"  # retried, not served from cache
    assert calls == {"hls": 2, "dem": 1}  # the good group was cached
