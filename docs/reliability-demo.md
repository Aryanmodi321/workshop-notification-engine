# Reliability demonstration guide

Run these demonstrations from the repository root in **PowerShell 7** with PostgreSQL, the API (`localhost:8000`), the mock service (`localhost:8001`), and the worker running. They use fresh workshop titles and member IDs; no existing registrations or jobs are assumed. Keep a dedicated local/demo database for manual demonstrations. Because mock scenarios apply globally, use an otherwise idle demo environment before running the failure and timeout steps; this avoids changing the outcome of other queued jobs.

For retry demonstrations, start the native worker in its own terminal with a longer first retry window so the mock can be restored after the first failure and before another attempt:

```powershell
$env:RETRY_BASE_SECONDS = '20'
$env:RETRY_MAX_SECONDS = '60'
python -m app.worker
```

The worker's first retry is then scheduled with jitter between 10 and 20 seconds. Restore the mock as soon as the failed attempt appears. These environment variables affect only this worker process. For Docker Compose, use the configured worker and restore the scenario promptly; the same state checks below apply.

## Shared PowerShell helpers

Paste this block once into the PowerShell session used for the API demonstrations. `Call-Api` returns error responses such as 409 and 422 instead of throwing, which lets the examples check their status codes.

```powershell
$api = 'http://localhost:8000'
$mock = 'http://localhost:8001'

function Call-Api {
    param([string]$Method, [string]$Uri, [object]$Json)
    $request = @{ Method = $Method; Uri = $Uri; SkipHttpErrorCheck = $true }
    if ($null -ne $Json) {
        $request.ContentType = 'application/json'
        $request.Body = $Json | ConvertTo-Json -Compress -Depth 8
    }
    Invoke-WebRequest @request
}

function Set-MockScenario {
    param([string]$Mode, [int]$StatusCode = 503, [int]$DelayMs = 5000)
    Invoke-RestMethod -Method Put -Uri "$mock/admin/scenario" -ContentType 'application/json' `
        -Body (@{ mode = $Mode; status_code = $StatusCode; delay_ms = $DelayMs } | ConvertTo-Json -Compress) | Out-Null
}

function New-DemoWorkshop {
    param([string]$Label)
    $suffix = [guid]::NewGuid().ToString('N')
    $response = Call-Api POST "$api/workshops" @{
        title = "$Label-$suffix"
        description = 'Local reliability demonstration'
        scheduled_at = '2030-01-01T10:00:00Z'
    }
    if ($response.StatusCode -ne 201) { throw "Workshop creation returned $($response.StatusCode): $($response.Content)" }
    $response.Content | ConvertFrom-Json
}

function New-DemoRegistration {
    param([string]$Label)
    $workshop = New-DemoWorkshop $Label
    $member = "$Label-$([guid]::NewGuid().ToString('N'))"
    $response = Call-Api POST "$api/workshops/$($workshop.id)/registrations" @{ member_id = $member }
    if ($response.StatusCode -ne 201) { throw "Registration returned $($response.StatusCode): $($response.Content)" }
    [pscustomobject]@{ workshop = $workshop; member = $member; registration = ($response.Content | ConvertFrom-Json) }
}

function Get-DemoJob {
    param([int]$Id)
    $matches = @((Invoke-RestMethod "$api/notification-jobs") | Where-Object id -eq $Id)
    if ($matches.Count -ne 1) { throw "Expected one job with ID $Id; found $($matches.Count)." }
    $matches[0]
}

function Get-DemoJobForMember {
    param([string]$Member)
    $matches = @((Invoke-RestMethod "$api/notification-jobs") | Where-Object recipient -eq $Member)
    if ($matches.Count -ne 1) { throw "Expected one job for $Member; found $($matches.Count)." }
    $matches[0]
}

