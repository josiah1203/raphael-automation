"""Kafka event handler — match automations to platform events."""

from __future__ import annotations

import time
from typing import Any

from raphael_automation.action_dispatch import run_drc, run_eol_scan, run_export
from raphael_automation.sonoma_store import SonomaApiStore

_store = SonomaApiStore()

_TRIGGER_MAP = {
    "raphael.workspaces.commit": "on_commit",
    "raphael.workspaces.merge": "on_merge",
    "raphael.artifacts.ingest": "pcb_updated",
    "module.commit": "on_commit",
}


def _dispatch_action(action: str, data: dict[str, Any]) -> tuple[str, str | None, int]:
    """Run automation action; returns (status, error, duration_ms)."""
    start = time.monotonic()
    action_lower = action.lower()
    try:
        if "drc" in action_lower:
            run_drc(data)
        elif "eol" in action_lower:
            run_eol_scan(data, _store)
        elif "export" in action_lower or "gerber" in action_lower or "bom" in action_lower:
            run_export(data)
        duration_ms = int((time.monotonic() - start) * 1000) or 1
        return "success", None, duration_ms
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000) or 1
        return "failed", str(exc), duration_ms


def _publish_failure(auto: dict[str, Any], trigger: str, error: str) -> None:
    try:
        from raphael_contracts.kafka import publish_event

        publish_event(
            "raphael.automations.failed",
            {
                "automation_id": auto["id"],
                "name": auto["name"],
                "action": auto.get("action", ""),
                "error": error,
                "trigger": trigger,
            },
            source="raphael-automation",
        )
    except Exception:
        pass


def _emit_automation_rwu(org_id: str | None) -> None:
    try:
        from raphael_contracts.rwu import emit_rwu

        emit_rwu(org_id or "org_default", 0.5, "automation.run")
    except Exception:
        pass


def dispatch_automation(auto: dict[str, Any], trigger: str, data: dict[str, Any]) -> dict[str, Any]:
    """Execute automation action and record run status."""
    payload = {**data, "automation_id": auto["id"], "trigger": trigger}
    status, error, duration_ms = _dispatch_action(auto.get("action", ""), payload)
    run = _store.record_run(auto["id"], auto["name"], status, trigger, duration_ms=duration_ms, error=error)
    _emit_automation_rwu(data.get("org_id"))
    if status == "failed":
        _publish_failure(auto, trigger, error or "unknown error")
    return run


def handle_bus_event(envelope: dict[str, Any]) -> None:
    event_type = envelope.get("type", "")
    data = envelope.get("data") or {}
    trigger = _TRIGGER_MAP.get(event_type)
    if event_type == "raphael.artifacts.ingest" and data.get("kind") not in ("kicad", "altium", "pcb"):
        return
    if not trigger:
        return
    for auto in _store.list_automations():
        if not auto.get("enabled"):
            continue
        tt = auto.get("trigger_type", "")
        if tt == trigger or tt.replace("_", "") in trigger.replace("_", ""):
            dispatch_automation(auto, trigger, data)
