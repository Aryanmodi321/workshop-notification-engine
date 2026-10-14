from datetime import timedelta

import httpx
from sqlalchemy import select

from app.models import NotificationAttempt, NotificationJob, utcnow
from app.worker import claim_one, process_one


def make_job(factory, recipient="member"):
    with factory() as session:
        job = NotificationJob(
            event_type="registration_confirmation",
            recipient=recipient,
            payload={"workshop_id": 1, "workshop_title": "Test"},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def test_worker_persists_failure_then_retries_success(db_factory, monkeypatch):
    job_id = make_job(db_factory)
    calls = []
    request_started_at = []

    def respond(request):
        calls.append(request.headers["Idempotency-Key"])
        request_started_at.append(utcnow().replace(tzinfo=None))
        if len(calls) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"status": "delivered"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    assert process_one(db_factory, client)
    with db_factory() as session:
        job = session.get(NotificationJob, job_id)
        assert job.status == "pending"
        assert job.attempt_count == 1
        job.next_attempt_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert process_one(db_factory, client)
    with db_factory() as session:
        job = session.get(NotificationJob, job_id)
        assert job.status == "sent"
        assert job.attempt_count == 2
        attempts = session.scalars(
            select(NotificationAttempt)
            .where(NotificationAttempt.job_id == job_id)
            .order_by(NotificationAttempt.attempt_number)
        ).all()
        assert [attempt.outcome for attempt in attempts] == ["failed", "sent"]
        assert all(
            attempt.started_at <= request_time <= attempt.finished_at
            for attempt, request_time in zip(attempts, request_started_at, strict=True)
        )
    assert calls == [f"notification-job-{job_id}", f"notification-job-{job_id}"]


def test_permanent_http_4xx_marks_job_dead_without_retry(db_factory):
    job_id = make_job(db_factory)
    calls = []

    def reject(request):
        calls.append(request.headers["Idempotency-Key"])
        return httpx.Response(400, request=request)

    assert process_one(db_factory, httpx.Client(transport=httpx.MockTransport(reject)))
    with db_factory() as session:
        job = session.get(NotificationJob, job_id)
        assert job.status == "dead"
        assert job.attempt_count == 1
        assert job.last_error == "notification service returned HTTP 400"
        attempts = session.scalars(
            select(NotificationAttempt).where(NotificationAttempt.job_id == job_id)
        ).all()
        assert len(attempts) == 1
        assert attempts[0].outcome == "failed"
    assert calls == [f"notification-job-{job_id}"]


def test_timeout_retries_and_exhaustion_is_terminal(db_factory, monkeypatch):
    job_id = make_job(db_factory)
    monkeypatch.setattr("app.worker.settings.worker_max_attempts", 1)

    def timeout(request):
        raise httpx.ReadTimeout("mock timeout", request=request)

    assert process_one(db_factory, httpx.Client(transport=httpx.MockTransport(timeout)))
    with db_factory() as session:
        job = session.get(NotificationJob, job_id)
        assert job.status == "dead"
        assert job.attempt_count == 1
        assert "ReadTimeout" in job.last_error


def test_stale_processing_job_is_reclaimed(db_factory):
    job_id = make_job(db_factory)
    with db_factory() as session:
        job = session.get(NotificationJob, job_id)
        job.status = "processing"
        job.locked_at = utcnow() - timedelta(hours=1)
        session.commit()

    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request))
    )
    assert process_one(db_factory, client)
    with db_factory() as session:
        assert session.get(NotificationJob, job_id).status == "sent"


def test_two_workers_claim_different_ready_jobs(db_factory):
    first_id = make_job(db_factory, "first")
    second_id = make_job(db_factory, "second")
    with db_factory() as first_session, db_factory() as second_session:
        first = claim_one(first_session)
        second = claim_one(second_session)
    assert {first.id, second.id} == {first_id, second_id}
