"""Price list import: file -> markitdown -> cleanup -> cache / rules / AI -> preview -> publish."""

import asyncio
import csv
import io
import logging
import time
from pathlib import Path

from markitdown import MarkItDown, StreamInfo
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import (
    Category, Condition, Currency, ImportStatus, Offer, ParseCache, PriceHistory, PriceImport, Product, Store, utcnow,
)
from app.services.catalog import make_match_key
from app.services.antifraud import check_offer, market_prices, save_offer_flags
from app.services.ai_parser import QuotaExhausted, parse_rows, split_specs
from app.services.exchange import get_usd_rate
from app.services.price_cleaner import CleanRow, cache_key, clean_markdown
from app.services.rule_parser import parse_by_rules
from app.services.text_import import no_rows_reason, text_to_rows
from app.services.spec_normalizer import (
    canonical_brand, merge_specs, normalize_specs, source_text, strip_modifiers, written_specs,
)

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf"}


def normalize_csv(data: bytes) -> bytes:
    """markitdown reads only comma CSV in UTF-8; Excel often saves ";" and cp1251. Rewrite to that."""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return data
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;	|")
    except csv.Error:
        return data  # one column or unclear: leave as is
    out = io.StringIO()
    csv.writer(out).writerows(csv.reader(io.StringIO(text), dialect))
    return out.getvalue().encode("utf-8")


