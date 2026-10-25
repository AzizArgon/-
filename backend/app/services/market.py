"""Price monitoring: market price of a product, offer labels, category price index. All numbers in USD.

Method (docs/history.md, phase 6):
- market price of a product = median of in-stock offer prices from different stores, new and used apart;
- UZS prices are converted by the CBU rate on the date of the price, not today's;
- past market price on a day = median of each store's last known price on that day (offers in stock now);
- price change of a product = change of the median over the same stores at both dates (a store that joined
  later does not move the number), each product compared only with itself;
- category index = geometric mean of these product changes;
- fewer than 2 stores, or too few history points -> "not enough data", no number.
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ArchivePrice, Category, Condition, Offer, PriceHistory, Product, Store
from app.services.exchange import RateBook

HISTORY_DAYS = 90  # daily market price is kept for the last 3 months
PERIODS = {"week": 7, "month": 30, "quarter": 90}
AT_MARKET = 3.0  # within +-3% of the median the offer is "at the market"
MIN_STORES = 2
MIN_CHANGE_DAYS = 14  # less history than two weeks: "not enough data"
MIN_INDEX_PRODUCTS = 3


@dataclass
class MarketData:
    dates: list[date]
    # (product_id, condition) -> market median per day (None = fewer than 2 stores that day)
    series: dict[tuple[int, str], list[float | None]] = field(default_factory=dict)
    # (product_id, condition) -> number of stores with the product in stock now
    stores: dict[tuple[int, str], int] = field(default_factory=dict)
    # (product_id, condition) -> store -> its price per day (None before its first known price)
    per_store: dict[tuple[int, str], dict[int, list[float | None]]] = field(default_factory=dict)
    offer_usd: dict[int, float] = field(default_factory=dict)  # in-stock offer -> its USD price now
    offers: list[tuple[int, int, int, str]] = field(default_factory=list)  # (offer, product, store, condition)
    category: dict[int, str] = field(default_factory=dict)  # product -> category slug
    # Stores whose prices are invented (scripts/seed_demo.py history is_demo): the pages say "includes demo data"
    demo_stores: set[int] = field(default_factory=set)

    def has_demo(self, key) -> bool:
        return any(s in self.demo_stores for s in self.per_store.get(key, {}))

    def now(self, key) -> float | None:
        values = self.series.get(key)
        return values[-1] if values else None

    def on(self, key, days_ago: int) -> float | None:
        values = self.series.get(key)
        return values[-1 - days_ago] if values and days_ago < len(values) else None


_cache: dict = {}


def _cache_key(db: Session, today: date) -> tuple:
    return (
        today,
        db.scalar(select(func.max(PriceHistory.id))), db.scalar(select(func.count(PriceHistory.id))),
        db.scalar(select(func.max(Offer.updated_at))), db.scalar(select(func.count(Offer.id))),
    )


def market_data(db: Session, today: date | None = None) -> MarketData:
    """Daily market prices of all products; cached until offers or history change."""
    today = today or date.today()
    key = _cache_key(db, today)
    if _cache.get("key") != key:
        _cache["key"], _cache["data"] = key, build_market(db, today)
    return _cache["data"]


def build_market(db: Session, today: date) -> MarketData:
    rates = RateBook(db)
    dates = [today - timedelta(days=d) for d in range(HISTORY_DAYS, -1, -1)]
    md = MarketData(dates=dates)
    offers = db.execute(
        select(Offer.id, Offer.product_id, Offer.store_id, Offer.condition, Offer.price, Offer.currency,
               Product.category_id)
        .join(Product).join(Store, Offer.store_id == Store.id).where(Offer.is_in_stock.is_(True), Offer.price.is_not(None),
                                         Store.is_archive.is_(False))
    ).all()
    slugs = dict(db.execute(select(Category.id, Category.slug)).all())
    history: dict[int, list[tuple[date, float]]] = {}
    demo_offers: set[int] = set()
    for offer_id, price, currency, at, is_demo in db.execute(
        select(PriceHistory.offer_id, PriceHistory.price, PriceHistory.currency, PriceHistory.recorded_at,
               PriceHistory.is_demo).order_by(PriceHistory.recorded_at)
    ):
        if is_demo:
            demo_offers.add(offer_id)
        usd = rates.usd(price, currency, at.date())
        if usd is not None:
            history.setdefault(offer_id, []).append((at.date(), usd))

    per_store = md.per_store
    for offer_id, product_id, store_id, condition, price, currency, category_id in offers:
        usd_now = rates.usd(price, currency, today)
        if usd_now is None:
            continue
        cond = condition.value if isinstance(condition, Condition) else condition
        md.offers.append((offer_id, product_id, store_id, cond))
        if offer_id in demo_offers:
            md.demo_stores.add(store_id)
        md.offer_usd[offer_id] = usd_now
        md.category[product_id] = slugs.get(category_id, "other")
        points = history.get(offer_id, [])
        daily: list[float | None] = []
        i, last = 0, None
        for day in dates[:-1]:
            while i < len(points) and points[i][0] <= day:
                last = points[i][1]
                i += 1
            daily.append(last)
        daily.append(usd_now)  # today: the current price, whatever the history says
        per_store.setdefault((product_id, cond), {})[store_id] = daily

    for key, by_store in per_store.items():
        md.stores[key] = len(by_store)
        series = []
        for d in range(len(dates)):
            values = [v[d] for v in by_store.values() if v[d] is not None]
            series.append(median(values) if len(values) >= MIN_STORES else None)
        md.series[key] = series
    return md


def diff_pct(price: float, market: float) -> float:
    return (price - market) / market * 100


def label(diff: float) -> str:
    return "at" if abs(diff) <= AT_MARKET else "below" if diff < 0 else "above"


def ratio(md: MarketData, key, d0: int, d1: int) -> tuple[float, float] | None:
    """Market price on two days over the stores that had a price on both (at least 2), else None."""
    common = [v for v in md.per_store.get(key, {}).values() if v[d0] is not None and v[d1] is not None]
    if len(common) < MIN_STORES:
        return None
    return median(v[d0] for v in common), median(v[d1] for v in common)


def change(md: MarketData, key, days: int = HISTORY_DAYS) -> dict | None:
    """Market price change over the period: from the first day with enough data to today, same stores."""
    last = len(md.dates) - 1
    for d0 in range(max(last - days, 0), last - min(MIN_CHANGE_DAYS, days) + 1):
        pair = ratio(md, key, d0, last)
        if pair:
            v0, v1 = pair
            return {"pct": round(diff_pct(v1, v0), 1), "days": last - d0, "from_usd": round(v0, 2),
                    "to_usd": round(v1, 2)}
    return None


def _archive(db: Session, product_ids: list[int]) -> dict[int, dict]:
    """Old price lists (Gshop): the archive price of a product (median if listed several times)."""
    rows = db.execute(
        select(ArchivePrice.product_id, ArchivePrice.price, ArchivePrice.price_date, Store.name)
        .join(Store).where(ArchivePrice.product_id.in_(product_ids), ArchivePrice.note.is_(None),
                           ArchivePrice.condition == Condition.new)
    ).all()
    rates = RateBook(db)
    result: dict[int, dict] = {}
    for pid, price, day, store in rows:
        item = result.setdefault(pid, {"prices": [], "date": day, "store": store})
        item["prices"].append(price)
    for pid, item in result.items():
        usd = median(item.pop("prices"))
        rate = rates.on(item["date"])
        item.update(price_usd=round(usd, 2), price_uzs=int(round(usd * rate, -3)) if rate else None,
                    date=item["date"].isoformat())
    return result


def product_market(db: Session, product_id: int, today: date | None = None) -> dict:
    """Card of a product: market price, daily chart, change phrase and labels of the offers, per condition."""
    md = market_data(db, today)
    result = {"conditions": {}, "offers": {}}
    for offer_id, pid, _, cond in md.offers:
        if pid != product_id:
            continue
        key = (pid, cond)
        market = md.now(key)
        if cond not in result["conditions"]:
            series = md.series.get(key) or []
            result["conditions"][cond] = {
                "stores": md.stores.get(key, 0),
                "includes_demo": md.has_demo(key),
                "market_usd": round(market, 2) if market is not None else None,
                "change": change(md, key),
                "series": [{"date": d.isoformat(), "usd": round(v, 2)} for d, v in zip(md.dates, series)
                           if v is not None],
            }
        if market is not None:
            diff = diff_pct(md.offer_usd[offer_id], market)
            result["offers"][offer_id] = {"diff_pct": round(diff), "label": label(diff)}
    result["archive"] = _archive(db, [product_id]).get(product_id)
    return result


def category_index(md: MarketData, days: int) -> list[dict]:
    """Per category: how prices of the same new products changed over the period (+ daily index for the chart).

    Each product is compared only with itself (median now / median then), so new expensive models
    do not distort the picture. Ratios are averaged geometrically (Jevons index): +10% and -10% cancel out.
    """
    base = len(md.dates) - 1 - days
    by_category: dict[str, list[tuple[int, str]]] = {}
    for key in md.series:
        if key[1] == Condition.new.value and md.series[key][base] is not None:
            by_category.setdefault(md.category.get(key[0], "other"), []).append(key)
    result = []
    for slug, keys in by_category.items():
        points, n_now = [], 0
        for d in range(base, len(md.dates)):
            pairs = [p for p in (ratio(md, k, base, d) for k in keys) if p]
            logs = [math.log(v1 / v0) for v0, v1 in pairs]
            points.append(round(100 * math.exp(sum(logs) / len(logs)), 2) if len(logs) >= MIN_INDEX_PRODUCTS else None)
            n_now = len(logs)
        if points[-1] is None:
            continue
        result.append({
            "category": slug, "products": n_now, "change_pct": round(points[-1] - 100, 1),
            "series": [{"date": md.dates[base + i].isoformat(), "index": p} for i, p in enumerate(points)],
        })
    return sorted(result, key=lambda r: -r["products"])


def _names(db: Session, product_ids) -> dict[int, dict]:
    rows = db.execute(
        select(Product.id, Product.normalized_name, Category.slug).outerjoin(Product.category)
        .where(Product.id.in_(list(product_ids)))
    ).all()
    return {pid: {"id": pid, "name": name, "category": slug or "other"} for pid, name, slug in rows}


def movers(db: Session, md: MarketData, days: int = HISTORY_DAYS, limit: int = 8) -> dict:
    """Products whose market price grew / fell the most (new condition, enough data only)."""
    changes = []
    for key in md.series:
        if key[1] != Condition.new.value:
            continue
        c = change(md, key, days)
        if c and c["days"] >= days * 0.7:
            changes.append((key[0], c))
    changes.sort(key=lambda x: x[1]["pct"])
    up = [x for x in reversed(changes) if x[1]["pct"] > 0][:limit]
    down = [x for x in changes if x[1]["pct"] < 0][:limit]
    names = _names(db, [pid for pid, _ in up + down])
    pack = lambda items: [{**names[pid], **c, "stores": md.stores[(pid, "new")]} for pid, c in items]  # noqa: E731
    return {"up": pack(up), "down": pack(down)}


def popular_with_archive(db: Session, md: MarketData, limit: int = 10) -> list[dict]:
    """"Then (old price list) -> now" for popular products that are both in an old price list and on the market now."""
    candidates = [pid for (pid, cond), v in md.series.items() if cond == "new" and v[-1] is not None]
    archive = _archive(db, candidates)
    ranked = sorted(archive, key=lambda pid: (-md.stores[(pid, "new")], -md.now((pid, "new"))))[:limit]
    names = _names(db, ranked)
    result = []
    for pid in ranked:
        now = md.now((pid, "new"))
        a = archive[pid]
        result.append({**names[pid], "archive": a, "market_usd": round(now, 2), "stores": md.stores[(pid, "new")],
                       "change_pct": round(diff_pct(now, a["price_usd"]), 1)})
    return result


def seller_position(db: Session, md: MarketData, store_id: int, limit: int = 10) -> dict:
    """The seller's in-stock offers against the market: how many cheaper / at / above, the biggest gaps."""
    counts = {"below": 0, "at": 0, "above": 0}
    rows, no_data = [], 0
    for offer_id, pid, sid, cond in md.offers:
        if sid != store_id:
            continue
        market = md.now((pid, cond))
        if market is None:
            no_data += 1
            continue
        diff = diff_pct(md.offer_usd[offer_id], market)
        counts[label(diff)] += 1
        rows.append((pid, cond, diff, md.offer_usd[offer_id], market))
    rows.sort(key=lambda r: -abs(r[2]))
    names = _names(db, [r[0] for r in rows[:limit]])
    return {
        "counts": counts, "no_data": no_data,
        "gaps": [{**names[pid], "condition": cond, "diff_pct": round(diff), "label": label(diff),
                  "price_usd": round(usd, 2), "market_usd": round(market, 2), "stores": md.stores[(pid, cond)]}
                 for pid, cond, diff, usd, market in rows[:limit]],
    }


