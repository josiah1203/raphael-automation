"""HTTP side effects for automation actions (connectors, artifacts, audit)."""

from __future__ import annotations

import os
from typing import Any, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from raphael_automation.sonoma_store import SonomaApiStore


def _connectors_url() -> str:
    return os.environ.get("RAPHAEL_CONNECTORS_URL", "http://127.0.0.1:8096").rstrip("/")


def _artifacts_url() -> str:
    return os.environ.get("RAPHAEL_ARTIFACTS_URL", "http://127.0.0.1:8107").rstrip("/")


def _audit_url() -> str:
    return os.environ.get("RAPHAEL_AUDIT_URL", "http://127.0.0.1:8093").rstrip("/")


def run_drc(data: dict[str, Any]) -> None:
    """Trigger DRC via connectors webhook and record an audit event."""
    module_id = data.get("module_id")
    if not module_id:
        raise ValueError("missing module_id for DRC")
    payload = {
        "module_id": module_id,
        "commit_id": data.get("commit_id") or data.get("commit_hash"),
        "workspace_id": data.get("workspace_id", "default"),
        "event": "drc_check",
    }
    with httpx.Client(timeout=15.0) as client:
        drc_res = client.post(f"{_connectors_url()}/v1/connectors/webhooks/drc", json=payload)
        drc_res.raise_for_status()
        audit_res = client.post(
            f"{_audit_url()}/v1/audit/events",
            json={
                "event_type": "automation.drc",
                "project_id": data.get("workspace_id", "default"),
                "payload": payload,
            },
        )
        audit_res.raise_for_status()


def run_export(data: dict[str, Any]) -> None:
    """Enqueue a release export job in the artifacts service."""
    if data.get("status") == "conflict":
        raise ValueError("cannot export: merge conflict")
    module_id = data.get("module_id")
    if not module_id:
        raise ValueError("missing module_id for export")
    formats: list[str] = []
    if data.get("formats"):
        formats = list(data["formats"])
    else:
        formats = ["gerber", "bom"]
    body = {
        "module_id": module_id,
        "kind": "release_export",
        "metadata": {
            "formats": formats,
            "merge_id": data.get("merge_id"),
            "workspace_id": data.get("workspace_id", "default"),
            "source": "raphael-automation",
        },
    }
    with httpx.Client(timeout=30.0) as client:
        res = client.post(f"{_artifacts_url()}/v1/artifacts", json=body)
        res.raise_for_status()


def run_eol_scan(data: dict[str, Any], store: SonomaApiStore) -> None:
    """Record a scheduled EOL BOM scan."""
    module_id = data.get("module_id") or data.get("project_id")
    if not module_id:
        raise ValueError("missing module_id for EOL scan")
    store.record_eol_scan(
        module_id=str(module_id),
        automation_id=data.get("automation_id"),
        metadata={
            "org_id": data.get("org_id"),
            "trigger": data.get("trigger", "scheduled"),
            "schedule": data.get("schedule", "weekly"),
        },
    )


def dispatch_drc(data: dict[str, Any]) -> None:
    run_drc(data)


def dispatch_export(data: dict[str, Any]) -> None:
    run_export(data)


def dispatch_eol(data: dict[str, Any], store: SonomaApiStore) -> None:
    run_eol_scan(data, store)
