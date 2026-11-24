import csv
import io
import os
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from .auth import Current, DB, digest, require
from .bookings import ACTIVE, PICKUP_STAGES, locked_booking, release_assignment
from .dispatch import clear_point
from .models import (
    Audit, Booking, BookingEvent, Delivery, Driver, DriverAvatar, DriverSkills, Earning, Incident, Login, Notice, Payment, Payout, Refund, Review, Share,
    SavedAddress, Setting, Ticket, TicketReply, User,
)
from .schemas import Profile

router = APIRouter(tags=["dashboards"])
Customer = Annotated[User, Depends(require("customer"))]
DriverUser = Annotated[User, Depends(require("driver"))]
Admin = Annotated[User, Depends(require("admin"))]


class AddressInput(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    address: str = Field(min_length=5, max_length=250)


class ReviewInput(BaseModel):
    booking_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1200)


class DriverSkillsInput(BaseModel):
    years: int = Field(ge=0, le=70)
    languages: str = Field(min_length=2, max_length=150)
    qualifications: str = Field(default="", max_length=1500)
    emergency_contact: str = Field(pattern=r"^\+?[0-9]{10,15}$")
    consent: Literal[True]


class IncidentInput(BaseModel):
    booking_id: UUID
    description: str = Field(min_length=3, max_length=2000)


class NameInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class PricingInput(BaseModel):
    base: int = Field(ge=0, le=1_000_000)
    hourly: int = Field(gt=0, le=1_000_000)
    half_day: int = Field(gt=0, le=10_000_000)
    full_day: int = Field(gt=0, le=10_000_000)
    extra_hour: int | None = Field(default=None, ge=0, le=1_000_000)
    waiting_hour: int | None = Field(default=None, ge=0, le=1_000_000)
    night: int | None = Field(default=None, ge=0, le=1_000_000)
    pickup_allowance: int | None = Field(default=None, ge=0, le=1_000_000)
    cancellation: int | None = Field(default=None, ge=0, le=1000000)
    tax_bps: int | None = Field(default=None, ge=0, le=10000)


class CommissionInput(BaseModel):
    commission_bps: int = Field(ge=0, le=10000)


FARE_KEYS = {
    "base": ("FARE_BASE_PAISE", 9900),
    "hourly": ("FARE_HOURLY_PAISE", 22000),
    "half_day": ("FARE_HALF_DAY_PAISE", 79900),
    "full_day": ("FARE_FULL_DAY_PAISE", 149900),
    "commission_bps": ("COMMISSION_BPS", 2000),
    "extra_hour": ("FARE_EXTRA_HOUR_PAISE", 22000),
    "waiting_hour": ("FARE_WAITING_HOUR_PAISE", 12000),
    "night": ("FARE_NIGHT_PAISE", 0),
    "pickup_allowance": ("FARE_PICKUP_ALLOWANCE_PAISE", 0),
    "tax_bps": ("FARE_TAX_BPS", 0),
    "cancellation": ("FARE_CANCELLATION_PAISE", 0),
}


def settings(db):
    overrides = dict(db.execute(select(Setting.key, Setting.value)).tuples().all())
    return {key: overrides.get(key, int(os.getenv(env, str(default))))
            for key, (env, default) in FARE_KEYS.items()}


def update_settings(db, user, values, action):
    for key, value in sorted(values.items()):
        statement = insert(Setting).values(key=key, value=value)
        db.execute(statement.on_conflict_do_update(index_elements=[Setting.key], set_={"value": value}))
    db.add(Audit(actor_id=user.id, subject_id=user.id, action=action))
    db.commit()
    return values


@router.patch("/auth/me", response_model=Profile)
def update_profile(data: NameInput, user: Current, db: DB):
    user.name = data.name.strip()
    if len(user.name) < 2:
        raise HTTPException(422, "Enter a valid name.")
    db.commit()
    return user


@router.get("/customers/addresses")
def addresses(user: Customer, db: DB):
    return list(db.scalars(select(SavedAddress).where(SavedAddress.customer_id == user.id)
                           .order_by(SavedAddress.created_at.desc()).limit(100)))


