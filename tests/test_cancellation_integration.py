from collections import defaultdict
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.models import NotificationAttempt, NotificationJob, utcnow
from app.worker import process_one


def test_cancellation_fanout_is_independent_when_one_recipient_fails(
    client, db_factory, monkeypatch, mock_http_service
):
    base_url, capture = mock_http_service
    monkeypatch.setattr("app.worker.settings.notification_service_url", base_url)
    monkeypatch.setattr("app.worker.request_backoff", lambda _attempt: 3600)
    recipients = {"fanout-member-a", "fanout-member-b", "fanout-member-c"}
    failed_recipient = "fanout-member-b"

    workshop_response = client.post(
        "/workshops",
        json={
            "title": "Cancellation fan-out integration",
            "description": "",
            "scheduled_at": "2030-01-01T10:00:00Z",
        },
    )
    assert workshop_response.status_code == 201
    workshop_id = workshop_response.json()["id"]

    for recipient in recipients:
        registration = client.post(
            f"/workshops/{workshop_id}/registrations", json={"member_id": recipient}
        )
        assert registration.status_code == 201
        assert process_one(db_factory)

    assert client.post(f"/workshops/{workshop_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/workshops/{workshop_id}/cancel").status_code == 200

    with db_factory() as session:
        cancellation_jobs = [
            job
            for job in session.scalars(
                select(NotificationJob).where(
                    NotificationJob.event_type == "workshop_cancelled"
                )
            )
            if job.payload["workshop_id"] == workshop_id
        ]
        assert len(cancellation_jobs) == len(recipients)
        jobs_by_recipient = {job.recipient: job.id for job in cancellation_jobs}
        assert set(jobs_by_recipient) == recipients
        assert len(set(jobs_by_recipient.values())) == len(recipients)

    capture.fail_once_for_recipient(failed_recipient)
    for _ in range(len(recipients)):
        assert process_one(db_factory)

    with db_factory() as session:
        jobs_by_id = {
            job.id: job
            for job in session.scalars(
                select(NotificationJob).where(
                    NotificationJob.id.in_(jobs_by_recipient.values())
                )
            )
        }
        attempts_by_job = defaultdict(list)
        for attempt in session.scalars(
            select(NotificationAttempt)
            .where(NotificationAttempt.job_id.in_(jobs_by_recipient.values()))
            .order_by(NotificationAttempt.attempt_number)
        ):
            attempts_by_job[attempt.job_id].append(attempt)

    for recipient, job_id in jobs_by_recipient.items():
        job = jobs_by_id[job_id]
        if recipient == failed_recipient:
            assert job.status == "pending"
            assert job.attempt_count == 1
            assert "HTTP 503" in job.last_error
            failure_history = [
                (attempt.attempt_number, attempt.outcome)
                for attempt in attempts_by_job[job_id]
            ]
            assert failure_history == [(1, "failed")]
            assert "HTTP 503" in attempts_by_job[job_id][0].error
        else:
            assert job.status == "sent"
            assert job.attempt_count == 1
            success_history = [
                (attempt.attempt_number, attempt.outcome)
                for attempt in attempts_by_job[job_id]
            ]
            assert success_history == [(1, "sent")]

    cancellation_requests = [
        request
        for request in capture.requests
        if request["event_type"] == "workshop_cancelled"
    ]
    requests_by_recipient = defaultdict(list)
    for request in cancellation_requests:
        requests_by_recipient[request["recipient"]].append(request)
        expected_key = f"notification-job-{jobs_by_recipient[request['recipient']]}"
        assert request["idempotency_key"] == expected_key
    assert len(cancellation_requests) == len(recipients)
    assert requests_by_recipient[failed_recipient][0]["status_code"] == 503
    for recipient in recipients - {failed_recipient}:
        assert [request["status_code"] for request in requests_by_recipient[recipient]] == [200]

    def cancellation_deliveries():
        response = httpx.get(f"{base_url}/admin/deliveries", timeout=1)
        assert response.status_code == 200
        return {
            item["idempotency_key"]: item["payload"]
            for item in response.json()
            if item["payload"]["event_type"] == "workshop_cancelled"
        }

    deliveries_before_retry = cancellation_deliveries()
    assert set(deliveries_before_retry) == {
        f"notification-job-{job_id}"
        for recipient, job_id in jobs_by_recipient.items()
        if recipient != failed_recipient
    }
    for recipient, job_id in jobs_by_recipient.items():
        key = f"notification-job-{job_id}"
        if recipient != failed_recipient:
            assert deliveries_before_retry[key]["recipient"] == recipient

    capture.restore_success()
    success_mode = httpx.put(
        f"{base_url}/admin/scenario", json={"mode": "success"}, timeout=1
    )
    assert success_mode.status_code == 200
    failed_job_id = jobs_by_recipient[failed_recipient]
    with db_factory() as session:
        failed_job = session.get(NotificationJob, failed_job_id)
        failed_job.next_attempt_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert process_one(db_factory)

    with db_factory() as session:
        final_jobs = {
            job.recipient: job
            for job in session.scalars(
                select(NotificationJob).where(
                    NotificationJob.id.in_(jobs_by_recipient.values())
                )
            )
        }
        final_attempts = defaultdict(list)
        for attempt in session.scalars(
            select(NotificationAttempt)
            .where(NotificationAttempt.job_id.in_(jobs_by_recipient.values()))
            .order_by(NotificationAttempt.attempt_number)
        ):
            final_attempts[attempt.job_id].append(attempt)

    for recipient, job_id in jobs_by_recipient.items():
        assert final_jobs[recipient].status == "sent"
        expected_outcomes = ["failed", "sent"] if recipient == failed_recipient else ["sent"]
        assert [attempt.outcome for attempt in final_attempts[job_id]] == expected_outcomes

    final_requests_by_recipient = defaultdict(list)
    for request in capture.requests:
        if request["event_type"] == "workshop_cancelled":
            final_requests_by_recipient[request["recipient"]].append(request)
    retry_statuses = [
        request["status_code"] for request in final_requests_by_recipient[failed_recipient]
    ]
    assert retry_statuses == [503, 200]
    for recipient in recipients - {failed_recipient}:
        assert len(final_requests_by_recipient[recipient]) == 1

    final_deliveries = cancellation_deliveries()
    assert set(final_deliveries) == {
        f"notification-job-{job_id}" for job_id in jobs_by_recipient.values()
    }
    for recipient, job_id in jobs_by_recipient.items():
        assert final_deliveries[f"notification-job-{job_id}"]["recipient"] == recipient
