"""Catalog: one product card per real product, offers from all stores, "recommended" order."""

import re
from datetime import datetime, timezone

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Category, Condition, Currency, FlagLevel, FlagStatus, Offer, Product, Store
from app.services.exchange import to_usd, to_uzs
from app.services.spec_dictionary import CARD_SPECS, NUMBER, YESNO, Spec, spec_map, specs_of
from app.services.spec_inference import INFERABLE
from app.services.spec_normalizer import INFERRED, SUSPECT, merge_specs, normalize_specs, strip_modifiers

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
    # Phase 7: words that describe, not identify — one store writes them, another does not
    "gaming", "geforce", "radeon", "ssd", "hdd", "nvme", "sata", "sataiii", "sata3", "desktop",
    "проц", "видюха", "видяха", "озу", "оперативка", "мать", "материнка", "моник", "винт", "ссд",
    "дюйм", "дюйма", "дюймов", "inch",
}
UNITS = r"gb|tb|mb|ghz|mhz|hz|w|va|mm|ms|mah|lm"
_RU_UNITS = (("гб", "gb"), ("тб", "tb"), ("мб", "mb"), ("мгц", "mhz"), ("ггц", "ghz"), ("гц", "hz"), ("вт", "w"))
# Characteristics an AI name or a long store name adds to the model: clocks, refresh rate, resolution, panel,
# video memory type and bus, response time, spindle speed, the M.2 slot. They are kept in specs, not in the key
_DESCRIPTORS = re.compile(
    r"\d+(?:[.,]\d+)?\s*ghz\b|(?<![\w.])\d{2,3}\s*hz\b|\b\d{3,4}\s*[x×х*]\s*\d{3,4}\b"
    r"|\b(?:full\s*hd|fhd|wqhd|qhd|uhd|4k|2k|hd)\b|\b(?:fast\s+)?(?:ips|va|tn|qd-?oled|oled)\b"
    r"|\bgddr\d\w*\b|\b\d{2,4}\s*-?\s*bits?\b|\b\d+(?:[.,]\d+)?\s*ms\b|\b\d{4,5}\s*rpm\b|\bm\.?\s?2\b"
    r"|\blga\s?-?\d{4}\b|\bam[345]\b"  # the socket follows from the chipset / CPU model
    r"|\bsata\s*(?:iii|ii|3|2)\b|\([\w./-]*\d[\w./-]*\)"  # "SATA III"; a part number in brackets "(TS2TESD360C)"
)
# Cyrillic letters typed inside a Latin code ("PХG27Q", "АМ4", "LGА1700") look the same and are the same
_LOOKALIKES = str.maketrans("авекмнорстухі", "abekmhopctyxi")
_MIXED_CODE = re.compile(r"[a-zа-я0-9]*(?:[a-z0-9][а-я]|[а-я][a-z0-9])[a-zа-я0-9]*")
_GPU_CHIP = re.compile(r"\b(rtx|gtx|gt|rx|arc\s*[ab])\s*-?\s*(\d{3,4})\s*(ti\s*super|ti|super|xtx|xt|gre)?(?![a-z0-9])")
# Code names of CPU generations ("Raptor Lake", "Granite Ridge"): the model number already says it
_CPU_CODENAMES = re.compile(
    r"\b(?:alder|raptor|arrow|comet|rocket|coffee|kaby|meteor|lunar|ice)\s+lake\b|\b(?:granite|dragon)\s+r(?:idge|ange)\b"
    r"|\b(?:raphael|vermeer|cezanne|matisse|picasso|renoir|phoenix|hawk\s+point)\b"
    r"|\b\d+\s*mb\b"  # cache size: "Core i9-14900K 33MB"
)
# Values that tell two products apart, read from the seller's row even when a name leaves them out
# ("Gigabyte B860M Gaming" with "DDR5" in the row is not the DDR4 board; "i5-12400F" written "OEM")
# (the same monitor name with 240 Hz and 320 Hz is two models)
IDENTITY_SPECS = {"motherboard": ("memory_type",), "cpu": ("pack",), "ram": ("type",), "monitor": ("refresh_rate",)}
PAGE_SIZE = 24
NUMBER_FACET_VALUES = 12  # numbers (capacity, diagonal) are offered by their most popular values


