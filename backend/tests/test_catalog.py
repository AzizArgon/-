from datetime import timedelta

from sqlalchemy import select

from app.db.models import Currency, FlagLevel, FlagSource, FraudFlag, Offer, Product, utcnow
from app.services.catalog import make_match_key, product_card, rebuild_match_keys, search_products
from app.services.exchange import to_uzs
from app.services.importer import publish_import
from tests.test_publish import _import, _row, _store, db  # noqa: F401  (db is a fixture)


def test_match_key_ignores_type_words_case_order_and_spaces():
    rule = make_match_key("cpu", "Intel Core i5-12400F OEM", "Intel")
    ai = make_match_key("cpu", "Процессор Intel Core i5-12400F OEM", "Intel")
    assert rule == ai
    assert make_match_key("ram", "Kingston DDR5 16 GB") == make_match_key("ram", "kingston 16GB ddr5")
    assert make_match_key("chair", "Игровое кресло MSI MAG CH120 X") == make_match_key("chair", "MSI MAG CH120 X")


def test_match_key_keeps_meaningful_words():
    wired = make_match_key("keyboard", "Механическая проводная клавиатура AULA F75 White")
    wireless = make_match_key("keyboard", "Механическая беспроводная клавиатура AULA F75 White")
    assert wired != wireless
    assert make_match_key("cpu", "Intel Core i5-12400F") != make_match_key("cpu", "Intel Core i5-12400")
    assert make_match_key("gpu", "RTX 4060") != make_match_key("ram", "RTX 4060")  # category is part of the key


def test_rule_and_ai_names_from_two_stores_share_one_card(db):
    a, b = _store(db, "a@example.com"), _store(db, "b@example.com")
    cpu = lambda name: {**_row(1, name, 120), "category": "cpu", "brand": "Intel"}  # noqa: E731
    publish_import(db, _import(db, a), a, [cpu("Intel Core i5-12400F OEM")])
    publish_import(db, _import(db, b), b, [cpu("Процессор Intel Core i5-12400F OEM")])
    assert len(db.scalars(select(Product)).all()) == 1


def test_rebuild_merges_old_cards(db):
    store = _store(db, "a@example.com")
    # Two cards made by the old rule (full name with the type word -> different keys)
    for name, raw in (("Kingston DDR5 16GB", "k1"), ("Оперативная память Kingston DDR5 16GB", "k2")):
        db.add(Offer(store=store, raw_name=raw, price=50,
                     product=Product(normalized_name=name, match_key=f"old:{raw}", brand="Kingston")))
    db.commit()
    assert rebuild_match_keys(db) == {"products": 1, "merged": 1}
    assert len(db.scalars(select(Product)).one().offers) == 2


def test_search_filters_and_stock(db):
    a, b = _store(db, "a@example.com"), _store(db, "b@example.com")
    publish_import(db, _import(db, a), a, [
        {**_row(1, "Intel Core i5-12400F OEM", 120), "category": "cpu"},
        _row(2, "Kingston DDR5 16GB", 50), {**_row(3, "Lexar DDR4 8GB", 30), "is_in_stock": False},
    ])
    publish_import(db, _import(db, b, Currency.UZS), b, [_row(1, "Kingston DDR5 16GB", 590_000)])
    names = lambda r: [i["name"] for i in r["items"]]  # noqa: E731

    # Russian category word + Latin model: "Процессоры" matches "процессор"
    assert names(search_products(db, 12_000, "процессор i5")) == ["Intel Core i5-12400F OEM"]
    assert names(search_products(db, 12_000, category="ram")) == ["Kingston DDR5 16GB"]  # Lexar is out of stock
    assert len(search_products(db, 12_000, category="ram", in_stock=False)["items"]) == 2
    kingston = search_products(db, 12_000, "kingston")["items"][0]
    assert kingston["offers"] == 2 and kingston["min_price_usd"] == 49.17  # 590 000 UZS < $50
    assert (kingston["min_price"], kingston["min_currency"]) == (590_000, "UZS")  # as the seller wrote it
    assert names(search_products(db, 12_000, price_min=100)) == ["Intel Core i5-12400F OEM"]
    assert names(search_products(db, 12_000, price_max=60)) == ["Kingston DDR5 16GB"]


def test_converted_sums_are_rounded_to_thousands():
    assert to_uzs(113.4, Currency.USD, 11_839) == 1_343_000
    assert to_uzs(1_342_542, Currency.UZS, 11_839) == 1_342_542  # the seller's own price is kept as is


def test_recommended_order_and_price_order(db):
    stores = [_store(db, f"{n}@example.com") for n in ("cheap", "verified", "stale", "gone")]
    stores[1].is_verified = True
    for store, price in zip(stores, (40, 55, 45, 30)):
        publish_import(db, _import(db, store), store, [_row(1, "Kingston DDR5 16GB", price)])
    offers = {o.store.name: o for o in db.scalars(select(Offer))}
    offers["stale@example.com"].updated_at = utcnow() - timedelta(days=60)
    offers["gone@example.com"].is_in_stock = False
    offers["cheap@example.com"].fraud_flags.append(FraudFlag(
        type="used_as_new", level=FlagLevel.danger, reason_key="used_words", params={}, source=FlagSource.rule))
    db.commit()
    product_id = offers["cheap@example.com"].product_id

    card = product_card(db, product_id, 12_000)
    order = [o["store"]["name"].split("@")[0] for o in card["offers"]]
    # Verified first; a serious flag and an old price list go lower; out of stock is always last
    assert order == ["verified", "stale", "cheap", "gone"]
    assert card["offers"][2]["flags"][0]["reason_key"] == "used_words"
    assert card["offers"][0]["price_uzs"] == 55 * 12_000

    by_price = [o["store"]["name"].split("@")[0] for o in product_card(db, product_id, 12_000, "price")["offers"]]
    assert by_price == ["cheap", "stale", "verified", "gone"]
