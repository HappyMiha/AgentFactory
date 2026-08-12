# Production API contract

AF-026 supplies the durable service boundary contract used by the versioned FastAPI surface. Every production request authenticates with a bearer token, mutations carry an `Idempotency-Key`, and conditional updates require `If-Match` against the resource ETag; stale tags fail with a conflict. Idempotency records are tenant-scoped and immutable, and key reuse with a different request digest is rejected.

Webhook deliveries are tenant-scoped, HMAC-SHA256 signed, retried up to the configured attempt limit, and replayed idempotently by delivery key. `SDKClient` is the generated-SDK contract exercised against the same transport shape as the API. OpenAPI remains available at `/api/openapi.json` and covers the registry, mission/workflow, approval, evidence, event, incident/budget, and operation resources exposed by the app.
