"""Automations API — /v1/automations/*."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from raphael_automation.sonoma_store import SonomaApiStore

from raphael_automation.event_bus import dispatch_automation

router = APIRouter(tags=["automation"])
_store = SonomaApiStore()


@router.get("")
def list_automations() -> dict[str, list]:
    return {"automations": _store.list_automations()}


@router.post("")
def create_automation(body: dict[str, Any]) -> dict[str, Any]:
    return _store.create_automation(body["name"], body["trigger_type"], body["action"])


@router.get("/runs")
def list_runs() -> dict[str, list]:
    return {"runs": _store.list_automation_runs()}


@router.post("/{automation_id}/toggle")
def toggle(automation_id: str, body: dict[str, Any]) -> dict[str, Any]:
    result = _store.patch_automation(automation_id, body.get("enabled", True))
    if not result:
        raise HTTPException(404, detail="not_found")
    return result


@router.post("/{automation_id}/trigger")
def trigger(automation_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    auto = _store.get_automation(automation_id)
    if not auto:
        raise HTTPException(404, detail="not_found")
    run = dispatch_automation(auto, auto.get("trigger_type", "manual"), body or {})
    return {"status": "triggered", "run": run, "automation": auto}
