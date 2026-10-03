from fastapi.testclient import TestClient

from app.main import app


def test_health():
    # No `with`: entering the client runs lifespan, which migrates + seeds the
    # real database.
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
