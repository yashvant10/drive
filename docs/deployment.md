# Deployment

Deploy FastAPI from `services/api/Dockerfile` and provision PostgreSQL
separately. Use an encrypted PostgreSQL connection, a dedicated database role,
and backups with a verified restoration process. Set API-only credentials in
the deployment environment. Run `alembic upgrade head` as a single release
job before rolling out the API. Check `/health` and alert on failed readiness.

Build the frontend with `apps/web` as the root and set `API_URL` to the
trusted HTTPS API upstream at build and runtime. Route browser HTTP and
WebSocket traffic to the API under the same public site origin. For hosting
that forwards HTTP rewrites only, use an edge proxy that handles WebSocket
upgrades or rely on the existing browser polling until a suitable proxy is
configured. Set `WEB_ORIGIN` on the API to the exact public site origin and
`COOKIE_SECURE=true`. Ensure proxy forwarding and trusted proxy IP settings
are explicitly configured. Use HTTPS and redact password-reset query strings.

Enable body size limits at the gateway, restrict administrator access and
configure monitoring before production. Licence PDFs use private object storage when configured and PostgreSQL for local development. Administrators download them through authorized, audited attachments. Add malware scanning and retention controls before commercial operation. Add a retention policy for stored
coordinates, licences and authentication records.

Razorpay orders left in `CREATING` after a provider error require manual
reconciliation in Razorpay by the receipt reference (the local payment UUID).
Review the captured payment and trip records before making financial
adjustments. The refund and payout panels record provider state and support manual reconciliation. Exercise both with provider test credentials before enabling real funds.

If the build host uses a TLS-inspecting proxy, provide its trusted CA bundle
to BuildKit for PyPI access. The bundle is mounted during dependency
installation and is omitted from the resulting image.

```sh
docker build --secret id=pip_ca,src=/etc/ssl/certs/ca-certificates.crt -t drivewell-api services/api
```

Configure a private S3-compatible bucket for new licence uploads, enable the
provider's default encryption and use an identity restricted to the document
prefix. Grant read access only to the API service. The API authorizes and logs
licence downloads. Add malware scanning and a PII retention process before
handling live documents.

The background scheduler uses PostgreSQL row locking for idempotent request
expiry and delivery claims. Dispatches with ambiguous provider responses
stay in the delivery log for operator review. Alert on expiring/expired
sessions, stuck payments, notification failures, and rejected payout
reconciliations.

Enable provider network destinations for configured integrations. Razorpay and
RazorpayX use api.razorpay.com. Verify uses verify.twilio.com and notification
SMS uses api.twilio.com. The browser loads checkout from checkout.razorpay.com.
Private object storage and SMTP need access to the selected providers.