def make_match_key(category: str, name: str, brand: str | None = None, specs: dict | None = None) -> str:
    """Same product from different stores -> same key: brand + model words, any order.

    Type words ("Процессор", "Видеокарта") and descriptions (clocks, "IPS", "1920x1080", "GDDR7") are dropped,
    other words stay ("беспроводная"), so the rule parser name "Intel Core i5-12400F OEM" and the AI name
    "Процессор Intel Core i5-12400F OEM" match. Identity specs of the row (DDR5 of a board, OEM of a CPU) are added.
    """
    # Modifiers ("LHR", "ver 5.30", "коробки нет") are kept as characteristics, not as model words
    text = f"{brand or ''} {strip_modifiers(category, name)[0]}".lower().replace("ё", "е")
    text = _MIXED_CODE.sub(lambda m: m[0].translate(_LOOKALIKES), text)
    text = _GPU_CHIP.sub(lambda m: " ".join(filter(None, m.groups())), text)  # "RTX5060Ti" == "RTX 5060 Ti"
    for ru, en in _RU_UNITS:
        text = re.sub(rf"(\d)\s*{ru}\b", rf"\1{en}", text)  # "16 ГБ" == "16GB"
    text = _DESCRIPTORS.sub(" ", text)
    if category == "cpu":
        text = _CPU_CODENAMES.sub(" ", text)
    if category == "ram":
        text = re.sub(r"\b(\d{4})\b(?!\s*mhz)", r"\1mhz", text)  # "DDR4 3200" == "DDR4 3200MHz"
    text = re.sub(rf"(\d)\s+({UNITS})\b", r"\1\2", text)  # "16 GB" == "16GB"
    tokens = re.findall(r"[a-zа-я0-9]+", text)
    words = {t for t in tokens if t not in TYPE_WORDS} or set(tokens)
    for key in IDENTITY_SPECS.get(category, ()):
        value = (specs or {}).get(key)
        if isinstance(value, str):
            words |= set(re.findall(r"[a-zа-я0-9]+", value.lower()))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            words.add(f"{value:g}{(spec_map(category)[key].unit or '').lower()}")  # 240 -> "240hz"
    return f"{category}:{' '.join(sorted(words))}"


# Key words that come from IDENTITY_SPECS
_IDENTITY_WORD = {"motherboard": r"ddr\d", "cpu": r"oem|box", "ram": r"ddr\d", "monitor": r"\d+hz"}


def split_identity(key: str) -> tuple[str, frozenset[str]]:
    """"monitor:27 army kg277s titan 240hz" -> ("monitor:27 army kg277s titan", {"240hz"})."""
    category, _, words = key.partition(":")
    pattern = _IDENTITY_WORD.get(category)
    ident = {w for w in words.split() if pattern and re.fullmatch(pattern, w)}
    return f"{category}:{' '.join(w for w in words.split() if w not in ident)}", frozenset(ident)


def completion_index(keys) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for key in keys:
        index.setdefault(split_identity(key)[0], []).append(key)
    return index


def unique_completion(key: str, index: dict[str, list[str]]) -> str | None:
    """A row that does not say an identity value ("Titan Army KG277S 27\"" without "240Hz") goes to the card that
    has it, but only if that card is the only one: "Redmi G27Q" with 240 Hz and 320 Hz cards stays apart."""
    base, ident = split_identity(key)
    found = [k for k in index.get(base, []) if ident < split_identity(k)[1]]
    return found[0] if len(found) == 1 else None


def rebuild_match_keys(db: Session) -> dict:
    """Recomputes keys of all products and merges cards that now share a key."""
    products = db.scalars(select(Product).options(selectinload(Product.category), selectinload(Product.offers))).all()
    by_key: dict[str, Product] = {}
    merged = 0
    for p in sorted(products, key=lambda p: p.id):
        slug = p.category.slug if p.category else "other"
        p.normalized_name = strip_modifiers(slug, p.normalized_name)[0] or p.normalized_name
        key = make_match_key(slug, p.normalized_name, p.brand, p.specs_json)
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
        # Old values of keys a rule can infer are not trusted as written: they are found or inferred again
        old = {k: v for k, v in (p.specs_json or {}).items() if k not in INFERABLE.get(category, ())}
        for i, text in enumerate(dict.fromkeys(texts)):
            # Old specs were checked against the first store's row; other rows only add what is missing
            specs = merge_specs(specs, normalize_specs(category, text, old if i == 0 else None, p.brand, trace))
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


