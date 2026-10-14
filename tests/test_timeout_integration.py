from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import NotificationAttempt, NotificationJob, utcnow
from app.worker import process_one


def create_registration(client, recipient):
    workshop = client.post(
        "/workshops",
        json={
            "title": "Timeout retry integration",
            "description": "",
            "scheduled_at": "2030-01-01T10:00:00Z",
        },
    )
    assert workshop.status_code == 201
    registration = client.post(
        f"/workshops/{workshop.json()['id']}/registrations", json={"member_id": recipient}
    )
    assert registration.status_code == 201
    return registration.json()


def set_scenario(base_url, mode, delay_ms=0):
    response = httpx.put(
        f"{base_url}/admin/scenario",
        json={"mode": mode, "delay_ms": delay_ms},
        timeout=1,
    )
    assert response.status_code == 200


def deliveries_from(base_url):
    response = httpx.get(f"{base_url}/admin/deliveries", timeout=1)
    assert response.status_code == 200
    return response.json()


def test_registration_timeout_retries_and_delivers_same_job(
    client, db_factory, monkeypatch, mock_http_service
):
    base_url, capture = mock_http_service
    monkeypatch.setattr("app.worker.settings.notification_service_url", base_url)
    monkeypatch.setattr("app.worker.settings.http_timeout_seconds", 0.05)
    recipient = "timeout-retry-member"
    create_registration(client, recipient)
    with db_factory() as session:
        job = session.scalar(select(NotificationJob).where(NotificationJob.recipient == recipient))
        job_id = job.id
        assert job.status == "pending"

    set_scenario(base_url, "timeout", delay_ms=250)
    assert process_one(db_factory)

    with db_factory() as session:
        job = session.get(NotificationJob, job_id)
        assert job.status == "pending"
        assert job.attempt_count == 1
        assert "ReadTimeout" in job.last_error
        failed_attempt = session.scalar(
            select(NotificationAttempt).where(
                NotificationAttempt.job_id == job_id,
                NotificationAttempt.attempt_number == 1,
            )
        )
        assert failed_attempt.outcome == "failed"
    idempotency_key = f"notification-job-{job_id}"
    assert capture.idempotency_keys == [idempotency_key]
    assert deliveries_from(base_url) == []

    set_scenario(base_url, "success")
    with db_factory() as session:
        job = session.get(NotificationJob, job_id)
        job.next_attempt_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert process_one(db_factory)
    assert capture.wait_for_completed_requests(2)

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
        assert all(attempt.started_at <= attempt.finished_at for attempt in attempts)

    assert capture.idempotency_keys == [idempotency_key, idempotency_key]
    deliveries = deliveries_from(base_url)
    assert deliveries == [
        {
            "idempotency_key": idempotency_key,
            "payload": {
                "workshop_id": job.payload["workshop_id"],
                "workshop_title": "Timeout retry integration",
                "event_type": "registration_confirmation",
                "recipient": recipient,
            },
        }
    ]


def test_timed_out_mock_request_never_records_delivery_before_success(mock_http_service):
    base_url, capture = mock_http_service
    set_scenario(base_url, "timeout", delay_ms=120)
    key = "notification-job-timeout-no-side-effect"
    payload = {"event_type": "registration_confirmation", "recipient": "timeout-member"}

    with pytest.raises(httpx.ReadTimeout):
        httpx.post(
            f"{base_url}/notifications",
            json=payload,
            headers={"Idempotency-Key": key},
            timeout=httpx.Timeout(connect=1, read=0.03, write=1, pool=1),
        )
    assert deliveries_from(base_url) == []
    assert capture.wait_for_completed_requests(1)
    assert deliveries_from(base_url) == []

    set_scenario(base_url, "success")
    response = httpx.post(
        f"{base_url}/notifications",
        json=payload,
        headers={"Idempotency-Key": key},
        timeout=1,
    )
    assert response.status_code == 200
    assert capture.wait_for_completed_requests(2)
    assert deliveries_from(base_url) == [{"idempotency_key": key, "payload": payload}]
