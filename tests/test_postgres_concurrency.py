import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.main import register
from app.models import NotificationAttempt, NotificationJob, Registration, Workshop
from app.schemas import RegistrationCreate

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set TEST_DATABASE_URL for PostgreSQL concurrency test"
)


def test_concurrent_duplicate_registration_has_one_winner():
    engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=5)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    workshop_title = f"concurrency-{uuid4()}"
    member_id = f"member-{uuid4()}"
    with factory() as session:
        workshop = Workshop(title=workshop_title, scheduled_at=datetime.now(UTC))
        session.add(workshop)
        session.commit()
        workshop_id = workshop.id

    barrier = threading.Barrier(2)

    def submit_registration():
        with factory() as session:
            barrier.wait(timeout=5)
            try:
                register(workshop_id, RegistrationCreate(member_id=member_id), session)
                return 201
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: submit_registration(), range(2)))
        assert sorted(results) == [201, 409]
        with factory() as session:
            assert session.query(Registration).filter_by(workshop_id=workshop_id).count() == 1
            assert session.query(NotificationJob).filter_by(recipient=member_id).count() == 1
    finally:
        with factory.begin() as connection:
            job_ids = connection.scalars(
                delete(NotificationJob)
                .where(NotificationJob.recipient == member_id)
                .returning(NotificationJob.id)
            ).all()
            if job_ids:
                connection.execute(
                    delete(NotificationAttempt).where(NotificationAttempt.job_id.in_(job_ids))
                )
            connection.execute(delete(Registration).where(Registration.workshop_id == workshop_id))
            connection.execute(delete(Workshop).where(Workshop.id == workshop_id))
        engine.dispose()
