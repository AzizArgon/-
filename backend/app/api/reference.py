from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Category
from app.schemas.seller import CategoryOut, RateOut
from app.services.exchange import get_usd_rate

router = APIRouter(tags=["reference"])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.id)).all()


@router.get("/rates/usd", response_model=RateOut)
def usd_rate(db: Session = Depends(get_db)):
    rate = get_usd_rate(db)
    if rate is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Exchange rate unavailable")
    return rate
