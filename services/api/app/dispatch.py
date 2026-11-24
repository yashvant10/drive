import math
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .auth import DB, require
from .models import Driver, DriverWindow, User
from .schemas import PickupPoint

router = APIRouter(prefix="/availability", tags=["availability"])
DriverUser = Annotated[User, Depends(require("driver"))]


class WindowInput(BaseModel):
    starts_at: datetime
    ends_at: datetime


@router.get("/windows")
def windows(user: DriverUser, db: DB):
    return list(db.scalars(select(DriverWindow).where(DriverWindow.driver_id == user.id,
                           DriverWindow.ends_at > datetime.now(UTC)).order_by(DriverWindow.starts_at).limit(120)))


@router.post("/windows", status_code=201)
def add_window(data: WindowInput, user: DriverUser, db: DB):
    now = datetime.now(UTC)
    if (data.starts_at.utcoffset() is None or data.ends_at.utcoffset() is None
            or not now < data.starts_at < data.ends_at <= now + timedelta(days=90)
            or data.ends_at - data.starts_at > timedelta(hours=24)):
        raise HTTPException(422, "Choose a future window of up to 24 hours, within the next 90 days.")
    db.get(Driver, user.id, with_for_update=True)
    overlapping = db.scalar(select(DriverWindow.id).where(DriverWindow.driver_id == user.id,
                           DriverWindow.starts_at < data.ends_at, DriverWindow.ends_at > data.starts_at).limit(1))
    if overlapping:
        raise HTTPException(409, "This window overlaps existing availability.")
    item = DriverWindow(driver_id=user.id, **data.model_dump())
    db.add(item)
    db.commit()
    return item


@router.delete("/windows/{window_id}", status_code=204)
def delete_window(window_id: UUID, user: DriverUser, db: DB):
    db.get(Driver, user.id, with_for_update=True)
    item = db.get(DriverWindow, window_id)
    if not item or item.driver_id != user.id:
        raise HTTPException(404, "Availability window not found.")
    db.delete(item)
    db.commit()


@router.put("/dispatch-point")
def update_point(data: PickupPoint, user: DriverUser, db: DB):
    item = db.get(Driver, user.id, with_for_update=True)
    if not item.online:
        raise HTTPException(409, "Go online before sharing your dispatch location.")
    item.dispatch_latitude, item.dispatch_longitude = point(data)
    item.dispatch_at = datetime.now(UTC)
    db.commit()
    return {"recorded_at":item.dispatch_at}


@router.delete("/dispatch-point", status_code=204)
def remove_point(user: DriverUser, db: DB):
    item = db.get(Driver, user.id, with_for_update=True)
    clear_point(item)
    db.commit()


def clear_point(driver):
    driver.dispatch_latitude = driver.dispatch_longitude = driver.dispatch_at = None


def point(location):
    return (round(location.latitude * 1_000_000), round(location.longitude * 1_000_000)) if location else (None,None)


def distance_km(driver, pickup, starts):
    now = datetime.now(UTC)
    if (pickup[0] is None or not driver.dispatch_at or driver.dispatch_latitude is None
            or driver.dispatch_at < now - timedelta(minutes=20) or starts > now + timedelta(minutes=30)):
        return None
    lat1, lon1 = (math.radians(coordinate / 1_000_000) for coordinate in pickup)
    lat2, lon2 = (math.radians(coordinate / 1_000_000)
                  for coordinate in (driver.dispatch_latitude, driver.dispatch_longitude))
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return round(6371 * 2 * math.asin(math.sqrt(min(1, a))), 1)


def matches_window(db, driver, starts, hours):
    if not driver.schedule_only:
        return True
    return bool(db.scalar(select(DriverWindow.id).where(DriverWindow.driver_id == driver.user_id,
                          DriverWindow.starts_at <= starts,
                          DriverWindow.ends_at >= starts + timedelta(hours=hours)).limit(1)))


def matches(db, driver, starts, hours, pickup):
    if not matches_window(db, driver, starts, hours):
        return False
    distance = distance_km(driver, pickup, starts)
    return distance is None or distance <= 25
