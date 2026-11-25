# Drivewell

Drivewell is a Bengaluru driver-booking platform for customers using their own cars. The current release supports account registration, fare estimates, bookings, licence review, driver assignment, handovers, and recorded trip earnings. See [implementation status](docs/status.md) for coverage and prerequisites.

## Run locally

Use Docker Compose, Python 3.12 or later, and Node 22 or later.

```sh
docker compose up -d --wait
python3 -m venv .venv
.venv/bin/python -m pip install -r services/api/requirements.txt
(cd apps/web && npm ci)
(cd services/api && ../../.venv/bin/alembic upgrade head)
```

Run in separate terminals from the repository root.

```sh
cd services/api
../../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```sh
cd apps/web
npm run dev -- --hostname 0.0.0.0
```

Open [Drivewell](http://localhost:3000) and the [API docs](http://localhost:8000/docs). The API's database readiness check is at [health](http://localhost:8000/health). For configuration overrides, copy `.env.example` to `.env` and source it in each shell using `set -a; . ./.env; set +a` from the root before you start a service.

Create the first administrator from a trusted API terminal.

```sh
cd services/api
../../.venv/bin/python -m app.create_admin
```

Customers and drivers register on the website. The driver uploads a licence in **Licence verification**. An administrator reviews the document, the driver sets availability, and a customer adds their vehicle and makes a request. Driver and customer both participate in pickup and return acknowledgements. Completion records accrued earnings. Payment defaults to optional for local use.

## Test

Use a fresh disposable database, then apply migrations and run the PostgreSQL suite.

```sh
docker compose exec -T postgres createdb -U drive drive_test
export DATABASE_URL=postgresql+psycopg://drive:drive@127.0.0.1:5432/drive_test
(cd services/api && ../../.venv/bin/alembic upgrade head && ../../.venv/bin/alembic check && RUN_DB_TESTS=1 ../../.venv/bin/python -m pytest -q)
(cd apps/web && npm run lint && npm run build && npm run typecheck)
```

Start the API and web commands against the disposable database before running browser tests. Run `npx playwright install chromium` from `apps/web`, then `PLAYWRIGHT_MUTATIONS=1 npm test`. Set `PLAYWRIGHT_CHROMIUM_PATH` to use an existing local Chromium binary.

## Configure external services

- **Razorpay** requires a test or production key ID, key secret and webhook signing secret. Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` on the API. Subscribe to `payment.captured` at `/api/v1/payments/webhook`. Enable capture in the Razorpay account. Set `REQUIRE_ONLINE_PAYMENT=true` only after testing checkout, webhook delivery, and failure recovery.
- **Password reset** uses SMTP with STARTTLS. Set `PUBLIC_WEB_URL`, `SMTP_HOST`, `SMTP_FROM`, and the provider's port and authentication variables. Keep password-reset URLs out of request logs.
- **Maps** opens directions and shared points in Google Maps links. Browser geolocation requires HTTPS in deployed use and explicit permission. Coordinates are shared while the app is open, when the driver chooses to send them.
- The current build requires no credential for basic local use. See the [deployment notes](docs/deployment.md) before exposing either service.

### Advanced integrations and roles

- **Twilio Verify** requires `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_VERIFY_SERVICE_SID`. To offer consent-based SMS booking notifications, also configure a permitted `TWILIO_SMS_FROM`. Users opt in from Notifications after verifying their number. SMTP also supports opted-in email updates.
- **Private licence storage** uses `DRIVEWELL_DOCUMENT_BUCKET`, the AWS SDK credential chain, and optionally `S3_ENDPOINT_URL` and `AWS_REGION`. Choose a private bucket that supports the configured encryption option. Existing PostgreSQL-backed licences remain readable by authorized reviewers.
- **RazorpayX settlements** require `RAZORPAYX_KEY_ID`, `RAZORPAYX_KEY_SECRET`, and `RAZORPAYX_ACCOUNT_NUMBER`. A full administrator maps the driver's verified provider fund account in Drivers. Finance staff can request review, submit with an idempotency key and reconcile provider status. Use test credentials before any real transfer.
- **Staff** accounts are provisioned from the trusted API terminal. A full administrator can restrict another administrator to operations, finance or support from Staff. The restricted session receives the relevant panels on the next navigation.
- The browser admin tour uses `PLAYWRIGHT_ADMIN_EMAIL` and `PLAYWRIGHT_ADMIN_PASSWORD`. To provision an isolated account, export those values and `RUN_DB_TESTS=1`, then run `PYTHONPATH=. ../../.venv/bin/python tests/bootstrap_browser.py` from `services/api` with the test database configured.

