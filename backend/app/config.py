import os
import secrets
from pathlib import Path

DB_PATH = os.getenv("PISO_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "pisowifi.db"))
_jwt_secret_env = os.getenv("PISO_JWT_SECRET")
if _jwt_secret_env:
    JWT_SECRET = _jwt_secret_env
else:
    # Persist JWT secret next to DB so restarts don't invalidate sessions
    _jwt_file = Path(DB_PATH).with_name("jwt-secret")
    if _jwt_file.exists():
        JWT_SECRET = _jwt_file.read_text().strip()
    else:
        JWT_SECRET = secrets.token_hex(32)
        try:
            _jwt_file.parent.mkdir(parents=True, exist_ok=True)
            _jwt_file.write_text(JWT_SECRET + "\n")
            _jwt_file.chmod(0o600)
        except Exception:
            pass
MOCK_MAC = os.getenv("PISO_MOCK_MAC", "")  # dev/tests only; never set in the device image
GPIO_ENABLED = os.getenv("PISO_GPIO_ENABLED", "0") == "1"
ADMIN_USER = os.getenv("PISO_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("PISO_ADMIN_PASS", "admin@123")


def image_version() -> str:
    """Image build version baked into the app dir; repo copy covers host dev."""
    path = Path(os.getenv("PISO_VERSION_PATH", "/opt/pisowifi/backend/app/version"))
    if not path.is_file():
        path = Path(__file__).resolve().parents[2] / "device" / "version"
    try:
        return path.read_text().strip() or "dev"
    except OSError:
        return "dev"


# Physical pin -> (gpiochip, offset) for Allwinner H3.
PIN_MAP = {3: ("gpiochip0", 12), 5: ("gpiochip0", 11), 11: ("gpiochip0", 1)}
