import pytest
from sqlalchemy import event, func, select

from app.models import NotificationJob, Registration


def create_workshop(client):
    response = client.post(
        "/workshops",
        json={"title": "Backend Basics", "description": "", "scheduled_at": "2030-01-01T10:00:00Z"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_create_read_and_health(client):
    workshop_id = create_workshop(client)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/db").json() == {"status": "ok"}
    assert client.get(f"/workshops/{workshop_id}").json()["title"] == "Backend Basics"
    assert client.get("/workshops/999").status_code == 404


def test_registration_is_atomic_and_duplicate_is_rejected(client, db_factory):
    workshop_id = create_workshop(client)
    registered = client.post(
        f"/workshops/{workshop_id}/registrations", json={"member_id": "member-1"}
    )
    assert registered.status_code == 201
    assert registered.json()["member_id"] == "member-1"
    duplicate = client.post(
        f"/workshops/{workshop_id}/registrations", json={"member_id": "member-1"}
    )
    assert duplicate.status_code == 409
    with db_factory() as session:
        assert session.scalar(select(func.count()).select_from(Registration)) == 1
        jobs = session.scalars(select(NotificationJob)).all()
        assert len(jobs) == 1
        assert jobs[0].status == "pending"


def test_failed_registration_has_no_confirmation(client, db_factory):
    workshop_id = create_workshop(client)
    response = client.post(f"/workshops/{workshop_id}/registrations", json={"member_id": ""})
    assert response.status_code == 422
    with db_factory() as session:
        assert session.scalar(select(func.count()).select_from(NotificationJob)) == 0
    assert (
        client.post("/workshops/999/registrations", json={"member_id": "member-2"}).status_code
        == 404
    )


def test_transaction_rollback_does_not_leave_registration_or_job(client, db_factory):
    workshop_id = create_workshop(client)

    def fail_before_commit(session):
        if any(isinstance(item, NotificationJob) for item in session.new):
            raise RuntimeError("injected commit failure")

    event.listen(db_factory.class_, "before_commit", fail_before_commit)
    try:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            client.post(f"/workshops/{workshop_id}/registrations", json={"member_id": "rollback"})
    finally:
        event.remove(db_factory.class_, "before_commit", fail_before_commit)
    with db_factory() as session:
        assert session.scalar(select(func.count()).select_from(Registration)) == 0
        assert session.scalar(select(func.count()).select_from(NotificationJob)) == 0


def test_cancel_fans_out_once_and_rejects_later_registration(client, db_factory):
    workshop_id = create_workshop(client)
    for member in ("member-1", "member-2"):
        assert (
            client.post(
                f"/workshops/{workshop_id}/registrations", json={"member_id": member}
            ).status_code
            == 201
        )
    assert client.post(f"/workshops/{workshop_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/workshops/{workshop_id}/cancel").status_code == 200
    assert (
        client.post(
            f"/workshops/{workshop_id}/registrations", json={"member_id": "late"}
        ).status_code
        == 409
    )
    with db_factory() as session:
        jobs = session.scalars(select(NotificationJob).order_by(NotificationJob.id)).all()
        assert [job.event_type for job in jobs].count("registration_confirmation") == 2
        cancellations = [job for job in jobs if job.event_type == "workshop_cancelled"]
        assert {job.recipient for job in cancellations} == {"member-1", "member-2"}
        assert len(cancellations) == 2


def test_registration_details_and_invalid_workshop(client):
    workshop_id = create_workshop(client)
    response = client.post(f"/workshops/{workshop_id}/registrations", json={"member_id": "member"})
    registration_id = response.json()["id"]
    assert client.get(f"/registrations/{registration_id}").status_code == 200
    assert client.get("/registrations/12345").status_code == 404
    assert client.post("/workshops/12345/cancel").status_code == 404
