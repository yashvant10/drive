import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from sqlalchemy import func, select, text
from starlette.concurrency import run_in_threadpool

from .bookings import PICKUP_STAGES, deadline, release_assignment, transition
from .db import Session
from .delivery import dispatch_notifications
from .models import Booking


def expire_bookings():
    with Session.begin() as db:
        no_shows = db.scalars(select(Booking).where(
            Booking.status.in_(PICKUP_STAGES),
            Booking.starts_at + text("interval '10 minutes'") <= func.now(),
            Booking.driver_id.is_not(None),
        ).order_by(Booking.starts_at).limit(100).with_for_update(skip_locked=True))
        for booking in no_shows:
            release_assignment(db, booking, None)
        items = db.scalars(select(Booking).where(Booking.status == "SEARCHING", deadline() <= func.now())
                           .limit(100).with_for_update(skip_locked=True))
        for booking in items:
            transition(db, booking, None, "EXPIRED")


async def job_loop():
    while True:
        try:
            await run_in_threadpool(expire_bookings)
        except Exception:
            logging.getLogger(__name__).exception("Booking expiry job failed")
        try:
            await run_in_threadpool(dispatch_notifications)
        except Exception:
            logging.getLogger(__name__).exception("Notification job failed")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(job_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
