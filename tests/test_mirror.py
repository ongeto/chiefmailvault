"""Mirror/zip tests."""

from datetime import datetime
from pathlib import Path

from storage.local import get_mailbox_storage_root
from storage.mirror import create_backup_zip, mirror_mailbox


def test_backup_zip_naming(tmp_path, monkeypatch):
    import config
    import storage.local as local_mod
    import storage.mirror as mirror_mod

    storage_dir = tmp_path / "storage"
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(config, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(config, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(local_mod, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(mirror_mod, "UPLOADS_DIR", uploads_dir)

    email = "info@example.com"
    root = get_mailbox_storage_root(email)
    eml = root / "2026" / "06_June" / "email_1.eml"
    eml.parent.mkdir(parents=True, exist_ok=True)
    eml.write_bytes(b"test eml content")

    zip_path = create_backup_zip(email)
    assert zip_path is not None
    assert zip_path.exists()
    assert "example.com" in zip_path.name
    assert "backup_" in zip_path.name


def test_mirror_skips_zip_when_cloud_disabled(tmp_path, monkeypatch):
    import config
    import storage.local as local_mod
    import storage.mirror as mirror_mod

    storage_dir = tmp_path / "storage"
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(config, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(config, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(config, "DRIVE_ENABLED", False)
    monkeypatch.setattr(config, "DROPBOX_ENABLED", False)
    monkeypatch.setattr(config, "NAS_ENABLED", False)
    monkeypatch.setattr(local_mod, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(mirror_mod, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(mirror_mod, "DRIVE_ENABLED", False)
    monkeypatch.setattr(mirror_mod, "DROPBOX_ENABLED", False)
    monkeypatch.setattr(mirror_mod, "NAS_ENABLED", False)

    email = "info@example.com"
    root = get_mailbox_storage_root(email)
    eml = root / "2026" / "06_June" / "email_1.eml"
    eml.parent.mkdir(parents=True, exist_ok=True)
    eml.write_bytes(b"test eml content")

    logs: list[str] = []
    result = mirror_mailbox(1, email, log_fn=logs.append, messages_added=0)
    assert result.get("local_only") is True
    assert list(uploads_dir.glob("*.zip")) == []
    assert any("cloud mirror disabled" in line for line in logs)
