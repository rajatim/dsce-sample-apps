# Financial LoanHub backend

This FastAPI service provides demo login, loan submission, IBM Cloud Object
Storage (COS) uploads, watsonx Orchestrate agent processing, and PostgreSQL
persistence through SQLAlchemy. SQLite remains a temporary local rollback path;
PostgreSQL is selected whenever `DATABASE_URL` is present.

## Install

The project requires Python 3.13 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked
```

Do not commit `.env` files, database credentials, API keys, tokens, or rendered
connection URLs.

## Required environment variables

Set values in the process environment. The application does not require IBM
credentials merely to import or serve OpenAPI, but the corresponding workflow
needs all of its variables before it is invoked.

- Database runtime: `DATABASE_URL`
- Demo seed: `DEMO_USERNAME`, `DEMO_PASSWORD`, `DEMO_FIRST_NAME`,
  `DEMO_LAST_NAME`, `DEMO_DATE_OF_BIRTH`
- Local database bootstrap: `LOAN_DB_PASSWORD`; optional overrides are
  `PG_ADMIN_DSN`, `LOAN_DB_NAME`, and `LOAN_DB_USER`
- COS: `COS_ENDPOINT`, `COS_API_KEY_ID`, `COS_INSTANCE_CRN`, `COS_BUCKET_NAME`
- watsonx extraction: `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`
- watsonx Orchestrate: `WXO_API_KEY`, `WXO_INSTANCE_ID`,
  `WXO_SERVICE_INSTANCE_URL`, `DOC_PROCESSOR_AGENT_ID`,
  `DOCUMENT_VALIDATION_AGENT_ID`, and `FINAL_DECISION_AGENT_ID`
- Optional watsonx Orchestrate location overrides: `WXO_INSTANCE_CLOUD` and
  `WXO_INSTANCE_CLOUD_REGION`
- Optional OpenLLMetry tracing: `OPENLLMETRY_ENABLED`, `TRACELOOP_BASE_URL`,
  `OTEL_SERVICE_NAME`, `OTEL_DEPLOYMENT_ENVIRONMENT`, and `APP_VERSION`

`DATABASE_URL` must use SQLAlchemy's psycopg form:

```text
postgresql+psycopg://<user>:<password>@<host>:5432/<database>
```

For the local POC, keep the password in macOS Keychain under a dedicated
service/account and retrieve it directly into a short-lived shell variable:

```bash
LOAN_DB_PASSWORD="$(security find-generic-password \
  -s dsce-loan-postgres-local -a loan_app_dev -w)"
export LOAN_DB_PASSWORD
```

Build `DATABASE_URL` with `sqlalchemy.URL.create()` so reserved password
characters are escaped correctly. Capture the rendered value directly into the
environment; do not echo it or place it in a file. Unset `LOAN_DB_PASSWORD`
after constructing the URL.

## Local PostgreSQL 17

Install and manage only the versioned Homebrew service:

```bash
brew install postgresql@17
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/pg_isready -h 127.0.0.1 -p 5432
brew services stop postgresql@17
```

With `LOAN_DB_PASSWORD` loaded from Keychain, reconcile the local role and
database, then apply the schema:

```bash
uv run python scripts/bootstrap_local_postgres.py
uv run alembic upgrade head
uv run alembic current
```

Revision `0001` is the expected current revision.

## Import the protected legacy snapshot

Always point the importer at backup-protected SQLite and TinyDB source files.
Omitting `--apply` is a dry run and writes nothing:

```bash
uv run python scripts/migrate_legacy_data.py \
  --sqlite "$LEGACY_SQLITE_PATH" \
  --logs "$LEGACY_LOGS_PATH" \
  --database-url "$DATABASE_URL"

uv run python scripts/migrate_legacy_data.py \
  --sqlite "$LEGACY_SQLITE_PATH" \
  --logs "$LEGACY_LOGS_PATH" \
  --database-url "$DATABASE_URL" \
  --apply
```

The migrated legacy baseline is:

- 1 user
- 10 applications: 2 `passed`, 3 `rejected`, and 5 `Processing Failed`
- 325 agent events
- 1 migration anomaly
- 18 orphan agent events
- 0 application documents and 0 processing runs

The 18 orphan events all refer to the same missing legacy application. They are
preserved with a nullable application foreign key, while the missing
application is represented by one deduplicated anomaly. Therefore the correct
acceptance result is 18 orphan events and 1 anomaly, not 1 orphan event.

Running `--apply` again must insert zero rows. Verify only aggregate values; do
not print customer rows, event payloads, hashes, or credentials:

```bash
LOAN_DB_PASSWORD="$(security find-generic-password \
  -s dsce-loan-postgres-local -a loan_app_dev -w)"
