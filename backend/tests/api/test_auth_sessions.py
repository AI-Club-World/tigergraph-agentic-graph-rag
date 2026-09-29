"""Sign-in sessions and roles: no secret in the browser bundle (TECHNICAL-SPEC §4.5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.api import security
from ogr.api.security import get_config
from ogr.common.config import RunConfig


@pytest.fixture
def client_for():
    clients = []

    def make(**keys):
        api_main.app.dependency_overrides[get_config] = lambda: RunConfig(**keys)
        c = TestClient(api_main.app)
        clients.append(c)
        return c

    yield make
    api_main.app.dependency_overrides.clear()


def _sign_in(client, key):
    return client.post("/auth/session", json={"key": key})


def test_a_key_exchanges_for_a_session_token_that_authorises_requests(client_for):
    client = client_for(ogr_api_key="viewer-key")
    r = _sign_in(client, "viewer-key")
    assert r.status_code == 200 and r.json()["role"] == "admin"  # no admin key set: full rights
    bearer = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/auth/session", headers=bearer).json() == {"role": "admin"}
    assert client.get("/runs", headers=bearer).status_code == 200


def test_a_wrong_key_is_refused_and_repeated_failures_lock_the_client_out(client_for):
    client = client_for(ogr_api_key="viewer-key")
    for _ in range(security.sign_in_limiter.limit):
        assert _sign_in(client, "guess").status_code == 401
    assert _sign_in(client, "viewer-key").status_code == 429


def test_sign_out_revokes_the_session(client_for):
    client = client_for(ogr_api_key="viewer-key")
    bearer = {"Authorization": f"Bearer {_sign_in(client, 'viewer-key').json()['token']}"}
    assert client.delete("/auth/session", headers=bearer).status_code == 204
    r = client.get("/runs", headers=bearer)
    assert r.status_code == 401 and "sign in again" in r.json()["detail"]


def test_an_expired_session_is_refused(client_for, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: now[0])
    client = client_for(ogr_api_key="viewer-key", ogr_session_ttl_s=60)
    bearer = {"Authorization": f"Bearer {_sign_in(client, 'viewer-key').json()['token']}"}
    now[0] += 61
    assert client.get("/runs", headers=bearer).status_code == 401


def test_with_an_admin_key_the_api_key_is_a_viewer(client_for):
    client = client_for(ogr_api_key="viewer-key", ogr_admin_key="admin-key")
    viewer = {"Authorization": f"Bearer {_sign_in(client, 'viewer-key').json()['token']}"}
    admin = {"Authorization": f"Bearer {_sign_in(client, 'admin-key').json()['token']}"}
    assert client.get("/auth/session", headers=viewer).json() == {"role": "viewer"}
    assert client.get("/runs", headers=viewer).status_code == 200  # reading is allowed
    # Names that do not exist: past the auth gate the request fails validation
    # (404/422), so nothing is built, run or switched against a live service.
    for method, path, body in (
        ("post", "/build", {"dataset": "no-such-dataset"}),
        ("post", "/batch", {"dataset": "no-such-question-set"}),
        ("post", "/embeddings/switch", {"model": "no-such-model"}),
        ("post", "/corpora/no-such-dataset", {}),
        ("post", "/runs/import", {}),
    ):
        r = getattr(client, method)(path, json=body, headers=viewer)
        assert r.status_code == 403, (path, r.status_code)
        passed = getattr(client, method)(path, json=body, headers=admin).status_code
        assert passed in (400, 404, 409, 415, 422), (path, passed)


def test_scripts_can_still_send_the_key_itself(client_for):
    client = client_for(ogr_api_key="viewer-key", ogr_admin_key="admin-key")
    assert client.get("/runs", headers={"X-API-Key": "viewer-key"}).status_code == 200
    assert client.post("/build", json={"dataset": "no-such-dataset"}, headers={"X-API-Key": "viewer-key"}).status_code == 403


def test_no_key_configured_refuses_everything(client_for):
    client = client_for(ogr_api_key="")
    assert _sign_in(client, "anything").status_code == 503