def missing_popular(db: Session, md: MarketData, store_id: int, limit: int = 10) -> list[dict]:
    """Popular products other stores sell and this one does not: what the seller could add."""
    own = set(db.scalars(select(Offer.product_id).where(Offer.store_id == store_id)))
    keys = [k for k in md.series if k[1] == "new" and k[0] not in own and md.stores[k] >= MIN_STORES]
    # Popular = sold by more stores; among equals, from the busier categories ("other" last) and cheaper.
    # At most 3 per category, so the hint covers several kinds of goods
    category_size: dict[str, int] = {}
    for k in keys:
        category_size[md.category[k[0]]] = category_size.get(md.category[k[0]], 0) + 1
    category_size["other"] = 0
    keys.sort(key=lambda k: (-md.stores[k], -category_size[md.category[k[0]]], md.now(k) or 0))
    picked, per_category = [], {}
    for k in keys:
        slug = md.category[k[0]]
        if per_category.get(slug, 0) < 3:
            picked.append(k)
            per_category[slug] = per_category.get(slug, 0) + 1
    keys = picked
    names = _names(db, [k[0] for k in keys[:limit]])
    return [{**names[pid], "stores": md.stores[(pid, cond)], "market_usd": round(md.now((pid, cond)), 2)}
            for pid, cond in keys[:limit]]


def index_table(md: MarketData, period: str = "quarter") -> dict:
    """Categories with the index change for a week, a month and 3 months, plus the daily index of one period."""
    by_period = {name: {r["category"]: r for r in category_index(md, days)} for name, days in PERIODS.items()}
    slugs = dict.fromkeys(slug for name in PERIODS for slug in by_period[name])
    rows = [{"category": slug,
             "products": max(by_period[n][slug]["products"] for n in PERIODS if slug in by_period[n]),
             **{n: by_period[n][slug]["change_pct"] if slug in by_period[n] else None for n in PERIODS}}
            for slug in slugs]
    rows.sort(key=lambda r: -r["products"])
    return {"rows": rows, "series": {slug: r["series"] for slug, r in by_period[period].items()}}