PGPASSWORD="$LOAN_DB_PASSWORD" \
  /opt/homebrew/opt/postgresql@17/bin/psql \
  -h 127.0.0.1 -p 5432 -U loan_app_dev -d loan_poc_dev \
  -c "SELECT
        (SELECT count(*) FROM users) AS users,
        (SELECT count(*) FROM applications) AS applications,
        (SELECT count(*) FROM application_documents) AS documents,
        (SELECT count(*) FROM processing_runs) AS processing_runs,
        (SELECT count(*) FROM agent_events) AS events,
        (SELECT count(*) FROM migration_anomalies) AS anomalies,
        (SELECT count(*) FROM agent_events WHERE application_id IS NULL)
          AS orphan_events;"
unset LOAN_DB_PASSWORD
```

## Preserve the demo login

The seed fails closed unless `DATABASE_URL` and every `DEMO_*` variable above
is set. It matches by username, creates the user only when absent, and leaves an
existing password hash and profile unchanged by default:

```bash
uv run python scripts/seed_demo_user.py
```

Rotate the existing password only when explicitly intended:

```bash
uv run python scripts/seed_demo_user.py --rotate-password
```

The command reports only whether it created a user or rotated a password. It
does not print the username, password, hash, or database URL.

## Run and verify PostgreSQL mode

```bash
uv run main.py
curl --fail http://127.0.0.1:8000/openapi.json >/dev/null
curl --fail http://127.0.0.1:8000/docs >/dev/null
```

## Health, readiness, and demo status

The backend exposes three unauthenticated operational endpoints with distinct
purposes:

- `GET /healthz` is a shallow liveness check. It reports only whether the
  FastAPI process can respond and does not contact PostgreSQL or any IBM
  service. Use it for the OpenShift liveness probe.
- `GET /readyz` is readiness for traffic. It executes only PostgreSQL
  `SELECT 1`; failure returns HTTP 503 with a fixed, sanitized body. Use it for
  the OpenShift readiness probe. COS, watsonx.ai, WXO, and OpenLLMetry do not
  affect this endpoint.
- `GET /system-status` is a public, sanitized status document for the frontend
  `/status` page. Its schema contains only fixed capability and dependency
  fields; it never returns credentials, provider endpoints or identifiers,
  applicant data, raw exceptions, or provider response bodies.

The status service defaults to a 30-second cache, a 15-second cooldown for
`?refresh=true`, a 90-second stale threshold, and a five-second total check
budget. Concurrent callers share one refresh. A manual refresh is still
subject to the cooldown and performs no model inference, WXO thread or run,
Agent execution, or COS write.

After an ephemeral IAM token exchange where required, the IBM service checks
are low-cost and read-only: COS `HEAD Bucket`, watsonx.ai project metadata
`GET`, and WXO registered-agents `GET`. WXO registration is the live check for
the three Agents. The page may also show informational, timestamp-only local
history derived from a bounded scan of the newest 500 Agent events. That
history has no freshness window or guarantee, and its timestamps never promote
a failed live check to `ready`. The status check never runs an Agent.
OpenLLMetry is informational and never changes a user capability or the overall
availability result.

Verify only allowlisted public fields. Do not print the full dependency
document during a shared-screen check:

```bash
curl --fail --silent http://127.0.0.1:8000/healthz \
  | jq -e '.status == "ok"'
curl --fail --silent http://127.0.0.1:8000/readyz \
  | jq -e '.status == "ready"'
curl --fail --silent http://127.0.0.1:8000/system-status \
  | jq -e '
      (.overall.status | IN("ready", "limited", "unavailable", "unknown")) and
      (.capabilities | length == 4) and
      ([.dependencies[].id] | index("postgresql") != null)
    '
curl --fail --silent \
  'http://127.0.0.1:8000/system-status?refresh=true' \
  | jq '{overall_status: .overall.status, checked_at, stale}'
```

When troubleshooting requires retaining a response, write it to a
permission-restricted temporary file and inspect only named fields:

```bash
umask 077
LOAN_STATUS_FILE="$(mktemp -t loan-system-status.XXXXXX)"
curl --fail --silent http://127.0.0.1:8000/system-status \
  --output "$LOAN_STATUS_FILE"
jq '{overall_status: .overall.status, capability_count: (.capabilities | length), stale}' \
  "$LOAN_STATUS_FILE"
