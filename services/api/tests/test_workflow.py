import hmac
import io
import json
import os
from secrets import token_urlsafe
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import func, select

from app.auth import digest, hasher
from app.db import Session, engine
from app.main import app
from app.models import BookingEvent, Earning, PaymentEvent, PasswordReset, User

pytestmark = pytest.mark.skipif(
    not (engine.url.database or "").startswith("drive_test") or os.getenv("RUN_DB_TESTS") != "1",
    reason="Requires an isolated, migrated drive_test database.",
)
PASSWORD = "test-only-long-password"
RUN_ID = uuid4().hex


def account(role, name):
    client = TestClient(app)
    email = f"{name}.{RUN_ID}@example.com"
    if role in {"admin", "owner"}:
        with Session.begin() as db:
            db.add(User(name=name, email=email, password_hash=hasher.hash(PASSWORD), role=role))
        response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
    else:
        response = client.post("/api/v1/auth/register", json={"name": name, "email": email, "password": PASSWORD, "role": role})
        assert response.status_code == 201, response.text
    assert "httponly" in response.headers["set-cookie"].lower()
    return client


def test_role_cookie_and_logout():
    client = TestClient(app)
    assert client.get("/api/v1/vehicles").status_code == 401
    assert client.post("/api/v1/auth/register", json={"role": "admin"}).status_code == 422
    assert client.post("/api/v1/auth/logout", headers={"origin": "https://other.example"}).status_code == 403
    customer = account("customer", "access")
    assert customer.get("/api/v1/admin/metrics").status_code == 403
    assert customer.get("/api/v1/auth/me").json()["role"] == "customer"
    assert customer.post("/api/v1/auth/logout").status_code == 204
    assert customer.get("/api/v1/auth/me").status_code == 401
    assert customer.post("/api/v1/auth/login", json={"email": f"access.{RUN_ID}@example.com", "password": "a-long-wrong-password"}).status_code == 401
    assert customer.post("/api/v1/auth/login", json={"email": f"access.{RUN_ID}@example.com", "password": PASSWORD}).status_code == 200


