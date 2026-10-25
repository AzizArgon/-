"""Catalog: one product card per real product, offers from all stores, "recommended" order."""

import re
from datetime import datetime, timezone

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Category, Currency, FlagLevel, FlagStatus, Offer, Product, Store
from app.services.exchange import to_usd, to_uzs
from app.services.spec_normalizer import normalize_specs

# Type words some stores add and others don't ("Процессор ...", "... Motherboard"): not part of the model
TYPE_WORDS = {
    "motherboard", "processor", "cpu", "videocard", "graphics", "card", "monitor", "laptop", "notebook",
    "keyboard", "mouse", "headset", "headphones", "for", "with", "and", "the",
    "процессор", "видеокарта", "материнская", "плата", "монитор", "ноутбук", "клавиатура", "мышь", "мышка",
    "игровой", "игровая", "игровое", "игровые", "кресло", "наушники", "гарнитура", "блок", "питания", "корпус",
    "кулер", "оперативная", "память", "модуль", "памяти", "накопитель", "жесткий", "диск", "твердотельный",
    "внешний", "компьютерный", "компьютерная", "моноблок", "системный", "ибп", "источник", "бесперебойного",
    "проектор", "принтер", "мфу", "роутер", "маршрутизатор", "веб", "камера", "колонки", "акустика", "флешка",
    "для", "и", "с", "в",
}
UNITS = r"gb|tb|mb|ghz|mhz|hz|w|va|mm|ms|mah|lm"
PAGE_SIZE = 24


def make_match_key(category: str, name: str, brand: str | None = None) -> str:
    """Same product from different stores -> same key: brand + model words, any order.

    Type words ("Процессор", "Видеокарта") are dropped, other words stay ("беспроводная"), so the rule parser name
    "Intel Core i5-12400F OEM" and the AI name "Процессор Intel Core i5-12400F OEM" match.
    """
    text = f"{brand or ''} {name}".lower().replace("ё", "е")
    text = re.sub(rf"(\d)\s+({UNITS})\b", r"\1\2", text)  # "16 GB" == "16GB"
    tokens = re.findall(r"[a-zа-я0-9]+", text)
    words = sorted({t for t in tokens if t not in TYPE_WORDS} or set(tokens))
    return f"{category}:{' '.join(words)}"


def rebuild_match_keys(db: Session) -> dict:
    """Recomputes keys of all products and merges cards that now share a key."""
    products = db.scalars(select(Product).options(selectinload(Product.category), selectinload(Product.offers))).all()
    by_key: dict[str, Product] = {}
    merged = 0
    for p in sorted(products, key=lambda p: p.id):
        key = make_match_key(p.category.slug if p.category else "other", p.normalized_name, p.brand)
        keeper = by_key.get(key)
        if keeper is None:
            p.match_key = key
            by_key[key] = p
            continue
        for offer in list(p.offers):
            offer.product = keeper
        keeper.brand = keeper.brand or p.brand
        keeper.specs_json = {**(p.specs_json or {}), **(keeper.specs_json or {})}
        db.delete(p)
        merged += 1
    db.commit()
    return {"products": len(by_key), "merged": merged}


def rebuild_specs(db: Session, trace: dict | None = None, demo_store_ids: set[int] = frozenset(),
                  commit: bool = True) -> dict:
    """Recomputes product specs by the dictionary from what the stores wrote. No AI requests.

    Sources: original rows (offers.raw_name) and specs already confirmed by those rows. Demo stores copy
    product names, not real rows, so they are used only if a product has no other offers.
    """
    products = db.scalars(select(Product).options(selectinload(Product.category), selectinload(Product.offers))).all()
    changed = 0
    for p in products:
        category = p.category.slug if p.category else "other"
        offers = sorted(p.offers, key=lambda o: o.id)
        texts = [o.raw_name for o in offers if o.store_id not in demo_store_ids] or [o.raw_name for o in offers]
        specs: dict = {}
        for i, text in enumerate(dict.fromkeys(texts)):
            # Old specs were checked against the first store's row; other rows only add what is missing
            found = normalize_specs(category, text, p.specs_json if i == 0 else None, p.brand, trace)
            specs.update({k: v for k, v in found.items() if k not in specs})
        if specs != p.specs_json:
            p.specs_json = specs
            changed += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return {"products": len(products), "changed": changed}


def _search_stem(word: str) -> str:
    """Russian endings vary ("видеокарта" / "Видеокарты", "кресло" / "кресла"): search by the stem."""
    if not re.search("[а-я]", word):
        return word
    return word[:-2] if len(word) >= 6 else word[:-1] if len(word) >= 4 else word


def _usd_price(usd_rate: float | None):
    """SQL expression: offer price in USD (UZS divided by the CBU rate)."""
    return case((Offer.currency == Currency.UZS, Offer.price / (usd_rate or 1e18)), else_=Offer.price)


