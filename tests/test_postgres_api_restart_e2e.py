"""PostgreSQL API restart recovery using test-owned API and worker processes.

Set POSTGRES_E2E_TEST_DATABASE_URL to a dedicated test database to enable this test.
It creates a unique schema and intentionally leaves that schema intact for inspection.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models import NotificationJob

POSTGRES_URL = os.getenv("POSTGRES_E2E_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set POSTGRES_E2E_TEST_DATABASE_URL to a dedicated PostgreSQL test database",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_until(description, check, process, log_path, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"{description}: process exited:\n{log_path.read_text()}")
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {description}:\n{log_path.read_text()}")


def test_postgres_pending_job_survives_api_restart_and_is_delivered(
    tmp_path, mock_http_service
):
    assert POSTGRES_URL is not None
    project_root = Path(__file__).resolve().parents[1]
    schema = f"restart_e2e_{uuid4().hex}"
    base_engine = create_engine(POSTGRES_URL)
    try:
        with base_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        base_engine.dispose()

    schema_url = make_url(POSTGRES_URL).set(
        query={"options": f"-csearch_path={schema},public"}
    )
    database_url = schema_url.render_as_string(hide_password=False)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["NOTIFICATION_SERVICE_URL"] = mock_http_service[0]

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert migration.returncode == 0, (
        f"Isolated-schema migration failed:\n{migration.stdout}\n{migration.stderr}"
    )

    api_port = _free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    worker = None
    api = None
    api_after_restart = None
    engine = create_engine(database_url, pool_pre_ping=True)

    def start_api(log_path: Path) -> subprocess.Popen:
        log = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=project_root,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()
        def api_is_healthy() -> bool:
            try:
                return httpx.get(f"{api_url}/health/db", timeout=0.3).status_code == 200
            except httpx.HTTPError:
                return False

        try:
            _wait_until(
                "API database health",
                api_is_healthy,
                process,
                log_path,
            )
        except BaseException:
            _stop(process)
            raise
        return process

    try:
        api = start_api(tmp_path / "api-first.log")
        member = f"restart-e2e-{uuid4().hex}"
        workshop_response = httpx.post(
            f"{api_url}/workshops",
            json={
                "title": f"Restart recovery {uuid4().hex[:8]}",
                "description": "PostgreSQL API restart integration test",
                "scheduled_at": "2030-01-01T10:00:00Z",
            },
            timeout=3,
        )
        assert workshop_response.status_code == 201, workshop_response.text
        workshop_id = workshop_response.json()["id"]
        registration_response = httpx.post(
            f"{api_url}/workshops/{workshop_id}/registrations",
            json={"member_id": member},
            timeout=3,
        )
        assert registration_response.status_code == 201, registration_response.text

        with Session(engine) as session:
            job = session.scalar(
                select(NotificationJob).where(
                    NotificationJob.recipient == member,
                    NotificationJob.event_type == "registration_confirmation",
                )
            )
            assert job is not None
            job_id = job.id
            assert job.status == "pending"
            assert job.attempt_count == 0

        _stop(api)
        api = None
        api_after_restart = start_api(tmp_path / "api-after-restart.log")
        jobs = httpx.get(f"{api_url}/notification-jobs", timeout=3).json()
        same_api_job = next(item for item in jobs if item["id"] == job_id)
        assert same_api_job["recipient"] == member
        assert same_api_job["status"] == "pending"

        with Session(engine) as session:
            same_db_job = session.get(NotificationJob, job_id)
            assert same_db_job is not None
            assert same_db_job.recipient == member
            assert same_db_job.status == "pending"

        worker_log = tmp_path / "worker.log"
        worker_file = worker_log.open("w", encoding="utf-8")
        worker = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            cwd=project_root,
            env=environment,
            stdout=worker_file,
            stderr=subprocess.STDOUT,
        )
        worker_file.close()

        def is_sent():
            with Session(engine) as session:
                current = session.get(NotificationJob, job_id)
                return current is not None and current.status == "sent"

        assert _wait_until("the original job to be sent", is_sent, worker, worker_log, timeout=20)
        delivery_key = f"notification-job-{job_id}"

        def delivery_exists():
            try:
                response = httpx.get(f"{mock_http_service[0]}/admin/deliveries", timeout=1)
            except httpx.HTTPError:
                return None
            return next(
                (
                    record
                    for record in response.json()
                    if record["idempotency_key"] == delivery_key
                ),
                None,
            )

        delivery = _wait_until(
            "the matching mock delivery record", delivery_exists, worker, worker_log
        )
        assert delivery["payload"]["recipient"] == member
        assert delivery["payload"]["event_type"] == "registration_confirmation"
        with Session(engine) as session:
            final_job = session.get(NotificationJob, job_id)
            assert final_job is not None
            assert final_job.status == "sent"
            assert final_job.recipient == member
    finally:
        _stop(worker)
        _stop(api_after_restart)
        _stop(api)
        engine.dispose()
