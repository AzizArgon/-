"""Price list import: file -> markitdown -> cleanup -> Gemini in chunks -> preview -> publish."""

import asyncio
import io
import logging
import re
from pathlib import Path

from markitdown import MarkItDown, StreamInfo
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import Category, Condition, ImportStatus, Offer, PriceHistory, PriceImport, Product, Store
from app.services.ai_parser import QuotaExhausted, merge_rows, parse_chunk
from app.services.price_cleaner import clean_markdown, make_chunks

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf"}


def file_to_markdown(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    result = MarkItDown().convert_stream(io.BytesIO(data), stream_info=StreamInfo(extension=ext, filename=filename))
    return result.text_content


def _set(import_id: int, **fields) -> None:
    with SessionLocal() as db:
        db.execute(update(PriceImport).where(PriceImport.id == import_id).values(**fields))
        db.commit()


async def run_import(import_id: int, data: bytes, filename: str) -> None:
    """Background job: fills price_imports.rows_json and reports progress per chunk."""
    try:
        md = await asyncio.to_thread(file_to_markdown, data, filename)
        rows = clean_markdown(md)
        chunks = make_chunks(rows, settings.parser_chunk_rows)
        if not chunks:
            _set(import_id, status=ImportStatus.failed, error="empty_file")
            return
        _set(import_id, chunks_total=len(chunks))

        sem = asyncio.Semaphore(settings.parser_concurrency)
        done, failed, quota_hit, items = 0, 0, False, []

        async def worker(chunk: str):
            nonlocal done, failed, quota_hit
            async with sem:
                try:
                    items.extend(await parse_chunk(chunk))
                except QuotaExhausted:
                    quota_hit = True
                    failed += 1
                except RuntimeError as e:
                    log.error("Import %s: chunk failed: %s", import_id, e)
                    failed += 1
            done += 1
            _set(import_id, chunks_done=done)

        await asyncio.gather(*(worker(c) for c in chunks))

        if failed == len(chunks):
            _set(import_id, status=ImportStatus.failed, error="ai_quota" if quota_hit else "ai_failed")
            return
        _set(
            import_id,
            status=ImportStatus.ready,
            rows_json=merge_rows(rows, items),
            error=f"chunks_failed:{failed}" if failed else None,
        )
    except Exception as e:  # never leave an import stuck in "processing"
        log.exception("Import %s failed", import_id)
        _set(import_id, status=ImportStatus.failed, error=str(e)[:500])


def fail_stale_imports() -> None:
    """Imports interrupted by a server restart can never finish."""
    with SessionLocal() as db:
        db.execute(
            update(PriceImport)
            .where(PriceImport.status == ImportStatus.processing)
            .values(status=ImportStatus.failed, error="interrupted")
        )
        db.commit()


def make_match_key(category: str, name: str) -> str:
    """Same product from different stores -> same key (case, spaces and punctuation ignored)."""
    tokens = re.findall(r"[a-zа-я0-9]+", name.lower())
    return f"{category}:{' '.join(tokens)}"


def publish_import(db: Session, imp: PriceImport, store: Store, rows: list[dict]) -> dict:
    """Creates/updates offers. Store offers missing from the file become "out of stock"."""
    categories = {c.slug: c for c in db.scalars(select(Category))}
    offers_by_raw = {o.raw_name: o for o in db.scalars(select(Offer).where(Offer.store_id == store.id))}
    products: dict[str, Product] = {}
    seen: set[int] = set()
    stats = {"created": 0, "updated": 0, "out_of_stock": 0}

    for r in rows:
        category = categories.get(r["category"]) or categories["other"]
        key = make_match_key(category.slug, r["name"])
        product = products.get(key) or db.scalar(select(Product).where(Product.match_key == key))
        if product is None:
            product = Product(
                category=category, brand=r.get("brand"), model=r.get("model"),
                normalized_name=r["name"], match_key=key, specs_json=r.get("specs") or {},
            )
            db.add(product)
        products[key] = product

        price = r.get("price")
        in_stock = price is not None and r.get("is_in_stock", True)
        offer = offers_by_raw.get(r["raw_name"])
        price_changed = True
        if offer is None:
            offer = Offer(store=store, raw_name=r["raw_name"])
            db.add(offer)
            offers_by_raw[r["raw_name"]] = offer
            stats["created"] += 1
        else:
            price_changed = offer.price != price or offer.currency != imp.currency
            stats["updated"] += 1
        offer.product = product
        offer.price = price
        offer.currency = imp.currency
        offer.condition = Condition(r.get("condition") or "new")
        offer.is_in_stock = in_stock
        if price is not None and price_changed:
            offer.price_history.append(PriceHistory(price=price, currency=imp.currency))
        db.flush()
        seen.add(offer.id)

    for offer in offers_by_raw.values():
        if offer.id not in seen and offer.is_in_stock:
            offer.is_in_stock = False
            stats["out_of_stock"] += 1

    imp.status = ImportStatus.published
    imp.rows_json = rows
    db.commit()
    return stats
