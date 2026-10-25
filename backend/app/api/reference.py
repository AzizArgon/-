from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Category
from app.schemas.seller import CategoryOut, RateOut
from app.services.exchange import get_usd_rate
from app.services.spec_dictionary import DICTIONARY

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


@router.get("/spec-dictionary")
def spec_dictionary():
    """The characteristics dictionary: keys, value kinds, units and allowed values of every category."""
    return {
        category: [{"key": s.key, "kind": s.kind, "unit": s.unit, "values": s.values, "at_least": s.at_least}
                   for s in specs]
        for category, specs in DICTIONARY.items()
    }
