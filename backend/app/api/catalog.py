from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.catalog import product_card, search_products
from app.services.exchange import get_usd_rate

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _rate(db: Session) -> tuple[float | None, str | None]:
    """CBU USD rate and its date (the page says "by the CBU rate on 25.10")."""
    rate = get_usd_rate(db)  # cached in the DB for a day
    return (rate.rate, rate.rate_date.isoformat()) if rate else (None, None)


@router.get("/products")
def list_products(
    q: str = Query("", max_length=200),
    category: str | None = None,
    price_min: float | None = Query(None, ge=0),
    price_max: float | None = Query(None, ge=0),
    in_stock: bool = True,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """Catalog with search and filters. The price filter is in UZS (shown to buyers), compared in USD inside."""
    usd_rate, rate_date = _rate(db)
    to_usd = lambda uzs: uzs / usd_rate if uzs is not None and usd_rate else None  # noqa: E731
    result = search_products(db, usd_rate, q.strip(), category, to_usd(price_min), to_usd(price_max), in_stock, page)
    return {**result, "usd_rate": usd_rate, "usd_rate_date": rate_date}


@router.get("/products/{product_id}")
def get_product(product_id: int, sort: str = Query("recommended", pattern="^(recommended|price)$"),
                db: Session = Depends(get_db)):
    """Product card with store offers: "recommended" order by default, or by price."""
    usd_rate, rate_date = _rate(db)
    card = product_card(db, product_id, usd_rate, sort)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return {**card, "usd_rate_date": rate_date}
