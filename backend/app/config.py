import os
import secrets
from pathlib import Path

DB_PATH = os.getenv("PISO_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "pisowifi.db"))
JWT_SECRET = os.getenv("PISO_JWT_SECRET") or secrets.token_hex(32)
MOCK_MAC = os.getenv("PISO_MOCK_MAC", "")  # dev/tests only; never set in the device image
GPIO_ENABLED = os.getenv("PISO_GPIO_ENABLED", "0") == "1"
ADMIN_USER = os.getenv("PISO_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("PISO_ADMIN_PASS")
if ADMIN_PASS is None:
    # Persist a generated password next to the DB so restarts don't lock the admin out.
    credentials = Path(DB_PATH).with_name("admin-credentials")
    if credentials.exists():
        ADMIN_PASS = credentials.read_text().strip()
    else:
        ADMIN_PASS = secrets.token_urlsafe(12)
        credentials.parent.mkdir(parents=True, exist_ok=True)
        credentials.write_text(ADMIN_PASS + "\n")
        credentials.chmod(0o600)

# Physical pin -> (gpiochip, offset) for Allwinner H3.
PIN_MAP = {3: ("gpiochip0", 12), 5: ("gpiochip0", 11), 11: ("gpiochip0", 1)}