@router.post("/customers/addresses", status_code=201)
def add_address(data: AddressInput, user: Customer, db: DB):
    item = SavedAddress(customer_id=user.id, **data.model_dump())
    db.add(item)
    db.commit()
    return item


@router.delete("/customers/addresses/{address_id}", status_code=204)
def remove_address(address_id: UUID, user: Customer, db: DB):
    item = db.get(SavedAddress, address_id, with_for_update=True)
    if not item or item.customer_id != user.id:
        raise HTTPException(404, "Address not found.")
    db.delete(item)
    db.commit()


@router.get("/reviews")
def reviews(user: Customer, db: DB):
    return list(db.scalars(select(Review).where(Review.customer_id == user.id).order_by(Review.created_at.desc()).limit(100)))


@router.post("/reviews", status_code=201)
def create_review(data: ReviewInput, user: Customer, db: DB):
    booking = locked_booking(db, data.booking_id)
    if booking.customer_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status != "COMPLETED" or not booking.driver_id:
        raise HTTPException(409, "Only completed trips can be reviewed.")
    if db.scalar(select(Review.id).where(Review.booking_id == booking.id)):
        raise HTTPException(409, "This trip already has a review.")
    item = Review(customer_id=user.id, driver_id=booking.driver_id, **data.model_dump())
    db.add(item)
    db.commit()
    return item


@router.get("/drivers/skill-passport")
def passport(user: DriverUser, db: DB):
    driver = db.get(Driver, user.id)
    skills = db.get(DriverSkills, user.id)
    completed = db.scalar(select(func.count()).select_from(Booking)
                          .where(Booking.driver_id == user.id, Booking.status == "COMPLETED"))
    count, average = db.execute(select(func.count(), func.avg(Review.rating))
                                .where(Review.driver_id == user.id)).one()
    expiry = driver.licence_expiry
    return {"experience": skills, "licence_current": bool(driver.approved and expiry and expiry > datetime.now(UTC)),
            "licence_reviewed_until": expiry, "verified_categories":driver.verified_categories if driver.approved else None, "completed_trips": completed, "review_count": count,
            "average_rating": round(float(average), 2) if average is not None else None}


@router.put("/drivers/skill-passport")
def update_passport(data: DriverSkillsInput, user: DriverUser, db: DB):
    values = data.model_dump(exclude={"consent"})
    statement = insert(DriverSkills).values(driver_id=user.id, consent_at=datetime.now(UTC), **values)
    db.execute(statement.on_conflict_do_update(index_elements=[DriverSkills.driver_id],
                                               set_={**values, "consent_at": statement.excluded.consent_at}))
    db.commit()
    return {"saved": True}


@router.get("/notifications")
def notifications(user: Current, db: DB):
    return list(db.scalars(select(Notice).where(Notice.user_id == user.id).order_by(Notice.created_at.desc()).limit(100)))


