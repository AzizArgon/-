from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.catalog import product_card, search_products
from app.services.exchange import get_usd_rate

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _rate(db: Session) -> float | None:
    rate = get_usd_rate(db)  # cached in the DB for a day
    return rate.rate if rate else None


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
    """Catalog with search and filters. Prices for the filter are in USD (UZS converted by the CBU rate)."""
    usd_rate = _rate(db)
    result = search_products(db, usd_rate, q.strip(), category, price_min, price_max, in_stock, page)
    return {**result, "usd_rate": usd_rate}


@router.get("/products/{product_id}")
def get_product(product_id: int, sort: str = Query("recommended", pattern="^(recommended|price)$"),
                db: Session = Depends(get_db)):
    """Product card with store offers: "recommended" order by default, or by price."""
    card = product_card(db, product_id, _rate(db), sort)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return card