```

Remove the temporary file when the investigation is complete. Never print
credentials, the complete environment, or the complete dependency array.

## OpenLLMetry traces to Instana

OpenLLMetry is disabled by default. In the `itz-pl4yvb` OpenShift cluster, the
Loan FastAPI Deployment can send OTLP/gRPC traces directly to the existing
Instana Agent service without a Traceloop Cloud account, API key, extra
Collector Pod, or PVC:

```text
OPENLLMETRY_ENABLED=true
TRACELOOP_BASE_URL=instana-agent.instana-agent:4317
OTEL_SERVICE_NAME=loan-fastapi
OTEL_DEPLOYMENT_ENVIRONMENT=poc
APP_VERSION=<image tag or git SHA>
```

The endpoint has no URL scheme intentionally; OpenLLMetry treats that form as
insecure OTLP/gRPC inside the cluster. Never configure `TRACELOOP_API_KEY` for
this direct Instana path.

The application enforces the following privacy and scope controls whenever
OpenLLMetry is enabled:

- `TRACELOOP_TRACE_CONTENT=false`: do not record prompts, completions,
  embeddings, document contents, or extracted loan fields.
- `TRACELOOP_METRICS_ENABLED=false` and `TRACELOOP_LOGGING_ENABLED=false`: emit
  traces only; use the existing Instana Agent for infrastructure telemetry.
- `TRACELOOP_TELEMETRY=false`: defensively disable SDK telemetry.
- `/token`, `/docs`, and `/openapi.json` are excluded from FastAPI request
  tracing.

If tracing initialization or FastAPI instrumentation fails, the backend logs a
sanitized warning and continues serving the Loan workflow. If
`OPENLLMETRY_ENABLED=true` but `TRACELOOP_BASE_URL` is absent, tracing fails
closed instead of falling back to Traceloop Cloud.

OpenLLMetry can trace the local Loan workflow, outbound WXO HTTP requests,
SQLAlchemy, LangChain, and local watsonx SDK calls. It cannot reveal the
internal steps of remotely hosted WXO agents unless that remote runtime also
exports compatible traces.

For the guarded local integration suite, use the same loopback-only URL without
query parameters:

```bash
TEST_DATABASE_URL="$DATABASE_URL" \
  uv run python -m unittest tests.test_postgres_integration -v
```

## SQLite rollback switch

Until OpenShift cutover is separately approved, retain the untracked local
`loan_app.db` and `logs.json` files. To smoke-test or temporarily select the
untouched SQLite source:

1. Gracefully stop the FastAPI process.
2. Run `unset DATABASE_URL` in the launch shell while retaining any IBM service
   variables needed by the application.
3. Start `uv run main.py` and confirm `/openapi.json` responds with HTTP 200.
4. Do not submit or retry applications in rollback mode.
5. Stop FastAPI, restore the PostgreSQL `DATABASE_URL`, and start it again.

The fallback resolves to `sqlite:///./loan_app.db`. Check protected snapshot
checksums before and after a rollback smoke test.

## OpenShift deployment gate and handoff

OpenShift must supply `DATABASE_URL` from a Secret using the
`postgresql+psycopg://` format shown above. PDF and image bytes remain in COS
(or the existing local filesystem rollback copy); PostgreSQL stores only
application state, document metadata, processing runs, events, and anomalies.

Creating an OCP Shared PostgreSQL service, namespace, cluster, storage,
backups, database roles, and project Secret is explicitly deferred outside
this local cutover plan. Do not modify existing WXO, Zen, Instana, Tekton, or
PostgreSQL resources as part of this procedure.

Task 8 does not connect to or change `itz-pl4yvb`. Before any deployment work,
obtain a separate, explicit approval for that deployment. Only after approval,
perform the following read-only preflight and confirm the expected namespace
is `dsce-loan-poc`:

```bash
kubectl config current-context
kubectl auth whoami
kubectl get deployment,service,route -n dsce-loan-poc
kubectl get deployment loan-fastapi -n dsce-loan-poc -o yaml \
  | yq '{
      livenessProbe: .spec.template.spec.containers[].livenessProbe,
      readinessProbe: .spec.template.spec.containers[].readinessProbe
    }'
kubectl get deployment loan-fastapi -n dsce-loan-poc \
  -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
```

The expected Deployment name is `loan-fastapi`. If the live name differs,
stop and update this procedure with the observed name before any mutation.
Record the existing immutable image digest in the protected deployment record
before rollout; do not rely on a mutable tag.

Deployment execution must keep `/healthz` as liveness and set readiness to
`/readyz`. Do not point either probe at `/system-status`, because IBM service
latency must not restart a Pod or remove an otherwise ready API from service.
After rollout, verify the probes, rollout state, `/status` route, desktop and
mobile navigation, and the three public endpoints using only the allowlisted
checks above.

If rollback is required, set the Deployment image back to the exact recorded
prior `registry/repository@sha256:...` digest and monitor the rollback. Never
rebuild an old tag or infer a prior image from tag text. All deployment and
rollback mutations remain behind the same explicit approval gate.
