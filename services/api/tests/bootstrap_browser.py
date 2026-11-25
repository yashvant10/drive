"""Create browser-test privileged accounts in a disposable database."""
import os

from app.auth import hasher
from app.db import Session, engine
from app.models import User


def main():
    if os.getenv("RUN_DB_TESTS") != "1" or not (engine.url.database or "").startswith("drive_test"):
        raise SystemExit("A disposable drive_test database is required.")
    with Session.begin() as db:
        for name,role in (("ADMIN","admin"),("OWNER","owner")):
            email = os.getenv(f"PLAYWRIGHT_{name}_EMAIL")
            password = os.getenv(f"PLAYWRIGHT_{name}_PASSWORD")
            if email and password:
                db.add(User(email=email,name=f"Browser Test {role.title()}",role=role,password_hash=hasher.hash(password)))


if __name__ == "__main__":
    main()
