"""Limits of the public server: invite code for sellers, login attempts, daily imports and AI requests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import limits
from app.core.config import settings
from app.db.database import Base, get_db
from main import app


@pytest.fixture
def Session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(limits, "SessionLocal", Session)
    limits.login_failures.clear()
    limits.registrations.clear()
    return Session


@pytest.fixture
def client(Session):
    def db():
        with Session() as session:
            yield session

    app.dependency_overrides[get_db] = db
    yield TestClient(app)  # no "with": startup would touch the real database
    app.dependency_overrides.clear()


def _register(client, email, role="buyer", invite=""):
    return client.post("/api/auth/register",
                       json={"email": email, "password": "password123", "role": role, "invite_code": invite})


def test_seller_needs_invite_code(client, monkeypatch):
    monkeypatch.setattr(settings, "seller_invite_code", "secret-code")
    assert client.get("/api/auth/options").json() == {"seller_invite_required": True}
    r = _register(client, "s@example.com", "seller")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "invite_required"
    assert _register(client, "s@example.com", "seller", "wrong").status_code == 403
    assert _register(client, "s@example.com", "seller", "secret-code").status_code == 201
    assert _register(client, "b@example.com").status_code == 201  # buyers register freely


def test_no_invite_code_on_the_laptop(client, monkeypatch):
    monkeypatch.setattr(settings, "seller_invite_code", "")
    assert _register(client, "s@example.com", "seller").status_code == 201


def test_login_attempts_limited_per_real_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    _register(client, "b@example.com")
    bad = {"email": "b@example.com", "password": "wrong-pass"}
    for _ in range(3):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    r = client.post("/api/auth/login", json={**bad, "password": "password123"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_logins"
    # X-Real-IP is trusted only from nginx on localhost; the test client is not localhost
    assert limits.login_failures.count("testclient", 60) == 3


def test_client_ip_from_nginx_only():
    class Req:
        def __init__(self, host, headers):
            self.client = type("C", (), {"host": host})
            self.headers = headers

    assert limits.client_ip(Req("127.0.0.1", {"x-real-ip": "203.0.113.7"})) == "203.0.113.7"
    assert limits.client_ip(Req("198.51.100.1", {"x-real-ip": "203.0.113.7"})) == "198.51.100.1"


def test_daily_import_limits(Session, monkeypatch):
    monkeypatch.setattr(settings, "seller_daily_imports", 2)
    monkeypatch.setattr(settings, "server_daily_imports", 3)
    with Session() as db:
        for _ in range(2):
            limits.spend_import(db, 1)
        with pytest.raises(Exception) as e:
            limits.spend_import(db, 1)
        assert e.value.status_code == 429 and e.value.detail["code"] == "import_limit_store"
        limits.spend_import(db, 2)
        with pytest.raises(Exception) as e:
            limits.spend_import(db, 2)
        assert e.value.detail["code"] == "import_limit_server"


def test_daily_ai_limit(Session, monkeypatch):
    monkeypatch.setattr(settings, "server_daily_ai_requests", 2)
    assert [limits.spend_ai_request() for _ in range(3)] == [True, True, False]
    monkeypatch.setattr(settings, "server_daily_ai_requests", 0)
    assert limits.spend_ai_request()
