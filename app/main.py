"""FastAPI application: webhook receiver, JSON API, and dashboard."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.config import get_settings
from app.database import get_session, init_db
from app.devin_client import DevinAPIError
from app.github_client import GitHubAPIError
from app.models import Issue, IssueStatus
from app.poller import poller_loop
from app.schemas import DeclineRequest, IssueView
from app.webhook import parse_issue_event, verify_signature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("godseye")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings = get_settings()
    stop_event = asyncio.Event()
    task: asyncio.Task | None = None
    if settings.enable_poller:
        task = asyncio.create_task(poller_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        if task is not None:
            await task


app = FastAPI(title="Devin Godseye", version="0.1.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Health + dashboard
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "target_repo": settings.target_repo,
            "poll_interval": settings.poll_interval_seconds,
        },
    )


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    db: Session = Depends(get_session),
) -> JSONResponse:
    settings = get_settings()
    body = await request.body()
    if not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event == "ping":
        return JSONResponse({"status": "pong"})
    if x_github_event != "issues":
        return JSONResponse({"status": "ignored", "reason": f"event {x_github_event}"})

    payload = await request.json()
    event = parse_issue_event(payload)
    if event is None:
        return JSONResponse({"status": "ignored", "reason": "no issue in payload"})

    issue, should_auto = services.record_issue_from_event(db, event, settings)
    if issue is None:
        return JSONResponse(
            {"status": "ignored", "reason": "label is not a trigger label"}
        )

    auto_approved = False
    if should_auto:
        try:
            services.approve_issue(db, issue)
            auto_approved = True
        except (DevinAPIError, ValueError) as exc:
            logger.error("Auto-approval failed for issue %s: %s", issue.id, exc)

    return JSONResponse(
        {
            "status": "recorded",
            "issue_id": issue.id,
            "issue_status": issue.status.value,
            "auto_approved": auto_approved,
        }
    )


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #
def _issue_or_404(db: Session, issue_id: int) -> Issue:
    issue = services.get_issue(db, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@app.get("/api/issues")
def list_issues(db: Session = Depends(get_session)) -> dict[str, list[dict]]:
    issues = db.scalars(select(Issue).order_by(Issue.created_at.desc())).all()
    views = [IssueView.from_model(issue) for issue in issues]

    pending = [v for v in views if v.status == IssueStatus.PENDING_APPROVAL.value]
    active = [
        v
        for v in views
        if v.status in (IssueStatus.APPROVED.value, IssueStatus.RUNNING.value)
    ]
    completed = [
        v
        for v in views
        if v.status in (IssueStatus.COMPLETED.value, IssueStatus.FAILED.value)
    ]
    declined = [v for v in views if v.status == IssueStatus.DECLINED.value]
    return {
        "pending": [v.model_dump(mode="json") for v in pending],
        "active": [v.model_dump(mode="json") for v in active],
        "completed": [v.model_dump(mode="json") for v in completed],
        "declined": [v.model_dump(mode="json") for v in declined],
    }


@app.get("/api/issues/{issue_id}")
def get_issue(issue_id: int, db: Session = Depends(get_session)) -> dict:
    issue = _issue_or_404(db, issue_id)
    return IssueView.from_model(issue).model_dump(mode="json")


@app.post("/api/issues/{issue_id}/approve")
def approve(issue_id: int, db: Session = Depends(get_session)) -> dict:
    issue = _issue_or_404(db, issue_id)
    try:
        issue = services.approve_issue(db, issue)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DevinAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return IssueView.from_model(issue).model_dump(mode="json")


@app.post("/api/issues/{issue_id}/decline")
def decline(
    issue_id: int,
    payload: DeclineRequest,
    db: Session = Depends(get_session),
) -> dict:
    issue = _issue_or_404(db, issue_id)
    try:
        issue = services.decline_issue(db, issue, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GitHubAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return IssueView.from_model(issue).model_dump(mode="json")


@app.post("/api/issues/{issue_id}/refresh")
def refresh(issue_id: int, db: Session = Depends(get_session)) -> dict:
    issue = _issue_or_404(db, issue_id)
    if issue.session is None:
        raise HTTPException(status_code=409, detail="Issue has no session")
    try:
        services.sync_session(db, issue.session)
    except DevinAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.refresh(issue)
    return IssueView.from_model(issue).model_dump(mode="json")
