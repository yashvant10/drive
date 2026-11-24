import os
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from .auth import Current, DB, digest, throttle
from .models import PhoneChallenge, User

router = APIRouter(prefix="/auth/phone", tags=["auth"])


class PhoneInput(BaseModel):
    phone: str = Field(pattern=r"^\+[1-9][0-9]{9,14}$")


class CodeInput(BaseModel):
    code: str = Field(pattern=r"^[0-9]{4,10}$")


def settings():
    account = os.getenv("TWILIO_ACCOUNT_SID")
    credential = os.getenv("TWILIO_AUTH_TOKEN")
    service = os.getenv("TWILIO_VERIFY_SERVICE_SID")
    return (account, credential, service) if account and credential and service else None


def provider(path, data):
    config = settings()
    if not config:
        raise HTTPException(503, "Phone verification is unconfigured.")
    account, credential, service = config
    try:
        result = httpx.post(f"https://verify.twilio.com/v2/Services/{service}/{path}", data=data,
                            auth=(account, credential), timeout=8)
        if path == "VerificationCheck" and result.status_code in (400, 404):
            raise HTTPException(400, "The code is incorrect or expired.")
        result.raise_for_status()
        return result.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(502, "The verification provider could not confirm the request.") from error


@router.get("")
def status(user: Current, db: DB):
    item = db.get(PhoneChallenge, user.id)
    return {"configured":settings() is not None, "verified_phone":user.verified_phone,
            "pending_phone":item.phone if item and item.expires_at > datetime.now(UTC) else None}


@router.post("/send", status_code=202)
def send_code(data: PhoneInput, request: Request, user: Current, db: DB):
    if not settings():
        raise HTTPException(503, "Phone verification is unconfigured.")
    throttle(db, f"otp-send:{user.id}", 4)
    throttle(db, "otp-number:"+digest(data.phone), 4)
    throttle(db, "otp-ip:"+digest(request.client.host if request.client else "unknown"), 20)
    db.get(User, user.id, with_for_update=True)
    result = provider("Verifications", {"To":data.phone,"Channel":"sms"})
    sid = result.get("sid")
    if result.get("status") != "pending" or not isinstance(sid, str) or not sid.startswith("VE") or len(sid) > 40:
        raise HTTPException(502, "The verification provider did not accept the request.")
    statement = insert(PhoneChallenge).values(user_id=user.id, phone=data.phone, provider_sid=sid,
                                               expires_at=datetime.now(UTC) + timedelta(minutes=10))
    statement = statement.on_conflict_do_update(index_elements=[PhoneChallenge.user_id], set_={
        "phone":statement.excluded.phone, "provider_sid":statement.excluded.provider_sid,
        "expires_at":statement.excluded.expires_at,
    })
    try:
        db.execute(statement)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A verification for this number is already pending.")
    return {"status":"pending"}


@router.post("/verify")
def verify_code(data: CodeInput, user: Current, db: DB):
    throttle(db, f"otp-check:{user.id}", 10)
    member = db.scalar(select(User).where(User.id == user.id).with_for_update())
    challenge = db.get(PhoneChallenge, user.id, with_for_update=True)
    if not challenge or challenge.expires_at <= datetime.now(UTC):
        raise HTTPException(400, "Request a new verification code.")
    result = provider("VerificationCheck", {"VerificationSid":challenge.provider_sid,"Code":data.code})
    if result.get("status") != "approved" or result.get("to") != challenge.phone:
        raise HTTPException(400, "The code is incorrect or expired.")
    member.verified_phone = challenge.phone
    member.phone_verified_at = datetime.now(UTC)
    db.delete(challenge)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That phone number is already associated with an account.")
    return {"verified_phone":member.verified_phone}