def test_booking_through_completion(monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN", "http://localhost:3000")
    customer = account("customer", "customer")
    stranger = account("customer", "stranger")
    drivers = [account("driver", "driver" + str(index)) for index in range(2)]
    admin = account("admin", "operations")

    vehicle = customer.post("/api/v1/vehicles", json={"label": "Test car", "transmission": "automatic"})
    assert vehicle.status_code == 201
    selection = {"vehicle_id": vehicle.json()["id"], "hours": 2, "pickup": "Test pickup, Bengaluru"}
    quote = customer.post("/api/v1/fares/quote", json=selection).json()
    assert quote["total_paise"] == 53900
    assert quote["eligible_driver_available"] is False
    assert stranger.post("/api/v1/fares/quote", json=selection).status_code == 404

    preferences = {"area": "Bengaluru", "online": True, "transmission": "automatic"}
    for driver in drivers:
        assert driver.put("/api/v1/availability", json=preferences).status_code == 403
        expiry = (datetime.now(UTC) + timedelta(days=365)).date().isoformat()
        document = driver.post("/api/v1/drivers/documents", data={"licence_number": "TEST00001", "expiry": expiry},
                               files={"document": ("test.pdf", b"%PDF-1.4 test fixture", "application/pdf")})
        assert document.status_code == 201, document.text
        document_id = document.json()["id"]
        assert customer.get(f"/api/v1/admin/verifications/{document_id}/download").status_code == 403
        assert admin.get(f"/api/v1/admin/verifications/{document_id}/download").content.startswith(b"%PDF-")
        assert admin.post(f"/api/v1/admin/verifications/{document_id}", json={"decision": "APPROVED"}).status_code == 200
        assert driver.put("/api/v1/availability", json=preferences).status_code == 200

    assert customer.post("/api/v1/fares/quote", json=selection).json()["eligible_driver_available"] is True
    requested = customer.post("/api/v1/bookings", json=selection)
    assert requested.status_code == 201, requested.text
    booking_id = requested.json()["id"]
    booking_path = f"/api/v1/bookings/{booking_id}"
    assert stranger.get(booking_path).status_code == 404
    assert all(driver.get("/api/v1/booking-offers").json()[0]["id"] == booking_id for driver in drivers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda driver: driver.post(f"/api/v1/booking-offers/{booking_id}/accept"), drivers))
    assert sorted(result.status_code for result in outcomes) == [200, 409]
    driver = drivers[next(index for index, result in enumerate(outcomes) if result.is_success)]
    advance = f"/api/v1/trips/{booking_id}/advance"
    assert customer.post(advance, json={"expected_status": "ASSIGNED"}).status_code == 403
    previous = "ASSIGNED"
    for state in ("CONFIRMED", "DRIVER_EN_ROUTE", "DRIVER_ARRIVED"):
        response = driver.post(advance, json={"expected_status": previous})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == state
        assert driver.post(advance, json={"expected_status": previous}).status_code == 409
        previous = state
    assert driver.post(advance, json={"expected_status": previous}).status_code == 409

    point = {"latitude":12.9716,"longitude":77.5946,"accuracy_m":12}
    path = f"/api/v1/locations/{booking_id}"
    assert stranger.get(path).status_code == 404
    assert customer.get(path).json() is None
    assert driver.post(path,json=point).status_code == 201
    assert driver.post(path,json=point).status_code == 429
    assert customer.get(path).json()["latitude"] == point["latitude"]
    stream = f"/api/v1/realtime/bookings/{booking_id}"
    allowed_origin = {"origin":"http://localhost:3000"}
    with pytest.raises(WebSocketDisconnect) as rejected:
        with stranger.websocket_connect(stream,headers=allowed_origin):
            pytest.fail("Unexpected stream for another customer")
    assert rejected.value.code == 1008
    with customer.websocket_connect(stream,headers=allowed_origin) as socket:
        snapshot = socket.receive_json()
        assert snapshot["status"] == "DRIVER_ARRIVED"
        assert snapshot["location_event"]

    share_response = customer.post(f"/api/v1/family-shares/{booking_id}")
    assert share_response.status_code == 201, share_response.text
    share = share_response.json()
    public_client = TestClient(app)
    public = public_client.post("/api/v1/family-shares/view",json={"token":share["token"]}).json()
    assert set(public) == {"status","location"}
    assert public["location"]["latitude"] == point["latitude"]
    assert stranger.delete(f"/api/v1/family-shares/{share['id']}").status_code == 404
    assert customer.delete(f"/api/v1/family-shares/{share['id']}").status_code == 204
    assert public_client.post("/api/v1/family-shares/view",json={"token":share["token"]}).status_code == 404

    pickup = f"/api/v1/trips/{booking_id}/pickup-verification"
    assert stranger.post(pickup).status_code == 404
    code = customer.post(pickup).json()["code"]
    wrong = "000000" if code != "000000" else "000001"
    assert driver.post(pickup+"/check",json={"code":wrong}).status_code == 400
    assert driver.post(pickup+"/check",json={"code":code}).json()["verified"] is True

    urgent=customer.post(f"/api/v1/incidents/{booking_id}/sos")
    assert urgent.status_code==201,urgent.text
    incident_id=urgent.json()["id"]
    assert customer.post(f"/api/v1/incidents/{booking_id}/sos").json()["id"]==incident_id
    assert admin.post(f"/api/v1/admin/incidents/{incident_id}/escalate").status_code==204
    assert customer.get(f"/api/v1/incidents/{booking_id}").json()[0]["status"]=="ESCALATED"

    payment_path = f"/api/v1/payments/{booking_id}"
    assert customer.post(payment_path + "/order").status_code == 503
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fixture")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "testing-only-fixture")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "testing-only-webhook")
    monkeypatch.setenv("REQUIRE_ONLINE_PAYMENT", "true")
    order_id = "order_" + RUN_ID
    provider_calls = []
    def fixture_provider(method, path, **kwargs):
        provider_calls.append((method, path))
        return {"id": order_id}
    monkeypatch.setattr("app.payments.provider", fixture_provider)
    assert stranger.post(payment_path + "/order").status_code == 404
    assert customer.post(payment_path + "/order").json()["provider_order_id"] == order_id
    assert customer.post(payment_path + "/order").json()["provider_order_id"] == order_id
    assert provider_calls == [("POST", "/orders")]
    payload = {"event":"payment.captured", "payload":{"payment":{"entity":{
        "id":"pay_" + RUN_ID, "order_id":order_id, "amount":53900, "currency":"INR", "status":"captured",
    }}}}
    raw = json.dumps(payload).encode()
    sig = hmac.digest(b"testing-only-webhook", raw, "sha256").hex()
    webhook = "/api/v1/payments/webhook"
    headers = {"x-razorpay-event-id":RUN_ID, "x-razorpay-signature":"invalid"}
    assert customer.post(webhook, content=raw, headers=headers).status_code == 400
    headers["x-razorpay-signature"] = sig
    assert customer.post(booking_path + "/cancel").status_code == 409
    handover = f"/api/v1/handovers/{booking_id}"
    for stage, odometer, state in (("before", 100, "IN_PROGRESS"), ("after", 110, "COMPLETED")):
        response = driver.post(handover, json={"stage": stage, "odometer": odometer, "fuel_percent": 60, "condition": "Test condition"})
        assert response.status_code == 201, response.text
        assert driver.post(advance, json={"expected_status":previous}).status_code == 409
        photo_data = io.BytesIO()
        Image.new("RGB",(30,20),"blue").save(photo_data,"PNG")
        upload = f"{handover}/{stage}/photos"
        file = {"photo":("isolated.png",photo_data.getvalue(),"image/png")}
        assert driver.post(upload,files={"photo":("fake.png",b"not image","image/png")}).status_code==422
        photo=driver.post(upload,files=file)
        assert photo.status_code==201, photo.text
        download=f"{handover}/photos/{photo.json()['id']}"
        assert customer.get(download).headers["content-type"]=="image/jpeg"
        assert stranger.get(download).status_code==404
        assert customer.post(f"{handover}/{stage}/acknowledge").status_code == 204
        assert driver.post(upload,files=file).status_code==409
        if stage == "before":
            assert driver.post(advance, json={"expected_status":previous}).status_code == 409
            assert customer.post(webhook, content=raw, headers=headers).status_code == 200
            assert customer.post(webhook, content=raw, headers=headers).status_code == 200
            assert customer.get("/api/v1/payments").json()["payments"][0]["status"] == "CAPTURED"
        assert driver.post(advance, json={"expected_status":previous}).json()["status"] == state
        previous = state
    assert admin.get(booking_path).json()["status"] == "COMPLETED"
    assert customer.get("/api/v1/bookings").json()[0]["id"] == booking_id
    assert customer.get(path).json() is None
    assert driver.get("/api/v1/drivers/earnings").json()[0]["net_paise"] == 43120
    rating = customer.post("/api/v1/reviews",json={"booking_id":booking_id,"rating":5,"comment":"Good trip"})
    assert rating.status_code == 201
    assert customer.post("/api/v1/reviews",json={"booking_id":booking_id,"rating":1}).status_code == 409
    assert driver.get("/api/v1/drivers/skill-passport").json()["average_rating"] == 5
    receipt = customer.get("/api/v1/customers/receipts").json()[0]
    assert stranger.get("/api/v1/customers/receipts/"+receipt["id"]).status_code == 404
    assert "INR 539.00" in customer.get("/api/v1/customers/receipts/"+receipt["id"]).text
    dispute=f"/api/v1/admin/bookings/{booking_id}"
    assert admin.post(dispute+"/dispute",json={"reason":"Isolated dispute workflow"}).json()["status"]=="DISPUTED"
    assert customer.get(booking_path).json()["status"]=="DISPUTED"
    assert admin.post(dispute+"/resolve").json()["status"]=="COMPLETED"
    payout = admin.get("/api/v1/admin/payouts").json()[0]
    assert admin.post("/api/v1/admin/payouts/"+payout["id"]).json()["status"] == "PENDING_REVIEW"

    payout_path = "/api/v1/admin/payouts/"+payout["id"]
    assert admin.post(payout_path+"/submit").status_code == 503
    monkeypatch.setenv("RAZORPAYX_KEY_ID","fixture-key")
    monkeypatch.setenv("RAZORPAYX_KEY_SECRET","fixture-secret")
    monkeypatch.setenv("RAZORPAYX_ACCOUNT_NUMBER","000000000")
    transfer = {}
    def payout_provider(method, path, *, body=None, identity=None):
        if path.startswith("/fund_accounts/"):
            return {"id":"fa_"+RUN_ID,"active":True}
        if method == "POST":
            assert str(identity) == body["reference_id"]
            transfer.update(id="pout_"+RUN_ID, fund_account_id=body["fund_account_id"],
                            reference_id=body["reference_id"], amount=body["amount"], currency="INR")
            return {**transfer,"status":"processed"}
        return {**transfer,"status":"reversed"}
    monkeypatch.setattr("app.settlements.provider",payout_provider)
    driver_id = driver.get("/api/v1/auth/me").json()["id"]
    assert admin.put(f"/api/v1/admin/drivers/{driver_id}/payout-account",json={"reference":"fa_"+RUN_ID}).status_code == 200
    submitted = admin.post(payout_path+"/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "PROCESSED"
    assert driver.get("/api/v1/drivers/earnings").json()[0]["status"] == "SETTLED"
    assert admin.post("/api/v1/admin/refunds/"+receipt["id"]).status_code == 409
    assert admin.post(payout_path+"/reconcile",json={"reference":"pout_"+RUN_ID}).json()["status"] == "REVERSED"
    assert driver.get("/api/v1/drivers/earnings").json()[0]["status"] == "UNSETTLED"

    from app.models import BookingCharge

    # A second charge must reconcile separately from the captured booking fare.
    with Session.begin() as db:
        db.add(BookingCharge(booking_id=booking_id,kind="OVERAGE",amount_paise=22000,description="Fixture overage"))
    extra_order,extra_payment="order_extra"+RUN_ID,"pay_extra"+RUN_ID
    def extra_provider(method, path, **kwargs):
        if method=="POST":
            assert kwargs["body"]["amount"]==22000
            return {"id":extra_order}
        assert path=="/payments/"+extra_payment
        return {"id":extra_payment,"order_id":extra_order,"amount":22000,"currency":"INR","status":"captured"}
    monkeypatch.setattr("app.payments.provider",extra_provider)
    assert customer.get("/api/v1/payments").json()["test_mode"] is True
    extra=customer.post(payment_path+"/order?kind=OVERAGE")
    assert extra.status_code==200,extra.text
    assert customer.post(payment_path+"/order?kind=OVERAGE").json()["id"]==extra.json()["id"]
    signature=hmac.digest(b"testing-only-fixture",f"{extra_order}|{extra_payment}".encode(),"sha256").hex()
    verify_data={"order_id":extra_order,"payment_id":extra_payment,"signature":signature}
    assert customer.post(payment_path+"/verify",json={**verify_data,"signature":"0"*64}).status_code==400
    assert customer.post(payment_path+"/verify",json=verify_data).json()["kind"]=="OVERAGE"
    assert sorted(item["kind"] for item in customer.get("/api/v1/customers/receipts").json())==["BASE","OVERAGE"]

    refund_calls = []
    payment_id = receipt["id"]
    def refund_provider(method, path, **kwargs):
        refund_calls.append((method,path))
        return {"id":"rfnd_"+RUN_ID,"payment_id":"pay_"+RUN_ID,"amount":53900,"currency":"INR",
                "status":"pending" if method=="POST" else "processed"}
    monkeypatch.setattr("app.payments.provider",refund_provider)
    refund = admin.post("/api/v1/admin/refunds/"+payment_id)
    assert refund.status_code == 201, refund.text
    assert refund.json()["status"] == "PENDING"
    assert admin.post("/api/v1/admin/refunds/"+payment_id).status_code == 409
    reconcile = admin.post("/api/v1/admin/refunds/"+refund.json()["id"]+"/reconcile",json={"reference":"rfnd_"+RUN_ID})
    assert reconcile.json()["status"] == "PROCESSED"
    assert admin.get("/api/v1/admin/financials").json()["Processed refunds"] == 53900
    assert [method for method,_ in refund_calls] == ["POST","GET"]

    rescue = customer.post("/api/v1/bookings", json=selection).json()
    rescue_id = rescue["id"]
    assert driver.post(f"/api/v1/booking-offers/{rescue_id}/accept").status_code == 200
    assert driver.post(f"/api/v1/trips/{rescue_id}/release").json()["status"] == "SEARCHING"
    assert driver.post(f"/api/v1/booking-offers/{rescue_id}/accept").status_code == 409
    other = next(candidate for candidate in drivers if candidate is not driver)
    assert other.post(f"/api/v1/booking-offers/{rescue_id}/decline").status_code == 204
    assert other.post(f"/api/v1/booking-offers/{rescue_id}/accept").status_code == 409
    from app.models import Booking
    from app.workers import expire_bookings

    with Session.begin() as db:
        db.get(Booking, rescue_id).starts_at = datetime.now(UTC) - timedelta(minutes=16)
    expire_bookings()
    assert customer.get(f"/api/v1/bookings/{rescue_id}").json()["status"] == "EXPIRED"

    no_show = customer.post("/api/v1/bookings",json=selection).json()["id"]
    assert driver.post(f"/api/v1/booking-offers/{no_show}/accept").status_code == 200
    with Session.begin() as db:
        db.get(Booking,no_show).starts_at = datetime.now(UTC)-timedelta(minutes=11)
    expire_bookings()
    assert customer.get(f"/api/v1/bookings/{no_show}").json()["status"] == "SEARCHING"
    assert driver.post(f"/api/v1/booking-offers/{no_show}/accept").status_code == 409
    assert other.post(f"/api/v1/booking-offers/{no_show}/accept").status_code == 200
    assert customer.post(f"/api/v1/bookings/{no_show}/cancel").status_code == 200

    cancelled = customer.post("/api/v1/bookings", json=selection).json()
    assert customer.post("/api/v1/bookings/" + cancelled["id"] + "/cancel").json()["status"] == "CANCELLED"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.booking_id.in_([booking_id, cancelled["id"]]))) == 13
        assert db.scalar(select(func.count()).select_from(Earning).where(Earning.booking_id == booking_id)) == 1
        assert db.scalar(select(func.count()).select_from(PaymentEvent).where(PaymentEvent.provider_event_id == "webhook:" + RUN_ID)) == 1


