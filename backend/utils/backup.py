import os
import shutil
import datetime
from pathlib import Path

# Resolve project root (two levels up from this file: backend/utils/backup.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
DB_FILE = DATA_DIR / "db" / "focuslock.db"
MODEL_FILE = DATA_DIR / "ml" / "focus_model.pkl"

def _ensure_backup_dir() -> None:
    """Create the backup directory if it does not exist."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def create_backup() -> Path:
    """Create a timestamped backup of the DB and model files.

    Returns the directory containing the backup files.
    """
    _ensure_backup_dir()
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_subdir = BACKUP_DIR / f"backup_{timestamp}"
    backup_subdir.mkdir(parents=True, exist_ok=True)
    # Copy DB if present
    if DB_FILE.is_file():
        shutil.copy2(DB_FILE, backup_subdir / DB_FILE.name)
    # Copy model if present
    if MODEL_FILE.is_file():
        shutil.copy2(MODEL_FILE, backup_subdir / MODEL_FILE.name)
    return backup_subdir

def get_latest_backup() -> Path | None:
    """Return the most recent backup directory, or ``None`` if no backups exist."""
    if not BACKUP_DIR.is_dir():
        return None
    backups = sorted(BACKUP_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return backups[0] if backups else None
