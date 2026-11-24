import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import database
from .permissions import admin_section, permit
from .models import AuthLimit, Driver, Login, PasswordReset, User
from .schemas import Credentials, Profile, Registration, ResetPassword, ResetRequest

router = APIRouter(prefix="/auth", tags=["auth"])
DB = Annotated[Session, Depends(database)]
hasher = PasswordHasher()
dummy_hash = hasher.hash(token_urlsafe())
cookie = "drive_session"
lifetime = timedelta(days=7)


def digest(value: str):
    return sha256(value.encode()).hexdigest()


def throttle(db: Session, key: str, limit: int):
    reset = AuthLimit.expires_at <= func.now()
    query = insert(AuthLimit).values(key=key, attempts=1, expires_at=datetime.now(UTC) + timedelta(minutes=15))
    query = query.on_conflict_do_update(
        index_elements=[AuthLimit.key],
        set_={
            "attempts": case((reset, 1), else_=AuthLimit.attempts + 1),
            "expires_at": case((reset, query.excluded.expires_at), else_=AuthLimit.expires_at),
        },
    ).returning(AuthLimit.attempts)
    attempts = db.scalar(query)
    db.commit()
    if attempts > limit:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")


def authenticate(request: Request, db: DB):
    token = request.cookies.get(cookie)
    if token:
        user = db.scalar(select(User).join(Login).where(
            Login.token_hash == digest(token), Login.expires_at > func.now(), User.disabled_at.is_(None),
        ))
        if user:
            return user
    raise HTTPException(401, "Sign in to continue.")


Current = Annotated[User, Depends(authenticate)]


def require(role: str):
    def check(user: Current, request: Request):
        if user.role != role:
            raise HTTPException(403, "This action is restricted.")
        if role == "admin":
            permit(user, admin_section(request.url.path))
        return user
    return check


def issue(db: Session, response: Response, user: User, request: Request):
    old = request.cookies.get(cookie)
    if old and (previous := db.get(Login, digest(old))):
        db.delete(previous)
    token = token_urlsafe(32)
    db.add(Login(token_hash=digest(token), user_id=user.id, expires_at=datetime.now(UTC) + lifetime))
    db.commit()
    response.set_cookie(cookie, token, httponly=True, secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
                        samesite="lax", max_age=int(lifetime.total_seconds()), path="/")
    return user


@router.post("/register", response_model=Profile, status_code=201)
def register(data: Registration, request: Request, response: Response, db: DB):
    throttle(db, "register:" + digest(request.client.host if request.client else "unknown"), 20)
    user = User(name=data.name, email=data.email.lower(), password_hash=hasher.hash(data.password), role=data.role)
    db.add(user)
    try:
        db.flush()
        if user.role == "driver":
            db.add(Driver(user_id=user.id))
        return issue(db, response, user, request)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account already exists for this email.")


@router.post("/login", response_model=Profile)
def login(data: Credentials, request: Request, response: Response, db: DB):
    throttle(db, "login:" + digest(data.email.lower()), 10)
    throttle(db, "login-ip:" + digest(request.client.host if request.client else "unknown"), 100)
    user = db.scalar(select(User).where(User.email == data.email.lower()).with_for_update())
    try:
        hasher.verify(user.password_hash if user else dummy_hash, data.password)
    except VerifyMismatchError:
        raise HTTPException(401, "Email or password is incorrect.")
    if not user or user.disabled_at:
        raise HTTPException(401, "Email or password is incorrect.")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data.password)
    return issue(db, response, user, request)


@router.get("/me", response_model=Profile)
def me(user: Current):
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    token = request.cookies.get(cookie)
    if token and (session := db.get(Login, digest(token))):
        db.delete(session)
        db.commit()
    response.delete_cookie(cookie, path="/")


def email_reset(address: str, token: str):
    from email.message import EmailMessage
    import smtplib
    import ssl

    message = EmailMessage()
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = address
    message["Subject"] = "Reset your Drivewell password"
    message.set_content(
        f"Reset your password within 30 minutes: {os.environ['PUBLIC_WEB_URL'].rstrip('/')}/reset-password?token={token}"
    )
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=10) as server:
        server.starttls(context=ssl.create_default_context())
        if username := os.getenv("SMTP_USERNAME"):
            server.login(username, os.environ["SMTP_PASSWORD"])
        server.send_message(message)


def deliver_reset(user_id, address, token):
    import logging
    import smtplib

    from .db import Session as open_session

    try:
        email_reset(address, token)
    except (OSError, smtplib.SMTPException, ValueError, KeyError):
        logging.getLogger(__name__).warning("Password reset delivery failed for user %s", user_id)
        with open_session.begin() as db:
            db.execute(delete(PasswordReset).where(PasswordReset.token_hash == digest(token)))


@router.post("/password-reset", status_code=202)
def request_reset(data: ResetRequest, request: Request, tasks: BackgroundTasks, db: DB):
    if not all(os.getenv(name) for name in ("SMTP_HOST", "SMTP_FROM", "PUBLIC_WEB_URL")):
        raise HTTPException(503, "Password reset email is unavailable.")
    address = data.email.lower()
    throttle(db, "reset:" + digest(address), 5)
    throttle(db, "reset-ip:" + digest(request.client.host if request.client else "unknown"), 30)
    user = db.scalar(select(User).where(User.email == address).with_for_update())
    if user:
        token = token_urlsafe(32)
        db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
        db.add(PasswordReset(token_hash=digest(token), user_id=user.id, expires_at=datetime.now(UTC) + timedelta(minutes=30)))
        db.commit()
        tasks.add_task(deliver_reset, user.id, user.email, token)
    return {"message": "If the address is registered, a reset link will be sent."}


@router.post("/password-reset/confirm", status_code=204)
def confirm_reset(data: ResetPassword, request: Request, db: DB):
    throttle(db, "reset-check:" + digest(request.client.host if request.client else "unknown"), 30)
    hashed = digest(data.token)
    user_id = db.scalar(select(PasswordReset.user_id).where(PasswordReset.token_hash == hashed))
    if not user_id:
        raise HTTPException(400, "This reset link is invalid or has expired.")
    user = db.get(User, user_id, with_for_update=True)
    reset = db.get(PasswordReset, hashed, with_for_update=True)
    if not reset or reset.expires_at <= datetime.now(UTC):
        raise HTTPException(400, "This reset link is invalid or has expired.")
    user.password_hash = hasher.hash(data.password)
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    db.execute(delete(Login).where(Login.user_id == user.id))
    db.commit()
