import logging
import random
import signal
import time
from datetime import timedelta
from uuid import uuid4

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import NotificationAttempt, NotificationJob, utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
stopping = False


def request_backoff(attempt: int) -> float:
    cap = min(settings.retry_max_seconds, settings.retry_base_seconds * (2 ** max(attempt - 1, 0)))
    return random.uniform(cap * 0.5, cap)


def claim_one(session: Session) -> NotificationJob | None:
    now = utcnow()
    stale_before = now - timedelta(seconds=settings.worker_lease_seconds)
    # PostgreSQL workers skip rows already locked by another worker. A stale lease is
    # reclaimable after a crash; changing it to pending and claiming it is atomic.
    candidate = session.scalar(
        select(NotificationJob)
        .where(
            or_(
                (NotificationJob.status == "pending") & (NotificationJob.next_attempt_at <= now),
                (NotificationJob.status == "processing")
                & (NotificationJob.locked_at < stale_before),
            )
        )
        .order_by(NotificationJob.created_at, NotificationJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if candidate is None:
        session.rollback()
        return None
    candidate.status = "processing"
    candidate.locked_at = now
    candidate.locked_by = str(uuid4())
    session.commit()
    session.refresh(candidate)
    return candidate


def process_one(session_factory=SessionLocal, client: httpx.Client | None = None) -> bool:
    with session_factory() as session:
        job = claim_one(session)
        if job is None:
            return False
        job_id = job.id
        lock_token = job.locked_by
        event_type = job.event_type
        recipient = job.recipient
        payload = {**job.payload, "event_type": event_type, "recipient": recipient}
        attempt_number = job.attempt_count + 1

    owns_client = client is None
    client = client or httpx.Client(timeout=settings.http_timeout_seconds)
    error: str | None = None
    permanent = False
    attempt_started_at = utcnow()
    try:
        response = client.post(
            f"{settings.notification_service_url}/notifications",
            json=payload,
            headers={"Idempotency-Key": f"notification-job-{job_id}"},
        )
        if response.is_success:
            with session_factory() as session:
                job = session.get(NotificationJob, job_id)
                if job is not None and job.status == "processing" and job.locked_by == lock_token:
                    job.status = "sent"
                    job.attempt_count = attempt_number
                    job.sent_at = utcnow()
                    job.locked_at = None
                    job.locked_by = None
                    job.last_error = None
                    session.add(
                        NotificationAttempt(
                            job_id=job_id,
                            attempt_number=attempt_number,
                            started_at=attempt_started_at,
                            finished_at=utcnow(),
                            outcome="sent",
                            error=None,
                        )
                    )
                    session.commit()
            logger.info("notification delivered job_id=%s attempt=%s", job_id, attempt_number)
            return True
        error = f"notification service returned HTTP {response.status_code}"
        permanent = response.status_code < 500 and response.status_code not in (408, 429)
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if owns_client:
            client.close()

    with session_factory() as session:
        job = session.get(NotificationJob, job_id)
        if job is not None and job.status == "processing" and job.locked_by == lock_token:
            job.attempt_count = attempt_number
            job.last_error = error
            job.locked_at = None
            job.locked_by = None
            session.add(
                NotificationAttempt(
                    job_id=job_id,
                    attempt_number=attempt_number,
                    started_at=attempt_started_at,
                    finished_at=utcnow(),
                    outcome="failed",
                    error=error,
                )
            )
            if permanent or attempt_number >= settings.worker_max_attempts:
                job.status = "dead"
            else:
                job.status = "pending"
                job.next_attempt_at = utcnow() + timedelta(seconds=request_backoff(attempt_number))
            session.commit()
    logger.warning(
        "notification failed job_id=%s attempt=%s error=%s", job_id, attempt_number, error
    )
    return True


def _stop(_signum: int, _frame: object) -> None:
    global stopping
    stopping = True


def run() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("notification worker started")
    while not stopping:
        if not process_one():
            time.sleep(settings.worker_poll_seconds)
    logger.info("notification worker stopped")


if __name__ == "__main__":
    run()