@router.post("/notifications/{notice_id}/read", status_code=204)
def mark_read(notice_id: UUID, user: Current, db: DB):
    item = db.get(Notice, notice_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Notification not found.")
    item.read = True
    db.commit()


@router.post("/incidents", status_code=201)
def report(data: IncidentInput, user: Current, db: DB):
    booking = locked_booking(db, data.booking_id)
    if user.id not in (booking.customer_id, booking.driver_id):
        raise HTTPException(404, "Booking not found.")
    item = Incident(reporter_id=user.id, **data.model_dump())
    db.add(item)
    for admin_id in db.scalars(select(User.id).where(User.role == "admin")):
        db.add(Notice(user_id=admin_id, message="A booking safety incident has been reported."))
    db.commit()
    return {"id": item.id, "status": item.status}


@router.get("/customers/receipts")
def receipts(user: Customer, db: DB):
    rows = db.execute(select(Payment, Booking).join(Booking)
                      .where(Booking.customer_id == user.id, Payment.status == "CAPTURED")
                      .order_by(Payment.created_at.desc()).limit(100))
    return [{"id": payment.id, "reference": payment.provider_payment_id, "amount_paise": payment.amount_paise,
             "booking_id": booking.id, "kind": payment.kind} for payment, booking in rows]


@router.get("/customers/receipts/{payment_id}")
def download_receipt(payment_id: UUID, user: Customer, db: DB):
    row = db.execute(select(Payment, Booking).join(Booking)
                     .where(Payment.id == payment_id, Booking.customer_id == user.id, Payment.status == "CAPTURED")).one_or_none()
    if not row:
        raise HTTPException(404, "Receipt not found.")
    payment, booking = row
    return Response(
        f"Drivewell payment receipt\nReceipt: {payment.id}\nBooking: {booking.id}\n"
        f"Charge: {payment.kind}\nRazorpay capture: {payment.provider_payment_id}\nAmount: INR {payment.amount_paise // 100}.{payment.amount_paise % 100:02d}\n",
        media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="receipt-{payment.id}.txt"'},
    )


@router.get("/admin/pricing")
def pricing(user: Admin, db: DB):
    return settings(db)


@router.put("/admin/pricing")
def set_pricing(data: PricingInput, user: Admin, db: DB):
    return update_settings(db, user, data.model_dump(exclude_none=True), "PRICING_UPDATED")


@router.put("/admin/commissions")
def set_commission(data: CommissionInput, user: Admin, db: DB):
    return update_settings(db, user, data.model_dump(), "COMMISSION_UPDATED")


@router.post("/admin/drivers/{driver_id}/suspend", status_code=204)
def suspend(driver_id: UUID, user: Admin, db: DB):
    driver = db.get(Driver, driver_id, with_for_update=True)
    if not driver:
        raise HTTPException(404, "Driver not found.")
    driver.approved = False
    driver.online = False
    driver.licence_expiry = None
    clear_point(driver)
    assignments = db.scalars(select(Booking).where(Booking.driver_id==driver_id, Booking.status.in_(PICKUP_STAGES))
                             .order_by(Booking.id).with_for_update())
    for booking in assignments:
        release_assignment(db, booking, user.id)
    db.add(Audit(actor_id=user.id, subject_id=driver_id, action="DRIVER_SUSPENDED"))
    db.add(Notice(user_id=driver_id, message="Your driver account was suspended. Contact support for review."))
    db.commit()


@router.post("/admin/incidents/{incident_id}/close", status_code=204)
def close_incident(incident_id: UUID, user: Admin, db: DB):
    item = db.get(Incident, incident_id, with_for_update=True)
    if not item:
        raise HTTPException(404, "Incident not found.")
    if item.status != "CLOSED":
        item.status = "CLOSED"
        db.add(Audit(actor_id=user.id, subject_id=item.id, action="INCIDENT_CLOSED"))
        db.add(Notice(user_id=item.reporter_id,message="Drivewell closed your safety report."))
        db.commit()


@router.post("/admin/support/{ticket_id}/close", status_code=204)
def close_ticket(ticket_id: UUID, user: Admin, db: DB):
    item = db.get(Ticket, ticket_id, with_for_update=True)
    if not item:
        raise HTTPException(404, "Ticket not found.")
    if item.status == "OPEN":
        item.status = "CLOSED"
        db.add(Audit(actor_id=user.id, subject_id=item.id, action="SUPPORT_TICKET_CLOSED"))
        db.add(Notice(user_id=item.user_id, message="Your support ticket was closed."))
        db.commit()


Directory = Literal["customers", "drivers", "staff", "bookings", "live-operations", "payments", "reviews", "incidents", "audit-logs"]


def directory_query(section, q):
    if section in {"customers", "staff", "drivers"}:
        role = {"customers": "customer", "staff": "admin", "drivers": "driver"}[section]
        columns = [User.id, User.name, User.email, User.role]
        if section == "staff":
            columns.append(User.staff_scope)
        if section == "customers":
            columns.append(User.disabled_at)
        if section == "drivers":
            columns.extend([Driver.approved, Driver.online, Driver.area, Driver.licence_expiry])
        stmt = select(*columns).select_from(User).where(User.role == role)
        if section == "drivers":
            stmt = stmt.join(Driver, Driver.user_id == User.id)
        if q:
            stmt = stmt.where(User.name.icontains(q, autoescape=True) | User.email.icontains(q, autoescape=True))
        return stmt, User.created_at, User.id
    specs = {
        "bookings": (Booking, [Booking.id, Booking.pickup, Booking.status, Booking.fare_paise, Booking.starts_at], Booking.pickup),
        "live-operations": (Booking, [Booking.id, Booking.area, Booking.status, Booking.starts_at], Booking.area),
        "payments": (Payment, [Payment.id, Payment.booking_id, Payment.amount_paise, Payment.kind, Payment.status], Payment.status),
        "reviews": (Review, [Review.id, Review.booking_id, Review.rating, Review.comment], Review.comment),
        "incidents": (Incident, [Incident.id, Incident.booking_id, Incident.description, Incident.status], Incident.description),
        "audit-logs": (Audit, [Audit.id, Audit.actor_id, Audit.subject_id, Audit.action], Audit.action),
    }
    model, columns, searchable = specs[section]
    stmt = select(*columns, model.created_at)
    if section == "live-operations":
        stmt = stmt.where(Booking.status.in_(ACTIVE | {"SEARCHING"}))
    if q:
        stmt = stmt.where(searchable.icontains(q, autoescape=True))
    return stmt, model.created_at, model.id


def csv_cell(value):
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@router.get("/admin/directory/{section}")
def directory(section: Directory, user: Admin, db: DB, q: Annotated[str, Query(max_length=100)] = "",
              page: Annotated[int, Query(ge=1, le=10000)] = 1, newest: bool = True, export: bool = False):
    stmt, created, identity = directory_query(section, q)
    stmt = stmt.order_by(created.desc() if newest else created.asc(), identity)
    if export:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        rows = db.execute(stmt.limit(5000)).mappings()
        writer.writerow(rows.keys())
        for row in rows:
            writer.writerow([csv_cell(value) for value in row.values()])
        return Response(buffer.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{section}.csv"'})
    rows = [dict(row) for row in db.execute(stmt.offset((page - 1) * 25).limit(26)).mappings()]
    return {"rows": rows[:25], "has_more": len(rows) > 25}


@router.get("/admin/refunds")
def list_refunds(user: Admin, db: DB):
    return list(db.scalars(select(Refund).order_by(Refund.created_at.desc()).limit(100)))


@router.post("/admin/refunds/{payment_id}", status_code=201)
def refund(payment_id: UUID, user: Admin, db: DB):
    from .payments import provider, settings as payment_settings

    if not payment_settings():
        raise HTTPException(503, "Razorpay is unconfigured.")
    payment = db.get(Payment, payment_id, with_for_update=True)
    if not payment or payment.status != "CAPTURED" or not payment.provider_payment_id:
        raise HTTPException(404, "Captured payment not found.")
    from .settlements import BLOCK_REFUND_STATUSES

    if db.scalar(select(Payout.id).join(Earning).where(Earning.booking_id == payment.booking_id,
                                                       Payout.status.in_(BLOCK_REFUND_STATUSES))):
        raise HTTPException(409, "A payout is in flight or processed. Reconcile it before refunding.")
    if db.scalar(select(Refund.id).where(Refund.payment_id == payment_id)):
        raise HTTPException(409, "A refund already exists. Check its status before retrying.")
    item = Refund(payment_id=payment_id, requested_by=user.id, amount_paise=payment.amount_paise,
                  status="REQUIRES_RECONCILIATION")
    db.add(item)
    db.add(Audit(actor_id=user.id, subject_id=payment_id, action="REFUND_REQUESTED"))
    db.commit()
    result = provider("POST", f"/payments/{payment.provider_payment_id}/refund",
                      body={"amount":item.amount_paise, "receipt":str(item.id)})
    return update_refund(db, item, payment, result)


def update_refund(db, item, payment, result):
    provider_id = result.get("id")
    if (not isinstance(provider_id, str) or not provider_id.startswith("rfnd_") or len(provider_id) > 80
            or result.get("payment_id") != payment.provider_payment_id or result.get("amount") != item.amount_paise
            or result.get("currency") != "INR" or (item.provider_refund_id and item.provider_refund_id != provider_id)):
        raise HTTPException(502, "Provider response requires reconciliation.")
    item.provider_refund_id = provider_id
    item.status = {"processed":"PROCESSED","pending":"PENDING","failed":"FAILED"}.get(
        result.get("status"), "REQUIRES_RECONCILIATION")
    db.commit()
    return item


class RefundReference(BaseModel):
    reference: str = Field(pattern=r"^rfnd_[A-Za-z0-9]+$", max_length=80)


@router.post("/admin/refunds/{refund_id}/reconcile")
def reconcile(refund_id: UUID, data: RefundReference, user: Admin, db: DB):
    from .payments import provider

    item = db.get(Refund, refund_id, with_for_update=True)
    if not item:
        raise HTTPException(404, "Refund not found.")
    payment = db.get(Payment, item.payment_id)
    result = provider("GET", "/refunds/" + data.reference)
    db.add(Audit(actor_id=user.id, subject_id=item.id, action="REFUND_RECONCILED"))
    return update_refund(db, item, payment, result)


@router.get("/admin/payouts")
def payouts(user: Admin, db: DB):
    rows = db.execute(select(Earning, Payout).outerjoin(Payout)
                      .order_by(Earning.created_at.desc()).limit(100))
    return [{"id":earning.id, "booking_id":earning.booking_id, "driver_id":earning.driver_id,
             "amount_paise":earning.net_paise, "status":item.status if item else earning.status,
             "provider_payout_id":item.provider_payout_id if item else None}
            for earning, item in rows]


@router.post("/admin/payouts/{earning_id}", status_code=201)
def request_payout(earning_id: UUID, user: Admin, db: DB):
    earning = db.get(Earning, earning_id, with_for_update=True)
    if not earning:
        raise HTTPException(404, "Earning not found.")
    if earning.status != "UNSETTLED" or db.scalar(select(Payout.id).where(Payout.earning_id == earning.id)):
        raise HTTPException(409, "A payout has already been recorded.")
    payment = db.scalar(select(Payment).where(Payment.booking_id == earning.booking_id, Payment.kind == "BASE", Payment.status == "CAPTURED"))
    if not payment:
        raise HTTPException(409, "A captured payment is required before requesting a settlement.")
    db.refresh(payment, with_for_update=True)
    if db.scalar(select(Refund.id).where(Refund.payment_id == payment.id, Refund.status != "FAILED")):
        raise HTTPException(409, "Resolve the booking refund before requesting a settlement.")
    item = Payout(earning_id=earning.id, amount_paise=earning.net_paise, requested_by=user.id)
    db.add(item)
    db.add(Audit(actor_id=user.id, subject_id=earning.id, action="PAYOUT_REVIEW_REQUESTED"))
    db.commit()
    return item


@router.get("/admin/settings")
def settings_status(user: Admin, db: DB):
    from .payments import demo_enabled, settings as payment_settings

    return {"payment_mode": "demo" if demo_enabled() else "razorpay", "online_checkout_configured": bool(payment_settings()),
            "online_payment_required": os.getenv("REQUIRE_ONLINE_PAYMENT", "false").lower() == "true",
            "reset_email_configured": all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_FROM", "PUBLIC_WEB_URL")),
            "service_area": "Bengaluru", "currency": "INR"}


class ShareToken(BaseModel):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


@router.post("/family-shares/view")
def view_share(data: ShareToken, db: DB):
    from .tracking import VISIBLE, latest, location_record

    item = db.scalar(select(Share).where(Share.token_hash == digest(data.token), ~Share.revoked,
                                         Share.expires_at > func.now()))
    booking = db.get(Booking, item.booking_id) if item else None
    if not booking or booking.status not in VISIBLE:
        raise HTTPException(404, "This trip share is unavailable.")
    location = latest(db, booking.id)
    return {"status":booking.status, "location":location_record(location)
            if location and location.driver_id == booking.driver_id else None}


@router.post("/family-shares/{booking_id}", status_code=201)
def create_share(booking_id: UUID, user: Customer, db: DB):
    from .tracking import VISIBLE

    booking = locked_booking(db, booking_id)
    if booking.customer_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status not in VISIBLE:
        raise HTTPException(409, "Sharing becomes available when the driver is en route.")
    raw = token_urlsafe(32)
    item = Share(booking_id=booking.id, customer_id=user.id, token_hash=digest(raw),
                 expires_at=datetime.now(UTC) + timedelta(hours=4))
    db.add(item)
    db.commit()
    return {"id":item.id, "token":raw, "expires_at":item.expires_at}


@router.get("/family-shares/{booking_id}")
def own_shares(booking_id: UUID, user: Customer, db: DB):
    items = db.scalars(select(Share).where(Share.booking_id == booking_id, Share.customer_id == user.id, Share.expires_at > func.now())
                       .order_by(Share.created_at.desc()).limit(100))
    return [{"id":item.id,"expires_at":item.expires_at,"revoked":item.revoked} for item in items]


@router.delete("/family-shares/{share_id}", status_code=204)
def revoke_share(share_id: UUID, user: Customer, db: DB):
    item = db.get(Share, share_id)
    if not item or item.customer_id != user.id:
        raise HTTPException(404, "Share not found.")
    item.revoked = True
    db.commit()




class StaffScopeInput(BaseModel):
    scope: Literal["operations", "finance", "support"]


@router.put("/admin/staff/{staff_id}/scope")
def set_staff_scope(staff_id: UUID, data: StaffScopeInput, user: Admin, db: DB):
    db.execute(text("SELECT pg_advisory_xact_lock(37932428)"))
    db.refresh(user)
    if user.staff_scope is not None:
        raise HTTPException(403, "A full administrator must manage staff access.")
    if staff_id == user.id:
        raise HTTPException(409, "You cannot change your own administrative access.")
    member = db.get(User, staff_id, with_for_update=True)
    if not member or member.role != "admin":
        raise HTTPException(404, "Staff member not found.")
    member.staff_scope = data.scope
    db.add(Audit(actor_id=user.id, subject_id=staff_id, action="STAFF_SCOPE_" + data.scope.upper()))
    db.commit()
    return {"scope": member.staff_scope}


@router.get("/admin/refunds/configuration")
def refunds_configuration(user: Admin, db: DB):
    from .payments import settings as payment_settings

    return {"online_checkout_configured": bool(payment_settings())}


class Preferences(BaseModel):
    email: bool
    sms: bool


@router.get("/notifications/preferences")
def notification_preferences(user: Current, db: DB):
    from .delivery import email_ready, sms_ready

    return {"email":user.notify_email,"sms":user.notify_sms,"email_configured":email_ready(),
            "sms_configured":sms_ready(),"sms_available":bool(user.verified_phone)}


@router.put("/notifications/preferences", status_code=204)
def change_preferences(data: Preferences, user: Current, db: DB):
    db.refresh(user, with_for_update=True)
    if data.sms and not user.verified_phone:
        raise HTTPException(409, "Verify your phone before opting in to SMS.")
    now = datetime.now(UTC)
    if data.email and not user.notify_email:
        user.notify_email_since = now
    if data.sms and not user.notify_sms:
        user.notify_sms_since = now
    user.notify_email = data.email
    user.notify_sms = data.sms
    db.commit()


@router.get("/admin/notifications/deliveries")
def notification_deliveries(user: Admin, db: DB):
    return list(db.scalars(select(Delivery).order_by(Delivery.created_at.desc()).limit(100)))


class ReplyInput(BaseModel):
    message: str = Field(min_length=2,max_length=2000)


def authorized_ticket(db, ticket_id, user, lock=False):
    from .permissions import permit

    if user.role == "admin":
        permit(user,"support")
    ticket = db.get(Ticket,ticket_id,with_for_update=lock)
    if not ticket or (user.role!="admin" and user.id!=ticket.user_id):
        raise HTTPException(404,"Support ticket not found.")
    return ticket


@router.get("/support/{ticket_id}/replies")
def ticket_replies(ticket_id: UUID, user: Current, db: DB):
    ticket = authorized_ticket(db,ticket_id,user)
    rows = db.execute(select(TicketReply,User.name,User.role).join(User,User.id==TicketReply.author_id)
                      .where(TicketReply.ticket_id==ticket.id).order_by(TicketReply.created_at).limit(250))
    return [{"id":item.id,"name":"Drivewell Support" if role=="admin" else name,"message":item.message,
             "created_at":item.created_at} for item,name,role in rows]


@router.post("/support/{ticket_id}/replies", status_code=201)
def reply(ticket_id: UUID, data: ReplyInput, user: Current, db: DB):
    ticket=authorized_ticket(db,ticket_id,user,lock=True)
    if ticket.status!="OPEN":
        raise HTTPException(409,"This ticket is closed.")
    item = TicketReply(ticket_id=ticket.id,author_id=user.id,message=data.message)
    db.add(item)
    if user.role=="admin":
        db.add(Notice(user_id=ticket.user_id,message="Drivewell Support replied to your ticket."))
    db.commit()
    return {"id":item.id}


@router.get("/incidents/{booking_id}")
def trip_incidents(booking_id: UUID, user: Current, db: DB):
    booking=db.get(Booking,booking_id)
    if not booking or user.id not in (booking.customer_id,booking.driver_id):
        raise HTTPException(404,"Booking not found.")
    return list(db.scalars(select(Incident).where(Incident.booking_id==booking.id,Incident.reporter_id==user.id)
                           .order_by(Incident.created_at.desc()).limit(25)))


@router.post("/incidents/{booking_id}/sos", status_code=201)
def sos(booking_id: UUID, user: Current, db: DB):
    booking=locked_booking(db,booking_id)
    if user.id not in (booking.customer_id,booking.driver_id):
        raise HTTPException(404,"Booking not found.")
    if booking.status not in ACTIVE:
        raise HTTPException(409,"Urgent alerts are available for active assignments.")
    existing=db.scalar(select(Incident).where(Incident.booking_id==booking.id,Incident.reporter_id==user.id,
                       Incident.status.in_(["URGENT","ESCALATED"])).limit(1))
    if existing:
        return {"id":existing.id,"status":existing.status}
    item=Incident(booking_id=booking.id,reporter_id=user.id,description="Urgent in-app safety alert",status="URGENT")
    db.add(item)
    for admin_id in db.scalars(select(User.id).where(User.role=="admin")):
        db.add(Notice(user_id=admin_id,message="Urgent safety alert. Open the incidents panel."))
    db.commit()
    return {"id":item.id,"status":item.status}


@router.post("/admin/incidents/{incident_id}/escalate", status_code=204)
def escalate(incident_id: UUID, user: Admin, db: DB):
    item=db.get(Incident,incident_id,with_for_update=True)
    if not item:
        raise HTTPException(404,"Incident not found.")
    if item.status=="CLOSED":
        raise HTTPException(409,"This incident is closed.")
    if item.status!="ESCALATED":
        item.status="ESCALATED"
        db.add(Notice(user_id=item.reporter_id,message="Drivewell escalated your report internally."))
        db.add(Audit(actor_id=user.id,subject_id=item.id,action="INCIDENT_ESCALATED"))
        db.commit()


class DisputeInput(BaseModel):
    reason: str = Field(min_length=8,max_length=2000)


@router.post("/admin/bookings/{booking_id}/dispute")
def open_dispute(booking_id: UUID, data: DisputeInput, user: Admin, db: DB):
    from .bookings import transition

    if user.staff_scope == "finance":
        raise HTTPException(403,"Operations or support permission is required.")
    booking=locked_booking(db,booking_id)
    if booking.status not in {"COMPLETED","CANCELLED","EXPIRED"}:
        raise HTTPException(409,"Open booking disputes only after the trip or request ends.")
    db.add(Incident(booking_id=booking.id,reporter_id=user.id,description=data.reason,status="ESCALATED"))
    db.add(Audit(actor_id=user.id,subject_id=booking.id,action="BOOKING_DISPUTED"))
    db.add(Notice(user_id=booking.customer_id,message="Drivewell opened a dispute for your booking."))
    transition(db,booking,user.id,"DISPUTED")
    db.commit()
    return {"status":"DISPUTED"}


@router.post("/admin/bookings/{booking_id}/resolve")
def resolve_dispute(booking_id: UUID, user: Admin, db: DB):
    from .bookings import transition
    from .models import BookingEvent

    if user.staff_scope == "finance":
        raise HTTPException(403,"Operations or support permission is required.")
    booking=locked_booking(db,booking_id)
    if booking.status!="DISPUTED":
        raise HTTPException(409,"This booking is not disputed.")
    prior=db.scalar(select(BookingEvent.status).where(BookingEvent.booking_id==booking.id,
                    BookingEvent.status.in_(["COMPLETED","CANCELLED","EXPIRED"]))
                    .order_by(BookingEvent.created_at.desc()).limit(1))
    if not prior:
        raise HTTPException(409,"The pre-dispute status requires manual review.")
    db.add(Audit(actor_id=user.id,subject_id=booking.id,action="BOOKING_DISPUTE_RESOLVED"))
    db.add(Notice(user_id=booking.customer_id,message="Drivewell resolved your booking dispute."))
    transition(db,booking,user.id,prior)
    db.commit()
    return {"status":prior}


@router.get("/drivers/avatar-status")
def avatar_status(user: DriverUser, db: DB):
    return {"has_photo":bool(db.scalar(select(DriverAvatar.driver_id).where(DriverAvatar.driver_id==user.id)))}


class CustomerAccess(BaseModel):
    suspended: bool


@router.put("/admin/customers/{customer_id}/access")
def customer_access(customer_id: UUID, data: CustomerAccess, user: Admin, db: DB):
    from .permissions import permit

    permit(user,"live-operations")
    member=db.get(User,customer_id,with_for_update=True)
    if not member or member.role!="customer":
        raise HTTPException(404,"Customer not found.")
    if data.suspended:
        active=db.scalar(select(Booking.id).where(Booking.customer_id==member.id,
                         Booking.status.in_(ACTIVE|{"SEARCHING"})).limit(1))
        if active:
            raise HTTPException(409,"Resolve open bookings before suspending this customer.")
        member.disabled_at=datetime.now(UTC)
        db.execute(delete(Login).where(Login.user_id==member.id))
    else:
        member.disabled_at=None
    db.add(Audit(actor_id=user.id,subject_id=member.id,
                 action="CUSTOMER_SUSPENDED" if data.suspended else "CUSTOMER_REACTIVATED"))
    db.commit()
    return {"suspended":data.suspended}


@router.get("/bookings/{booking_id}/events")
def timeline(booking_id: UUID, user: Current, db: DB):
    from .permissions import permit

    booking=db.get(Booking,booking_id)
    if user.role=="admin":
        permit(user,"bookings")
    if not booking or (user.role!="admin" and user.id not in (booking.customer_id,booking.driver_id)):
        raise HTTPException(404,"Booking not found.")
    rows=db.scalars(select(BookingEvent).where(BookingEvent.booking_id==booking.id)
                    .order_by(BookingEvent.created_at.desc()).limit(100))
    return [{"id":item.id,"status":item.status,"created_at":item.created_at} for item in rows]


@router.get("/drivers/payout-history")
def driver_payouts(user: DriverUser, db: DB):
    results=db.execute(select(Payout,Earning).join(Earning)
                       .where(Earning.driver_id==user.id).order_by(Payout.created_at.desc()).limit(100))
    return [{"id":item.id,"booking_id":earning.booking_id,"amount_paise":item.amount_paise,
             "status":item.status,"reference":item.provider_payout_id} for item,earning in results]
