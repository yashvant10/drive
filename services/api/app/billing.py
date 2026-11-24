from datetime import UTC, datetime, timedelta
from math import ceil

from fastapi import HTTPException
from sqlalchemy import select

from .models import BookingCharge, BookingEvent, Handover

LATE_CANCEL_STAGES = {"ASSIGNED", "CONFIRMED", "DRIVER_EN_ROUTE"}


def cancellation_amount(booking):
    if booking.status in LATE_CANCEL_STAGES and booking.starts_at <= datetime.now(UTC)+timedelta(minutes=15):
        return booking.cancellation_paise
    return 0


def add_cancellation(db, booking, amount):
    if amount:
        db.add(BookingCharge(booking_id=booking.id, kind="CANCELLATION", amount_paise=amount,
                             description="Late cancellation of an assigned driver"))


def add_overage(db, booking):
    if not booking.overage_hour_paise:
        return
    start = db.scalar(select(BookingEvent.created_at).where(
        BookingEvent.booking_id==booking.id, BookingEvent.status=="IN_PROGRESS"
    ).order_by(BookingEvent.created_at.desc()).limit(1))
    finish = db.scalar(select(Handover.created_at).where(
        Handover.booking_id==booking.id,Handover.stage=="after"
    ))
    if not start or not finish:
        return
    elapsed = finish - start
    excess = elapsed - timedelta(hours=booking.hours)
    if excess <= timedelta(minutes=15):
        return
    hours = min(4,ceil(excess / timedelta(hours=1)))
    db.add(BookingCharge(booking_id=booking.id, kind="OVERAGE", amount_paise=hours*booking.overage_hour_paise,
                         description=f"Post-trip overage · {hours} additional hour(s)"))


def checkout_amount(db, booking, kind):
    if kind == "BASE":
        if booking.status != "DRIVER_ARRIVED":
            raise HTTPException(409, "Trip checkout opens after the driver arrives.")
        return booking.fare_paise
    charge = db.scalar(select(BookingCharge).where(BookingCharge.booking_id==booking.id, BookingCharge.kind==kind))
    if not charge:
        raise HTTPException(404,"Charge not found.")
    if booking.status != {"OVERAGE":"COMPLETED","CANCELLATION":"CANCELLED"}[kind]:
        raise HTTPException(409,"This charge is currently unavailable.")
    return charge.amount_paise
