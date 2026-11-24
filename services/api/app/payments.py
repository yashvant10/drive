import hmac
import json
import os
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .auth import DB, require
from .billing import checkout_amount
from .bookings import locked_booking
from .models import Booking, BookingCharge, DemoPayment, Payment, PaymentEvent, User

router = APIRouter(prefix="/payments", tags=["payments"])
Kind = Literal["BASE", "OVERAGE", "CANCELLATION"]
Customer = Annotated[User, Depends(require("customer"))]


class Verification(BaseModel):
    order_id: str = Field(min_length=1, max_length=80, pattern="^order_[A-Za-z0-9]+$")
    payment_id: str = Field(min_length=1, max_length=80, pattern="^pay_[A-Za-z0-9]+$")
    signature: str = Field(pattern="^[a-f0-9]{64}$")


def demo_enabled():
    return (os.getenv("APP_ENV", "production") in {"development", "test"}
            and os.getenv("PAYMENT_MODE", "razorpay") == "demo")


def demo_record(item):
    return {"id": item.id, "booking_id": item.booking_id, "amount_paise": item.amount_paise,
            "kind": item.kind, "status": "SIMULATED", "provider_order_id": None}


def settings():
    if os.getenv("PAYMENT_MODE", "razorpay") != "razorpay":
        return None
    key = os.getenv("RAZORPAY_KEY_ID")
    secret = os.getenv("RAZORPAY_KEY_SECRET")
    webhook = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    return (key, secret, webhook) if key and secret and webhook else None


def validates(secret, body, signature):
    expected = hmac.digest(secret.encode(), body, "sha256").hex()
    return hmac.compare_digest(expected, signature)


def provider(method, path, *, body=None):
    config = settings()
    if not config:
        raise HTTPException(503, "Online payment is unconfigured.")
    try:
        result = httpx.request(method, "https://api.razorpay.com/v1" + path,
                               auth=(config[0], config[1]), json=body, timeout=8)
        result.raise_for_status()
        return result.json()
    except (httpx.HTTPError, ValueError) as cause:
        raise HTTPException(502, "The payment provider could not confirm the operation.") from cause


def payment_record(item):
    return {"id": item.id, "booking_id": item.booking_id, "amount_paise": item.amount_paise,
            "kind": item.kind, "status": item.status, "provider_order_id": item.provider_order_id}


def owned_booking(db, booking_id, user):
    booking = locked_booking(db, booking_id)
    if booking.customer_id != user.id:
        raise HTTPException(404, "Booking not found.")
    return booking


def captured(db, payment, entity, event_id):
    if (entity.get("order_id") != payment.provider_order_id or entity.get("amount") != payment.amount_paise
            or entity.get("currency") != "INR" or entity.get("status") != "captured"):
        raise HTTPException(409, "The capture could not be reconciled with this order.")
    provider_id = entity.get("id")
    if not isinstance(provider_id, str) or not provider_id.startswith("pay_") or len(provider_id) > 80:
        raise HTTPException(422, "Invalid payment reference.")
    if payment.provider_payment_id and payment.provider_payment_id != provider_id:
        raise HTTPException(409, "This order already has a different capture.")
    if db.scalar(select(PaymentEvent.id).where(PaymentEvent.provider_event_id == event_id)):
        return
    payment.provider_payment_id = provider_id
    payment.status = "CAPTURED"
    db.add(PaymentEvent(payment_id=payment.id, provider_event_id=event_id, kind="CAPTURED"))
    db.commit()


@router.get("")
def history(user: Customer, db: DB, booking_id: UUID | None = None):
    payments = select(Payment).join(Booking).where(Booking.customer_id == user.id)
    simulations = select(DemoPayment).where(DemoPayment.customer_id == user.id)
    if booking_id:
        payments = payments.where(Payment.booking_id == booking_id)
        simulations = simulations.where(DemoPayment.booking_id == booking_id)
    items = db.scalars(payments.order_by(Payment.created_at.desc()).limit(100))
    demo = db.scalars(simulations.order_by(DemoPayment.created_at.desc()).limit(100))
    config = settings()
    return {"configured": config is not None, "test_mode": bool(config and config[0].startswith("rzp_test_")), "mode": "demo" if demo_enabled() else "razorpay",
            "payments": [payment_record(item) for item in items],
            "demo_payments": [demo_record(item) for item in demo]}


@router.get("/{booking_id}/charges")
def charges(booking_id: UUID, user: Customer, db: DB):
    booking = db.get(Booking, booking_id)
    if not booking or booking.customer_id != user.id:
        raise HTTPException(404,"Booking not found.")
    return list(db.scalars(select(BookingCharge).where(BookingCharge.booking_id==booking.id)))