### Local demo checkout and Gmail SMTP

The example environment selects demo checkout in development. Start the API
with `APP_ENV=development PAYMENT_MODE=demo` or source your own `.env`.
Customers can simulate checkout once the driver arrives. Demo checkout gates
trip start alongside the pickup code and handover. Demo records never become
provider captures, receipts, revenue, payable driver earnings, or payouts.
Production only permits the configured Razorpay provider.

To use Gmail for password resets and opted-in email updates, set
`SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, and set `SMTP_FROM` and
`SMTP_USERNAME` to the sending Gmail address. Keep `SMTP_PASSWORD` in the
runtime's secure settings. Use a Gmail App Password or an authorized Workspace
SMTP relay where enabled. Do not put the credential in Git or paste it into chat.
Set `PUBLIC_WEB_URL` to the customer-facing URL before testing password resets.
The API uses STARTTLS. A verified sender address and working credentials are
needed to test delivery.

### Additional billing

- A late cancellation fee is quoted upfront and confirmed again when a
  customer cancels an assigned booking within 15 minutes of pickup or later,
  before the driver marks arrival. The sample environment uses ₹49.
- Actual overage is measured from verified trip start to the driver's return
  handover. The first 15 minutes are free. Additional time is charged by
  started hour at the rate locked in the booking, capped at four hours.
- Customers pay each additional charge from the booking. No automatic card
  charge occurs. Captured charges get their own receipt. Demo payments produce
  no financial receipts or payout entries. Overage and cancellation proceeds
  do not modify the existing driver settlement calculation.
- To use Razorpay's sandbox, select `PAYMENT_MODE=razorpay` with an
  `rzp_test_` key and matching test secret and webhook secret on a dedicated
  test database. A sandbox webhook and browser callback can reconcile the same
  order. Deploy the webhook over HTTPS before expecting provider delivery.
- To send one Gmail SMTP diagnostic message to the configured sender, run
  `../../.venv/bin/python -m app.smtp_check` from `services/api` after
  configuring credentials securely. SMTP acceptance and inbox delivery are
  checked separately.

### Start and open the full website

After installing the dependencies above, run `./scripts/start-local.sh`
from the repository root. The command starts PostgreSQL, applies migrations,
starts the API, builds Next.js, and serves the production build on port 3000.
Keep the terminal running. Use `DRIVEWELL_DEV=1` for hot reload.

If the app is running on a Cloud computer, enable an authenticated HTTP
preview for port 3000 to open it from your phone. Configure `WEB_ORIGIN` with
the exact HTTPS preview origin and restart the app so login and booking
actions work through that URL. Browser GPS requires HTTPS or a browser-local
loopback address. Public deployment requires its own HTTPS hosting and exact
origin configuration.

### Map and business-owner workspace

The embedded map defaults to OpenStreetMap raster tiles. If the browser's
network restricts external domains, allow `tile.openstreetmap.org` or set
`NEXT_PUBLIC_MAP_TILE_URL` and matching attribution for your approved tile
provider before building. Tiles are separate from route calculations.
To enable route geometry and driving-time estimates, set the API-only
`OPENROUTESERVICE_API_KEY` and allow outbound access to
`api.openrouteservice.org`. Without routing, pickup pin selection, driver
markers, and the Google Maps directions link remain available. Drivewell shows
an estimated driving time from the provider and reports when a fresh location
or a route is unavailable.

Provision a read-only business owner from a trusted shell. From
`services/api`, run `../../.venv/bin/python -m app.create_admin --role owner`.
The owner signs in at the usual login page and lands at `/owner`. Owner
accounts see aggregate booking and financial metrics. They cannot use the
admin console or read individual bookings.
