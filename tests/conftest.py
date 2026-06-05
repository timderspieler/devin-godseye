"""Pytest fixtures: isolated SQLite DB and a TestClient."""

from __future__ import annotations

import os
import tempfile

import pytest

# Configure the environment BEFORE importing the app (engine is built at import).
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["ENABLE_POLLER"] = "false"
os.environ["GITHUB_WEBHOOK_SECRET"] = ""  # skip signature checks in tests
os.environ["DEVIN_API_KEY"] = "test-key"
os.environ["GITHUB_TOKEN"] = "test-token"
os.environ["TRIGGER_LABELS"] = "devin-fix"
os.environ["AUTO_APPROVE_LABELS"] = "devin-fix-auto"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
