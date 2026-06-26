# raphael-automation

Triggers, actions, scheduling, cron jobs

## API

- Prefix: `/v1/automations`
- Port: `8095`
- Health: `GET /health`

## Events

_Published and consumed events documented in `openapi.yaml` and raphael-contracts._

## Development

```bash
uv sync
uv run uvicorn raphael_automation.app:app --reload --port 8095
```

Part of the [Raphael Platform](https://github.com/hummingbird-labs) by HummingBird Labs.