def search_filter(query, q: str):
    """Every word of the search must be in the name, the match key or the category name (query joins Category)."""
    for word in q.lower().split()[:8]:
        # py_lower: SQLite lower() knows only ASCII, Russian words need Python's.
        # Category name too: "процессор i5" must find "Intel Core i5-12400F" without the type word
        like = f"%{_search_stem(word)}%"
        query = query.where(or_(
            func.py_lower(Product.normalized_name).like(like), Product.match_key.like(like),
            func.py_lower(Category.name).like(like),
        ))
    return query


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


def parse_spec_filters(category: str | None, raw: dict[str, str]) -> dict[str, list]:
    """URL "f_type=DDR5,DDR4&f_ecc=1" -> {"type": ["DDR5", "DDR4"], "ecc": [True]}. Unknown keys are ignored."""
    if not category:
        return {}
    specs = spec_map(category)
    result: dict[str, list] = {}
    for name, text in raw.items():
        spec = specs.get(name.removeprefix("f_")) if name.startswith("f_") else None
        if spec is None:
            continue
        values = []
        for part in filter(None, (v.strip() for v in text.split(","))):
            if spec.kind == NUMBER:
                try:
                    values.append(float(part))
                except ValueError:
                    continue
            elif spec.kind == YESNO:
                values.append(part in ("1", "true", "yes"))
            else:
                values.append(part)
        if values:
            result[spec.key] = values
    return result


def _matches(spec: Spec, value, selected: list) -> bool:
    """Several values of one filter = "or"; "at least" filters (refresh rate, power) = from the smallest."""
    if value is None:
        return False
    if spec.at_least:
        return value >= min(selected)
    return value in selected


def _spec_sql(spec: Spec, selected: list):
    value = func.json_extract(Product.specs_json, f"$.{spec.key}")
    if spec.at_least:
        return value >= min(selected)
    if spec.kind == YESNO:
        return value.in_([1 if v else 0 for v in selected])  # JSON true/false -> 1/0 in SQLite
    return value.in_(selected)


def _base_query(usd_rate, q, category, price_min, price_max, in_stock, condition=None):
    usd = _usd_price(usd_rate)
    offer_filter = [Offer.price.is_not(None)]
    if in_stock:
        offer_filter.append(Offer.is_in_stock.is_(True))
    if condition:
        offer_filter.append(Offer.condition == condition)
    stats = (
        select(Offer.product_id, func.min(usd).label("min_usd"), func.count(Offer.id).label("offers"))
        .where(*offer_filter).group_by(Offer.product_id).subquery()
    )
    query = (
        select(Product, stats.c.min_usd, stats.c.offers)
        .join(stats, stats.c.product_id == Product.id).outerjoin(Product.category)
    )
    query = search_filter(query, q)
    if category:
        query = query.where(Category.slug == category)
    if price_min is not None:
        query = query.where(stats.c.min_usd >= price_min)
    if price_max is not None:
        query = query.where(stats.c.min_usd <= price_max)
    return query, stats


def card_specs(category: str, specs: dict) -> list[dict]:
    """Key characteristics for the catalog tile, in dictionary order: DDR5 · 16 GB · 6000 MHz."""
    by_key = spec_map(category)
    return [{"key": k, "kind": by_key[k].kind, "unit": by_key[k].unit, "value": specs[k]}
            for k in CARD_SPECS.get(category, ()) if k in specs and k in by_key]


