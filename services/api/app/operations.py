import os
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select

from . import bookings, storage
from .auth import Current, DB, require
from .models import Acknowledgement, Audit, Booking, DemoPayment, Driver, DriverDocument, Earning, Handover, Notice, Payment, User
from .permissions import permit
from .schemas import DocumentReview, HandoverInput, HandoverRecord

router = APIRouter(tags=["operations"])
DriverUser = Annotated[User, Depends(require("driver"))]
Customer = Annotated[User, Depends(require("customer"))]
Admin = Annotated[User, Depends(require("admin"))]
IST = timezone(timedelta(hours=5, minutes=30))


def document_record(document):
    return {"id": document.id, "driver_id": document.driver_id, "licence_number": document.licence_number,
            "licence_expiry": document.licence_expiry, "status": document.status}


@router.post("/drivers/documents", status_code=201)
def upload_document(user: DriverUser, db: DB, document: Annotated[UploadFile, File()],
                    licence_number: Annotated[str, Form(min_length=5, max_length=30)],
                    expiry: Annotated[date, Form()]):
    if expiry < datetime.now(IST).date():
        raise HTTPException(422, "The licence must be current.")
    content = document.file.read(2_000_001)
    if document.content_type != "application/pdf" or not content.startswith(b"%PDF-") or len(content) > 2_000_000:
        raise HTTPException(422, "Upload a PDF up to 2 MB.")
    db.get(Driver, user.id, with_for_update=True)
    if db.scalar(select(DriverDocument.id).where(DriverDocument.driver_id == user.id, DriverDocument.status == "PENDING")):
        raise HTTPException(409, "A licence is already pending review.")
    item = DriverDocument(driver_id=user.id, licence_number=licence_number,
                          licence_expiry=datetime.combine(expiry + timedelta(days=1), time.min, IST), content=content)
    if storage.private_bucket():
        item.storage_key = f"licences/{user.id}/{uuid4()}.pdf"
        storage.put_document(item.storage_key, content)
        item.content = b""
    db.add(item)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # A failed commit may have reached PostgreSQL. Keep an orphan object
        # for controlled reconciliation instead of deleting a referenced file.
        if item.storage_key:
            import logging

            logging.getLogger(__name__).warning("Check the document storage reference after a failed commit: %s", item.storage_key)
        raise
    return document_record(item)


@router.get("/drivers/documents")
def own_documents(user: DriverUser, db: DB):
    items = db.scalars(select(DriverDocument).where(DriverDocument.driver_id == user.id)
                       .order_by(DriverDocument.created_at.desc()).limit(25))
    return [document_record(item) for item in items]


@router.get("/admin/verifications")
def verifications(user: Admin, db: DB):
    rows = db.execute(select(DriverDocument, User.name).join(User, User.id == DriverDocument.driver_id)
                      .order_by(DriverDocument.created_at.desc()).limit(100))
    return [{**document_record(item), "driver_name": name} for item, name in rows]