def file_to_markdown(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        data = normalize_csv(data)
    result = MarkItDown().convert_stream(io.BytesIO(data), stream_info=StreamInfo(extension=ext, filename=filename))
    return result.text_content


def _set(import_id: int, **fields) -> None:
    with SessionLocal() as db:
        db.execute(update(PriceImport).where(PriceImport.id == import_id).values(**fields))
        db.commit()


def _preview_row(r: CleanRow, parsed: dict | None, source: str) -> dict:
    """One row of the preview table. Price, article and stock always come from the file."""
    p = parsed or {}
    specs, guessed = p.get("specs") or {}, {}
    if source in ("ai", "cache"):
        # AI specs must be backed by the row text; the rest is only a guess
        specs, guessed = split_specs(specs, f"{r.sheet} {r.section} {r.raw_name}")
    category = p.get("category") or "other"
    if category == "other" and r.category_hint:
        category = r.category_hint
    # Only dictionary keys and values reach the product (values are read from the row itself first)
    specs = normalize_specs(category, source_text(r.raw_name, r.article), specs, p.get("brand"))
    return {
        "row": r.row,
        "raw_name": r.raw_name,
        "sheet": r.sheet,
        "section": r.section,
        "ai_text": r.ai_text,
        "cache_key": cache_key(r.ai_text),
        "article": r.article,
        "category": category,
        "brand": canonical_brand(p["brand"]) if p.get("brand") else None,  # "T-Force" -> TeamGroup
        "model": p.get("model") or r.article,
        "name": strip_modifiers(category, p.get("name") or r.name)[0] or r.name,  # "LHR" -> a characteristic
        "price": r.price,
        "condition": r.condition or p.get("condition", "new"),
        "note": r.note,
        "specs": specs,
        "specs_guess": guessed,
        "is_in_stock": r.is_in_stock,
        "currency": r.currency,  # pasted text: per line; None = the currency of the whole import
        "currency_check": r.currency_check,
        "ai_risks": p.get("risks") or [],  # Anti-Fraud hints from the AI, checked after the rules
        "source": source,  # cache / rule / ai / failed
    }


def _cache_data(row: dict) -> dict:
    data = {k: row.get(k) for k in ("category", "brand", "model", "name", "condition")}
    data["risks"] = row.get("ai_risks") or row.get("risks") or []
    # Guesses stay in the cache: they are re-checked against the row text every time
    data["specs"] = {**(row.get("specs_guess") or {}), **written_specs(row.get("specs"))}  # inferred ones are redone
    return data


def save_cache(db: Session, entries: dict[str, dict], source: str) -> None:
    if not entries:
        return
    existing = {c.key: c for c in db.scalars(select(ParseCache).where(ParseCache.key.in_(list(entries))))}
    for key, data in entries.items():
        if key in existing:
            existing[key].data, existing[key].source = data, source
        else:
            db.add(ParseCache(key=key, data=data, source=source))
    db.commit()


async def parse_clean_rows(db: Session, rows: list[CleanRow], stats: dict, on_progress=None) -> list[dict]:
    """Cache first, then rules, and only the rest goes to the AI in big chunks."""
    started = time.monotonic()
    keys = list({cache_key(r.ai_text) for r in rows})
    cached = {c.key: c.data for c in db.scalars(select(ParseCache).where(ParseCache.key.in_(keys)))}
    result: dict[int, dict] = {}
    pending: list[CleanRow] = []
    skipped = 0
    for r in rows:
        hit = cached.get(cache_key(r.ai_text))
        rule = None if hit else parse_by_rules(r.name)
        if hit and hit.get("skip"):
            skipped += 1  # the AI said earlier: not a product
        elif hit:
            result[r.row] = _preview_row(r, hit, "cache")
        elif rule:
            result[r.row] = _preview_row(r, rule, "rule")
        else:
            pending.append(r)

    size = settings.parser_chunk_rows
    chunks = [pending[i : i + size] for i in range(0, len(pending), size)]
    by_source = [v["source"] for v in result.values()]
    stats.update(
        rows=len(rows), cache=by_source.count("cache") + skipped, rule=by_source.count("rule"),
        ai_rows=len(pending), chunks=len(chunks), requests=0,
    )
    done = 0
    if on_progress:
        on_progress(done, len(chunks))
    sem = asyncio.Semaphore(settings.parser_concurrency)

    async def worker(chunk: list[CleanRow]):
        nonlocal done
        async with sem:
            try:
                items = {it["row"]: it for it in await parse_rows(chunk, stats)}
            except RuntimeError as e:
                log.error("Chunk of %s rows failed: %s", len(chunk), str(e)[:300])
                stats["quota_hit"] = stats.get("quota_hit") or isinstance(e, QuotaExhausted)
                for r in chunk:
                    result[r.row] = _preview_row(r, None, "failed")
            else:
                # Rows the AI skipped are not products (notes, headers)
                for r in chunk:
                    if r.row in items:
                        result[r.row] = _preview_row(r, items[r.row], "ai")
                # Skipped rows are cached too, so notes are not sent to the AI again
                save_cache(db, {
                    cache_key(r.ai_text): _cache_data(items[r.row]) if r.row in items else {"skip": True}
                    for r in chunk
                }, "ai")
        done += 1
        if on_progress:
            on_progress(done, len(chunks))

    await asyncio.gather(*(worker(c) for c in chunks))
    stats["failed_rows"] = sum(v["source"] == "failed" for v in result.values())
    stats["seconds"] = round(time.monotonic() - started, 1)
    return [result[k] for k in sorted(result)]


def flag_rows(db: Session, rows: list[dict], store_id: int, currency: Currency) -> None:
    """Anti-Fraud for preview rows: fills row["flags"]. Market prices come from other stores."""
    rate = get_usd_rate(db)  # cached in the DB for a day
    usd_rate = rate.rate if rate else None
    keys = {make_match_key(r.get("category") or "other", r["name"], r.get("brand")) for r in rows}
    market = market_prices(db, keys, store_id, usd_rate)
    for r in rows:
        key = make_match_key(r.get("category") or "other", r["name"], r.get("brand"))
        r["flags"] = check_offer({**r, "currency": r.get("currency") or currency.value}, market.get(key), usd_rate)


def _finish(import_id: int, rows: list[dict], stats: dict) -> None:
    if not rows:
        # Rows were found, but the AI said none of them is a product (notes, adverts)
        _set(import_id, status=ImportStatus.failed, error="no_products", stats_json=stats)
        return
    with SessionLocal() as db:
        imp = db.get(PriceImport, import_id)
        flag_rows(db, rows, imp.store_id, imp.currency)
    stats["flagged"] = sum(bool(r["flags"]) for r in rows)
    failed = stats.get("failed_rows", 0)
    error = f"{'ai_quota' if stats.get('quota_hit') else 'rows_failed'}:{failed}" if failed else None
    _set(import_id, status=ImportStatus.ready, rows_json=rows, error=error, stats_json=stats)


def _progress(import_id: int):
    return lambda done, total: _set(import_id, chunks_done=done, chunks_total=total)


async def run_import(import_id: int, data: bytes, filename: str) -> None:
    """Background job: fills price_imports.rows_json and reports progress per chunk."""
    try:
        try:
            md = await asyncio.to_thread(file_to_markdown, data, filename)
        except Exception:
            log.exception("Import %s: file can't be read", import_id)
            _set(import_id, status=ImportStatus.failed, error="unreadable_file")
            return
        rows = clean_markdown(md)
        if not rows:
            _set(import_id, status=ImportStatus.failed, error="no_rows")
            return
        stats: dict = {}
        with SessionLocal() as db:
            parsed = await parse_clean_rows(db, rows, stats, _progress(import_id))
        _finish(import_id, parsed, stats)
    except Exception as e:  # never leave an import stuck in "processing"
        log.exception("Import %s failed", import_id)
        _set(import_id, status=ImportStatus.failed, error=f"internal:{str(e)[:400]}")


async def run_text_import(import_id: int, text: str, currency: Currency) -> None:
    """Background job for a pasted post: the same pipeline from the cleanup on, without a file."""
    try:
        rows = text_to_rows(text)
        if not rows:
            _set(import_id, status=ImportStatus.failed, error=no_rows_reason(text))
            return
        stats: dict = {}
        with SessionLocal() as db:
            parsed = await parse_clean_rows(db, rows, stats, _progress(import_id))
        _finish(import_id, parsed, stats)
    except Exception as e:  # never leave an import stuck in "processing"
        log.exception("Text import %s failed", import_id)
        _set(import_id, status=ImportStatus.failed, error=f"internal:{str(e)[:400]}")


async def retry_failed_rows(import_id: int) -> None:
    """Parses again only the rows that failed (e.g. after the AI quota ran out)."""
    try:
        with SessionLocal() as db:
            imp = db.get(PriceImport, import_id)
            rows = list(imp.rows_json)
            failed = [
                CleanRow(
                    row=r["row"], sheet=r.get("sheet", ""), section=r.get("section", ""), cells=[r["raw_name"]],
                    name=r["name"], article=r.get("article"), price=r.get("price"),
                    is_in_stock=r.get("is_in_stock", False), ai_text=r.get("ai_text") or r["name"],
                    currency=r.get("currency"), currency_check=r.get("currency_check", False),
                    condition=r.get("condition") if imp.source == "text" else None, note=r.get("note"),
                )
                for r in rows if r.get("source") == "failed"
            ]
            stats = dict(imp.stats_json or {})
            retry_stats: dict = {}
            reparsed = await parse_clean_rows(db, failed, retry_stats, _progress(import_id))
        by_row = {r["row"]: r for r in rows if r.get("source") != "failed"}
        by_row.update({r["row"]: r for r in reparsed})
        stats["retries"] = stats.get("retries", []) + [retry_stats]
        stats["failed_rows"] = retry_stats.get("failed_rows", 0)
        stats["quota_hit"] = retry_stats.get("quota_hit", False)
        _finish(import_id, [by_row[k] for k in sorted(by_row)], stats)
    except Exception as e:  # never leave an import stuck in "processing"
        log.exception("Retry of import %s failed", import_id)
        _set(import_id, status=ImportStatus.failed, error=f"internal:{str(e)[:400]}")


def fail_stale_imports() -> None:
    """Imports interrupted by a server restart can never finish."""
    with SessionLocal() as db:
        db.execute(
            update(PriceImport)
            .where(PriceImport.status == ImportStatus.processing)
            .values(status=ImportStatus.failed, error="interrupted")
        )
        db.commit()


def publish_import(db: Session, imp: PriceImport, store: Store, rows: list[dict]) -> dict:
    """Creates/updates offers. Store offers missing from a file become "out of stock" (not after pasted text)."""
    categories = {c.slug: c for c in db.scalars(select(Category))}
    store_offers = db.scalars(select(Offer).where(Offer.store_id == store.id)).all()
    offers_by_raw = {o.raw_name: o for o in store_offers}
    # One offer per card per store: a new name of a product the store already sells updates that offer
    offers_by_product = {o.product_id: o for o in store_offers}
    products: dict[str, Product] = {}
    seen: set[int] = set()
    stats = {"created": 0, "updated": 0, "out_of_stock": 0}

    # The same item listed twice in one file: a row without a price must not overwrite a priced one
    priced = {r["raw_name"] for r in rows if r.get("price") is not None}
    rows_to_save = [r for r in rows if r.get("price") is not None or r["raw_name"] not in priced]
    # Flags are checked again: the seller may have changed category, condition or price
    flag_rows(db, rows, store.id, imp.currency)
    for r in rows_to_save:
        category = categories.get(r["category"]) or categories["other"]
        key = make_match_key(category.slug, r["name"], r.get("brand"))
        product = products.get(key) or db.scalar(select(Product).where(Product.match_key == key))
        # The seller may have changed the category in the preview: specs are normalized again for it
        specs = normalize_specs(category.slug, source_text(r["raw_name"], r.get("article")), r.get("specs"), r.get("brand"))
        if product is None:
            product = Product(
                category=category, brand=r.get("brand"), model=r.get("model"),
                normalized_name=strip_modifiers(category.slug, r["name"])[0] or r["name"], match_key=key,
                specs_json=specs,
            )
            db.add(product)
        else:
            product.specs_json = merge_specs(product.specs_json, specs)
        products[key] = product

        price = r.get("price")
        in_stock = price is not None and r.get("is_in_stock", True)
        offer = offers_by_raw.get(r["raw_name"]) or (offers_by_product.get(product.id) if product.id else None)
        if offer is not None and offer.id in seen:
            continue  # duplicate within this file: the first priced row is kept
        currency = Currency(r["currency"]) if r.get("currency") else imp.currency
        price_changed = True
        if offer is None:
            offer = Offer(store=store, raw_name=r["raw_name"])
            db.add(offer)
            offers_by_raw[r["raw_name"]] = offer
            stats["created"] += 1
        else:
            price_changed = offer.price != price or offer.currency != currency
            stats["updated"] += 1
        offer.product = product
        offer.price = price
        offer.currency = currency
        offer.condition = Condition(r.get("condition") or "new")
        offer.note = r.get("note")
        offer.is_in_stock = in_stock
        offer.updated_at = utcnow()  # the price list confirmed this offer: freshness for "recommended"
        save_offer_flags(offer, r["flags"])
        if price is not None and price_changed:
            offer.price_history.append(PriceHistory(price=price, currency=currency))
        db.flush()
        seen.add(offer.id)
        offers_by_product.setdefault(product.id, offer)

    # Only a full price list file says "everything else is sold out"; a pasted post lists just a few goods
    for offer in offers_by_raw.values() if imp.source == "file" else ():
        if offer.id not in seen and offer.is_in_stock:
            offer.is_in_stock = False
            stats["out_of_stock"] += 1

    imp.status = ImportStatus.published
    imp.rows_json = rows
    db.commit()
    # Reviewed rows teach the cache: next upload of the same names needs no AI at all
    save_cache(db, {r["cache_key"]: _cache_data(r) for r in rows if r.get("cache_key")}, "seller")
    return stats
