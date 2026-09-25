"""The public link is closed without the access key and open with it."""
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_gate(monkeypatch):
    monkeypatch.setattr(settings, "DIVAN_ACCESS_KEY", "sirr")
    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert c.get("/demo").status_code == 401
    r = c.get("/demo?k=sirr")
    assert r.status_code == 200 and "divan_k" in r.headers.get("set-cookie", "")
    c.cookies.set("divan_k", "sirr")
    assert c.get("/demo").status_code == 200
    assert TestClient(app).get("/demo", headers={"X-Divan-Key": "sirr"}).status_code == 200
    c.cookies.set("divan_k", "yanlis")
    assert c.get("/demo").status_code == 401


def test_no_key_no_gate(monkeypatch):
    monkeypatch.setattr(settings, "DIVAN_ACCESS_KEY", "")
    assert TestClient(app).get("/demo").status_code == 200
