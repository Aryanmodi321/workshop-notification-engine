# Workshop Registration and Notifications

A FastAPI backend for workshop registration and cancellation. PostgreSQL stores the business data and a transactional outbox. A separate worker sends outbox jobs to a deterministic mock HTTP notification service.

## Requirements

- Python 3.11 or newer
- Docker Desktop with Docker Compose (recommended), or a PostgreSQL 14+ server
- Git

The API and worker use SQLAlchemy 2.x and psycopg 3. The mock notifier is a separate FastAPI service. It does not send real email or SMS.

## Run with Docker Compose

Run these commands from the repository root in PowerShell. Create `.env` only if one
does not already exist, so local settings are not overwritten:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build -d db mock-notifier
docker compose run --rm api alembic upgrade head
docker compose up --build -d api worker
```

The API is at <http://localhost:8000/docs>, and the mock service is at <http://localhost:8001/docs>. `GET /health` checks API liveness; `GET /health/db` checks database connectivity. The local Compose database credentials are for development only. Do not expose these ports or reuse those credentials in a deployed environment.

Stop the services with `docker compose down`. The PostgreSQL volume remains so pending notifications survive container restarts. `docker compose down -v` removes that volume and all local database data; do not use it when you want to preserve local records.

## Run without Docker

Create a Python virtual environment, install the project and a PostgreSQL driver, then copy `.env.example` to `.env` and point `DATABASE_URL` to your PostgreSQL instance:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env if your local PostgreSQL database, username, or password differs.
alembic upgrade head
```

Run the following from the repository root, each in its own PowerShell terminal. These
native Windows processes use the `localhost` service URLs from `.env.example`:

```powershell
uvicorn mock_service.main:app --port 8001 --reload
uvicorn app.main:app --port 8000 --reload
python -m app.worker
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local PostgreSQL URL in `.env.example` | SQLAlchemy connection URL |
| `NOTIFICATION_SERVICE_URL` | `http://localhost:8001` | Mock notification endpoint base URL |
| `WORKER_POLL_SECONDS` | `1` | Idle poll interval |
| `WORKER_MAX_ATTEMPTS` | `8` | Maximum attempts before a job becomes `dead` |
| `WORKER_LEASE_SECONDS` | `60` | Time before an abandoned processing job can be reclaimed |
| `RETRY_BASE_SECONDS` | `1` | Initial exponential retry delay |
| `RETRY_MAX_SECONDS` | `300` | Maximum retry delay |
| `HTTP_TIMEOUT_SECONDS` | `3` | Per-request timeout |

## API overview

- `POST /workshops` creates a workshop (`title`, `description`, `scheduled_at`).
- `GET /workshops` and `GET /workshops/{id}` retrieve workshops.
- `POST /workshops/{id}/registrations` registers a `member_id`; duplicate registration returns `409`.
- `GET /registrations/{id}` retrieves a registration.
- `POST /workshops/{id}/cancel` cancels once and creates one independent cancellation job for each registered member.
- `GET /notification-jobs` inspects delivery state and retry information.

Times should include a UTC offset, for example `2030-01-01T10:00:00Z`.

## Architecture and reliability

Registration and its confirmation job are inserted in one SQL transaction. If either insert fails, neither is committed. The unique database constraint on `(workshop_id, member_id)` is the final duplicate guard; failed requests do not leave confirmation jobs. Registration returns after that database transaction and never waits on the notification HTTP service.

Cancellation locks the workshop row, marks it cancelled, and inserts one outbox job per registered member in the same transaction. Repeated cancellation is idempotent: it observes the cancelled state and does not fan out another set of jobs. Each job is independent, so a failed recipient does not stop other jobs from being claimed.

Workers claim jobs in a short transaction with `FOR UPDATE SKIP LOCKED`, set a lease timestamp and unique claim token, then commit before making HTTP requests. The token prevents a worker whose lease expired from overwriting a newer worker's result. A crashed worker's `processing` job becomes eligible again after the lease expires. The receiver's idempotency key is the stable job ID, so retrying after an uncertain response does not create a second delivery effect in this mock service.

The worker records each attempt. HTTP 5xx, 408/429, and network/timeout errors are retried with capped exponential backoff and jitter. Other HTTP 4xx errors and exhausted retries become `dead` for inspection. This is **at-least-once processing**, not a universal exactly-once delivery guarantee: a real receiver must durably honor the same idempotency key for duplicate side effects to be prevented. A lost database acknowledgement after external delivery remains uncertain until the retry uses that key.

The mock service accepts `PUT /admin/scenario` with `{"mode":"success"}`, `{"mode":"http_error","status_code":503}`, or `{"mode":"timeout","delay_ms":5000}`. `GET /admin/deliveries` lists simulated deliveries. These unauthenticated controls are intended only for local demonstrations; do not expose this mock service publicly.

## Demonstration and tests

### One HTTP failure followed by delivery

With PostgreSQL, the API, worker, and mock service running, run this in PowerShell.
It creates a fresh workshop/member, leaves the mock at 503 until the worker records
one failed attempt, then restores success and checks the same job and delivery key.
The `finally` block restores success even if a check fails.

