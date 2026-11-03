"""API authentication tests."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_login_and_protected_route(client):
    res = client.post("/auth/login", json={"username": "testadmin", "password": "testpass123"})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert "cmv_token" in res.cookies

    res = client.get("/api/stats")
    assert res.status_code == 200


def test_protected_route_401_without_cookie(client):
    res = client.get("/api/stats")
    assert res.status_code == 401


def test_login_invalid_credentials(client):
    res = client.post("/auth/login", json={"username": "testadmin", "password": "wrong"})
    assert res.status_code == 401


def test_mailbox_password_masked(client):
    client.post("/auth/login", json={"username": "testadmin", "password": "testpass123"})
    client.post("/api/domains", json={"name": "mask.com", "imap_host": "imap.mask.com"})
    domains = client.get("/api/domains").json()
    with patch("imap.validate.validate_credentials", return_value=(True, "OK")):
        client.post("/api/mailboxes", json={
            "domain_id": domains[0]["id"],
            "email": "info@mask.com",
            "password": "secret-password",
        })
    mailboxes = client.get("/api/mailboxes").json()
    assert mailboxes[0]["password"] == "********"
    assert "secret-password" not in str(mailboxes)
