"""Sets new passwords for existing users: reads JSON {"email": "password", ...} from stdin.

The public server uses it after demo_reset.py, because the demo passwords are written in the repository.
Passwords come through stdin, so they are not seen in the process list or the shell history.
Usage (from backend/): python scripts/set_passwords.py < passwords.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import User  # noqa: E402

if __name__ == "__main__":
    passwords: dict[str, str] = json.load(sys.stdin)
    with SessionLocal() as db:
        for email, password in passwords.items():
            user = db.scalar(select(User).where(User.email == email.lower()))
            if user is None:
                print("not found:", email)
                continue
            user.password_hash = hash_password(password)
            print("changed:", email)
        db.commit()