```powershell
$api = 'http://localhost:8000'
$mock = 'http://localhost:8001'
$member = 'retry-' + [guid]::NewGuid().ToString('N')
$workshop = Invoke-RestMethod -Method Post -Uri "$api/workshops" -ContentType 'application/json' -Body (@{title='Retry demo'; description=''; scheduled_at='2030-01-01T10:00:00Z'} | ConvertTo-Json)
try {
    Invoke-RestMethod -Method Put -Uri "$mock/admin/scenario" -ContentType 'application/json' -Body '{"mode":"http_error","status_code":503}' | Out-Null
    Invoke-RestMethod -Method Post -Uri "$api/workshops/$($workshop.id)/registrations" -ContentType 'application/json' -Body (@{member_id=$member} | ConvertTo-Json) | Out-Null
    $job = $null
    $deadline = (Get-Date).AddSeconds(20)
    do {
        foreach ($item in (Invoke-RestMethod -Uri "$api/notification-jobs")) {
            if ($item.recipient -eq $member) { $job = $item; break }
        }
        if ($job -and $job.attempt_count -ge 1) { break }
        Start-Sleep -Milliseconds 100
    } while ((Get-Date) -lt $deadline)
    if (-not $job -or $job.status -ne 'pending' -or $job.attempt_count -lt 1 -or $job.last_error -notmatch '503') { throw 'No pending job with a recorded HTTP 503 attempt was observed.' }
    $jobId = $job.id
    Invoke-RestMethod -Method Put -Uri "$mock/admin/scenario" -ContentType 'application/json' -Body '{"mode":"success"}' | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    do {
        foreach ($item in (Invoke-RestMethod -Uri "$api/notification-jobs")) {
            if ($item.id -eq $jobId) { $job = $item; break }
        }
        if ($job.status -eq 'sent') { break }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    if ($job.status -ne 'sent') { throw "Job $jobId did not reach sent." }
    $deliveryKey = "notification-job-$jobId"
    $delivery = $null
    foreach ($item in (Invoke-RestMethod -Uri "$mock/admin/deliveries")) {
        if ($item.idempotency_key -eq $deliveryKey) { $delivery = $item; break }
    }
    if (-not $delivery -or $delivery.payload.recipient -ne $member) { throw "Delivery $deliveryKey was not found for $member." }
    "Verified job $jobId: one recorded 503 attempt, status sent, delivery key $deliveryKey."
} finally {
    Invoke-RestMethod -Method Put -Uri "$mock/admin/scenario" -ContentType 'application/json' -Body '{"mode":"success"}' | Out-Null
}
```

### Pending job recovery after an API restart

The automated test `python -m pytest tests/test_api_restart.py` launches a test-owned
API process against a temporary SQLite file, stops and restarts only that process, and
checks that the same pending job remains. It does not use the configured PostgreSQL
database or start a worker.

To demonstrate recovery with the native services, stop the worker in its terminal
with Ctrl+C. Set the mock to success, create a workshop and registration through
`/docs`, and note the matching `pending` job ID from `GET /notification-jobs`. Stop
and restart only the API terminal with the commands below; keep PostgreSQL and the
mock service running:

```powershell
# In the API terminal: Ctrl+C, then from the repository root:
uvicorn app.main:app --port 8000 --reload
```

Query `GET /notification-jobs` again and confirm that the same ID and recipient are
still `pending`. Start the worker again with `python -m app.worker`; wait for that ID
to become `sent` and find `notification-job-<id>` in `GET /admin/deliveries`.

### Automated checks

Run the automated suite with:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

API and worker tests use isolated SQLite databases and deterministic HTTP responses.
The process-restart test uses a temporary SQLite file. The PostgreSQL concurrency test
is skipped unless `TEST_DATABASE_URL` points to a dedicated test database. To run it,
set both variables to that test database, apply migrations there, and run the test:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://<user>:<password>@localhost:5432/<dedicated_test_database>'
$env:DATABASE_URL = $env:TEST_DATABASE_URL
alembic upgrade head
python -m pytest tests/test_postgres_concurrency.py
```

Do not point this test at a database whose records must be preserved: it creates
unique test fixtures and removes those fixtures after the assertions. The included CI
job runs it against a PostgreSQL service and upgrades a clean schema first.

## Design decisions and limitations

- PostgreSQL is the source of truth and queue; no Redis, broker, or real messaging provider is needed for this scope.
- Delivery jobs and attempt records are retained for inspection; there is no automatic cleanup or dead-job replay endpoint yet.
- The mock service stores deliveries and scenario state in memory. Restarting it clears those records, so it represents delivery behavior rather than a durable production provider.
- There is no authentication, authorization, rate limiting, capacity limit, or production secret management. Add these before public deployment.
- `GET /notification-jobs` is an evaluation/debug endpoint and would need access controls and pagination in production.
- No deployment URL or performance claim is included; neither has been produced or measured.

## Project layout

```text
app/                 API, SQLAlchemy models, configuration, and worker
mock_service/        controllable mock HTTP notification service
migrations/          Alembic environment and initial schema migration
tests/               API, worker, and mock-service tests
docker-compose.yml   PostgreSQL, API, worker, and mock service
```
