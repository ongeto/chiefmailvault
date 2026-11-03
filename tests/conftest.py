"""Test fixtures."""

import os
import tempfile
from pathlib import Path

import pytest

# Set test env before imports
_test_dir = tempfile.mkdtemp(prefix="cmv_test_")
os.environ["CMV_DATA_ROOT"] = _test_dir
os.environ["CMV_SECRET_KEY"] = "test-secret-key-for-jwt-signing-64chars!!"
os.environ["CMV_ADMIN_USER"] = "testadmin"
os.environ["CMV_ADMIN_PASSWORD"] = "testpass123"
os.environ["CMV_VAULT_KEY"] = "xI2k8vN0pQ3rS6tU9wX2yZ5aB8cD1eF4gH7jK0mN3pQ="


@pytest.fixture(autouse=True)
def fresh_db():
    from db.database import init_db, get_connection
    from config import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    yield
    conn = get_connection()
    conn.close()
