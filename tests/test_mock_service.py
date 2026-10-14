from fastapi.testclient import TestClient

from mock_service.main import app, deliveries, scenario


def test_mock_service_success_error_timeout_and_idempotency():
    deliveries.clear()
    scenario.update({"mode": "success", "status_code": 503, "delay_ms": 1})
    client = TestClient(app)
    key = "job-123"
    payload = {"event_type": "registration_confirmation", "recipient": "member"}
    assert (
        client.post("/notifications", json=payload, headers={"Idempotency-Key": key}).status_code
        == 200
    )
    duplicate = client.post("/notifications", json=payload, headers={"Idempotency-Key": key})
    assert duplicate.json()["duplicate"] is True
    assert len(client.get("/admin/deliveries").json()) == 1

    client.put("/admin/scenario", json={"mode": "http_error", "status_code": 503})
    assert (
        client.post(
            "/notifications", json=payload, headers={"Idempotency-Key": "job-2"}
        ).status_code
        == 503
    )
    client.put("/admin/scenario", json={"mode": "timeout", "delay_ms": 10})
    timeout = client.post("/notifications", json=payload, headers={"Idempotency-Key": "job-3"})
    assert timeout.status_code == 504
    assert len(client.get("/admin/deliveries").json()) == 1
