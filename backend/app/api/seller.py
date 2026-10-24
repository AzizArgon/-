from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.database import get_db
from app.db.models import Currency, ImportStatus, PriceImport, Store, User
from app.schemas.seller import ImportDetail, ImportOut, PublishRequest, PublishResult, StoreIn, StoreOut
from app.services.importer import ALLOWED_EXTENSIONS, publish_import, run_import

router = APIRouter(tags=["seller"])

MAX_FILE_SIZE = 10 * 1024 * 1024
seller_only = require_role("seller")


def _my_store(db: Session, user: User) -> Store | None:
    return db.scalar(select(Store).where(Store.user_id == user.id))


def _require_store(db: Session, user: User) -> Store:
    store = _my_store(db, user)
    if store is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not created")
    return store


def _my_import(db: Session, user: User, import_id: int) -> tuple[Store, PriceImport]:
    store = _require_store(db, user)
    imp = db.get(PriceImport, import_id)
    if imp is None or imp.store_id != store.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return store, imp


@router.get("/stores/me", response_model=StoreOut)
def get_my_store(user: User = Depends(seller_only), db: Session = Depends(get_db)):
    return _require_store(db, user)


@router.put("/stores/me", response_model=StoreOut)
def save_my_store(data: StoreIn, user: User = Depends(seller_only), db: Session = Depends(get_db)):
    store = _my_store(db, user) or Store(user_id=user.id)
    for field, value in data.model_dump().items():
        setattr(store, field, value)
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


@router.post("/imports", response_model=ImportOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_price(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    currency: Currency = Form(...),
    user: User = Depends(seller_only),
    db: Session = Depends(get_db),
):
    store = _require_store(db, user)
    filename = file.filename or "price"
    if not any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported file type")
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")

    imp = PriceImport(store_id=store.id, filename=filename, currency=currency)
    db.add(imp)
    db.commit()
    db.refresh(imp)
    # Parsing takes minutes: the client polls GET /imports/{id} for progress
    background.add_task(run_import, imp.id, data, filename)
    return imp


@router.get("/imports", response_model=list[ImportOut])
def list_imports(user: User = Depends(seller_only), db: Session = Depends(get_db)):
    store = _require_store(db, user)
    return db.scalars(
        select(PriceImport).where(PriceImport.store_id == store.id).order_by(PriceImport.id.desc()).limit(20)
    ).all()


@router.get("/imports/{import_id}", response_model=ImportDetail)
def get_import(import_id: int, user: User = Depends(seller_only), db: Session = Depends(get_db)):
    return _my_import(db, user, import_id)[1]


@router.post("/imports/{import_id}/publish", response_model=PublishResult)
def publish(import_id: int, data: PublishRequest, user: User = Depends(seller_only), db: Session = Depends(get_db)):
    store, imp = _my_import(db, user, import_id)
    if imp.status != ImportStatus.ready:
        raise HTTPException(status.HTTP_409_CONFLICT, "Import is not ready to publish")
    return publish_import(db, imp, store, [r.model_dump() for r in data.rows])
