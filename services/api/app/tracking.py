import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from .auth import Current, DB, cookie, digest, require
from .bookings import locked_booking
from .db import Session
from .models import Booking, DriverLocation, Login, User

router = APIRouter(tags=["tracking"])
DriverUser = Annotated[User, Depends(require("driver"))]
VISIBLE = {"DRIVER_EN_ROUTE", "DRIVER_ARRIVED", "IN_PROGRESS"}


class LocationInput(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float = Field(ge=0, le=10_000, allow_inf_nan=False)


def location_record(item):
    return {"latitude":item.latitude_e6 / 1_000_000, "longitude":item.longitude_e6 / 1_000_000,
            "accuracy_m":item.accuracy_m, "recorded_at":item.created_at,
            "stale":item.created_at < datetime.now(UTC) - timedelta(minutes=2)}


def latest(db, booking_id):
    return db.scalar(select(DriverLocation).where(DriverLocation.booking_id == booking_id)
                     .order_by(DriverLocation.created_at.desc()).limit(1))


@router.post("/locations/{booking_id}", status_code=201)
def update_location(booking_id: UUID, data: LocationInput, user: DriverUser, db: DB):
    booking = locked_booking(db, booking_id)
    if booking.driver_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status not in VISIBLE:
        raise HTTPException(409, "Location can only be shared during pickup or the trip.")
    recent = latest(db, booking_id)
    if recent and recent.created_at > datetime.now(UTC) - timedelta(seconds=5):
        raise HTTPException(429, "Wait at least five seconds between updates.")
    item = DriverLocation(booking_id=booking_id, driver_id=user.id, latitude_e6=round(data.latitude * 1_000_000),
                          longitude_e6=round(data.longitude * 1_000_000), accuracy_m=round(data.accuracy_m))
    db.add(item)
    db.commit()
    return location_record(item)


@router.get("/locations/{booking_id}")
def read_location(booking_id: UUID, user: Current, db: DB):
    booking = db.get(Booking, booking_id)
    if not booking or user.id not in (booking.customer_id, booking.driver_id):
        raise HTTPException(404, "Booking not found.")
    item = latest(db, booking_id) if booking.status in VISIBLE else None
    return location_record(item) if item and item.driver_id == booking.driver_id else None


def event_snapshot(token, booking_id):
    with Session() as db:
        user_id = db.scalar(select(Login.user_id).join(User,User.id==Login.user_id).where(Login.token_hash == digest(token), Login.expires_at > func.now(),User.disabled_at.is_(None)))
        booking = db.get(Booking, booking_id)
        if not user_id or not booking or user_id not in (booking.customer_id, booking.driver_id):
            return None
        location = latest(db, booking_id) if booking.status in VISIBLE else None
        return {"status":booking.status, "driver_id":str(booking.driver_id) if booking.driver_id else None,
                "location_event":str(location.id) if location and location.driver_id == booking.driver_id else None}


@router.websocket("/realtime/bookings/{booking_id}")
async def booking_events(socket: WebSocket, booking_id: UUID):
    token = socket.cookies.get(cookie)
    allowed = os.getenv("WEB_ORIGIN", "http://localhost:3000").split(",")
    if not token or socket.headers.get("origin") not in allowed:
        await socket.close(code=1008)
        return
    snapshot = await run_in_threadpool(event_snapshot, token, booking_id)
    if snapshot is None:
        await socket.close(code=1008)
        return
    await socket.accept()
    try:
        while snapshot is not None:
            await socket.send_json(snapshot)
            previous = snapshot
            while previous == snapshot:
                try:
                    message = await asyncio.wait_for(socket.receive(), timeout=3)
                    if message["type"] == "websocket.disconnect":
                        return
                    await socket.close(code=1008)
                    return
                except TimeoutError:
                    snapshot = await run_in_threadpool(event_snapshot, token, booking_id)
        await socket.close(code=1008)
    except WebSocketDisconnect:
        return