def _cheapest_offers(db: Session, product_ids: list[int], usd_rate: float | None, in_stock: bool) -> dict[int, Offer]:
    query = select(Offer).where(Offer.product_id.in_(product_ids), Offer.price.is_not(None))
    if in_stock:
        query = query.where(Offer.is_in_stock.is_(True))
    result: dict[int, Offer] = {}
    for o in db.scalars(query):
        best = result.get(o.product_id)
        usd = to_usd(o.price, o.currency, usd_rate) or float("inf")
        if best is None or usd < (to_usd(best.price, best.currency, usd_rate) or float("inf")):
            result[o.product_id] = o
    return result


def search_products(
    db: Session, usd_rate: float | None, q: str = "", category: str | None = None,
    price_min: float | None = None, price_max: float | None = None, in_stock: bool = True, page: int = 1,
) -> dict:
    """Catalog page: products with the lowest USD price and the number of offers."""
    usd = _usd_price(usd_rate)
    offer_filter = [Offer.price.is_not(None)]
    if in_stock:
        offer_filter.append(Offer.is_in_stock.is_(True))
    stats = (
        select(Offer.product_id, func.min(usd).label("min_usd"), func.count(Offer.id).label("offers"))
        .where(*offer_filter).group_by(Offer.product_id).subquery()
    )
    query = (
        select(Product, stats.c.min_usd, stats.c.offers)
        .join(stats, stats.c.product_id == Product.id).outerjoin(Product.category)
    )
    for word in q.lower().split()[:8]:
        # py_lower: SQLite lower() knows only ASCII, Russian words need Python's.
        # Category name too: "процессор i5" must find "Intel Core i5-12400F" without the type word
        like = f"%{_search_stem(word)}%"
        query = query.where(or_(
            func.py_lower(Product.normalized_name).like(like), Product.match_key.like(like),
            func.py_lower(Category.name).like(like),
        ))
    if category:
        query = query.where(Category.slug == category)
    if price_min is not None:
        query = query.where(stats.c.min_usd >= price_min)
    if price_max is not None:
        query = query.where(stats.c.min_usd <= price_max)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.options(selectinload(Product.category))
        .order_by(stats.c.offers.desc(), Product.normalized_name)
        .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    cheapest = _cheapest_offers(db, [p.id for p, _, _ in rows], usd_rate, in_stock)
    items = [
        {"id": p.id, "name": p.normalized_name, "brand": p.brand, "category": p.category.slug if p.category else "other",
         "min_price_usd": round(min_usd, 2) if min_usd is not None else None, "offers": n,
         # The cheapest offer as the seller wrote it: the page shows "≈" only for a converted currency
         "min_price": cheapest[p.id].price if p.id in cheapest else None,
         "min_currency": cheapest[p.id].currency.value if p.id in cheapest else None}
        for p, min_usd, n in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE}


def _age_bucket(updated_at: datetime) -> int:
    """Price freshness: today/yesterday, this week, this month, older."""
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - updated_at).days
    return 0 if days <= 1 else 1 if days <= 7 else 2 if days <= 30 else 3


def recommended_order(offer: dict) -> tuple:
    """In stock first, then verified store, no serious Anti-Fraud flag, fresh price list, cheaper."""
    return (
        not offer["is_in_stock"],
        not offer["store"]["is_verified"],
        any(f["level"] == FlagLevel.danger.value for f in offer["flags"]),
        _age_bucket(offer["updated_at"]),
        offer["price_usd"] if offer["price_usd"] is not None else float("inf"),
    )


def price_order(offer: dict) -> tuple:
    return (not offer["is_in_stock"], offer["price_usd"] if offer["price_usd"] is not None else float("inf"))


def product_card(db: Session, product_id: int, usd_rate: float | None, sort: str = "recommended") -> dict | None:
    product = db.scalar(
        select(Product).where(Product.id == product_id).options(
            selectinload(Product.category),
            selectinload(Product.offers).selectinload(Offer.store),
            selectinload(Product.offers).selectinload(Offer.fraud_flags),
        )
    )
    if product is None:
        return None
    offers = []
    for o in product.offers:
        if o.price is None:
            continue
        store: Store = o.store
        offers.append({
            "id": o.id, "raw_name": o.raw_name, "price": o.price, "currency": o.currency.value,
            "price_usd": to_usd(o.price, o.currency, usd_rate), "price_uzs": to_uzs(o.price, o.currency, usd_rate),
            "is_in_stock": o.is_in_stock, "condition": o.condition.value, "updated_at": o.updated_at,
            "store": {"id": store.id, "name": store.name, "is_verified": store.is_verified, "phone": store.phone,
                      "telegram": store.telegram, "address": store.address, "district": store.district},
            "flags": [{"type": f.type, "level": f.level.value, "reason_key": f.reason_key, "params": f.params,
                       "source": f.source.value} for f in o.fraud_flags if f.status == FlagStatus.active],
        })
    offers.sort(key=price_order if sort == "price" else recommended_order)
    return {
        "id": product.id, "name": product.normalized_name, "brand": product.brand, "model": product.model,
        "category": product.category.slug if product.category else "other",
        "mxik_code": product.category.mxik_code if product.category else None,
        "specs": product.specs_json or {}, "usd_rate": usd_rate, "offers": offers,
    }
