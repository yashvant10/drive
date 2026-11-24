from datetime import UTC, datetime, timedelta
from secrets import randbelow
from typing import Annotated
from uuid import UUID

from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import Current, DB, hasher, require, throttle
from .bookings import locked_booking
from .models import Booking, PickupVerification, User

router = APIRouter(prefix="/trips", tags=["trips"])
Customer = Annotated[User, Depends(require("customer"))]
DriverUser = Annotated[User, Depends(require("driver"))]


class PickupCode(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


def confirmed(db, booking_id):
    item = db.get(PickupVerification,booking_id)
    return bool(item and item.verified_at)


@router.get("/{booking_id}/pickup-verification")
def status(booking_id: UUID, user: Current, db: DB):
    booking = db.get(Booking,booking_id)
    if not booking or user.id not in (booking.driver_id,booking.customer_id):
        raise HTTPException(404,"Booking not found.")
    return {"verified":confirmed(db,booking_id)}


@router.post("/{booking_id}/pickup-verification", status_code=201)
def issue(booking_id: UUID, user: Customer, db: DB):
    # Limit code resets independently of verification attempts.
    throttle(db, f"pickup-issue:{user.id}", 12)
    booking = locked_booking(db, booking_id)
    if booking.customer_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status != "DRIVER_ARRIVED":
        raise HTTPException(409,"Generate the code when your driver has arrived.")
    existing = db.get(PickupVerification,booking_id)
    if existing and existing.verified_at:
        raise HTTPException(409,"Pickup is already verified.")
    if existing and existing.expires_at > datetime.now(UTC) + timedelta(minutes=8):
        raise HTTPException(429,"Wait two minutes before generating a new code.")
    code = f"{randbelow(1_000_000):06d}"
    item = existing or PickupVerification(booking_id=booking_id)
    item.code_hash = hasher.hash(code)
    item.attempts = 0
    item.expires_at = datetime.now(UTC)+timedelta(minutes=10)
    db.add(item)
    db.commit()
    return {"code":code,"expires_at":item.expires_at}


@router.post("/{booking_id}/pickup-verification/check")
def verify(booking_id: UUID, data: PickupCode, user: DriverUser, db: DB):
    throttle(db, f"pickup-check:{user.id}",30)
    booking = locked_booking(db, booking_id)
    if booking.driver_id != user.id:
        raise HTTPException(404,"Booking not found.")
    if booking.status != "DRIVER_ARRIVED":
        raise HTTPException(409,"Pickup verification is unavailable at this stage.")
    item = db.get(PickupVerification,booking_id)
    if item and item.verified_at:
        return {"verified":True}
    if not item or item.expires_at <= datetime.now(UTC) or item.attempts >= 5:
        raise HTTPException(409,"Ask the customer for a new pickup code.")
    item.attempts += 1
    try:
        hasher.verify(item.code_hash,data.code)
    except VerifyMismatchError:
        db.commit()
        raise HTTPException(400,"Incorrect pickup code.")
    item.verified_at = datetime.now(UTC)
    db.commit()
    return {"verified":True}
