"""Create a browser-test administrator in a disposable database."""
import os

from app.auth import hasher
from app.db import Session, engine
from app.models import User


def main():
    if os.getenv("RUN_DB_TESTS") != "1" or not (engine.url.database or "").startswith("drive_test"):
        raise SystemExit("A disposable drive_test database is required.")
    email = os.environ["PLAYWRIGHT_ADMIN_EMAIL"]
    password = os.environ["PLAYWRIGHT_ADMIN_PASSWORD"]
    with Session.begin() as db:
        db.add(User(email=email, name="Browser Test Administrator", role="admin",
                    password_hash=hasher.hash(password)))


if __name__ == "__main__":
    main()
