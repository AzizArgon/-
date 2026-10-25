"""Official USD rate from the Central Bank of Uzbekistan (cbu.uz), refreshed once a day."""

import logging
from datetime import date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Currency, ExchangeRate

log = logging.getLogger(__name__)


def _fetch_cbu_usd() -> tuple[float, date]:
    resp = httpx.get(settings.cbu_rate_url, timeout=10)
    resp.raise_for_status()
    data = resp.json()[0]  # [{"Ccy": "USD", "Rate": "12345.67", "Date": "25.10.2026", ...}]
    return float(data["Rate"]), datetime.strptime(data["Date"], "%d.%m.%Y").date()


def get_usd_rate(db: Session) -> ExchangeRate | None:
    """Today's rate from the DB; if missing, ask cbu.uz. Falls back to the latest known rate."""
    latest = db.scalar(
        select(ExchangeRate).where(ExchangeRate.currency == "USD").order_by(ExchangeRate.rate_date.desc())
    )
    if latest and latest.fetched_on >= date.today():
        return latest
    try:
        rate, rate_date = _fetch_cbu_usd()
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
        log.warning("CBU rate fetch failed, using last known rate: %s", e)
        return latest
    if latest and latest.rate_date == rate_date:
        # No new rate yet (weekend/holiday): keep the row, remember we checked today
        latest.rate = rate
        latest.fetched_on = date.today()
    else:
        latest = ExchangeRate(currency="USD", rate=rate, rate_date=rate_date)
        db.add(latest)
    db.commit()
    return latest


def to_usd(price: float | None, currency: Currency, usd_rate: float | None) -> float | None:
    if price is None:
        return None
    if currency == Currency.USD:
        return price
    return round(price / usd_rate, 2) if usd_rate else None


def to_uzs(price: float | None, currency: Currency, usd_rate: float | None) -> float | None:
    if price is None:
        return None
    if currency == Currency.UZS:
        return price
    # Converted sums are approximate anyway: rounded to 1 000 sum
    return int(round(price * usd_rate, -3)) if usd_rate else None
