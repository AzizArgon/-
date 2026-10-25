from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.database import get_db
from app.db.models import Category, Condition, Currency, ImportStatus, PriceImport, Product, Store, User
from app.schemas.seller import (
    CheckResult, ImportDetail, ImportOut, OfferIn, ProductIn, PublishRequest, PublishResult, StoreIn, StoreOut,
    TextImportIn,
)
from app.services.importer import (
    ALLOWED_EXTENSIONS, flag_rows, publish_import, retry_failed_rows, run_import, run_text_import,
)
from app.services.manual import create_product, product_brief, save_offer, store_offer, suggest_products

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


@router.post("/imports/text", response_model=ImportOut, status_code=status.HTTP_202_ACCEPTED)
def paste_text(data: TextImportIn, background: BackgroundTasks, user: User = Depends(seller_only),
               db: Session = Depends(get_db)):
    """"Paste as text": a Telegram post goes through the same pipeline and preview as a file."""
    store = _require_store(db, user)
    # No file name: the page calls it "Текст от 25.10, 14:30" by the creation time
    imp = PriceImport(store_id=store.id, filename="", source="text", text=data.text, currency=Currency(data.currency))
    db.add(imp)
    db.commit()
    db.refresh(imp)
    background.add_task(run_text_import, imp.id, data.text, imp.currency)
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


@router.post("/imports/{import_id}/check", response_model=CheckResult)
def check_rows(import_id: int, data: PublishRequest, user: User = Depends(seller_only), db: Session = Depends(get_db)):
    """Anti-Fraud for rows the seller just edited in the preview (rules only, no AI request)."""
    store, imp = _my_import(db, user, import_id)
    rows = [r.model_dump() for r in data.rows]
    flag_rows(db, rows, store.id, imp.currency)
    return {"flags": [r["flags"] for r in rows]}


@router.post("/imports/{import_id}/retry", response_model=ImportOut, status_code=status.HTTP_202_ACCEPTED)
def retry_import(
    import_id: int, background: BackgroundTasks, user: User = Depends(seller_only), db: Session = Depends(get_db)
):
    """Parses again the rows that failed, e.g. the next day when the AI quota is back."""
    _, imp = _my_import(db, user, import_id)
    if imp.status != ImportStatus.ready or not any(r.get("source") == "failed" for r in imp.rows_json):
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing to retry")
    imp.status = ImportStatus.processing
    imp.chunks_done = 0
    db.commit()
    background.add_task(retry_failed_rows, imp.id)
    return imp


@router.get("/seller/catalog-search")
def catalog_search(q: str = Query("", max_length=200), user: User = Depends(seller_only),
                   db: Session = Depends(get_db)):
    """"Find in the catalog": suggestions with key specs and the store's own offer on the card, if any."""
    return suggest_products(db, _require_store(db, user), q)


@router.post("/seller/offers", status_code=status.HTTP_201_CREATED)
def add_offer(data: OfferIn, user: User = Depends(seller_only), db: Session = Depends(get_db)):
    """"I have it too, here is my price". An existing offer is never duplicated: 409 unless `replace`."""
    store = _require_store(db, user)
    product = db.get(Product, data.product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    existing = store_offer(db, store, product)
    if existing is not None and not data.replace:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "offer_exists", "product": product_brief(product, existing)})
    return save_offer(db, store, product, data.price, Currency(data.currency), Condition(data.condition),
                      data.is_in_stock)


@router.post("/seller/products", status_code=status.HTTP_201_CREATED)
def add_product(data: ProductIn, user: User = Depends(seller_only), db: Session = Depends(get_db)):
    """"Not in the catalog": a new card by the dictionary. The same card already exists -> 409 with it."""
    store = _require_store(db, user)
    category = db.scalar(select(Category).where(Category.slug == data.category))
    if category is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown category")
    if not (data.name or data.model or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name or model required")
    product, created = create_product(db, store, category, data.brand, data.model, data.name, data.specs)
    if not created:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "product_exists", "product": product_brief(product, store_offer(db, store, product))})
    return product_brief(product)
