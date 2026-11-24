import io
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import func, select

from .auth import Current, DB, require
from .bookings import locked_booking
from .models import Acknowledgement, Booking, Handover, HandoverPhoto, User
from .permissions import permit

router = APIRouter(prefix="/handovers", tags=["handovers"])
DriverUser = Annotated[User, Depends(require("driver"))]
MAX_SIZE = 3_000_000


def sanitized_image(content):
    try:
        with Image.open(io.BytesIO(content), formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.width * image.height > 16_000_000 or getattr(image, "is_animated", False):
                raise ValueError("Invalid dimensions")
            clean = ImageOps.exif_transpose(image).convert("RGB")
            clean.thumbnail((1600,1600))
            output = io.BytesIO()
            clean.save(output, "JPEG", quality=83)
            return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as cause:
        raise HTTPException(422, "Upload a valid JPG, PNG or WebP photo under 16 megapixels.") from cause


def authorize(booking_id, user, db):
    booking = db.get(Booking, booking_id)
    if user.role == "admin":
        permit(user, "bookings")
    if not booking or (user.role != "admin" and user.id not in (booking.customer_id, booking.driver_id)):
        raise HTTPException(404, "Booking not found.")
    return booking


@router.post("/{booking_id}/{stage}/photos", status_code=201)
def upload(booking_id: UUID, stage: str, user: DriverUser, db: DB, photo: Annotated[UploadFile, File()]):
    booking = locked_booking(db, booking_id)
    if booking.driver_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status != {"before":"DRIVER_ARRIVED","after":"IN_PROGRESS"}.get(stage):
        raise HTTPException(409, "This handover is closed.")
    item = db.scalar(select(Handover).where(Handover.booking_id == booking.id, Handover.stage == stage))
    if not item:
        raise HTTPException(409, "Record the handover before uploading photos.")
    if db.scalar(select(Acknowledgement.id).where(Acknowledgement.handover_id == item.id)):
        raise HTTPException(409, "Photos cannot be changed after acknowledgement.")
    count = db.scalar(select(func.count()).select_from(HandoverPhoto).where(HandoverPhoto.handover_id == item.id))
    if count >= 4:
        raise HTTPException(409, "Each handover supports up to four photos.")
    body = photo.file.read(MAX_SIZE + 1)
    if len(body) > MAX_SIZE:
        raise HTTPException(413, "Photos must be at most 3 MB.")
    image = HandoverPhoto(handover_id=item.id, content=sanitized_image(body))
    db.add(image)
    db.commit()
    return {"id":image.id,"stage":stage}


@router.get("/{booking_id}/photos")
def photos(booking_id: UUID, user: Current, db: DB):
    authorize(booking_id, user, db)
    return [{"id":identity,"stage":stage} for identity, stage in db.execute(
        select(HandoverPhoto.id,Handover.stage).join(Handover)
        .where(Handover.booking_id == booking_id).order_by(HandoverPhoto.created_at)
    )]


@router.get("/{booking_id}/photos/{photo_id}")
def download(booking_id: UUID, photo_id: UUID, user: Current, db: DB):
    authorize(booking_id, user, db)
    item = db.scalar(select(HandoverPhoto).join(Handover)
                     .where(HandoverPhoto.id == photo_id,Handover.booking_id == booking_id))
    if not item:
        raise HTTPException(404, "Photo not found.")
    return Response(item.content, media_type="image/jpeg")
