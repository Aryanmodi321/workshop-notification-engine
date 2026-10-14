import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine

from app.models import Base


def test_pending_notification_survives_api_process_restart(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "restart-test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    api_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["NOTIFICATION_SERVICE_URL"] = "http://127.0.0.1:1"

    def stop_api(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def start_api(log_path: Path) -> subprocess.Popen:
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=project_root,
                env=environment,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f"API exited during startup:\n{log_path.read_text()}")
                try:
                    if httpx.get(f"{api_url}/health", timeout=0.25).status_code == 200:
                        return process
                except httpx.HTTPError:
                    time.sleep(0.05)
            raise AssertionError(f"API did not become healthy:\n{log_path.read_text()}")
        except BaseException:
            stop_api(process)
            raise

    first_process = None
    second_process = None
    try:
        first_process = start_api(tmp_path / "api-first.log")
        workshop_response = httpx.post(
            f"{api_url}/workshops",
            json={
                "title": "API restart persistence test",
                "description": "",
                "scheduled_at": "2030-01-01T10:00:00Z",
            },
            timeout=2,
        )
        assert workshop_response.status_code == 201
        workshop_id = workshop_response.json()["id"]
        recipient = "restart-test-member"
        registration_response = httpx.post(
            f"{api_url}/workshops/{workshop_id}/registrations",
            json={"member_id": recipient},
            timeout=2,
        )
        assert registration_response.status_code == 201

        jobs = httpx.get(f"{api_url}/notification-jobs", timeout=2).json()
        job = next(item for item in jobs if item["recipient"] == recipient)
        assert job["status"] == "pending"
        assert job["attempt_count"] == 0
        job_id = job["id"]

        stop_api(first_process)
        first_process = None
        second_process = start_api(tmp_path / "api-second.log")

        jobs_after_restart = httpx.get(f"{api_url}/notification-jobs", timeout=2).json()
        same_job = next(item for item in jobs_after_restart if item["id"] == job_id)
        assert same_job["recipient"] == recipient
        assert same_job["status"] == "pending"
        assert same_job["attempt_count"] == 0
    finally:
        if second_process is not None:
            stop_api(second_process)
        if first_process is not None:
            stop_api(first_process)