def test_reset_is_one_time_and_revokes_sessions(monkeypatch):
    customer = account("customer", "reset")
    email = f"reset.{RUN_ID}@example.com"
    raw_token = token_urlsafe(32)
    assert customer.post("/api/v1/auth/password-reset", json={"email":email}).status_code == 503
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        db.add(PasswordReset(token_hash=digest(raw_token), user_id=user.id, expires_at=datetime.now(UTC) + timedelta(minutes=30)))
    reset = {"token":raw_token, "password":"changed-test-password"}
    assert customer.post("/api/v1/auth/password-reset/confirm", json=reset).status_code == 204
    assert customer.post("/api/v1/auth/password-reset/confirm", json=reset).status_code == 400
    assert customer.get("/api/v1/auth/me").status_code == 401
    assert customer.post("/api/v1/auth/login", json={"email":email,"password":PASSWORD}).status_code == 401
    assert customer.post("/api/v1/auth/login", json={"email":email,"password":reset["password"]}).status_code == 200


def test_advanced_panels_roles_and_phone(monkeypatch):
    from app.models import Notice

    customer = account("customer", "panels")
    stranger = account("customer", "otherpanel")
    driver = account("driver", "passport")
    admin = account("admin", "paneladmin")
    finance = account("admin", "panelfinance")
    assert customer.patch("/api/v1/auth/me", json={"name":"Updated customer"}).json()["name"] == "Updated customer"
    address = customer.post("/api/v1/customers/addresses", json={"label":"Home","address":"Bengaluru test address"})
    assert address.status_code == 201, address.text
    address_url = "/api/v1/customers/addresses/" + address.json()["id"]
    assert stranger.delete(address_url).status_code == 404
    assert customer.delete(address_url).status_code == 204

    assert driver.put("/api/v1/drivers/skill-passport", json={
        "years":12,"languages":"Kannada, English","qualifications":"Defensive driving",
        "emergency_contact":"+919999999998","consent":True,
    }).status_code == 200
    passport = driver.get("/api/v1/drivers/skill-passport").json()
    assert passport["experience"]["years"] == 12 and passport["licence_current"] is False
    assert passport["completed_trips"] == 0 and passport["average_rating"] is None

    photo=io.BytesIO()
    Image.new("RGB",(25,25),"navy").save(photo,"PNG")
    assert driver.put("/api/v1/drivers/avatar",files={"photo":("test.png",photo.getvalue(),"image/png")}).status_code==204
    assert driver.get("/api/v1/drivers/avatar-status").json()["has_photo"] is True
    assert customer.get("/api/v1/drivers/avatar").status_code==403
    assert driver.get("/api/v1/drivers/avatar").headers["content-type"]=="image/jpeg"
    stranger_id=stranger.get("/api/v1/auth/me").json()["id"]
    suspension=f"/api/v1/admin/customers/{stranger_id}/access"
    assert admin.put(suspension,json={"suspended":True}).status_code==200
    assert stranger.get("/api/v1/auth/me").status_code==401
    assert stranger.post("/api/v1/auth/login",json={"email":f"otherpanel.{RUN_ID}@example.com","password":PASSWORD}).status_code==401
    assert admin.put(suspension,json={"suspended":False}).status_code==200
    assert stranger.post("/api/v1/auth/login",json={"email":f"otherpanel.{RUN_ID}@example.com","password":PASSWORD}).status_code==200

    finance_id = finance.get("/api/v1/auth/me").json()["id"]
    assert admin.put(f"/api/v1/admin/staff/{finance_id}/scope",json={"scope":"finance"}).status_code == 200
    assert finance.get("/api/v1/admin/directory/drivers").status_code == 403
    assert finance.get("/api/v1/admin/directory/payments").status_code == 200
    found = admin.get("/api/v1/admin/directory/customers",params={"q":"Updated customer"})
    assert found.json()["rows"][0]["name"] == "Updated customer"
    exported = admin.get("/api/v1/admin/directory/customers",params={"export":True})
    assert exported.headers["content-type"].startswith("text/csv")
    assert "Updated customer" in exported.text

    original = admin.get("/api/v1/admin/pricing").json()
    values = {key:value for key,value in original.items() if key!="commission_bps"}
    try:
        assert finance.put("/api/v1/admin/pricing",json={**values,"base":25000}).status_code == 200
        vehicle = customer.post("/api/v1/vehicles",json={"label":"Panel car","transmission":"manual"}).json()
        selection = {"vehicle_id":vehicle["id"],"pickup":"Bengaluru test address"}
        quote = customer.post("/api/v1/fares/quote",json=selection).json()
        assert quote["base_paise"] == 25000
        assert admin.put("/api/v1/admin/pricing",json=values).status_code == 200
        quoted_selection = {**selection,"quote_id":quote["quote_id"]}
        assert stranger.post("/api/v1/bookings",json=quoted_selection).status_code == 404
        assert customer.post("/api/v1/bookings",json={**quoted_selection,"hours":4}).status_code == 409
        booked = customer.post("/api/v1/bookings",json=quoted_selection)
        assert booked.status_code == 201, booked.text
        booking = booked.json()
        assert booking["fare_paise"] == quote["total_paise"]
        assert customer.post("/api/v1/bookings",json=quoted_selection).json()["id"] == booking["id"]
        vehicle_path = "/api/v1/vehicles/"+vehicle["id"]
        assert customer.delete(vehicle_path).status_code == 409
        report = {"booking_id":booking["id"],"description":"Test safety report"}
        assert stranger.post("/api/v1/incidents",json=report).status_code == 404
        response = customer.post("/api/v1/incidents",json=report)
        assert response.status_code == 201
        assert admin.post("/api/v1/admin/incidents/"+response.json()["id"]+"/close").status_code == 204
        assert customer.post("/api/v1/bookings/"+booking["id"]+"/cancel").status_code == 200
        assert customer.delete(vehicle_path).status_code == 204
        assert customer.get("/api/v1/bookings/"+booking["id"]).status_code == 200
        notice = customer.get("/api/v1/notifications").json()[0]
        assert not notice["read"]
        assert customer.post("/api/v1/notifications/"+notice["id"]+"/read").status_code == 204
        with Session() as db:
            assert db.get(Notice, notice["id"]).read
    finally:
        assert admin.put("/api/v1/admin/pricing",json=values).status_code == 200

    ticket=customer.post("/api/v1/support",json={"message":"Please help with my test booking"}).json()
    replies="/api/v1/support/"+ticket["id"]+"/replies"
    assert stranger.get(replies).status_code==404
    assert finance.get(replies).status_code==403
    assert admin.post(replies,json={"message":"We are investigating."}).status_code==201
    assert customer.get(replies).json()[0]["name"]=="Drivewell Support"

    assert customer.get("/api/v1/auth/phone").json()["configured"] is False
    monkeypatch.setenv("TWILIO_ACCOUNT_SID","test-only")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN","test-only")
    monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID","test-only")
    phone = "+919999999999"
    def verify_provider(path, payload):
        if path == "Verifications":
            assert payload["To"] == phone and payload["Channel"] == "sms"
            return {"status":"pending","sid":"VE"+RUN_ID}
        return {"status":"approved" if payload["Code"] == "123456" else "pending","to":phone}
    monkeypatch.setattr("app.phone.provider",verify_provider)
    assert customer.post("/api/v1/auth/phone/send",json={"phone":phone}).status_code == 202
    assert customer.post("/api/v1/auth/phone/verify",json={"code":"000000"}).status_code == 400
    assert customer.post("/api/v1/auth/phone/verify",json={"code":"123456"}).json()["verified_phone"] == phone
    assert customer.post("/api/v1/auth/phone/verify",json={"code":"123456"}).status_code == 400


