"""Adding goods on the site without a price list file.

"Find in the catalog" (like Oson Apteka): the seller does not create a product, he says "I have it too, here is my
price" — an offer on an existing reference card. "Not in the catalog": a new card from a short form, specs only by
the dictionary. Neither marks other offers of the store "out of stock": only a full price list file does that.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Category, Condition, Currency, ImportStatus, Offer, PriceHistory, PriceImport, Product, Store, utcnow,
)
from app.services.antifraud import check_offer, market_prices, save_offer_flags
from app.services.catalog import card_specs, make_match_key, search_filter
from app.services.exchange import get_usd_rate
from app.services.spec_dictionary import spec_map
from app.services.spec_normalizer import (
    INFERRED, SUSPECT, _from_value, canonical_brand, normalize_specs, strip_modifiers,
)

SUGGEST_LIMIT = 8


def product_brief(product: Product, my_offer: Offer | None = None) -> dict:
    """What the seller sees in a suggestion: enough to tell similar models apart."""
    slug = product.category.slug if product.category else "other"
    return {
        "id": product.id, "name": product.normalized_name, "brand": product.brand, "category": slug,
        "specs": card_specs(slug, product.specs_json or {})[:3],
        "my_offer": offer_brief(my_offer) if my_offer else None,
    }


def offer_brief(offer: Offer) -> dict:
    return {"id": offer.id, "price": offer.price, "currency": offer.currency.value,
            "condition": offer.condition.value, "is_in_stock": offer.is_in_stock}


def suggest_products(db: Session, store: Store, q: str) -> list[dict]:
    """Autocomplete over reference cards: the same search as the catalog, cards with more offers first."""
    if len(q.strip()) < 2:
        return []
    offers = select(Offer.product_id, func.count(Offer.id).label("n")).group_by(Offer.product_id).subquery()
    query = (
        select(Product).outerjoin(Product.category).outerjoin(offers, offers.c.product_id == Product.id)
        .options(selectinload(Product.category))
        .order_by(func.coalesce(offers.c.n, 0).desc(), Product.normalized_name).limit(SUGGEST_LIMIT)
    )
    products = db.scalars(search_filter(query, q.strip())).all()
    mine = {o.product_id: o for o in db.scalars(
        select(Offer).where(Offer.store_id == store.id, Offer.product_id.in_([p.id for p in products])))}
    return [product_brief(p, mine.get(p.id)) for p in products]


def store_offer(db: Session, store: Store, product: Product) -> Offer | None:
    return db.scalar(select(Offer).where(Offer.store_id == store.id, Offer.product_id == product.id))


def save_offer(db: Session, store: Store, product: Product, price: float, currency: Currency,
               condition: Condition, is_in_stock: bool) -> dict:
    """Creates the store's offer on the card or updates its price. Anti-Fraud and price history as for a file."""
    slug = product.category.slug if product.category else "other"
    offer = store_offer(db, store, product)
    created = offer is None
    if created:
        offer = Offer(store=store, product=product, raw_name=product.normalized_name)
        db.add(offer)
    price_changed = created or offer.price != price or offer.currency != currency
    offer.price, offer.currency, offer.condition, offer.is_in_stock = price, currency, condition, is_in_stock
    offer.updated_at = utcnow()

    rate = get_usd_rate(db)
    usd_rate = rate.rate if rate else None
    row = {
        "raw_name": product.normalized_name, "name": product.normalized_name, "category": slug,
        "brand": product.brand, "model": product.model, "specs": product.specs_json or {},
        "price": price, "currency": currency.value, "condition": condition.value, "is_in_stock": is_in_stock,
    }
    market = market_prices(db, {product.match_key}, store.id, usd_rate)
    row["flags"] = check_offer(row, market.get(product.match_key), usd_rate)
    save_offer_flags(offer, row["flags"])
    if price_changed:
        offer.price_history.append(PriceHistory(price=price, currency=currency))
    # The import history shows where the goods came from: "added by hand"
    db.add(PriceImport(
        store_id=store.id, filename=product.normalized_name, source="manual", currency=currency,
        status=ImportStatus.published, rows_json=[{"row": 1, **row, "source": "seller"}],
        stats_json={"created": int(created), "updated": int(not created)},
    ))
    db.commit()
    return {"created": created, "offer": offer_brief(offer), "flags": row["flags"]}


def seller_specs(category: str, given: dict) -> dict:
    """Values chosen in the form, checked by the dictionary; unknown keys and wrong values are dropped."""
    specs = spec_map(category)
    result = {}
    for key, value in given.items():
        if key in specs and value not in (None, ""):
            normalized = _from_value(category, specs[key], value)
            if normalized is not None:
                result[key] = normalized
    return result


def create_product(db: Session, store: Store, category: Category, brand: str | None, model: str | None,
                   name: str | None, given_specs: dict) -> tuple[Product, bool]:
    """A new reference card from the form. Returns (card, created): an existing card with the same key is
    returned instead of a duplicate, so the seller can use it."""
    brand = canonical_brand(brand or "") or None
    name = (name or " ".join(filter(None, [brand, model]))).strip()
    written, name = name, strip_modifiers(category.slug, name)[0] or name  # "LHR" stays a characteristic
    chosen = seller_specs(category.slug, given_specs)
    if brand and "brand" in spec_map(category.slug) and "brand" not in chosen:
        brand_value = _from_value(category.slug, spec_map(category.slug)["brand"], brand)
        if brand_value is not None:
            chosen["brand"] = brand_value
    # What the seller chose is "specified by the seller"; inference rules may add the rest (marked as inferred)
    specs = normalize_specs(category.slug, " ".join(filter(None, [brand, model, written])), chosen, brand)
    suspect = specs.pop(SUSPECT, {})
    specs.update({k: v for k, v in chosen.items() if k not in suspect})  # a typo in the form stays doubtful
    inferred = {k: v for k, v in specs.pop(INFERRED, {}).items() if k not in chosen}
    if inferred:
        specs[INFERRED] = inferred
    if suspect:
        specs[SUSPECT] = suspect
    key = make_match_key(category.slug, name, brand, specs)
    existing = db.scalar(select(Product).where(Product.match_key == key))
    if existing is not None:
        return existing, False
    product = Product(
        category=category, brand=brand, model=model, normalized_name=name, match_key=key, specs_json=specs,
        manual_store_id=store.id,
    )
    db.add(product)
    db.commit()
    return product, True