@router.get("/admin/verifications/{document_id}/download")
def download(document_id: UUID, user: Admin, db: DB):
    item = db.get(DriverDocument, document_id)
    if not item:
        raise HTTPException(404, "Document not found.")
    content = storage.get_document(item.storage_key) if item.storage_key else item.content
    db.add(Audit(actor_id=user.id, subject_id=item.id, action="LICENCE_DOWNLOADED"))
    db.commit()
    return Response(content, media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="licence.pdf"'})


@router.post("/admin/verifications/{document_id}")
def review(document_id: UUID, data: DocumentReview, user: Admin, db: DB):
    item = db.get(DriverDocument, document_id, with_for_update=True)
    if not item or item.status != "PENDING":
        raise HTTPException(409, "This document is no longer pending review.")
    driver = db.get(Driver, item.driver_id, with_for_update=True)
    if data.decision == "APPROVED":
        if item.licence_expiry <= datetime.now(UTC):
            raise HTTPException(409, "An expired licence cannot be approved.")
        driver.approved = True
        driver.licence_expiry = item.licence_expiry
        if data.verified_categories:
            driver.verified_categories = ",".join(sorted(set(data.verified_categories)))
    db.add(Notice(user_id=item.driver_id, message="Your licence submission was "+data.decision.lower()+"."))
    item.status = data.decision
    item.reviewed_by = user.id
    db.add(Audit(actor_id=user.id, subject_id=item.id, action="LICENCE_" + data.decision))
    db.commit()
    return document_record(item)


def get_handovers(db, booking_id):
    return db.execute(select(Handover, Acknowledgement.id).outerjoin(Acknowledgement)
                      .where(Handover.booking_id == booking_id).order_by(Handover.created_at)).all()


@router.get("/handovers/{booking_id}", response_model=list[HandoverRecord])
def list_handovers(booking_id: UUID, user: Current, db: DB):
    if user.role == "admin":
        permit(user, "bookings")
    booking = db.get(Booking, booking_id)
    if not booking or (user.role != "admin" and user.id not in (booking.customer_id, booking.driver_id)):
        raise HTTPException(404, "Booking not found.")
    return [HandoverRecord.model_validate(item).model_copy(update={"acknowledged": bool(ack)})
            for item, ack in get_handovers(db, booking.id)]


@router.post("/handovers/{booking_id}", response_model=HandoverRecord, status_code=201)
def handover(booking_id: UUID, data: HandoverInput, user: DriverUser, db: DB):
    booking = bookings.locked_booking(db, booking_id)
    if booking.driver_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status != {"before": "DRIVER_ARRIVED", "after": "IN_PROGRESS"}[data.stage]:
        raise HTTPException(409, "This stage is unavailable.")
    records = {item.stage: item for item, _ in get_handovers(db, booking.id)}
    if data.stage in records:
        raise HTTPException(409, "This handover has already been recorded.")
    if data.stage == "after" and data.odometer < records["before"].odometer:
        raise HTTPException(422, "The final odometer must be at least the initial reading.")
    item = Handover(booking_id=booking.id, **data.model_dump())
    db.add(item)
    db.commit()
    return item


@router.post("/handovers/{booking_id}/{stage}/acknowledge", status_code=204)
def acknowledge(booking_id: UUID, stage: str, user: Customer, db: DB):
    booking = bookings.locked_booking(db, booking_id)
    if booking.customer_id != user.id:
        raise HTTPException(404, "Booking not found.")
    for item, ack in get_handovers(db, booking.id):
        if item.stage == stage:
            if not ack:
                db.add(Acknowledgement(handover_id=item.id, customer_id=user.id))
                db.commit()
            return
    raise HTTPException(404, "Handover not found.")


def check_trip_advance(db, booking, next_status):
    required = {"IN_PROGRESS": "before", "COMPLETED": "after"}.get(next_status)
    if required and not any(item.stage == required and ack for item, ack in get_handovers(db, booking.id)):
        raise HTTPException(409, "Record the handover and ask the customer to acknowledge it.")
    if next_status == "IN_PROGRESS" and os.getenv("REQUIRE_PICKUP_PIN","true").lower()=="true":
        from .pickup import confirmed

        if not confirmed(db,booking.id):
            raise HTTPException(409,"Verify the customer's pickup code before starting the trip.")
    from .payments import demo_enabled

    demo = demo_enabled()
    if next_status == "IN_PROGRESS" and (demo or os.getenv("REQUIRE_ONLINE_PAYMENT", "false").lower() == "true"):
        if demo:
            paid = db.scalar(select(DemoPayment.id).where(DemoPayment.booking_id == booking.id, DemoPayment.kind == "BASE"))
        else:
            paid = db.scalar(select(Payment.id).where(Payment.booking_id == booking.id, Payment.kind == "BASE", Payment.status == "CAPTURED"))
        if not paid:
            raise HTTPException(409, "Complete checkout before starting the trip.")
    if next_status == "COMPLETED" and not demo and not db.scalar(select(DemoPayment.id).where(DemoPayment.booking_id == booking.id, DemoPayment.kind == "BASE")):
        from .panels import settings

        basis_points = booking.commission_bps if booking.commission_bps is not None else settings(db)["commission_bps"]
        if not 0 <= basis_points <= 10_000:
            raise RuntimeError("COMMISSION_BPS is outside its allowed range")
        gross = booking.fare_paise - booking.fare_tax_paise
        commission = gross * basis_points // 10_000
        db.add(Earning(driver_id=booking.driver_id, booking_id=booking.id, gross_paise=gross,
                       commission_paise=commission, net_paise=gross - commission))


@router.get("/drivers/earnings")
def earnings(user: DriverUser, db: DB):
    records = db.scalars(select(Earning).where(Earning.driver_id == user.id)
                         .order_by(Earning.created_at.desc()).limit(100))
    return [{"booking_id": item.booking_id, "gross_paise": item.gross_paise, "commission_paise": item.commission_paise,
             "net_paise": item.net_paise, "status": item.status} for item in records]