@router.post("/{booking_id}/demo")
def simulate(booking_id: UUID, user: Customer, db: DB, kind: Kind = "BASE"):
    if not demo_enabled():
        raise HTTPException(404, "Demo checkout is unavailable.")
    booking = owned_booking(db, booking_id, user)
    item = db.scalar(select(DemoPayment).where(DemoPayment.booking_id == booking.id, DemoPayment.kind == kind))
    if item:
        return demo_record(item)
    amount = checkout_amount(db, booking, kind)
    if db.scalar(select(Payment.id).where(Payment.booking_id == booking.id, Payment.kind == kind)):
        raise HTTPException(409, "This booking already has a provider payment.")
    item = DemoPayment(booking_id=booking.id, customer_id=user.id, kind=kind, amount_paise=amount)
    db.add(item)
    db.commit()
    return demo_record(item)


@router.post("/{booking_id}/order")
def create_order(booking_id: UUID, user: Customer, db: DB, kind: Kind = "BASE"):
    config = settings()
    if not config:
        raise HTTPException(503, "Online payment is unconfigured.")
    booking = owned_booking(db, booking_id, user)
    amount = checkout_amount(db, booking, kind)
    if db.scalar(select(DemoPayment.id).where(DemoPayment.booking_id == booking.id, DemoPayment.kind == kind)):
        raise HTTPException(409, "This booking used demo checkout.")
    payment = db.scalar(select(Payment).where(Payment.booking_id == booking.id, Payment.kind == kind))
    if payment:
        if payment.status != "CREATED" or not payment.provider_order_id:
            raise HTTPException(409, "This payment already exists or needs reconciliation.")
        return {**payment_record(payment), "key_id": config[0]}
    # Persist the intent first. An ambiguous provider failure requires manual
    # reconciliation by receipt reference before another order can be issued.
    payment = Payment(booking_id=booking.id, kind=kind, amount_paise=amount, status="CREATING")
    db.add(payment)
    db.commit()
    result = provider("POST", "/orders", body={"amount": payment.amount_paise, "currency": "INR", "receipt": str(payment.id)})
    order_id = result.get("id")
    if not isinstance(order_id, str) or not order_id.startswith("order_") or len(order_id) > 80:
        raise HTTPException(502, "The provider did not return a valid order.")
    payment.provider_order_id = order_id
    payment.status = "CREATED"
    db.commit()
    return {**payment_record(payment), "key_id": config[0]}


@router.post("/{booking_id}/verify")
def verify(booking_id: UUID, data: Verification, user: Customer, db: DB):
    config = settings()
    if not config:
        raise HTTPException(503, "Online payment is unconfigured.")
    booking = owned_booking(db, booking_id, user)
    payment = db.scalar(select(Payment).where(Payment.booking_id == booking.id, Payment.provider_order_id == data.order_id).with_for_update())
    if not payment or payment.provider_order_id != data.order_id:
        raise HTTPException(404, "Payment order not found.")
    if not validates(config[1], f"{payment.provider_order_id}|{data.payment_id}".encode(), data.signature):
        raise HTTPException(400, "Invalid checkout signature.")
    entity = provider("GET", "/payments/" + data.payment_id)
    captured(db, payment, entity, "checkout:" + data.payment_id)
    return payment_record(payment)


@router.post("/webhook")
async def webhook(request: Request, db: DB):
    config = settings()
    if not config:
        raise HTTPException(503, "Payment webhooks are unconfigured.")
    signature = request.headers.get("x-razorpay-signature", "")
    event_id = request.headers.get("x-razorpay-event-id", "")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 256_000:
            raise HTTPException(413, "Webhook exceeds the size limit.")
    if not event_id.isascii() or not 1 <= len(event_id) <= 125 or not validates(config[2], raw, signature):
        raise HTTPException(400, "Invalid webhook signature or event ID.")
    try:
        event = json.loads(raw)
        if event["event"] != "payment.captured":
            return {"received": True}
        entity = event["payload"]["payment"]["entity"]
        order_id = entity["order_id"]
        if not isinstance(order_id, str) or not 1 <= len(order_id) <= 80:
            raise ValueError("Invalid order")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, "Invalid webhook payload.")
    payment = db.scalar(select(Payment).where(Payment.provider_order_id == order_id).with_for_update())
    if not payment:
        raise HTTPException(404, "Payment order not found.")
    captured(db, payment, entity, "webhook:" + event_id)
    return {"received": True}
