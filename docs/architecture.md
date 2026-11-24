# Architecture

Next.js renders public pages and the three portals. Browser API requests use
same-origin rewrites to FastAPI, which owns authentication, pricing, booking
state, and authorization. PostgreSQL stores sessions and operational records.
Use Alembic for schema changes. Use a persistent worker with a transactional
outbox when adding push notifications and gateway reconciliation.

See FastAPI's OpenAPI document at /openapi.json on the API service.

The API groups below use the `/api/v1` prefix. Full request schemas and
paths are discoverable through the OpenAPI document.

| Group | Purpose |
| --- | --- |
| auth | Registration, login, session, logout and password reset |
| vehicles, fares, bookings | Customer-owned cars, server quotes, request lifecycle |
| drivers, availability, booking-offers | Licence submission, service preferences and serialized acceptance |
| trips, handovers, locations | Trip milestones, signed-in acknowledgements and permitted location points |
| payments | Optional orders, checkout verification, signed provider webhooks and history |
| support, admin | Tickets, operational and financial counts, licence review |
| realtime | Authenticated WebSocket status and location event hints |
