"""Automation API tests."""

from fastapi.testclient import TestClient

from raphael_automation.app import app

client = TestClient(app)


def test_list_automations_seeded() -> None:
    res = client.get("/v1/automations")
    assert res.status_code == 200
    assert len(res.json()["automations"]) >= 1


def test_list_runs() -> None:
    res = client.get("/v1/automations/runs")
    assert res.status_code == 200
    assert isinstance(res.json()["runs"], list)
