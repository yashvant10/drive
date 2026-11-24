from getpass import getpass

from sqlalchemy import select

from .auth import hasher
from .db import Session
from .models import User
from .schemas import Credentials


def main():
    name = input("Admin name: ").strip()
    credentials = Credentials(email=input("Admin email: "), password=getpass("Admin password: "))
    if not 2 <= len(name) <= 100:
        raise SystemExit("Admin name must be between 2 and 100 characters.")
    with Session.begin() as db:
        if db.scalar(select(User.id).where(User.email == credentials.email.lower())):
            raise SystemExit("That email is already registered.")
        db.add(User(name=name, email=credentials.email.lower(), password_hash=hasher.hash(credentials.password), role="admin"))
    print("Administrator created.")


if __name__ == "__main__":
    main()
