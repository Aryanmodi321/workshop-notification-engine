# Architecture and design decisions

## Data ownership

PostgreSQL owns workshop state, registrations, notification jobs, and attempt history. The API does not keep registration state in process memory. A database uniqueness constraint on `(workshop_id, member_id)` makes the once-per-workshop rule hold across API processes.

## Registration transaction

```text
BEGIN
  lock workshop row and confirm it is active
  insert registration
  insert registration_confirmation outbox job
COMMIT
return registration response
```

The API performs no notification HTTP call. If any write fails, the transaction rolls back and no confirmation obligation exists. The registration response represents the committed registration; delivery proceeds independently.

## Cancellation transaction

```text
BEGIN
  lock workshop row
  if already cancelled: return current state
  mark workshop cancelled
  insert one workshop_cancelled job for each registered member
COMMIT
```

The row lock serializes registration against cancellation in PostgreSQL. A registration that commits first is included in the fan-out; one that reaches the lock after cancellation receives `409`. Cancellation jobs are independent records and are retried separately.

## Worker claim and delivery

The worker selects the oldest due `pending` job with `FOR UPDATE SKIP LOCKED`, assigns a lease timestamp and random claim token, and commits. It performs HTTP outside the transaction. On completion, the worker writes status and attempt history only if its token still owns the row. This prevents an expired worker from overwriting the result of a newer claimant.

An expired `processing` lease can be reclaimed. Therefore, if a worker stops after the receiver delivered but before the database records success, the job will be attempted again. Each job sends the same `Idempotency-Key`; the mock receiver deduplicates that effect. A production receiver must provide durable idempotency storage for the same protection. The system offers at-least-once processing; transport and database boundaries prevent claiming general exactly-once delivery.

Transient HTTP errors, timeouts, and connection failures are retried with bounded exponential backoff and jitter. Permanent client errors are marked `dead`; transient errors become `dead` when the attempt limit is reached. The job row retains its latest error and `notification_attempts` retains the outcome of each completed attempt.

## Mock service boundary

The notifier is a separate HTTP application and container. Its scenario endpoint deterministically selects success, an HTTP failure, or a delayed response that can exceed the worker timeout. Successful simulated deliveries are indexed by the idempotency key. Scenario configuration and delivery inspection are intentionally unauthenticated for local evaluation only.

## Limitations

- A `dead` job requires manual database inspection and does not yet have an operator replay endpoint.
- The mock receiver's idempotency store is in memory and is cleared on restart.
- Worker claims and migration are designed for PostgreSQL; the quick unit suite uses SQLite for isolated API and state-machine tests. PostgreSQL behavior should be verified with the included Compose and CI setup.
- There is no authentication or authorization, rate limiting, queue metrics, or load test. The debug job listing and mock administration routes must not be exposed to an untrusted network.
