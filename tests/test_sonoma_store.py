"""Automation store domain tests."""

from pathlib import Path

import pytest

from raphael_automation.sonoma_store import SonomaApiStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SonomaApiStore:
    monkeypatch.delenv("RAPHAEL_DATABASE_URL", raising=False)
    return SonomaApiStore(db_path=tmp_path / "automation.db")


def test_list_automations_seeded(store: SonomaApiStore) -> None:
    automations = store.list_automations()
    assert len(automations) >= 3
    assert any(a["id"] == "auto-drc" for a in automations)


def test_create_automation(store: SonomaApiStore) -> None:
    created = store.create_automation("Smoke test", "on_commit", "Run checks")
    assert created["name"] == "Smoke test"
    assert created["enabled"] is True
    assert store.get_automation(created["id"]) is not None


def test_record_run_updates_last_status(store: SonomaApiStore) -> None:
    auto = store.list_automations()[0]
    run = store.record_run(auto["id"], auto["name"], "succeeded", "Manual", duration_ms=50)
    assert run["status"] == "succeeded"
    updated = store.get_automation(auto["id"])
    assert updated is not None
    assert updated["last_run_status"] == "succeeded"
    runs = store.list_automation_runs(limit=5)
    assert any(r["id"] == run["id"] for r in runs)


def test_automation_persists_across_instances(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAPHAEL_DATABASE_URL", raising=False)
    db = tmp_path / "automation-persist.db"
    store1 = SonomaApiStore(db_path=db)
    created = store1.create_automation("Persist", "scheduled", "Scan")
    store2 = SonomaApiStore(db_path=db)
    assert store2.get_automation(created["id"]) is not None