def test_optional_document_storage_and_notification_delivery(monkeypatch):
    from app import delivery, storage
    from app.models import Delivery, Notice

    driver = account("driver","storage")
    admin = account("admin","storageadmin")
    files = {}
    monkeypatch.setattr(storage,"private_bucket",lambda:"fixture")
    monkeypatch.setattr(storage,"put_document",lambda key,data:files.update({key:data}))
    monkeypatch.setattr(storage,"get_document",lambda key:files[key])
    expiry = (datetime.now(UTC)+timedelta(days=30)).date().isoformat()
    result = driver.post("/api/v1/drivers/documents",data={"licence_number":"S3TEST123","expiry":expiry},
                         files={"document":("fixture.pdf",b"%PDF-1.4 isolated fixture","application/pdf")})
    assert result.status_code==201, result.text
    url = "/api/v1/admin/verifications/"+result.json()["id"]+"/download"
    assert driver.get(url).status_code == 403
    assert admin.get(url).content == b"%PDF-1.4 isolated fixture"

    assert driver.put("/api/v1/notifications/preferences",json={"email":True,"sms":True}).status_code == 409
    assert driver.put("/api/v1/notifications/preferences",json={"email":True,"sms":False}).status_code == 204
    identity = driver.get("/api/v1/auth/me").json()["id"]
    monkeypatch.setattr(delivery,"email_ready",lambda:True)
    delivered = []
    monkeypatch.setattr(delivery,"send_email",lambda address,text:delivered.append((address,text)))
    with Session.begin() as db:
        event = Notice(user_id=identity,message="Isolated delivery test")
        db.add(event)
        db.flush()
        notice_id = event.id
    delivery.dispatch_notifications()
    delivery.dispatch_notifications()
    assert delivered == [(f"storage.{RUN_ID}@example.com","Isolated delivery test")]
    with Session() as db:
        item = db.scalar(select(Delivery).where(Delivery.notice_id==notice_id))
        assert item.status=="PROVIDER_ACCEPTED"


