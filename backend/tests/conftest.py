import pytest

from app.services import importer


@pytest.fixture(autouse=True)
def no_cbu_requests(monkeypatch):
    """Tests never ask cbu.uz: the USD rate is unknown, USD prices need no conversion."""
    monkeypatch.setattr(importer, "get_usd_rate", lambda db: None)
