from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from .auth import DB, require
from .models import Booking, DemoPayment, Incident, Payment, Payout, Refund, User

router = APIRouter(prefix="/owner", tags=["business owner"])
Owner = Annotated[User, Depends(require("owner"))]


@router.get("/overview")
def overview(user: Owner, db: DB):
    result = db.execute(select(
        select(func.count()).select_from(Booking).scalar_subquery().label("booking_count"),
        select(func.count()).select_from(Booking).where(Booking.status == "COMPLETED").scalar_subquery().label("completed_trips"),
        select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(Payment.status == "CAPTURED").scalar_subquery().label("captured_paise"),
        select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(Refund.status == "PROCESSED").scalar_subquery().label("refunded_paise"),
        select(func.coalesce(func.sum(Payout.amount_paise), 0)).where(Payout.status == "PROCESSED").scalar_subquery().label("paid_out_paise"),
        select(func.count()).select_from(Incident).where(Incident.status != "CLOSED").scalar_subquery().label("open_safety_cases"),
        select(func.count()).select_from(DemoPayment).scalar_subquery().label("demo_payment_count"),
    )).mappings().one()
    return dict(result)
