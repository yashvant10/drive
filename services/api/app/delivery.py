import os
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .db import Session
from .models import Delivery, Notice, User


def email_ready():
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def sms_ready():
    return all(os.getenv(name) for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM"))


def queue(db, notice, user):
    for channel, allowed, after, configured in (
        ("email", user.notify_email, user.notify_email_since, email_ready()),
        ("sms", user.notify_sms and user.verified_phone, user.notify_sms_since, sms_ready()),
    ):
        if allowed and after and notice.created_at >= after and configured:
            statement = insert(Delivery).values(notice_id=notice.id, channel=channel, status="QUEUED")
            db.execute(statement.on_conflict_do_nothing(index_elements=[Delivery.notice_id, Delivery.channel]))


def enqueue_current():
    with Session.begin() as db:
        for channel, allowed, since, configured in (
            ("email", User.notify_email, User.notify_email_since, email_ready()),
            ("sms", User.notify_sms & User.verified_phone.is_not(None), User.notify_sms_since, sms_ready()),
        ):
            if not configured:
                continue
            exists = select(Delivery.id).where(Delivery.notice_id == Notice.id, Delivery.channel == channel).exists()
            rows = db.execute(select(Notice, User).join(User, User.id == Notice.user_id)
                              .where(allowed, ~exists, Notice.created_at >= since,
                                     Notice.created_at >= datetime.now(UTC) - timedelta(days=1))
                              .order_by(Notice.created_at).limit(50))
            for notice, user in rows:
                queue(db, notice, user)


def process_one():
    with Session.begin() as db:
        queued = db.scalar(select(Delivery).where(Delivery.status=="QUEUED")
                           .order_by(Delivery.created_at).limit(1).with_for_update(skip_locked=True))
        if not queued:
            return False
        notice = db.get(Notice, queued.notice_id)
        user = db.get(User, notice.user_id)
        email = queued.channel == "email"
        consent = user.notify_email if email else user.notify_sms
        destination = user.email if email else user.verified_phone
        ready = email_ready() if email else sms_ready()
        if not consent or not destination or not ready:
            queued.status = "CANCELLED"
            return True
        identity, channel, text = queued.id, queued.channel, notice.message
        queued.status = "DISPATCHING"
    try:
        if channel == "email":
            reference = send_email(destination, text)
        else:
            reference = send_sms(destination, text)
        status = "PROVIDER_ACCEPTED"
    except (OSError, ValueError, KeyError, smtplib.SMTPException, httpx.HTTPError):
        # Dispatch may have reached the provider. Require inspection instead
        # of guessing whether a second message would be a duplicate.
        reference = None
        status = "REQUIRES_REVIEW"
    with Session.begin() as db:
        item = db.get(Delivery, identity, with_for_update=True)
        item.status = status
        item.provider_ref = reference
    return True


def send_email(address, text):
    message = EmailMessage()
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = address
    message["Subject"] = "Drivewell booking update"
    message.set_content(text + "\nSign in to Drivewell for full details.")
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=8) as server:
        server.starttls(context=ssl.create_default_context())
        if username := os.getenv("SMTP_USERNAME"):
            server.login(username, os.environ["SMTP_PASSWORD"])
        failures = server.send_message(message)
        if failures:
            raise smtplib.SMTPException("Recipient rejected.")
    return None


def send_sms(phone, text):
    account = os.environ["TWILIO_ACCOUNT_SID"]
    result = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{account}/Messages.json", timeout=8,
                        auth=(account, os.environ["TWILIO_AUTH_TOKEN"]),
                        data={"To":phone,"From":os.environ["TWILIO_SMS_FROM"],"Body":"Drivewell: "+text})
    result.raise_for_status()
    reference = result.json().get("sid")
    if not isinstance(reference,str) or not reference.startswith("SM") or len(reference)>80:
        raise ValueError("The delivery reference is invalid.")
    return reference


def dispatch_notifications():
    if not (email_ready() or sms_ready()):
        return
    enqueue_current()
    with Session.begin() as db:
        abandoned = db.scalars(select(Delivery).where(Delivery.status=="DISPATCHING",
                               Delivery.created_at < func.now() - timedelta(minutes=15))
                               .limit(50).with_for_update(skip_locked=True))
        for item in abandoned:
            item.status = "REQUIRES_REVIEW"
    for _ in range(8):
        if not process_one():
            break
