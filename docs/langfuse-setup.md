# Langfuse Observability Setup

Self-hosted Langfuse stack for local AI telemetry via Podman Compose.

## Implementation Checklist

- [ ] Add `langfuse>=3.0.0` dependency to `pyproject.toml`
- [ ] Add instrumentation to `app.py` (Langfuse init + `Agent.instrument_all()`)
- [ ] Update `.env.example` with Langfuse env var templates
- [ ] Create `docker-compose.yaml` (chatbot + Langfuse 7-service stack)
- [ ] Add Langfuse keys to local `.env`
- [ ] Regenerate lockfile (`uv lock && uv sync`)

## Verification

```bash
podman compose up --build -d
```

1. Wait ~30s for Langfuse health checks to pass
2. Open `http://localhost:3000` -- log in with `admin@local.dev` / `password`
3. Open `http://localhost:8080` -- log in to chatbot, send a message
4. Back in Langfuse UI, check **Traces** page -- should see a trace with the PydanticAI agent run including the `retrieve` tool call, token counts, and latency
