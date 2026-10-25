from datetime import date, datetime, time, timedelta, timezone

from app.db.models import (
    ArchivePrice, Category, Condition, Currency, ExchangeRate, Offer, PriceHistory, Product, Store, User,
)
from app.services import market
from app.services.archive import Matcher
from app.services.exchange import RateBook
from app.services.sheet_blocks import block_items, find_blocks
from tests.test_publish import db  # noqa: F401  (db is a fixture)

TODAY = date(2026, 10, 25)


def _stores(db, n):
    stores = [Store(owner=User(email=f"s{i}@example.com", password_hash="x"), name=f"S{i}") for i in range(n)]
    db.add_all(stores)
    db.commit()
    return stores


def _product(db, name, slug="ram"):
    p = Product(category=db.query(Category).filter_by(slug=slug).one(), brand=name.split()[0], normalized_name=name,
                match_key=name.lower())
    db.add(p)
    db.commit()
    return p


def _offer(db, product, store, price, history=(), currency=Currency.USD, condition=Condition.new):
    """history: (days ago, price) pairs before today's price."""
    o = Offer(product=product, store=store, raw_name=product.normalized_name, price=price, currency=currency,
              condition=condition)
    for ago, old in [*history, (0, price)]:
        at = datetime.combine(TODAY - timedelta(days=ago), time(12), tzinfo=timezone.utc)
        o.price_history.append(PriceHistory(price=old, currency=currency, recorded_at=at))
    db.add(o)
    db.commit()
    return o


def test_offer_labels_against_median_and_not_enough_data_for_one_store(db):
    s = _stores(db, 3)
    ram, lonely = _product(db, "Kingston Fury 16GB"), _product(db, "Lexar Ares 32GB")
    cheap, mid, dear = _offer(db, ram, s[0], 92), _offer(db, ram, s[1], 100), _offer(db, ram, s[2], 112)
    _offer(db, lonely, s[0], 80)
    # A used one is a market of its own: not mixed into the new median
    _offer(db, ram, s[0], 40, condition=Condition.used)
    md = market.build_market(db, TODAY)
    assert md.now((ram.id, "new")) == 100  # median, not the mean
    labels = {o: (market.label(market.diff_pct(md.offer_usd[o], 100)), round(market.diff_pct(md.offer_usd[o], 100)))
              for o in (cheap.id, mid.id, dear.id)}
    assert labels == {cheap.id: ("below", -8), mid.id: ("at", 0), dear.id: ("above", 12)}
    assert md.now((lonely.id, "new")) is None and md.stores[(lonely.id, "new")] == 1
    assert md.now((ram.id, "used")) is None


def test_uzs_history_converted_by_the_rate_of_its_own_day(db):
    db.add_all([ExchangeRate(currency="USD", rate=10_000, rate_date=TODAY - timedelta(days=60)),
                ExchangeRate(currency="USD", rate=12_500, rate_date=TODAY - timedelta(days=1))])
    s = _stores(db, 2)
    p = _product(db, "Kingston Fury 16GB")
    _offer(db, p, s[0], 100, history=[(60, 100)])
    # 1 000 000 sum was $100 two months ago, today 1 250 000 sum is the same $100: no change in USD
    _offer(db, p, s[1], 1_250_000, history=[(60, 1_000_000)], currency=Currency.UZS)
    md = market.build_market(db, TODAY)
    assert md.series[(p.id, "new")][-61] == 100 and md.now((p.id, "new")) == 100
    assert market.change(md, (p.id, "new"))["pct"] == 0
    assert RateBook(db).on(TODAY - timedelta(days=30)) == 10_000  # the last rate set before that day


def test_change_compares_same_stores_and_needs_enough_history(db):
    s = _stores(db, 3)
    p, fresh = _product(db, "Kingston Fury 16GB"), _product(db, "Lexar Ares 32GB")
    _offer(db, p, s[0], 120, history=[(90, 100)])
    _offer(db, p, s[1], 132, history=[(90, 110)])
    _offer(db, p, s[2], 300)  # joined today with a high price: does not move the change
    _offer(db, fresh, s[0], 50, history=[(5, 45)])
    _offer(db, fresh, s[1], 52, history=[(5, 47)])
    md = market.build_market(db, TODAY)
    c = market.change(md, (p.id, "new"))
    assert c == {"pct": 20.0, "days": 90, "from_usd": 105, "to_usd": 126}
    assert market.change(md, (fresh.id, "new")) is None  # 5 days of history only


def test_category_index_is_geometric_mean_of_product_changes(db):
    s = _stores(db, 2)
    ups = [_product(db, f"Kingston Fury {n}GB") for n in (8, 16, 32)]
    for p, (old, new) in zip(ups, [(100, 125), (100, 80), (100, 100)]):
        _offer(db, p, s[0], new, history=[(90, old)])
        _offer(db, p, s[1], new, history=[(90, old)])
    rows = market.category_index(market.build_market(db, TODAY), 90)
    # +25% and -20% cancel out geometrically: 1.25 * 0.8 * 1 = 1
    assert (rows[0]["category"], rows[0]["products"], rows[0]["change_pct"]) == ("ram", 3, 0)
    # Fewer than 3 products: no index
    db.delete(ups[0].offers[0])
    db.commit()
    assert market.category_index(market.build_market(db, TODAY), 90) == []


