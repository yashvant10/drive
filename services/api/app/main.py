import os
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from . import auth, avatars, billing, bookings, dispatch, handover_photos, operations, panels, payments, phone, pickup, settlements, tracking, workers
from .auth import Current, DB, require
from .models import Audit, Booking, Decline, Driver, DriverDocument, Earning, FareQuote, Incident, Payment, Refund, Ticket, User, Vehicle
from .permissions import permit
from .schemas import BookingInput, BookingRecord, DriverInput, DriverRecord, FareInput, TicketInput, TripProgress, VehicleInput, VehicleRecord

app = FastAPI(title="Drivewell API", version="0.2.0", lifespan=workers.lifespan)
api = APIRouter(prefix="/api/v1")
api.include_router(auth.router)
api.include_router(phone.router)
api.include_router(settlements.router)
api.include_router(panels.router)
api.include_router(operations.router)
api.include_router(handover_photos.router)
api.include_router(avatars.router)
api.include_router(dispatch.router)
api.include_router(pickup.router)
api.include_router(payments.router)
api.include_router(tracking.router)
Customer = Annotated[User, Depends(require("customer"))]
DriverUser = Annotated[User, Depends(require("driver"))]
Admin = Annotated[User, Depends(require("admin"))]


@app.middleware("http")
async def security(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        allowed = os.getenv("WEB_ORIGIN", "http://localhost:3000").split(",")
        if (origin and origin not in allowed) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Origin rejected."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@api.get("/vehicles", response_model=list[VehicleRecord])
def vehicles(user: Customer, db: DB):
    return list(db.scalars(select(Vehicle).where(Vehicle.customer_id == user.id, ~Vehicle.archived).order_by(Vehicle.created_at.desc())))


@api.post("/vehicles", response_model=VehicleRecord, status_code=201)
def add_vehicle(data: VehicleInput, user: Customer, db: DB):
    vehicle = Vehicle(customer_id=user.id, **data.model_dump())
    db.add(vehicle)
    db.commit()
    return vehicle


def editable_vehicle(db, user, vehicle_id):
    vehicle = bookings.owned_vehicle(db, user.id, vehicle_id, lock=True)
    has_booking = db.scalar(select(Booking.id).where(
        Booking.vehicle_id == vehicle_id, Booking.status.in_(bookings.ACTIVE | {"SEARCHING"})
    ).limit(1))
    if has_booking:
        raise HTTPException(409, "Resolve the open booking before changing this vehicle.")
    return vehicle


@api.put("/vehicles/{vehicle_id}", response_model=VehicleRecord)
def update_vehicle(vehicle_id: UUID, data: VehicleInput, user: Customer, db: DB):
    vehicle = editable_vehicle(db, user, vehicle_id)
    vehicle.label = data.label
    vehicle.transmission = data.transmission
    vehicle.category = data.category
    db.commit()
    return vehicle


@api.delete("/vehicles/{vehicle_id}", status_code=204)
def archive_vehicle(vehicle_id: UUID, user: Customer, db: DB):
    vehicle = editable_vehicle(db, user, vehicle_id)
    vehicle.archived = True
    db.commit()


@api.post("/fares/quote")
def fare(data: FareInput, user: Customer, db: DB):
    vehicle = bookings.owned_vehicle(db, user.id, data.vehicle_id)
    pricing = panels.settings(db)
    starts, hours, amounts = bookings.quote(data, pricing)
    pickup = dispatch.point(data.pickup_point)
    amounts["overage_hour_paise"] = pricing["extra_hour"]
    amounts["cancellation_paise"] = pricing["cancellation"]
    item = FareQuote(pickup_latitude=pickup[0],pickup_longitude=pickup[1],customer_id=user.id, vehicle_id=vehicle.id, area=data.area,
                     requested_start=data.starts_at, scheduled_start=starts, plan=data.plan,
                     requested_hours=data.hours, extra_hours=data.extra_hours, waiting_hours=data.waiting_hours, breakdown=amounts, hours=hours, base_paise=amounts["base_paise"],
                     service_paise=amounts["service_paise"], commission_bps=pricing["commission_bps"],
                     expires_at=datetime.now(UTC) + timedelta(minutes=10))
    db.add(item)
    db.commit()
    return {**amounts, "quote_id":item.id, "expires_at":item.expires_at, "hours":hours,
            "eligible_driver_available":bookings.available(db, vehicle, data.area, starts, hours, pickup)}


@api.post("/bookings", response_model=BookingRecord, status_code=201)
def create_booking(data: BookingInput, user: Customer, db: DB):
    db.refresh(user,with_for_update=True)
    if user.disabled_at:
        raise HTTPException(403,"This account is suspended.")
    pickup = dispatch.point(data.pickup_point)
    quote = db.get(FareQuote, data.quote_id, with_for_update=True) if data.quote_id else None
    if data.quote_id and (not quote or quote.customer_id != user.id):
        raise HTTPException(404, "Quote not found.")
    if quote:
        accepted = db.scalar(select(Booking).where(Booking.quote_id == quote.id))
        if accepted:
            return accepted
        if quote.expires_at <= datetime.now(UTC) or (quote.requested_start and quote.requested_start <= datetime.now(UTC)):
            raise HTTPException(409, "This quote expired. Get a new estimate.")
        if (quote.vehicle_id, quote.area, quote.requested_start, quote.plan, quote.requested_hours) != (
            data.vehicle_id, data.area, data.starts_at, data.plan, data.hours,
        ) or (quote.pickup_latitude, quote.pickup_longitude) != pickup or (
            quote.extra_hours,quote.waiting_hours
        ) != (data.extra_hours,data.waiting_hours):
            raise HTTPException(409, "The quote does not match this booking.")
    vehicle = bookings.owned_vehicle(db, user.id, data.vehicle_id, lock=True)
    pricing = panels.settings(db)
    if quote:
        starts, hours = quote.requested_start or datetime.now(UTC), quote.hours
        total = quote.breakdown["total_paise"] if quote.breakdown else quote.base_paise + quote.service_paise
        tax = quote.breakdown["tax_paise"] if quote.breakdown else 0
        commission = quote.commission_bps
    else:
        starts, hours, amounts = bookings.quote(data, pricing)
        total, tax, commission = amounts["total_paise"], amounts["tax_paise"], pricing["commission_bps"]
    booking = Booking(customer_id=user.id, vehicle_id=vehicle.id, pickup=data.pickup, destination=data.destination,
                      pickup_latitude=pickup[0],pickup_longitude=pickup[1],
                      instructions=data.instructions, area=data.area, starts_at=starts, hours=hours,
                      fare_paise=total, fare_tax_paise=tax, commission_bps=commission,
                      overage_hour_paise=(quote.breakdown or {}).get("overage_hour_paise",0) if quote else pricing["extra_hour"],
                      cancellation_paise=(quote.breakdown or {}).get("cancellation_paise",0) if quote else pricing["cancellation"], quote_id=data.quote_id, status="REQUESTED")
    db.add(booking)
    db.flush()
    bookings.transition(db, booking, user.id, "REQUESTED")
    return bookings.record(db, booking, user.id, "SEARCHING")


@api.get("/bookings", response_model=list[BookingRecord])
def list_bookings(user: Current, db: DB):
    query = select(Booking)
    if user.role == "admin":
        permit(user, "bookings")
    if user.role == "customer":
        query = query.where(Booking.customer_id == user.id)
    elif user.role == "driver":
        query = query.where(Booking.driver_id == user.id)
    return list(db.scalars(query.order_by(Booking.created_at.desc()).limit(100)))


@api.get("/bookings/{booking_id}", response_model=BookingRecord)
def booking_detail(booking_id: UUID, user: Current, db: DB):
    if user.role == "admin":
        permit(user, "bookings")
    booking = db.get(Booking, booking_id)
    if not booking or (user.role != "admin" and user.id not in (booking.customer_id, booking.driver_id)):
        raise HTTPException(404, "Booking not found.")
    return booking


@api.get("/bookings/{booking_id}/cancellation")
def cancellation_quote(booking_id: UUID, user: Customer, db: DB):
    booking = db.get(Booking, booking_id)
    if not booking or booking.customer_id != user.id:
        raise HTTPException(404,"Booking not found.")
    return {"amount_paise":billing.cancellation_amount(booking)}


@api.post("/bookings/{booking_id}/cancel", response_model=BookingRecord)
def cancel(booking_id: UUID, user: Customer, db: DB, accepted_fee_paise: Annotated[int, Query(ge=0)] = 0):
    booking = bookings.locked_booking(db, booking_id)
    if booking.customer_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status not in {"SEARCHING", "ASSIGNED", "CONFIRMED", "DRIVER_EN_ROUTE"}:
        raise HTTPException(409, "This booking cannot be cancelled at its current stage.")
    fee = billing.cancellation_amount(booking)
    if fee > accepted_fee_paise:
        raise HTTPException(409, "Review and accept the cancellation fee before cancelling.")
    billing.add_cancellation(db, booking, fee)
    return bookings.record(db, booking, user.id, "CANCELLED")


@api.get("/drivers/me", response_model=DriverRecord)
def driver_profile(user: DriverUser, db: DB):
    return db.get(Driver, user.id)


@api.put("/availability", response_model=DriverRecord)
def driver_availability(data: DriverInput, user: DriverUser, db: DB):
    driver = db.get(Driver, user.id, with_for_update=True)
    if data.online and (not driver.approved or not driver.licence_expiry or driver.licence_expiry <= datetime.now(UTC)):
        raise HTTPException(403, "Driver approval is required before going online.")
    for key, value in data.model_dump(exclude={"categories"},exclude_none=True).items():
        setattr(driver, key, value)
    if data.categories is not None:
        driver.categories = ",".join(sorted(set(data.categories)))
    if not driver.online:
        dispatch.clear_point(driver)
    db.commit()
    return driver


@api.get("/booking-offers")
def offers(user: DriverUser, db: DB):
    driver = db.get(Driver, user.id)
    if not driver.approved or not driver.online:
        return []
    rows = db.execute(select(Booking, Vehicle).join(Vehicle, Booking.vehicle_id == Vehicle.id)
                      .where(Booking.status == "SEARCHING", Booking.area == driver.area,
                             bookings.deadline() > func.now(), ~bookings.declined(user.id))
                      .order_by(Booking.created_at).limit(100))
    return [
        {"id": booking.id, "area": booking.area, "hours": booking.hours, "starts_at": booking.starts_at,
         "fare_paise": booking.fare_paise, "transmission": vehicle.transmission,
         "expires_at": booking.starts_at + bookings.EXPIRY_WINDOW, "category":vehicle.category,
         "distance_km":dispatch.distance_km(driver,(booking.pickup_latitude,booking.pickup_longitude),booking.starts_at)}
        for booking, vehicle in rows if bookings.eligible(driver, vehicle, booking.area)
        and dispatch.matches(db,driver,booking.starts_at,booking.hours,(booking.pickup_latitude,booking.pickup_longitude))
        and driver.licence_expiry > booking.starts_at
        and not bookings.conflict(db, user.id, booking.starts_at, booking.hours)
    ]


@api.post("/booking-offers/{booking_id}/accept", response_model=BookingRecord)
def accept(booking_id: UUID, user: DriverUser, db: DB):
    driver = db.get(Driver, user.id, with_for_update=True)
    booking = bookings.locked_booking(db, booking_id)
    if booking.driver_id == user.id and booking.status in bookings.ACTIVE:
        return booking
    vehicle = db.get(Vehicle, booking.vehicle_id)
    expired = booking.starts_at + bookings.EXPIRY_WINDOW <= datetime.now(UTC)
    if (booking.status != "SEARCHING" or expired or not bookings.eligible(driver, vehicle, booking.area)
            or driver.licence_expiry <= booking.starts_at or db.scalar(select(bookings.declined(user.id)).where(Booking.id == booking.id))):
        raise HTTPException(409, "This request is unavailable.")
    if (not dispatch.matches(db,driver,booking.starts_at,booking.hours,(booking.pickup_latitude,booking.pickup_longitude))
            or bookings.conflict(db, user.id, booking.starts_at, booking.hours)):
        raise HTTPException(409, "This request conflicts with an assignment.")
    booking.driver_id = user.id
    return bookings.record(db, booking, user.id, "ASSIGNED")


@api.post("/booking-offers/{booking_id}/decline", status_code=204)
def decline(booking_id: UUID, user: DriverUser, db: DB):
    driver = db.get(Driver, user.id, with_for_update=True)
    booking = bookings.locked_booking(db, booking_id)
    vehicle = db.get(Vehicle, booking.vehicle_id)
    if booking.status != "SEARCHING" or not bookings.eligible(driver, vehicle, booking.area):
        raise HTTPException(404, "Offer not found.")
    statement = insert(Decline).values(driver_id=user.id, booking_id=booking.id)
    db.execute(statement.on_conflict_do_nothing(index_elements=[Decline.booking_id, Decline.driver_id]))
    db.commit()


@api.post("/trips/{booking_id}/release", response_model=BookingRecord)
def release(booking_id: UUID, user: Current, db: DB):
    booking = bookings.locked_booking(db, booking_id)
    if user.role != "admin" and booking.driver_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if user.role == "admin":
        permit(user, "live-operations")
        db.add(Audit(actor_id=user.id, subject_id=booking.id, action="ASSIGNMENT_RELEASED"))
    return bookings.release(db, booking, user.id)


@api.post("/trips/{booking_id}/advance", response_model=BookingRecord)
def advance(booking_id: UUID, data: TripProgress, user: DriverUser, db: DB):
    booking = bookings.locked_booking(db, booking_id)
    if booking.driver_id != user.id:
        raise HTTPException(404, "Booking not found.")
    next_status = bookings.TRANSITIONS.get(booking.status)
    if booking.status != data.expected_status:
        raise HTTPException(409, "The booking status changed. Refresh and try again.")
    if not next_status:
        raise HTTPException(409, "This trip cannot advance.")
    if next_status in {"DRIVER_ARRIVED", "IN_PROGRESS"} and booking.starts_at > datetime.now(UTC) + timedelta(minutes=30):
        raise HTTPException(409, "This pickup is more than 30 minutes away.")
    if next_status == "IN_PROGRESS":
        profile = db.get(Driver, user.id)
        if not profile.approved or not profile.licence_expiry or profile.licence_expiry <= datetime.now(UTC):
            raise HTTPException(403, "A current verified licence is required to start the trip.")
    operations.check_trip_advance(db, booking, next_status)
    if next_status == "COMPLETED":
        billing.add_overage(db,booking)
    return bookings.record(db, booking, user.id, next_status)


@api.get("/support")
def tickets(user: Current, db: DB):
    query = select(Ticket)
    if user.role == "admin":
        permit(user, "support")
    else:
        query = query.where(Ticket.user_id == user.id)
    return [{"id": ticket.id, "message": ticket.message, "status": ticket.status}
            for ticket in db.scalars(query.order_by(Ticket.created_at.desc()).limit(100))]


@api.post("/support", status_code=201)
def support(data: TicketInput, user: Current, db: DB):
    ticket = Ticket(user_id=user.id, message=data.message)
    db.add(ticket)
    db.commit()
    return {"id": ticket.id, "status": ticket.status}


@api.get("/admin/metrics")
def metrics(user: Admin, db: DB):
    return {
        "Customers": db.scalar(select(func.count()).select_from(User).where(User.role == "customer")),
        "Approved drivers": db.scalar(select(func.count()).select_from(Driver).where(Driver.approved)),
        "Pending licence reviews": db.scalar(select(func.count()).select_from(DriverDocument).where(DriverDocument.status == "PENDING")),
        "Completed bookings": db.scalar(select(func.count()).select_from(Booking).where(Booking.status == "COMPLETED")),
        "Active bookings": db.scalar(select(func.count()).select_from(Booking).where(Booking.status.in_(bookings.ACTIVE))),
        "Searching bookings": db.scalar(select(func.count()).select_from(Booking).where(Booking.status == "SEARCHING")),
        "Cancelled bookings": db.scalar(select(func.count()).select_from(Booking).where(Booking.status == "CANCELLED")),
        "Captured payments": db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "CAPTURED")),
        "Open safety incidents": db.scalar(select(func.count()).select_from(Incident).where(Incident.status != "CLOSED")),
        "Open support tickets": db.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "OPEN")),
    }


@api.get("/admin/financials")
def financials(user: Admin, db: DB):
    return {
        "Captured payments": db.scalar(select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(Payment.status == "CAPTURED")),
        "Processed refunds": db.scalar(select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(Refund.status == "PROCESSED")),
        "Accrued commission": db.scalar(select(func.coalesce(func.sum(Earning.commission_paise), 0))),
        "Unsettled earnings": db.scalar(select(func.coalesce(func.sum(Earning.net_paise), 0)).where(Earning.status == "UNSETTLED")),
    }


app.include_router(api)