def test_demo_mode_is_separate_and_dispatch_uses_verified_records(monkeypatch):
    from app.models import Booking, Driver

    customer=account("customer","democustomer")
    other=account("customer","demoother")
    driver=account("driver","demodriver")
    admin=account("admin","demoadmin")
    driver_id=driver.get("/api/v1/auth/me").json()["id"]
    with Session.begin() as db:
        item=db.get(Driver,driver_id)
        item.approved=True
        item.licence_expiry=datetime.now(UTC)+timedelta(days=365)
    prefs={"area":"Bengaluru","online":True,"transmission":"both","categories":["suv"],"schedule_only":True}
    assert driver.put("/api/v1/availability",json=prefs).status_code==200
    now=datetime.now(UTC)
    starts=now+timedelta(days=3)
    window={"starts_at":(starts-timedelta(minutes=10)).isoformat(),"ends_at":(starts+timedelta(hours=3)).isoformat()}
    assert driver.post("/api/v1/availability/windows",json=window).status_code==201
    assert driver.post("/api/v1/availability/windows",json=window).status_code==409
    vehicle=customer.post("/api/v1/vehicles",json={"label":"Family car","transmission":"manual","category":"suv"}).json()
    trip={"vehicle_id":vehicle["id"],"pickup":"Bengaluru test pickup","hours":2}
    scheduled={**trip,"starts_at":starts.isoformat()}
    assert customer.post("/api/v1/fares/quote",json=scheduled).json()["eligible_driver_available"] is True
    assert customer.post("/api/v1/fares/quote",json={**scheduled,"hours":4}).json()["eligible_driver_available"] is False
    assert driver.put("/api/v1/availability",json={**prefs,"schedule_only":False}).status_code==200
    point={"latitude":12.9716,"longitude":77.5946}
    destination={**trip,"pickup_point":point}
    assert driver.put("/api/v1/availability/dispatch-point",json={"latitude":13.4,"longitude":77.6}).status_code==200
    assert customer.post("/api/v1/fares/quote",json=destination).json()["eligible_driver_available"] is False
    assert driver.put("/api/v1/availability/dispatch-point",json=point).status_code==200
    assert customer.post("/api/v1/fares/quote",json=destination).json()["eligible_driver_available"] is True
    priced=customer.post("/api/v1/fares/quote",json={**destination,"extra_hours":1,"waiting_hours":1}).json()
    assert priced["extra_paise"]==22000 and priced["waiting_paise"]==12000
    assert priced["hours"]==4 and priced["total_paise"]==87900
    request=customer.post("/api/v1/bookings",json=destination).json()
    booking_id=request["id"]
    assert driver.post(f"/api/v1/booking-offers/{booking_id}/accept").status_code==200
    with Session.begin() as db:
        db.get(Booking,booking_id).status="DRIVER_ARRIVED"

    path=f"/api/v1/payments/{booking_id}/demo"
    monkeypatch.setenv("PAYMENT_MODE","demo")
    monkeypatch.setenv("APP_ENV","production")
    assert customer.post(path).status_code==404
    monkeypatch.setenv("APP_ENV","test")
    monkeypatch.setenv("REQUIRE_ONLINE_PAYMENT","true")
    assert other.post(path).status_code==404
    assert customer.post(path).json()["status"]=="SIMULATED"
    assert customer.post(path).json()["id"]==customer.get("/api/v1/payments").json()["demo_payments"][0]["id"]
    assert customer.get("/api/v1/payments").json()["payments"]==[]
    assert customer.get("/api/v1/customers/receipts").json()==[]
    assert admin.get("/api/v1/admin/directory/payments").json()["rows"]==[] or all(
        row["booking_id"]!=booking_id for row in admin.get("/api/v1/admin/directory/payments").json()["rows"]
    )
    pickup=f"/api/v1/trips/{booking_id}/pickup-verification"
    assert driver.post(pickup+"/check",json={"code":customer.post(pickup).json()["code"]}).status_code==200
    advance=f"/api/v1/trips/{booking_id}/advance"
    handover=f"/api/v1/handovers/{booking_id}"
    for stage, expected, outcome in (("before","DRIVER_ARRIVED","IN_PROGRESS"),("after","IN_PROGRESS","COMPLETED")):
        if stage=="after":
            with Session.begin() as db:
                event=db.scalar(select(BookingEvent).where(BookingEvent.booking_id==booking_id,BookingEvent.status=="IN_PROGRESS"))
                event.created_at=datetime.now(UTC)-timedelta(hours=2,minutes=20)
        assert driver.post(handover,json={"stage":stage,"odometer":100,"fuel_percent":50,"condition":"Demo only"}).status_code==201
        assert customer.post(handover+f"/{stage}/acknowledge").status_code==204
        assert driver.post(advance,json={"expected_status":expected}).json()["status"]==outcome
    assert customer.get(f"/api/v1/payments/{booking_id}/charges").json()[0]["amount_paise"]==22000
    assert customer.post(path+"?kind=OVERAGE").json()["kind"]=="OVERAGE"
    assert driver.get("/api/v1/drivers/earnings").json()==[]
    late=customer.post("/api/v1/bookings",json=destination).json()["id"]
    assert driver.post(f"/api/v1/booking-offers/{late}/accept").status_code==200
    with Session.begin() as db:
        db.get(Booking,late).cancellation_paise=4900
    assert customer.get(f"/api/v1/bookings/{late}/cancellation").json()["amount_paise"]==4900
    assert customer.post(f"/api/v1/bookings/{late}/cancel").status_code==409
    assert customer.post(f"/api/v1/bookings/{late}/cancel?accepted_fee_paise=4900").status_code==200
    fees=f"/api/v1/payments/{late}"
    assert other.get(fees+"/charges").status_code==404
    assert customer.get(fees+"/charges").json()[0]["amount_paise"]==4900
    assert customer.post(fees+"/demo?kind=CANCELLATION").json()["kind"]=="CANCELLATION"
    assert customer.post(fees+"/demo?kind=CANCELLATION").json()["amount_paise"]==4900
    assert customer.get("/api/v1/customers/receipts").json()==[]