def search_products(
    db: Session, usd_rate: float | None, q: str = "", category: str | None = None,
    price_min: float | None = None, price_max: float | None = None, in_stock: bool = True, page: int = 1,
    spec_filters: dict[str, list] | None = None, condition: Condition | None = None,
) -> dict:
    """Catalog page: products with the lowest USD price and the number of offers.

    With a category, also its spec filters ("facets") with product counts per value.
    """
    query, stats = _base_query(usd_rate, q, category, price_min, price_max, in_stock, condition)
    spec_filters = spec_filters or {}
    facets = spec_facets(db, query, category, spec_filters) if category else []
    specs = spec_map(category) if category else {}
    for key, selected in spec_filters.items():
        query = query.where(_spec_sql(specs[key], selected))

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.options(selectinload(Product.category))
        .order_by(stats.c.offers.desc(), Product.normalized_name)
        .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    cheapest = _cheapest_offers(db, [p.id for p, _, _ in rows], usd_rate, in_stock)
    items = []
    for p, min_usd, n in rows:
        slug = p.category.slug if p.category else "other"
        items.append({
            "id": p.id, "name": p.normalized_name, "brand": p.brand, "category": slug,
            "min_price_usd": round(min_usd, 2) if min_usd is not None else None, "offers": n,
            # The cheapest offer as the seller wrote it: the page shows "≈" only for a converted currency
            "min_price": cheapest[p.id].price if p.id in cheapest else None,
            "min_currency": cheapest[p.id].currency.value if p.id in cheapest else None,
            "specs": card_specs(slug, p.specs_json or {}),
        })
    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE, "facets": facets}


def spec_facets(db: Session, query, category: str, spec_filters: dict[str, list]) -> list[dict]:
    """Filters of a category with the number of products per value.

    A count answers "how many products will I see if I tick this too": it takes the search, the price, stock and
    all OTHER selected filters into account (several ticks inside one filter are "or"). Zero counts are hidden.
    """
    rows = [specs or {} for specs in db.scalars(query.with_only_columns(Product.specs_json))]
    by_key = spec_map(category)
    facets = []
    for spec in specs_of(category):
        others = [(by_key[k], v) for k, v in spec_filters.items() if k != spec.key]
        counts: dict = {}
        for specs in rows:
            value = specs.get(spec.key)
            if value is None or not all(_matches(s, specs.get(s.key), v) for s, v in others):
                continue
            counts[value] = counts.get(value, 0) + 1
        selected = spec_filters.get(spec.key, [])
        if not counts and not selected:
            continue
        if spec.kind == NUMBER:
            values = sorted(counts, key=lambda v: -counts[v])
            if not spec.at_least:
                values = values[:NUMBER_FACET_VALUES]
            values = sorted(set(values) | {v for v in selected if v in counts})
        elif spec.kind == YESNO:
            values = [v for v in (True, False) if v in counts]
        elif spec.values:
            values = [v for v in spec.values if v in counts]
        else:
            values = sorted(counts, key=lambda v: (-counts[v], str(v)))
        facets.append({
            "key": spec.key, "kind": spec.kind, "unit": spec.unit, "at_least": spec.at_least,
            "values": [{"value": v, "count": counts[v]} for v in values], "selected": selected,
        })
    return facets


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
            "is_in_stock": o.is_in_stock, "condition": o.condition.value, "note": o.note, "updated_at": o.updated_at,
            "store": {"id": store.id, "name": store.name, "is_verified": store.is_verified, "phone": store.phone,
                      "telegram": store.telegram, "address": store.address, "district": store.district},
            "flags": [{"type": f.type, "level": f.level.value, "reason_key": f.reason_key, "params": f.params,
                       "source": f.source.value} for f in o.fraud_flags if f.status == FlagStatus.active],
        })
    offers.sort(key=price_order if sort == "price" else recommended_order)
    slug = product.category.slug if product.category else "other"
    return {
        "id": product.id, "name": product.normalized_name, "brand": product.brand, "model": product.model,
        "category": product.category.slug if product.category else "other",
        "mxik_code": product.category.mxik_code if product.category else None,
        # Specs in dictionary order, with units and the source: "inferred" = the rule that added a value the
        # seller did not write (the page marks it), None = written by the seller
        "specs": [{"key": s.key, "kind": s.kind, "unit": s.unit, "value": (product.specs_json or {})[s.key],
                   "inferred": (product.specs_json or {}).get(INFERRED, {}).get(s.key)}
                  for s in specs_of(product.category.slug if product.category else "other")
                  if s.key in (product.specs_json or {})],
        # Numbers outside their plausible range (a typo?): not in filters, the page asks to check them
        "suspect": [{"key": k, "kind": NUMBER, "unit": spec_map(slug).get(k).unit if k in spec_map(slug) else None,
                     "value": v} for k, v in (product.specs_json or {}).get(SUSPECT, {}).items()],
        "usd_rate": usd_rate, "offers": offers,
    }
