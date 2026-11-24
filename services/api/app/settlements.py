import hmac
import os
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import DB, digest, require
from .payments import demo_enabled
from .models import Audit, Booking, Driver, Earning, Notice, Payment, Payout, Refund, User

router = APIRouter(prefix="/admin", tags=["settlements"])
Admin = Annotated[User, Depends(require("admin"))]
BLOCK_REFUND_STATUSES = {"SUBMITTING", "QUEUED", "PENDING", "PROCESSING", "PROCESSED", "REQUIRES_RECONCILIATION"}


class FundAccount(BaseModel):
    reference: str = Field(pattern=r"^fa_[A-Za-z0-9]+$", max_length=80)


class PayoutReference(BaseModel):
    reference: str = Field(pattern=r"^pout_[A-Za-z0-9]+$", max_length=80)


def credentials():
    if demo_enabled():
        return None
    key = os.getenv("RAZORPAYX_KEY_ID")
    secret = os.getenv("RAZORPAYX_KEY_SECRET")
    source = os.getenv("RAZORPAYX_ACCOUNT_NUMBER")
    return (key,secret,source) if key and secret and source else None


def configured():
    config = credentials()
    if not config:
        raise HTTPException(503, "RazorpayX payouts are unconfigured.")
    return config


def provider(method, path, *, body=None, identity=None):
    config = configured()
    headers = {"X-Payout-Idempotency": str(identity)} if identity else {}
    try:
        response = httpx.request(method, "https://api.razorpay.com/v1"+path, json=body,
                                 headers=headers, auth=(config[0], config[1]), timeout=10)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(502, "The payout provider could not confirm the operation. Reconcile before changing details.") from error


@router.get("/payouts/configuration")
def status(user: Admin, db: DB):
    return {"configured":bool(credentials())}


@router.put("/drivers/{driver_id}/payout-account")
def configure_beneficiary(driver_id: UUID, data: FundAccount, user: Admin, db: DB):
    if user.staff_scope is not None:
        raise HTTPException(403, "A full administrator must configure payout accounts.")
    driver = db.get(Driver, driver_id, with_for_update=True)
    if not driver:
        raise HTTPException(404, "Driver not found.")
    result = provider("GET", "/fund_accounts/"+data.reference)
    if result.get("id") != data.reference or result.get("active") is not True:
        raise HTTPException(409, "The payout beneficiary is unavailable.")
    driver.payout_fund_account = data.reference
    db.add(Audit(actor_id=user.id, subject_id=driver_id, action="PAYOUT_ACCOUNT_UPDATED"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That payout account is already assigned.")
    return {"configured":True}


def locked_settlement(db, earning_id):
    earning = db.get(Earning, earning_id, with_for_update=True)
    if not earning:
        raise HTTPException(404, "Earning not found.")
    payment = db.scalar(select(Payment).where(Payment.booking_id == earning.booking_id, Payment.kind == "BASE", Payment.status=="CAPTURED")
                        .with_for_update())
    if not payment:
        raise HTTPException(409, "A captured payment is required.")
    item = db.scalar(select(Payout).where(Payout.earning_id == earning.id).with_for_update())
    if not item:
        raise HTTPException(409, "Request a payout review first.")
    return earning, payment, item


def apply_status(db, earning, item, result):
    provider_id = result.get("id")
    if (not isinstance(provider_id, str) or not provider_id.startswith("pout_") or len(provider_id) > 80
            or (item.provider_payout_id and item.provider_payout_id != provider_id)
            or result.get("fund_account_id") != item.beneficiary or result.get("reference_id") != str(item.id)
            or result.get("amount") != item.amount_paise or result.get("currency") != "INR"):
        raise HTTPException(502, "The provider payout did not match this settlement.")
    statuses = {"queued":"QUEUED", "pending":"PENDING", "processing":"PROCESSING",
                "processed":"PROCESSED", "failed":"FAILED", "reversed":"REVERSED", "cancelled":"CANCELLED",
                "rejected":"REJECTED"}
    previous = item.status
    item.provider_payout_id = provider_id
    item.status = statuses.get(result.get("status"), "REQUIRES_RECONCILIATION")
    if item.status == "PROCESSED":
        earning.status = "SETTLED"
        if previous != "PROCESSED":
            db.add(Notice(user_id=earning.driver_id, message="A driver payout has been processed by RazorpayX."))
    elif item.status == "REVERSED":
        earning.status = "UNSETTLED"
        if previous != "REVERSED":
            db.add(Notice(user_id=earning.driver_id, message="A driver payout was reversed. Contact support."))
    db.commit()
    return {"status":item.status,"provider_payout_id":provider_id}


@router.post("/payouts/{earning_id}/submit")
def submit(earning_id: UUID, user: Admin, db: DB):
    key, _, source = configured()
    booking_id = db.scalar(select(Earning.booking_id).where(Earning.id==earning_id))
    if not booking_id:
        raise HTTPException(404,"Earning not found.")
    booking = db.get(Booking,booking_id,with_for_update=True)
    earning, payment, item = locked_settlement(db, earning_id)
    if booking.status == "DISPUTED":
        raise HTTPException(409,"Resolve the booking dispute before submitting this payout.")
    if item.status not in {"PENDING_REVIEW", "SUBMITTING"}:
        raise HTTPException(409, "This payout cannot be submitted from its current state.")
    if db.scalar(select(Refund.id).where(Refund.payment_id == payment.id, Refund.status != "FAILED")):
        raise HTTPException(409, "Resolve the booking refund before submitting this payout.")
    source_hash = digest(key + ":" + source)
    if item.status == "PENDING_REVIEW":
        driver = db.get(Driver, earning.driver_id)
        if not driver or not driver.payout_fund_account:
            raise HTTPException(409, "Configure the driver's provider payout account first.")
        if item.amount_paise <= 0:
            raise HTTPException(409, "This earning has no amount payable.")
        item.beneficiary = driver.payout_fund_account
        item.source_hash = source_hash
        item.status = "SUBMITTING"
        db.add(Audit(actor_id=user.id, subject_id=item.id, action="PAYOUT_SUBMITTED"))
        db.commit()
    elif not hmac.compare_digest(item.source_hash or "", source_hash):
        raise HTTPException(409, "The funding configuration changed. Reconcile the previous request.")
    db.commit()
    result = provider("POST", "/payouts", identity=item.id, body={
        "account_number":source, "fund_account_id":item.beneficiary, "amount":item.amount_paise,
        "currency":"INR", "mode":"IMPS", "purpose":"payout", "queue_if_low_balance":False,
        "reference_id":str(item.id),
    })
    earning, payment, item = locked_settlement(db, earning_id)
    db.refresh(item)
    if item.status != "SUBMITTING":
        return {"status":item.status,"provider_payout_id":item.provider_payout_id}
    return apply_status(db, earning, item, result)


@router.post("/payouts/{earning_id}/reconcile")
def reconcile(earning_id: UUID, data: PayoutReference, user: Admin, db: DB):
    configured()
    earning, payment, item = locked_settlement(db, earning_id)
    if item.status == "PENDING_REVIEW":
        raise HTTPException(409, "The payout has not been submitted.")
    result = provider("GET", "/payouts/"+data.reference)
    db.add(Audit(actor_id=user.id, subject_id=item.id, action="PAYOUT_RECONCILED"))
    return apply_status(db, earning, item, result)
