from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text

from . import dispatch
from .models import Booking, BookingEvent, Decline, Driver, Notice, Vehicle

PICKUP_STAGES = {"ASSIGNED", "CONFIRMED", "DRIVER_EN_ROUTE"}
EXPIRY_WINDOW = timedelta(minutes=15)
MESSAGES = {
    "ASSIGNED":"A driver accepted your request.",
    "DRIVER_EN_ROUTE":"Your driver is on the way.",
    "DRIVER_ARRIVED":"Your driver has arrived.",
    "IN_PROGRESS":"Your trip has started.",
    "COMPLETED":"Your trip is complete.",
    "EXPIRED":"The request expired before a driver accepted.",
    "CANCELLED":"Your booking was cancelled.",
}
ACTIVE = {"ASSIGNED", "CONFIRMED", "DRIVER_EN_ROUTE", "DRIVER_ARRIVED", "IN_PROGRESS"}
TRANSITIONS = {
    "ASSIGNED": "CONFIRMED",
    "CONFIRMED": "DRIVER_EN_ROUTE",
    "DRIVER_EN_ROUTE": "DRIVER_ARRIVED",
    "DRIVER_ARRIVED": "IN_PROGRESS",
    "IN_PROGRESS": "COMPLETED",
}


def owned_vehicle(db, customer_id, vehicle_id: UUID, lock=False):
    vehicle = db.get(Vehicle, vehicle_id, with_for_update=lock)
    if not vehicle or vehicle.archived or vehicle.customer_id != customer_id:
        raise HTTPException(404, "Vehicle not found.")
    return vehicle


def quote(data, pricing):
    now = datetime.now(UTC)
    starts = data.starts_at or now
    if data.starts_at and (starts < now or starts > now + timedelta(days=90)):
        raise HTTPException(422, "Choose a time within the next 90 days.")
    hours = {"half-day": 4, "full-day": 8}.get(data.plan, data.hours)
    total_hours = hours + data.extra_hours + data.waiting_hours
    if total_hours > 16:
        raise HTTPException(422,"A booking can cover at most 16 hours.")
    base = pricing["base"]
    service = {
        "hourly": pricing["hourly"] * hours,
        "half-day": pricing["half_day"],
        "full-day": pricing["full_day"],
    }[data.plan]
    pickup_hour = starts.astimezone(ZoneInfo("Asia/Kolkata")).hour
    components = {"base_paise":base, "service_paise":service,
                  "extra_paise":pricing["extra_hour"]*data.extra_hours,
                  "waiting_paise":pricing["waiting_hour"]*data.waiting_hours,
                  "night_paise":pricing["night"] if pickup_hour>=22 or pickup_hour<6 else 0,
                  "pickup_allowance_paise":pricing["pickup_allowance"]}
    subtotal=sum(components.values())
    tax=(subtotal*pricing["tax_bps"]+5000)//10000
    return starts,total_hours,{**components,"tax_paise":tax,"total_paise":subtotal+tax}


def conflict(db, driver_id, starts, hours):
    existing = db.scalars(select(Booking).where(Booking.driver_id == driver_id, Booking.status.in_(ACTIVE)))
    ends = starts + timedelta(hours=hours)
    return any(
        item.status == "IN_PROGRESS"
        or (item.starts_at < ends and starts < item.starts_at + timedelta(hours=item.hours))
        for item in existing
    )


def eligible(driver, vehicle, area):
    return (driver.approved and driver.online and driver.area == area
            and driver.licence_expiry is not None and driver.licence_expiry >= datetime.now(UTC)
            and driver.transmission in (vehicle.transmission, "both")
            and (not driver.categories or vehicle.category in driver.categories.split(","))
            and (not driver.verified_categories or vehicle.category in driver.verified_categories.split(",")))


def available(db, vehicle, area, starts, hours, pickup):
    drivers = db.scalars(select(Driver).where(Driver.approved, Driver.online, Driver.area == area,
                                              Driver.licence_expiry > starts,
                                              Driver.transmission.in_([vehicle.transmission, "both"])))
    return any(eligible(driver,vehicle,area) and dispatch.matches(db,driver,starts,hours,pickup)
               and not conflict(db, driver.user_id, starts, hours) for driver in drivers)


def locked_booking(db, booking_id):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking:
        raise HTTPException(404, "Booking not found.")
    return booking


def deadline():
    return Booking.starts_at + text("interval '15 minutes'")


def declined(driver_id):
    return select(Decline.id).where(Decline.booking_id == Booking.id, Decline.driver_id == driver_id).exists()


def transition(db, booking, actor_id, status):
    booking.status = status
    db.add(BookingEvent(booking_id=booking.id, actor_id=actor_id, status=status))
    if message := MESSAGES.get(status):
        db.add(Notice(user_id=booking.customer_id, message=message))
    if status == "CANCELLED" and booking.driver_id:
        db.add(Notice(user_id=booking.driver_id, message="A customer cancelled your assigned booking."))


def record(db, booking, actor_id, status):
    transition(db, booking, actor_id, status)
    db.commit()
    db.refresh(booking)
    return booking


def release_assignment(db, booking, actor_id):
    from sqlalchemy.dialects.postgresql import insert

    driver_id = booking.driver_id
    if booking.status not in PICKUP_STAGES or not driver_id:
        raise HTTPException(409, "Only bookings before arrival can be reassigned.")
    statement = insert(Decline).values(driver_id=driver_id, booking_id=booking.id)
    db.execute(statement.on_conflict_do_nothing(index_elements=[Decline.booking_id, Decline.driver_id]))
    booking.driver_id = None
    db.add(Notice(user_id=booking.customer_id, message="Your driver was released. We will look for a replacement if time remains."))
    db.add(Notice(user_id=driver_id, message="Your booking assignment was released."))
    status = "SEARCHING" if booking.starts_at + EXPIRY_WINDOW > datetime.now(UTC) else "EXPIRED"
    transition(db, booking, actor_id, status)


def release(db, booking, actor_id):
    release_assignment(db, booking, actor_id)
    db.commit()
    db.refresh(booking)
    return booking