def test_seller_position_and_missing_popular(db):
    s = _stores(db, 3)
    a, b, c = (_product(db, f"Kingston Fury {n}GB") for n in (8, 16, 32))
    for product, store, price in [(a, 0, 90), (a, 1, 100), (a, 2, 110), (b, 0, 100), (b, 1, 100), (c, 1, 60),
                                  (c, 2, 60)]:
        _offer(db, product, s[store], price)
    md = market.build_market(db, TODAY)
    pos = market.seller_position(db, md, s[0].id)
    assert pos["counts"] == {"below": 1, "at": 1, "above": 0}
    assert pos["gaps"][0]["id"] == a.id and pos["gaps"][0]["diff_pct"] == -10
    assert [m["id"] for m in market.missing_popular(db, md, s[0].id)] == [c.id]


def test_sheet_blocks_side_by_side_with_sections_notices_and_build_only_notes():
    rows = [
        ["Оплата производится только в национальной валюте!!!", None, None, None],
        ["Наименование", None, "", None],
        ["ПРОЦЕССОРЫ INTEL", None, "КОРПУСА LIAN LI", None],
        ["Intel Core i5-12400F 6C\\12T", 155, "Lian Li LANCOOL 205 Black", 120],
        ["Intel Core i3-10105", None, "Corsair SF600 SFX(Только в сборках)", 90],
        ["MSI PRO B660M-E LGA 1700 DDR4", None, "ПЕРИФЕРИЯ JBL", None],
        ["ПРОЦЕССОРЫ AMD", None, "НАУШНИКИ", None],
        ["AMD Ryzen 5 5600X", "180", "JBL Tune 125 BT", 36],
    ]
    assert find_blocks(rows) == [(0, 1), (2, 3)]
    items, notices = block_items(rows)
    assert notices == ["Оплата производится только в национальной валюте!!!"]
    assert [(i.block, i.section, i.name, i.price, i.note) for i in items] == [
        (0, "ПРОЦЕССОРЫ INTEL", "Intel Core i5-12400F 6C\\12T", 155, None),
        (0, "ПРОЦЕССОРЫ INTEL", "Intel Core i3-10105", None, None),
        (0, "ПРОЦЕССОРЫ INTEL", "MSI PRO B660M-E LGA 1700 DDR4", None, None),  # capitals, but a model code
        (0, "ПРОЦЕССОРЫ AMD", "AMD Ryzen 5 5600X", 180, None),
        (1, "КОРПУСА LIAN LI", "Lian Li LANCOOL 205 Black", 120, None),
        (1, "КОРПУСА LIAN LI", "Corsair SF600 SFX", 90, "only_in_builds"),
        (1, "ПЕРИФЕРИЯ JBL / НАУШНИКИ", "JBL Tune 125 BT", 36, None),
    ]


def test_archive_matcher_by_model_codes(db):
    i5 = _product(db, "Intel Core i5-12400F, 2.7 GHz, 18MB, OEM, LGA1700", "cpu")
    _product(db, "Intel Core i5-12400, 2.7 GHz, 18MB, OEM, LGA1700", "cpu")
    ssd = _product(db, "Samsung 980 1TB", "ssd")
    _product(db, "Lian Li LANCOOL 205 MESH Black", "case")
    jonsbo = _product(db, "Jonsbo D40 Silver", "case")
    m = Matcher(db)
    assert m.match("Intel Core i5-12400F 6C\\12T 2.5-4.4 GHz, 20M LGA1700") == i5
    assert m.match("Samsung 980 1TB M.2 NVMe V-NAND") == ssd
    assert m.match("Samsung 980 PRO 1TB Heatsink") is None  # a different model
    assert m.match("Samsung 980 250GB M.2 NVMe") is None  # other capacity
    assert m.match("Lian Li LANCOOL 205 Black") is None  # "MESH" is part of the card's model
    assert m.match("JONSBO D40 Silver Midi-Tower\\ATX") == jonsbo
    assert m.match("JONSBO D40 Black Midi-Tower\\ATX") is None  # other colour


def test_product_market_has_archive_point_without_build_only_prices(db):
    s = _stores(db, 2)
    p = _product(db, "Intel Core i5-12400F", "cpu")
    _offer(db, p, s[0], 100)
    _offer(db, p, s[1], 110)
    archive = Store(owner=User(email="archive-gshop@example.com", password_hash="x"), name="Gshop", is_archive=True)
    db.add(archive)
    db.flush()
    db.add_all([ArchivePrice(store_id=archive.id, product_id=p.id, sheet="1", raw_name="i5 12400F", price=155,
                             price_date=date(2022, 12, 8)),
                ArchivePrice(store_id=archive.id, product_id=p.id, sheet="1", raw_name="i5 12400F build", price=99,
                             price_date=date(2022, 12, 8), note="only_in_builds")])
    db.commit()
    market._cache.clear()
    result = market.product_market(db, p.id, TODAY)
    assert result["archive"]["price_usd"] == 155 and result["archive"]["store"] == "Gshop"
    assert result["conditions"]["new"]["market_usd"] == 105
    assert result["conditions"]["new"]["change"] is None  # history of one day only
