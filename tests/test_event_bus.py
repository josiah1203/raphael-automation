"""Automation event bus tests."""

from __future__ import annotations

from typing import Any

import raphael_automation.event_bus as bus
from raphael_automation.event_bus import handle_bus_event
from raphael_automation.sonoma_store import SonomaApiStore


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        self.calls.append(("POST", url, json))
        return _FakeResponse()

    def __enter__(self) -> _RecordingClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _patch_store(tmp_path, monkeypatch) -> SonomaApiStore:
    store = SonomaApiStore(tmp_path / "auto.db")
    monkeypatch.setattr(bus, "_store", store)
    return store


def test_commit_triggers_on_commit_automation(tmp_path, monkeypatch) -> None:
    store = _patch_store(tmp_path, monkeypatch)
    fake = _RecordingClient()
    monkeypatch.setattr("raphael_automation.action_dispatch.httpx.Client", lambda **_: fake)

    auto = store.create_automation("Test DRC", "on_commit", "Run DRC")
    before = len(store.list_automation_runs())
    handle_bus_event({"type": "raphael.workspaces.commit", "data": {"module_id": "m1"}})
    after = len(store.list_automation_runs())
    assert after >= before + 1
    assert any("/webhooks/drc" in call[1] for call in fake.calls)


def test_dispatch_drc_calls_connectors_webhook(tmp_path, monkeypatch) -> None:
    store = _patch_store(tmp_path, monkeypatch)
    fake = _RecordingClient()
    monkeypatch.setattr("raphael_automation.action_dispatch.httpx.Client", lambda **_: fake)

    auto = store.create_automation("DRC hook", "on_commit", "Run DRC")
    run = bus.dispatch_automation(auto, "on_commit", {"module_id": "mod-1", "workspace_id": "ws-1"})
    assert run["status"] == "success"
    assert len(fake.calls) == 2
    assert any("/webhooks/drc" in call[1] for call in fake.calls)
    assert any("/v1/audit/events" in call[1] for call in fake.calls)
    drc_call = next(call for call in fake.calls if "/webhooks/drc" in call[1])
    _method, url, payload = drc_call
    assert payload is not None
    assert payload["module_id"] == "mod-1"


def test_dispatch_drc_missing_module_id_fails(tmp_path, monkeypatch) -> None:
    store = _patch_store(tmp_path, monkeypatch)
    auto = store.create_automation("DRC fail", "on_commit", "Run DRC")
    run = bus.dispatch_automation(auto, "on_commit", {})
    assert run["status"] == "failed"
    assert "module_id" in (run.get("error") or "")


def test_dispatch_export_creates_artifact_job(tmp_path, monkeypatch) -> None:
    store = _patch_store(tmp_path, monkeypatch)
    fake = _RecordingClient()
    monkeypatch.setattr("raphael_automation.action_dispatch.httpx.Client", lambda **_: fake)

    auto = store.create_automation("Export", "on_merge", "Export Gerber + BOM")
    run = bus.dispatch_automation(
        auto,
        "on_merge",
        {"module_id": "mod-2", "workspace_id": "ws-2", "merge_ref": "v2.3"},
    )
    assert run["status"] == "success"
    assert len(fake.calls) == 1
    _method, url, payload = fake.calls[0]
    assert url.endswith("/v1/artifacts")
    assert payload is not None
    assert payload["kind"] == "release_export"
    assert payload["module_id"] == "mod-2"
    assert payload["metadata"]["formats"] == ["gerber", "bom"]


def test_dispatch_failure_publishes_failed_status(tmp_path, monkeypatch) -> None:
    store = _patch_store(tmp_path, monkeypatch)
    auto = store.create_automation("Bad export", "on_merge", "Export Gerber")
    run = bus.dispatch_automation(auto, "on_merge", {"status": "conflict", "module_id": "m1"})
    assert run["status"] == "failed"
    assert run["error"]


def test_dispatch_eol_records_scan(tmp_path, monkeypatch) -> None:
    store = _patch_store(tmp_path, monkeypatch)
    auto = store.create_automation("EOL", "scheduled", "Scan BOM for EOL parts")
    run = bus.dispatch_automation(auto, "scheduled", {"module_id": "power-board-v2"})
    assert run["status"] == "success"
    scans = store.list_eol_scans()
    assert len(scans) == 1
    assert scans[0]["module_id"] == "power-board-v2"
    assert scans[0]["automation_id"] == auto["id"]
    assert scans[0]["status"] == "scheduled"
