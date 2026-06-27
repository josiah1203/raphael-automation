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


def test_create_automation() -> None:
    res = client.post(
        "/v1/automations",
        json={"name": "Smoke flow", "trigger_type": "manual", "action": "Run DRC"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Smoke flow"
    assert body["trigger_type"] == "manual"


def test_trigger_automation_records_run(tmp_path, monkeypatch) -> None:
    import raphael_automation.event_bus as bus
    import raphael_automation.routes as routes

    store = __import__("raphael_automation.sonoma_store", fromlist=["SonomaApiStore"]).SonomaApiStore(
        tmp_path / "auto.db"
    )
    monkeypatch.setattr(bus, "_store", store)
    monkeypatch.setattr(routes, "_store", store)
    monkeypatch.setattr(bus, "run_drc", lambda data: None)

    auto = store.create_automation("Trigger me", "manual", "Run DRC")
    before = len(store.list_automation_runs())
    res = client.post(f"/v1/automations/{auto['id']}/trigger", json={"module_id": "m-trigger"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "triggered"
    assert body["run"]["status"] == "success"
    assert len(store.list_automation_runs()) == before + 1


def test_trigger_unknown_automation_404() -> None:
    res = client.post("/v1/automations/does-not-exist/trigger", json={})
    assert res.status_code == 404
