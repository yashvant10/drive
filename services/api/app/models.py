from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column

from .db import Base


class Record:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Record, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role in ('customer','driver','admin')"),)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    verified_phone: Mapped[str | None] = mapped_column(String(16), unique=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notify_email_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_sms_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    staff_scope: Mapped[str | None] = mapped_column(String(20))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Login(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthLimit(Base):
    __tablename__ = "auth_limits"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Vehicle(Record, Base):
    __tablename__ = "vehicles"
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    transmission: Mapped[str] = mapped_column(String(12))
    category: Mapped[str] = mapped_column(String(15), default="sedan", server_default="sedan")


class Driver(Base):
    __tablename__ = "driver_profiles"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    payout_fund_account: Mapped[str | None] = mapped_column(String(80), unique=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    licence_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    area: Mapped[str] = mapped_column(String(60), default="")
    transmission: Mapped[str] = mapped_column(String(12), default="")
    categories: Mapped[str] = mapped_column(String(60), default="", server_default="")
    verified_categories: Mapped[str | None] = mapped_column(String(60))
    schedule_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    dispatch_latitude: Mapped[int | None] = mapped_column(Integer)
    dispatch_longitude: Mapped[int | None] = mapped_column(Integer)
    dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DriverAvatar(Base):
    __tablename__ = "driver_avatars"
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("driver_profiles.user_id"), primary_key=True)
    content: Mapped[bytes]


class Booking(Record, Base):
    __tablename__ = "bookings"
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    driver_name = column_property(select(User.name).where(User.id == driver_id).scalar_subquery())
    driver_has_photo = column_property(select(DriverAvatar.driver_id).where(DriverAvatar.driver_id == driver_id).exists())
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicles.id"))
    pickup: Mapped[str] = mapped_column(String(250))
    pickup_latitude: Mapped[int | None] = mapped_column(Integer)
    pickup_longitude: Mapped[int | None] = mapped_column(Integer)
    destination: Mapped[str] = mapped_column(String(250))
    area: Mapped[str] = mapped_column(String(60), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hours: Mapped[int] = mapped_column(Integer)
    fare_paise: Mapped[int] = mapped_column(Integer)
    overage_hour_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cancellation_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fare_tax_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    quote_id: Mapped[UUID | None] = mapped_column(ForeignKey("fare_quotes.id"), unique=True)
    commission_bps: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(25), index=True)
    instructions: Mapped[str] = mapped_column(Text, default="")


class BookingEvent(Record, Base):
    __tablename__ = "booking_events"
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(25))


class Ticket(Record, Base):
    __tablename__ = "support_tickets"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")


class DriverDocument(Record, Base):
    __tablename__ = "driver_documents"
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("driver_profiles.user_id"), index=True)
    licence_number: Mapped[str] = mapped_column(String(30))
    licence_expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content: Mapped[bytes]
    storage_key: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class Audit(Record, Base):
    __tablename__ = "audit_logs"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    subject_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(60))


class Handover(Record, Base):
    __tablename__ = "vehicle_handovers"
    __table_args__ = (UniqueConstraint("booking_id", "stage"),)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    stage: Mapped[str] = mapped_column(String(10))
    odometer: Mapped[int] = mapped_column(Integer)
    fuel_percent: Mapped[int] = mapped_column(Integer)
    condition: Mapped[str] = mapped_column(Text)


class Acknowledgement(Record, Base):
    __tablename__ = "handover_acknowledgements"
    handover_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle_handovers.id"), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class Earning(Record, Base):
    __tablename__ = "earnings"
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), unique=True)
    gross_paise: Mapped[int] = mapped_column(Integer)
    commission_paise: Mapped[int] = mapped_column(Integer)
    net_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="UNSETTLED")


class Payment(Record, Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("booking_id", "kind", name="uq_payments_booking_kind"),)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"))
    kind: Mapped[str] = mapped_column(String(20), default="BASE", server_default="BASE")
    amount_paise: Mapped[int] = mapped_column(Integer)
    provider_order_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20))


class PaymentEvent(Record, Base):
    __tablename__ = "payment_events"
    payment_id: Mapped[UUID] = mapped_column(ForeignKey("payments.id"), index=True)
    provider_event_id: Mapped[str] = mapped_column(String(150), unique=True)
    kind: Mapped[str] = mapped_column(String(50))


