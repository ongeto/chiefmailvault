"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("CMV_DATA_ROOT", "./chiefmailvault_data")).resolve()
STORAGE_DIR = DATA_ROOT / "storage"
UPLOADS_DIR = DATA_ROOT / "uploads"
DB_PATH = DATA_ROOT / "config.db"

SECRET_KEY = os.getenv("CMV_SECRET_KEY", "dev-secret-change-in-production-64chars!!")
ADMIN_USER = os.getenv("CMV_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("CMV_ADMIN_PASSWORD", "admin123")
VAULT_KEY = os.getenv("CMV_VAULT_KEY", "")

OLLAMA_URL = os.getenv("CMV_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("CMV_OLLAMA_MODEL", "phi3:mini")
OLLAMA_ENABLED = os.getenv("CMV_OLLAMA_ENABLED", "false").lower() == "true"

IMAP_HOST = os.getenv("CMV_IMAP_HOST", "imap.hostinger.com")
IMAP_PORT = int(os.getenv("CMV_IMAP_PORT", "993"))
SYNC_INTERVAL_HOURS = int(os.getenv("CMV_SYNC_INTERVAL_HOURS", "6"))

DRIVE_ENABLED = os.getenv("CMV_DRIVE_ENABLED", "false").lower() == "true"
DRIVE_FOLDER_ID = os.getenv("CMV_DRIVE_FOLDER_ID", "")
DRIVE_CREDENTIALS_FILE = os.getenv("CMV_DRIVE_CREDENTIALS_FILE", "")

DROPBOX_ENABLED = os.getenv("CMV_DROPBOX_ENABLED", "false").lower() == "true"
DROPBOX_TOKEN = os.getenv("CMV_DROPBOX_TOKEN", "")
DROPBOX_PATH = os.getenv("CMV_DROPBOX_PATH", "/ChiefMailVault")

NAS_ENABLED = os.getenv("CMV_NAS_ENABLED", "false").lower() == "true"
NAS_PATH = os.getenv("CMV_NAS_PATH", "")

CLOUD_REQUIRED = os.getenv("CMV_CLOUD_REQUIRED", "false").lower() == "true"

LARGE_EMAIL_THRESHOLD = 25 * 1024 * 1024  # 25 MB
IMAP_THROTTLE_SECONDS = 0.5
IMAP_TIMEOUT_SECONDS = int(os.getenv("CMV_IMAP_TIMEOUT", "120"))
IMAP_FETCH_TIMEOUT_SECONDS = int(os.getenv("CMV_IMAP_FETCH_TIMEOUT", "300"))
IMAP_KEEPALIVE_INTERVAL_SECONDS = int(os.getenv("CMV_IMAP_KEEPALIVE_INTERVAL", "45"))
IMAP_KEEPALIVE_EVERY_N_OPS = int(os.getenv("CMV_IMAP_KEEPALIVE_OPS", "25"))
IMAP_MAX_RETRIES = int(os.getenv("CMV_IMAP_MAX_RETRIES", "5"))
IMAP_RETRY_DELAY_SECONDS = float(os.getenv("CMV_IMAP_RETRY_DELAY", "3"))

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 480
COOKIE_NAME = "cmv_token"

APP_TIMEZONE = os.getenv("CMV_TIMEZONE", "Africa/Nairobi")

def ensure_data_dirs() -> None:
    """Create required data directories."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