def test_gmail_smtp_check_uses_starttls_and_sends_to_sender(monkeypatch,capsys):
    from app.smtp_check import main

    for key,value in {"SMTP_HOST":"smtp.gmail.com","SMTP_PORT":"587","SMTP_FROM":"sender@example.com",
                      "SMTP_USERNAME":"sender@example.com","SMTP_PASSWORD":"isolated-fixture"}.items():
        monkeypatch.setenv(key,value)
    calls=[]
    class FixtureSMTP:
        def __init__(self,host,port,timeout):
            calls.append((host,port))
        def __enter__(self):
            return self
        def __exit__(self,*args):
            return None
        def starttls(self,context):
            assert context.check_hostname
            calls.append("tls")
        def login(self,username,password):
            assert username=="sender@example.com" and password=="isolated-fixture"
            calls.append("login")
        def send_message(self,message):
            assert message["To"]==message["From"]=="sender@example.com"
            calls.append("accepted")
            return {}
    monkeypatch.setattr("app.delivery.smtplib.SMTP",FixtureSMTP)
    main()
    assert calls==[("smtp.gmail.com",587),"tls","login","accepted"]
    assert "SMTP accepted" in capsys.readouterr().out


def test_owner_reports_and_map_route_scope(monkeypatch):
    import httpx

    owner = account("owner","businessowner")
    customer = account("customer","mapcustomer")
    stranger = account("customer","mapstranger")
    assert customer.get("/api/v1/owner/overview").status_code == 403
    assert owner.get("/api/v1/admin/metrics").status_code == 403
    assert owner.get("/api/v1/bookings").status_code == 403
    before = owner.get("/api/v1/owner/overview").json()
    assert TestClient(app).post("/api/v1/auth/register",json={
        "name":"Attempted owner","email":"attempt-owner@example.com","password":PASSWORD,"role":"owner"
    }).status_code == 422

    vehicle = customer.post("/api/v1/vehicles",json={"label":"Map vehicle","transmission":"manual"}).json()
    booking = customer.post("/api/v1/bookings",json={
        "vehicle_id":vehicle["id"],"pickup":"MG Road","destination":"Indiranagar",
        "pickup_point":{"latitude":12.972,"longitude":77.601},
    }).json()
    from app.models import DemoPayment

    with Session.begin() as db:
        customer_id=db.scalar(select(User.id).where(User.email==f"mapcustomer.{RUN_ID}@example.com"))
        db.add(DemoPayment(booking_id=booking["id"],customer_id=customer_id,amount_paise=12345))
    after = owner.get("/api/v1/owner/overview").json()
    assert after["booking_count"] == before["booking_count"]+1
    assert after["demo_payment_count"] == before["demo_payment_count"]+1
    assert after["captured_paise"] == before["captured_paise"]
    path = f"/api/v1/maps/bookings/{booking['id']}/route"
    assert stranger.post(path,json={}).status_code == 404
    assert owner.post(path,json={}).status_code == 404
    assert customer.post(path,json={"mode":"driver"}).status_code == 409
    assert customer.post(path,json={}).status_code == 503
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY","isolated-route-key")
    def geocode(url, **kwargs):
        assert "Indiranagar" in kwargs["params"]["text"]
        return httpx.Response(200,request=httpx.Request("GET",url),json={"features":[{"geometry":{"coordinates":[77.64,12.98]}}]})
    def route(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "isolated-route-key"
        assert kwargs["json"]["coordinates"] == [[77.601,12.972],[77.64,12.98]]
        return httpx.Response(200,request=httpx.Request("POST",url),json={"features":[{
            "properties":{"summary":{"distance":4500,"duration":850}},
            "geometry":{"coordinates":[[77.601,12.972],[77.64,12.98]]},
        }]})
    monkeypatch.setattr("app.maps.httpx.get",geocode)
    monkeypatch.setattr("app.maps.httpx.post",route)
    result = customer.post(path,json={})
    assert result.json()["line"] == [[12.972,77.601],[12.98,77.64]]
    assert result.json()["duration_s"] == 850
    assert customer.post(f"/api/v1/bookings/{booking['id']}/cancel").status_code == 200