function Wait-DemoJob {
    param([int]$Id, [string]$Status, [int]$AttemptsAtLeast = 0, [string]$ErrorLike = '', [int]$TimeoutSeconds = 60)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $job = Get-DemoJob $Id
        if ($job.status -eq $Status -and $job.attempt_count -ge $AttemptsAtLeast -and
            (!$ErrorLike -or $job.last_error -like "*$ErrorLike*")) { return $job }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Job $Id did not reach $Status with at least $AttemptsAtLeast attempts. Last observed: $($job | ConvertTo-Json -Compress)."
}

function Find-DemoDelivery {
    param([int]$JobId)
    $key = "notification-job-$JobId"
    @((Invoke-RestMethod "$mock/admin/deliveries") | Where-Object idempotency_key -eq $key)
}

function Assert-DemoDelivery {
    param([int]$JobId, [string]$Member)
    $matches = @(Find-DemoDelivery $JobId)
    if ($matches.Count -ne 1 -or $matches[0].payload.recipient -ne $Member) {
        throw "Expected exactly one delivery for notification-job-$JobId to $Member."
    }
    $matches[0]
}

Set-MockScenario success
```

Each scenario that changes the mock wraps the exercise in `try/finally` and restores success. Do not restart the mock during a demo: its delivery records are in memory.

## Create, register, reject duplicates, and reject invalid input

This checks successful workshop and registration creation, duplicate rejection, and that invalid registration input creates no additional job. The worker may deliver the confirmation quickly, so the expected final job state is `sent`.

```powershell
try {
    Set-MockScenario success
    $demo = New-DemoRegistration 'basic'
    $job = Get-DemoJobForMember $demo.member
    $countBeforeDuplicate = @((Invoke-RestMethod "$api/notification-jobs")).Count
    $duplicate = Call-Api POST "$api/workshops/$($demo.workshop.id)/registrations" @{ member_id = $demo.member }
    $countAfterDuplicate = @((Invoke-RestMethod "$api/notification-jobs")).Count
    if ($duplicate.StatusCode -ne 409) { throw "Duplicate registration returned $($duplicate.StatusCode), expected 409." }
    if ($countAfterDuplicate -ne $countBeforeDuplicate) { throw 'Duplicate registration unexpectedly created another notification job.' }

    $countBeforeInvalid = $countAfterDuplicate
    $invalid = Call-Api POST "$api/workshops/$($demo.workshop.id)/registrations" @{ member_id = '' }
    $countAfterInvalid = @((Invoke-RestMethod "$api/notification-jobs")).Count
    if ($invalid.StatusCode -ne 422) { throw "Invalid registration returned $($invalid.StatusCode), expected 422." }
    if ($countAfterInvalid -ne $countBeforeInvalid) { throw 'Invalid registration unexpectedly created a notification job.' }

    $job = Wait-DemoJob $job.id sent 1
    $delivery = Assert-DemoDelivery $job.id $demo.member
    "Workshop $($demo.workshop.id); registration $($demo.registration.id); job $($job.id) is $($job.status); key $($delivery.idempotency_key). Duplicate=409; invalid=422 with no additional job."
} finally {
    Set-MockScenario success
}
```

The API's `GET /notification-jobs` response does not include payloads or attempt-history rows. It does expose job ID, recipient, status, attempt count, and last error. To inspect full attempt rows in PostgreSQL, connect with your local PostgreSQL client without pasting credentials into a screenshot and run:

```sql
SELECT id, recipient, event_type, status, attempt_count, last_error
FROM notification_jobs WHERE id = <job_id>;
SELECT attempt_number, outcome, error, started_at, finished_at
FROM notification_attempts WHERE job_id = <job_id> ORDER BY attempt_number;
```

## Registration returns before notification delivery

In the worker terminal, stop the worker with Ctrl+C. With the API, PostgreSQL, and mock still running, create the registration while no worker can deliver it:

```powershell
try {
    Set-MockScenario success
    $demo = New-DemoRegistration 'async-return'
    $job = Get-DemoJobForMember $demo.member
    if ($demo.registration.member_id -ne $demo.member -or $job.status -ne 'pending' -or $job.attempt_count -ne 0) {
        throw 'Registration did not return with its confirmation job pending.'
    }
    if (@(Find-DemoDelivery $job.id).Count -ne 0) { throw 'A delivery exists while the worker is stopped.' }
    "POST registration returned 201 for job $($job.id); state=pending; no mock delivery exists."
} finally {
    Set-MockScenario success
}
```

Now restart the worker with `python -m app.worker`. Verify delivery of that same job:

```powershell
$job = Wait-DemoJob $job.id sent 1
$delivery = Assert-DemoDelivery $job.id $demo.member
"Job $($job.id) is $($job.status); delivered to $($delivery.payload.recipient)."
```

The successful `POST` response and pending outbox row are observed before any worker delivery, demonstrating that the API request does not wait on the notification service.

## HTTP 503 followed by successful retry

Set the global mock scenario before creating the new registration. Observe the first recorded failure, restore success immediately, then wait for that same job. The longer retry window configured above avoids burning attempts while the mock is being restored.

```powershell
try {
    Set-MockScenario http_error 503
    $demo = New-DemoRegistration 'http-retry'
    $job = Get-DemoJobForMember $demo.member
    $job = Wait-DemoJob $job.id pending 1 '503' 30
    "Observed HTTP 503 for job $($job.id), state=$($job.status), attempts=$($job.attempt_count)."
} finally {
    Set-MockScenario success
}
$job = Wait-DemoJob $job.id sent 2
$delivery = Assert-DemoDelivery $job.id $demo.member
"Same job $($job.id) is $($job.status), attempts=$($job.attempt_count), key=$($delivery.idempotency_key)."
```

Expected state after the first attempt: `pending`, `attempt_count >= 1`, and `last_error` containing `503`. After retry: `sent`, with one mock delivery for `notification-job-<job id>` and the fresh member recipient.

## Mock timeout followed by successful retry

The default worker HTTP timeout is 3 seconds. `delay_ms=5000` exceeds it. Keep the retry window setting above so there is time to restore the mock after the timeout attempt.

```powershell
try {
    Set-MockScenario timeout 503 5000
    $demo = New-DemoRegistration 'timeout-retry'
    $job = Get-DemoJobForMember $demo.member
    $job = Wait-DemoJob $job.id pending 1 'ReadTimeout' 30
    if (@(Find-DemoDelivery $job.id).Count -ne 0) { throw 'Timed-out request unexpectedly created a mock delivery.' }
    "Observed timeout for job $($job.id), state=$($job.status), attempts=$($job.attempt_count); no delivery yet."
} finally {
    Set-MockScenario success
}
$job = Wait-DemoJob $job.id sent 2
$delivery = Assert-DemoDelivery $job.id $demo.member
"Same job $($job.id) is $($job.status), attempts=$($job.attempt_count), key=$($delivery.idempotency_key)."
```

The timeout mode waits before returning its configured 504; the worker's shorter client timeout is expected to record `ReadTimeout`. The mock only adds a delivery after a successful response, so the delivery list remains empty for this key until the successful retry.

## Cancellation fan-out to all registered members

The public mock failure scenario is global: it cannot choose a recipient. First demonstrate successful fan-out to three fresh members:

```powershell
try {
    Set-MockScenario success
    $workshop = New-DemoWorkshop 'cancel-fanout'
    $members = @(
        "cancel-a-$([guid]::NewGuid().ToString('N'))",
        "cancel-b-$([guid]::NewGuid().ToString('N'))",
        "cancel-c-$([guid]::NewGuid().ToString('N'))"
    )
    foreach ($member in $members) {
        $response = Call-Api POST "$api/workshops/$($workshop.id)/registrations" @{ member_id = $member }
        if ($response.StatusCode -ne 201) { throw "Registration for $member returned $($response.StatusCode)." }
    }
    $cancel = Call-Api POST "$api/workshops/$($workshop.id)/cancel" $null
    if ($cancel.StatusCode -ne 200) { throw "Cancellation returned $($cancel.StatusCode)." }
    $cancelAgain = Call-Api POST "$api/workshops/$($workshop.id)/cancel" $null
    if ($cancelAgain.StatusCode -ne 200) { throw 'Repeated cancellation was not accepted idempotently.' }

    $jobs = @((Invoke-RestMethod "$api/notification-jobs") | Where-Object {
        $_.event_type -eq 'workshop_cancelled' -and $_.recipient -in $members
    })
    if ($jobs.Count -ne 3 -or (@($jobs.recipient | Sort-Object -Unique).Count -ne 3)) {
        throw "Expected exactly one cancellation job per member; found $($jobs.Count)."
    }
    foreach ($item in $jobs) {
        $sent = Wait-DemoJob $item.id sent 1
        $null = Assert-DemoDelivery $sent.id $sent.recipient
    }
    'Three members each have one sent cancellation job and one matching delivery; repeated cancellation added no duplicates.'
} finally {
    Set-MockScenario success
}
```

For the selective transient-failure case, run the existing integration test:

```powershell
python -m pytest tests/test_cancellation_integration.py::test_cancellation_fanout_is_independent_when_one_recipient_fails -v
```

This test uses the API `TestClient`, an isolated in-memory SQLite database, and the actual mock FastAPI app served in-process. Its request-capture middleware injects exactly one HTTP 503 for one selected cancellation recipient; other recipients succeed. It asserts one cancellation job per member, no duplicate fan-out after repeated cancellation, the failed job remains independently `pending`, successful jobs are `sent`, attempt outcomes and stable keys match, and the retry produces the final delivery without resending successful recipients. Fixture teardown restores mock success and clears its in-memory records. This targeted recipient failure is not available through the public mock's global `PUT /admin/scenario` API.

## PostgreSQL API restart recovery

For native services, stop only the worker with Ctrl+C. Ensure the mock is in success mode, then run:

```powershell
try {
    Set-MockScenario success
    $demo = New-DemoRegistration 'api-restart'
    $job = Get-DemoJobForMember $demo.member
    if ($job.status -ne 'pending' -or $job.attempt_count -ne 0) { throw 'Job was not pending; worker may still be running.' }
    $jobId = $job.id
    if (@(Find-DemoDelivery $jobId).Count -ne 0) { throw 'Delivery exists before the API restart.' }
    "Record this ID and recipient: job=$jobId recipient=$($demo.member) status=$($job.status)."
} finally {
    Set-MockScenario success
}
```

Stop and restart only the API in its terminal; keep PostgreSQL and the mock service running:

```powershell
# In the API terminal: Ctrl+C, then from the repository root:
uvicorn app.main:app --port 8000 --reload
```

Back in the PowerShell demo session, check the same ID and recipient are still pending. Then start the worker (`python -m app.worker`) and verify the same job is sent:

```powershell
$afterRestart = Get-DemoJob $jobId
if ($afterRestart.recipient -ne $demo.member -or $afterRestart.status -ne 'pending') {
    throw 'The same pending PostgreSQL job was not observed after the API restart.'
}
# Start/restart the worker in its terminal before waiting here.
$afterDelivery = Wait-DemoJob $jobId sent 1
$delivery = Assert-DemoDelivery $jobId $demo.member
"Restart recovery verified: job=$jobId recipient=$($afterDelivery.recipient) status=$($afterDelivery.status) key=$($delivery.idempotency_key)."
```

The automated `tests/test_api_restart.py` is a separate process-restart check using a temporary SQLite file; it does not start a worker. The opt-in `tests/test_postgres_api_restart_e2e.py` uses a unique schema in the explicitly configured `POSTGRES_E2E_TEST_DATABASE_URL`, real API and worker subprocesses, and the in-process mock service. It runs in CI against an ephemeral PostgreSQL service. Do not set that variable to the development database.

## Stable idempotency key and duplicate delivery

After a job is `sent`, repeat its already-successful request to the mock using the same key and payload. The mock should acknowledge a duplicate without creating another delivery record:

```powershell
try {
    Set-MockScenario success
    $demo = New-DemoRegistration 'idempotency'
    $job = Get-DemoJobForMember $demo.member
    $job = Wait-DemoJob $job.id sent 1
    $null = Assert-DemoDelivery $job.id $demo.member
    $key = "notification-job-$($job.id)"
    $payload = @{
        workshop_id = $demo.workshop.id
        workshop_title = $demo.workshop.title
        event_type = 'registration_confirmation'
        recipient = $demo.member
    }
    $repeat = Invoke-RestMethod -Method Post -Uri "$mock/notifications" `
        -Headers @{ 'Idempotency-Key' = $key } -ContentType 'application/json' `
        -Body ($payload | ConvertTo-Json -Compress)
    $matching = @(Find-DemoDelivery $job.id)
    if (-not $repeat.duplicate -or $matching.Count -ne 1 -or $matching[0].payload.recipient -ne $demo.member) {
        throw 'Repeated key was not deduplicated as expected.'
    }
    "Duplicate acknowledged; one delivery remains for $key."
} finally {
    Set-MockScenario success
}
```

The key is derived from the notification job ID and remains stable across worker retries. This demonstrates duplicate protection in this mock while it is running; it is not an exactly-once guarantee for arbitrary receivers.

## What the implementation guarantees and what to capture

- Registration and its confirmation outbox row commit in one PostgreSQL transaction. The HTTP registration response does not wait for the worker.
- Cancellation commits the cancelled workshop and one independent outbox job per registered member. A failure for one job does not block other jobs.
- The worker retries HTTP 5xx, 408/429, network errors, and timeouts with capped exponential backoff and jitter. `WORKER_MAX_ATTEMPTS` defaults to 8; exhausted jobs become `dead`. Other 4xx responses are permanent and become `dead` immediately. There is no replay endpoint yet; a dead job requires manual intervention.
- A worker claim is leased. If the worker crashes while a row is `processing`, another worker can reclaim it after `WORKER_LEASE_SECONDS` (default 60 seconds). This is lease recovery, not a promise of immediate recovery.
- Processing is at-least-once. A receiver must durably honor the idempotency key to suppress duplicate side effects. This mock deduplicates by key only in its current process memory.
- PostgreSQL preserves jobs across API restarts. The mock's delivery records and scenario are in memory and are cleared when the mock restarts. Restarting the mock therefore loses its delivery evidence and its remembered deduplication keys; the PostgreSQL job remains, but this mock cannot prove a prior receiver-side effect after its own restart.

Evidence checklist for screenshots or a short recording:

1. Show fresh workshop/registration responses, duplicate `409`, invalid `422`, and unchanged job count for invalid registration.
2. Show registration response with worker stopped, the job `pending` with zero attempts, and no matching mock delivery; then show the same job `sent` after worker start.
3. For HTTP failure and timeout, show the pending job's attempt count and error before restoring success, then the same ID `sent` and its matching `notification-job-<id>` delivery.
4. Show three cancellation recipients, their distinct job IDs and delivery keys; run the selective-failure integration test and include its actual passing output for the one-recipient 503/retry case.
5. For PostgreSQL restart, show the same job ID/recipient before and after restarting only the API, followed by `sent` and the mock delivery record.
6. Show a repeated request with the same idempotency key acknowledged as duplicate while the mock still lists one record.

Use only local demo data in captures. Do not include `.env`, database URLs/passwords, terminal history containing secrets, or logs with sensitive configuration. Keep output and screenshots as observed; do not edit or fabricate them.
