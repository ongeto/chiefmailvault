"""Mailbox credential validation tests."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _login(client):
    client.post("/auth/login", json={"username": "testadmin", "password": "testpass123"})


def test_validate_endpoint_rejects_bad_credentials(client):
    _login(client)
    client.post("/api/domains", json={"name": "val.com", "imap_host": "imap.val.com"})

    with patch("imap.validate.validate_credentials", return_value=(False, "Login failed")):
        res = client.post("/api/mailboxes/validate", json={
            "domain_id": 1,
            "email": "user@val.com",
            "password": "wrong",
        })

    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is False
    assert "Login failed" in data["message"]


def test_validate_endpoint_accepts_good_credentials(client):
    _login(client)
    client.post("/api/domains", json={"name": "good.com", "imap_host": "imap.good.com"})

    with patch("imap.validate.validate_credentials", return_value=(True, "Connection successful")):
        res = client.post("/api/mailboxes/validate", json={
            "domain_id": 1,
            "email": "user@good.com",
            "password": "correct",
        })

    assert res.status_code == 200
    assert res.json()["valid"] is True


def test_create_mailbox_rejected_without_valid_credentials(client):
    _login(client)
    client.post("/api/domains", json={"name": "reject.com", "imap_host": "imap.reject.com"})

    with patch("imap.validate.validate_credentials", return_value=(False, "Login failed")):
        res = client.post("/api/mailboxes", json={
            "domain_id": 1,
            "email": "user@reject.com",
            "password": "bad",
        })

    assert res.status_code == 400
    mailboxes = client.get("/api/mailboxes").json()
    assert len(mailboxes) == 0


def test_create_mailbox_saves_when_validated(client):
    _login(client)
    client.post("/api/domains", json={"name": "save.com", "imap_host": "imap.save.com"})

    with patch("imap.validate.validate_credentials", return_value=(True, "Connection successful")):
        res = client.post("/api/mailboxes", json={
            "domain_id": 1,
            "email": "info@save.com",
            "password": "good-pass",
        })

    assert res.status_code == 200
    data = res.json()
    assert data["credentials_validated"] is True

    mailboxes = client.get("/api/mailboxes").json()
    assert mailboxes[0]["credentials_validated"] == 1


def test_backup_skips_unvalidated_mailbox(client):
    from core import orchestrator
    from db import models
    from db.vault import CredentialVault

    _login(client)
    domain_id = models.create_domain("skip.com", "imap.skip.com")
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(domain_id, "user@skip.com", vault.encrypt("pass"), credentials_validated=False)

    results = orchestrator.trigger_backup(mailbox_id=mb_id)
    assert results[0]["success"] is False
    assert "not been validated" in results[0]["error"]


def test_delete_mailbox(client):
    _login(client)
    client.post("/api/domains", json={"name": "del.com", "imap_host": "imap.del.com"})

    with patch("imap.validate.validate_credentials", return_value=(True, "OK")):
        create = client.post("/api/mailboxes", json={
            "domain_id": 1, "email": "del@del.com", "password": "pass",
        })
    mb_id = create.json()["id"]

    res = client.delete(f"/api/mailboxes/{mb_id}")
    assert res.status_code == 200
    assert client.get("/api/mailboxes").json() == []


def test_update_mailbox_password(client):
    _login(client)
    client.post("/api/domains", json={"name": "upd.com", "imap_host": "imap.upd.com"})

    with patch("imap.validate.validate_credentials", return_value=(True, "OK")):
        create = client.post("/api/mailboxes", json={
            "domain_id": 1, "email": "old@upd.com", "password": "old-pass",
        })
    mb_id = create.json()["id"]

    with patch("imap.validate.validate_credentials", return_value=(True, "Updated OK")):
        res = client.put(f"/api/mailboxes/{mb_id}", json={
            "email": "new@upd.com",
            "password": "new-pass",
        })
    assert res.status_code == 200

    mailboxes = client.get("/api/mailboxes").json()
    assert mailboxes[0]["email"] == "new@upd.com"


def test_revalidate_success_keeps_validated(client):
    _login(client)
    client.post("/api/domains", json={"name": "reok.com", "imap_host": "imap.reok.com"})

    with patch("imap.validate.validate_credentials", return_value=(True, "OK")):
        create = client.post("/api/mailboxes", json={
            "domain_id": 1, "email": "ok@reok.com", "password": "pass",
        })
    mb_id = create.json()["id"]

    with patch("imap.validate.validate_credentials", return_value=(True, "Still good")):
        res = client.post(f"/api/mailboxes/{mb_id}/revalidate")

    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["open_edit"] is False
    assert client.get("/api/mailboxes").json()[0]["credentials_validated"] == 1


def test_revalidate_failure_marks_unvalidated_and_opens_edit(client):
    _login(client)
    client.post("/api/domains", json={"name": "refail.com", "imap_host": "imap.refail.com"})

    with patch("imap.validate.validate_credentials", return_value=(True, "OK")):
        create = client.post("/api/mailboxes", json={
            "domain_id": 1, "email": "bad@refail.com", "password": "pass",
        })
    mb_id = create.json()["id"]

    with patch("imap.validate.validate_credentials", return_value=(False, "Login failed")):
        res = client.post(f"/api/mailboxes/{mb_id}/revalidate")

    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is False
    assert data["open_edit"] is True
    assert "password" in data["message"].lower()
    assert client.get("/api/mailboxes").json()[0]["credentials_validated"] == 0
