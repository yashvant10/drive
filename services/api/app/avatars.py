from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.dialects.postgresql import insert

from .auth import Current, DB, require
from .handover_photos import MAX_SIZE, sanitized_image
from .models import Booking, DriverAvatar, User

router = APIRouter(tags=["drivers"])
DriverUser = Annotated[User, Depends(require("driver"))]


@router.put("/drivers/avatar", status_code=204)
def upload(user: DriverUser, db: DB, photo: Annotated[UploadFile,File()]):
    content=photo.file.read(MAX_SIZE+1)
    if len(content)>MAX_SIZE:
        raise HTTPException(413,"Photos must be at most 3 MB.")
    statement=insert(DriverAvatar).values(driver_id=user.id,content=sanitized_image(content))
    db.execute(statement.on_conflict_do_update(index_elements=[DriverAvatar.driver_id],
                                               set_={"content":statement.excluded.content}))
    db.commit()


@router.delete("/drivers/avatar",status_code=204)
def remove(user: DriverUser, db: DB):
    image=db.get(DriverAvatar,user.id,with_for_update=True)
    if image:
        db.delete(image)
        db.commit()


@router.get("/drivers/avatar")
def own(user: DriverUser, db: DB):
    return serve(db,user.id)


@router.get("/bookings/{booking_id}/driver-photo")
def booking_avatar(booking_id: UUID, user: Current, db: DB):
    booking=db.get(Booking,booking_id)
    if not booking or not booking.driver_id or user.id not in (booking.customer_id,booking.driver_id):
        raise HTTPException(404,"Driver photo not found.")
    return serve(db,booking.driver_id)


def serve(db, driver_id):
    image=db.get(DriverAvatar,driver_id)
    if not image:
        raise HTTPException(404,"Driver photo not found.")
    return Response(image.content,media_type="image/jpeg")