class PasswordReset(Base):
    __tablename__ = "password_resets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DriverLocation(Record, Base):
    __tablename__ = "driver_locations"
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    latitude_e6: Mapped[int] = mapped_column(Integer)
    longitude_e6: Mapped[int] = mapped_column(Integer)
    accuracy_m: Mapped[int] = mapped_column(Integer)


class SavedAddress(Record, Base):
    __tablename__ = "saved_addresses"
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(250))


class Review(Record, Base):
    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating between 1 and 5"),)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text)


class DriverSkills(Base):
    __tablename__ = "driver_skills"
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    years: Mapped[int] = mapped_column(Integer)
    languages: Mapped[str] = mapped_column(String(150))
    qualifications: Mapped[str] = mapped_column(Text)
    emergency_contact: Mapped[str] = mapped_column(String(20))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notice(Record, Base):
    __tablename__ = "notifications"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(String(250))
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class Incident(Record, Base):
    __tablename__ = "safety_incidents"
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    reporter_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)


class Setting(Base):
    __tablename__ = "platform_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


class Decline(Record, Base):
    __tablename__ = "booking_declines"
    __table_args__ = (UniqueConstraint("booking_id", "driver_id"),)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)


class Refund(Record, Base):
    __tablename__ = "refunds"
    payment_id: Mapped[UUID] = mapped_column(ForeignKey("payments.id"), unique=True)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    amount_paise: Mapped[int] = mapped_column(Integer)
    provider_refund_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(30))


class Payout(Record, Base):
    __tablename__ = "payouts"
    earning_id: Mapped[UUID] = mapped_column(ForeignKey("earnings.id"), unique=True)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    amount_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="PENDING_REVIEW")
    provider_payout_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    beneficiary: Mapped[str | None] = mapped_column(String(80))
    source_hash: Mapped[str | None] = mapped_column(String(64))


class Share(Record, Base):
    __tablename__ = "family_shares"
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class PhoneChallenge(Base):
    __tablename__ = "phone_challenges"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    phone: Mapped[str] = mapped_column(String(16))
    provider_sid: Mapped[str] = mapped_column(String(40), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Delivery(Record, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (UniqueConstraint("notice_id", "channel"),)
    notice_id: Mapped[UUID] = mapped_column(ForeignKey("notifications.id"), index=True)
    channel: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(25), index=True)
    provider_ref: Mapped[str | None] = mapped_column(String(80))


class FareQuote(Record, Base):
    __tablename__ = "fare_quotes"
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicles.id"))
    area: Mapped[str] = mapped_column(String(60))
    requested_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    plan: Mapped[str] = mapped_column(String(20))
    requested_hours: Mapped[int] = mapped_column(Integer)
    extra_hours: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    waiting_hours: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    breakdown: Mapped[dict | None] = mapped_column(JSON)
    pickup_latitude: Mapped[int | None] = mapped_column(Integer)
    pickup_longitude: Mapped[int | None] = mapped_column(Integer)
    hours: Mapped[int] = mapped_column(Integer)
    base_paise: Mapped[int] = mapped_column(Integer)
    service_paise: Mapped[int] = mapped_column(Integer)
    commission_bps: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DemoPayment(Record, Base):
    __tablename__ = "demo_payments"
    __table_args__ = (UniqueConstraint("booking_id", "kind", name="uq_demo_payments_booking_kind"),)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="BASE", server_default="BASE")
    amount_paise: Mapped[int] = mapped_column(Integer)


class HandoverPhoto(Record, Base):
    __tablename__ = "handover_photos"
    handover_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle_handovers.id"), index=True)
    content: Mapped[bytes]


class DriverWindow(Record, Base):
    __tablename__ = "driver_availability"
    __table_args__ = (CheckConstraint("ends_at > starts_at"),)
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("driver_profiles.user_id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PickupVerification(Base):
    __tablename__ = "pickup_verifications"
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), primary_key=True)
    code_hash: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TicketReply(Record, Base):
    __tablename__ = "support_replies"
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("support_tickets.id"), index=True)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)


class BookingCharge(Record, Base):
    __tablename__ = "booking_charges"
    __table_args__ = (UniqueConstraint("booking_id", "kind"),)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    amount_paise: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(150))
