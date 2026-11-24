from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Transmission = Literal["manual", "automatic"]
Area = Literal["Bengaluru"]


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=2, max_length=100)
    role: Literal["customer", "driver"] = "customer"


class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    email: EmailStr
    role: str
    staff_scope: str | None = None


VehicleCategory = Literal["hatchback", "sedan", "suv", "mpv"]


class VehicleInput(BaseModel):
    category: VehicleCategory = "sedan"
    label: str = Field(min_length=2, max_length=100)
    transmission: Transmission


class VehicleRecord(VehicleInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class PickupPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class FareInput(BaseModel):
    pickup_point: PickupPoint | None = None
    vehicle_id: UUID
    area: Area = "Bengaluru"
    starts_at: datetime | None = None
    plan: Literal["hourly", "half-day", "full-day"] = "hourly"
    hours: int = Field(default=2, ge=1, le=12)
    extra_hours: int = Field(default=0, ge=0, le=4)
    waiting_hours: int = Field(default=0, ge=0, le=3)

    @field_validator("starts_at")
    @classmethod
    def require_timezone(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Provide a timezone")
        return value


class BookingInput(FareInput):
    quote_id: UUID | None = None
    pickup: str = Field(min_length=5, max_length=250)
    destination: str = Field(default="", max_length=250)
    instructions: str = Field(default="", max_length=1000)


class BookingRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pickup: str
    destination: str
    area: str
    starts_at: datetime
    hours: int
    fare_paise: int
    status: str
    driver_id: UUID | None
    driver_name: str | None
    driver_has_photo: bool
    pickup_latitude: int | None
    pickup_longitude: int | None


class DriverInput(BaseModel):
    categories: list[VehicleCategory] | None = Field(default=None, max_length=4)
    schedule_only: bool | None = None
    area: Area
    transmission: Literal["manual", "automatic", "both"]
    online: bool


class DriverRecord(BaseModel):
    categories: str
    schedule_only: bool
    dispatch_at: datetime | None
    model_config = ConfigDict(from_attributes=True)
    approved: bool
    online: bool
    area: str
    transmission: str


class TicketInput(BaseModel):
    message: str = Field(min_length=10, max_length=2000)


class DocumentReview(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    verified_categories: list[VehicleCategory] | None = Field(default=None, min_length=1,max_length=4)


class HandoverInput(BaseModel):
    stage: Literal["before", "after"]
    odometer: int = Field(ge=0, le=2_000_000)
    fuel_percent: int = Field(ge=0, le=100)
    condition: str = Field(min_length=3, max_length=2000)


class HandoverRecord(HandoverInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    acknowledged: bool = False


class ResetRequest(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str = Field(pattern="^[A-Za-z0-9_-]{43}$")
    password: str = Field(min_length=12, max_length=128)


class TripProgress(BaseModel):
    expected_status: Literal["ASSIGNED", "CONFIRMED", "DRIVER_EN_ROUTE", "DRIVER_ARRIVED", "IN_PROGRESS"]
