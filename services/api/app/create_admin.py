from argparse import ArgumentParser
from getpass import getpass

from sqlalchemy import select

from .auth import hasher
from .db import Session
from .models import User
from .schemas import Credentials


def main():
    parser = ArgumentParser(description="Provision a privileged account from a trusted shell.")
    parser.add_argument("--role", choices=("admin", "owner"), default="admin")
    role = parser.parse_args().role
    name = input("Account name: ").strip()
    credentials = Credentials(email=input("Account email: "), password=getpass("Account password: "))
    if not 2 <= len(name) <= 100:
        raise SystemExit("Account name must be between 2 and 100 characters.")
    with Session.begin() as db:
        if db.scalar(select(User.id).where(User.email == credentials.email.lower())):
            raise SystemExit("That email is already registered.")
        db.add(User(name=name, email=credentials.email.lower(), password_hash=hasher.hash(credentials.password), role=role))
    print(f"{role.capitalize()} account created.")


if __name__ == "__main__":
    main()
