import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import Base
from mock_service import main as mock_app


class NotificationRequestCapture:
    """Observe real mock-service requests and optionally fail one recipient once."""

    def __init__(self, app):
        self.app = app
        self._condition = threading.Condition()
        self._requests = []
        self._completed_requests = 0
        self._fail_once_recipient = None
        self._failed_recipients = set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/notifications":
            await self.app(scope, receive, send)
            return

        request_messages = []
        body = bytearray()
        while True:
            message = await receive()
            request_messages.append(message)
            if message["type"] != "http.request":
                break
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        payload = json.loads(body)
        headers = dict(scope["headers"])
        record = {
            "idempotency_key": headers.get(b"idempotency-key", b"").decode(),
            "recipient": payload.get("recipient"),
            "event_type": payload.get("event_type"),
            "status_code": None,
        }
        with self._condition:
            self._requests.append(record)
            inject_failure = (
                record["event_type"] == "workshop_cancelled"
                and record["recipient"] == self._fail_once_recipient
                and record["recipient"] not in self._failed_recipients
            )
            if inject_failure:
                self._failed_recipients.add(record["recipient"])

        if inject_failure:
            record["status_code"] = 503
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {"type": "http.response.body", "body": b'{"detail":"injected transient failure"}'}
            )
            self._mark_completed()
            return

        replay = iter(request_messages)

        async def replay_receive():
            try:
                return next(replay)
            except StopIteration:
                return {"type": "http.disconnect"}

        async def capture_send(message):
            if message["type"] == "http.response.start":
                record["status_code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, replay_receive, capture_send)
        finally:
            self._mark_completed()

    def _mark_completed(self):
        with self._condition:
            self._completed_requests += 1
            self._condition.notify_all()

    @property
    def requests(self):
        with self._condition:
            return [request.copy() for request in self._requests]

    @property
    def idempotency_keys(self):
        return [request["idempotency_key"] for request in self.requests]

    def fail_once_for_recipient(self, recipient):
        with self._condition:
            self._fail_once_recipient = recipient
            self._failed_recipients.discard(recipient)

    def restore_success(self):
        with self._condition:
            self._fail_once_recipient = None

    def wait_for_completed_requests(self, count, timeout=3):
        with self._condition:
            return self._condition.wait_for(lambda: self._completed_requests >= count, timeout)


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(db_factory):
    def override_session():
        with db_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_http_service():
    mock_app.scenario.update({"mode": "success", "status_code": 503, "delay_ms": 5000})
    mock_app.deliveries.clear()
    capture = NotificationRequestCapture(mock_app.app)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                capture,
                host="127.0.0.1",
                port=port,
                log_level="error",
                lifespan="off",
                timeout_graceful_shutdown=2,
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "in-process mock notification server did not start"
            yield base_url, capture
        finally:
            try:
                httpx.put(
                    f"{base_url}/admin/scenario",
                    json={"mode": "success"},
                    timeout=1,
                )
            except httpx.HTTPError:
                pass
            capture.restore_success()
            server.should_exit = True
            thread.join(timeout=5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=1)
            mock_app.scenario.update({"mode": "success", "status_code": 503, "delay_ms": 5000})
            mock_app.deliveries.clear()
