# Devin Godseye

Identify issues before they become a real problem — reducing your attack surface, automatically with Devin.

**Devin Godseye** is an event-driven automation service that turns GitHub issues into Devin
sessions, with a human-in-the-loop approval dashboard.

When a GitHub issue is labeled **`devin-fix`** in a watched repo (default
[`timderspieler/superset`](https://github.com/timderspieler/superset)), the service detects it
via a GitHub webhook *and* a background scanner that periodically polls the GitHub API for
pre-existing labeled issues. The issue shows up on a dashboard for review. On **Approve**, the
service calls the [Devin API](https://docs.devin.ai/api-reference) to spin up a session that
fixes the issue and opens a pull request. The service stores the session ↔ issue mapping and
polls Devin to track status, the resulting PR, and a result summary.

## How it works

```
GitHub issue labeled "devin-fix"
        │
        ├─ webhook: POST /webhooks/github
        ├─ scanner: background poll of GitHub API (catches pre-existing issues)
        ├─ manual:  dashboard "Sync issues" button → POST /api/scan
        ▼
  record issue as "pending approval"
        │
        ├─ label in AUTO_APPROVE_LABELS ─► auto-approve
        ▼
   Dashboard  ──Approve──►  POST /v1/sessions (Devin API)  ─► store devin_session_id
        │                         │
        └──Decline (reason)──►  close GitHub issue          ▼
                                              background poller: GET /v1/sessions/{id}
                                                     │
                                                     ▼
                                  track status · PR url · result · success/failure
```

### Lifecycle / states

| State | Meaning |
|-------|---------|
| `pending_approval` | Issue received, awaiting human approve/decline |
| `running` | Approved; a Devin session is working on it |
| `completed` | Devin session finished (`status_enum = finished`) |
| `failed` | Devin session expired/errored |
| `declined` | Rejected by a reviewer; GitHub issue closed with a reason |

## Dashboard

The dashboard (served at `/`) auto-refreshes and shows four sections:

- **Pending approvals** — incoming issues with **Approve** / **Decline** buttons. Declining
  prompts for a reason and closes the GitHub issue.
- **Active sessions** — approved issues with live Devin status (plus a manual *Refresh*).
- **Completed fixes** — finished/failed runs with PR links, timestamps, result summaries, and
  green/red success indicators.
- **Declined** — closed issues with the recorded reason.

## Quick start (Docker)

```bash
cp .env.example .env       # then fill in DEVIN_API_KEY, DEVIN_ORG_ID, GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET
docker compose up --build
```

The dashboard is then available at <http://localhost:8000>. The SQLite database is persisted in
the `godseye-data` Docker volume.

## Quick start (local, without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # fill in secrets
uvicorn app.main:app --reload
```

## Configuration

All configuration is via environment variables (or a `.env` file). See `.env.example`.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVIN_API_KEY` | — | Service user API key ([create one](https://app.devin.ai/settings/api-keys), starts with `cog_`). Required to create sessions. |
| `DEVIN_ORG_ID` | — | Organization ID (find it on [Settings → Service Users](https://app.devin.ai/settings/api-keys), starts with `org-`). Required for v3 API. |
| `DEVIN_API_BASE_URL` | `https://api.devin.ai` | Devin API base URL. |
| `GITHUB_TOKEN` | — | GitHub token with `repo` scope. Required to close declined issues. |
| `GITHUB_API_BASE_URL` | `https://api.github.com` | GitHub API base URL. |
| `GITHUB_WEBHOOK_SECRET` | — | Shared secret for webhook HMAC verification. If empty, verification is skipped (dev only). |
| `TARGET_REPO` | `timderspieler/superset` | Repo the automation watches. |
| `TRIGGER_LABELS` | `devin-fix` | Comma-separated labels that trigger the automation. |
| `AUTO_APPROVE_LABELS` | _(empty)_ | Comma-separated labels that auto-approve (skip manual review). |
| `DATABASE_URL` | `sqlite:///./data/godseye.db` | SQLAlchemy database URL. |
| `POLL_INTERVAL_SECONDS` | `30` | How often the poller syncs active sessions. |
| `SCAN_INTERVAL_SECONDS` | `60` | How often the scanner polls GitHub for labeled issues. |
| `ENABLE_SCANNER` | `true` | Enable/disable the background GitHub issue scanner. |
| `SESSION_MAX_ACU_LIMIT` | _(empty)_ | Optional ACU cap per created session. |

## Configuring the GitHub webhook

On the watched repository (e.g. `timderspieler/superset`):

1. **Settings → Webhooks → Add webhook**.
2. **Payload URL**: `https://<your-host>/webhooks/github`
3. **Content type**: `application/json`
4. **Secret**: the same value as `GITHUB_WEBHOOK_SECRET`.
5. **Events**: select **Let me select individual events → Issues**.

Then create an issue and add the `devin-fix` label — it will appear on the dashboard.

> **No webhook configured yet?** No problem — the service also runs a background scanner that
> polls the GitHub API for open issues with the trigger label(s). Pre-existing labeled issues
> are automatically discovered. You can also click **"Sync issues from GitHub"** in the
> dashboard header or call `POST /api/scan` to trigger an immediate scan.
>
> For local testing you can expose your machine with a tunnel (e.g. `ngrok http 8000`) and use
> that URL as the payload URL, or simply POST a sample `issues` payload to `/webhooks/github`.

## HTTP API

| Method & path | Description |
|---------------|-------------|
| `POST /webhooks/github` | GitHub webhook receiver (verifies HMAC signature). |
| `POST /api/scan` | Manually trigger a GitHub issue scan (returns `new_issues_recorded`). |
| `GET /api/issues` | All issues grouped into `pending` / `active` / `completed` / `declined`. |
| `GET /api/issues/{id}` | Single issue with its session. |
| `POST /api/issues/{id}/approve` | Approve → create a Devin session. |
| `POST /api/issues/{id}/decline` | Body `{"reason": "..."}` → close the GitHub issue. |
| `POST /api/issues/{id}/refresh` | Force a Devin status sync for the issue's session. |
| `GET /health` | Liveness probe. |
| `GET /` | Dashboard. |

## Devin API usage

- **Create**: `POST /v1/sessions` with a prompt containing the issue title, description, and a
  direct link to the GitHub issue (so Devin can pull more context from GitHub).
- **Track**: `GET /v1/sessions/{session_id}` for `status_enum`, the resulting `pull_request.url`,
  and `structured_output` (used as the result summary).

## Project layout

```
app/
  config.py        # env-var settings
  database.py      # SQLAlchemy engine/session
  models.py        # Issue + FixSession tables
  schemas.py       # Pydantic API schemas
  devin_client.py  # Devin API client
  github_client.py # GitHub API client
  webhook.py       # signature verification + payload parsing
  services.py      # approve / decline / sync business logic
  scanner.py       # background GitHub issue scanner
  poller.py        # background session status poller
  main.py          # FastAPI app: webhook, JSON API, dashboard
  templates/dashboard.html
tests/             # pytest suite (Devin/GitHub mocked)
Dockerfile, docker-compose.yml
```

## Development

```bash
pip install -e ".[dev]"
ruff check .       # lint
pytest -q          # tests
```
