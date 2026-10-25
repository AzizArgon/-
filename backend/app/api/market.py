from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.exchange import get_usd_rate
from app.services.market import PERIODS, index_table, market_data, movers, popular_with_archive

router = APIRouter(prefix="/market", tags=["market"])
PERIOD = Query("quarter", pattern=f"^({'|'.join(PERIODS)})$")


def usd_rate_info(db: Session) -> dict:
    rate = get_usd_rate(db)
    return {"usd_rate": rate.rate if rate else None, "usd_rate_date": rate.rate_date.isoformat() if rate else None}


@router.get("/overview")
def overview(period: str = PERIOD, db: Session = Depends(get_db)):
    """Public "Prices on the market": category indices, biggest risers and fallers, "then -> now" by old price lists.

    `includes_demo`: some market prices are computed with the invented demo stores.
    """
    md = market_data(db)
    return {"indices": index_table(md, period), "movers": movers(db, md), "archive": popular_with_archive(db, md),
            "includes_demo": bool(md.demo_stores),
            **usd_rate_info(db)}
