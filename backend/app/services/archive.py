"""Archive price lists (Gshop, Dec 2022): loaded only into history, matched to reference cards by the model.

Old rows are written in another style than our cards ("Intel Core i5-12400F 6C\\12T 2.5-4.4 GHz, ..." vs card
"Intel Core i5-12400F, 2.7 GHz, 18MB, OEM, LGA1700"), so the full match key never coincides. The model
signature is used instead: brand + model codes (words with digits: "i5", "12400f"), units and sockets dropped.
A card matches when all its model words are in the old row (its codes include the main code of the row),
model qualifiers right after the code agree ("980 PRO" is not "980"), capacities and colours do not contradict. Unmatched rows stay in the archive and never create cards.
"""

import re
import secrets
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import ArchivePrice, Condition, Currency, Offer, Product, Store, User, UserRole
from app.services.sheet_blocks import block_items

_LOOKALIKES = str.maketrans("АВЕКМНОРСТХаеорсхукКС", "ABEKMHOPCTXaeopcxykKC")
_SUFFIX = re.compile(r"(\d)\s+(ti|super|xtx|xt|gre|x3d)\b")
_NOT_CODE = re.compile(
    r"^(\d+(\.\d+)?(gb|tb|mb|kb|ghz|mhz|hz|w|mm|cm|ms|c|t|bit|bits|rpm|mah|fps|p|dpi|db|v|nm|ma|m)"
    r"|\d{3,4}x\d{3,4}|\dx(fan)?|x\d+|lga\d+|am\d|ddr\d\w*|gddr\d\w*|pcie?\d\w*|usb\d\w*|wifi\d\w*"
    r"|hdmi\d\w*|dp\d\w*|bluetooth\d\w*|rgb\d*|\d+(cores?|threads?))$"
)
_QUALIFIERS = {"pro", "plus", "evo", "ti", "super", "xt", "xtx", "mini", "max", "ultra", "elite", "lite", "i", "s",
               "se", "oc", "x", "mesh", "rgb", "argb", "snow", "air"}
_CAPACITY = re.compile(r"^\d+(gb|tb)$")
_SKIP_WORDS = {"oem", "box", "tray", "edition"}
_COLORS = {"black", "white", "silver", "grey", "gray", "red", "blue", "pink", "green", "yellow", "orange", "purple"}


def _tokens(text: str) -> list[str]:
    text = _SUFFIX.sub(r"\1\2", text.translate(_LOOKALIKES).lower().replace("ё", "е"))
    return re.findall(r"[a-zа-я0-9]+(?:\.\d+)?", text)


def codes(text: str) -> list[str]:
    """Model codes in order: words with a digit that are not units, sockets or memory types."""
    return [t for t in _tokens(text) if re.search(r"\d", t) and not _NOT_CODE.match(t)]


def _main_code(name: str) -> str | None:
    """The first strong code of the row's name part (before the specs after "\\"): "12400f", "205", "4080"."""
    return next((c for c in codes(name.split("\\")[0]) if len(c) >= 3), None)


def _model_words(name: str, brand: str) -> set[str]:
    """Words a card's model is made of: no type words ("Корпус"), units, sockets, colours or the brand."""
    from app.services.catalog import TYPE_WORDS

    skip = TYPE_WORDS | _COLORS | _SKIP_WORDS | set(_tokens(brand))
    return {t for t in _tokens(name) if t not in skip and not _NOT_CODE.match(t) and not re.search("[а-я]", t)}


class Matcher:
    def __init__(self, db: Session):
        self.by_code: dict[str, list[tuple[Product, set[str], set[str]]]] = {}
        # Several cards fit equally ("Intel Core i5-12400F" made by hand for a used one): the one sold new by more stores
        self.offers = dict(db.execute(
            select(Offer.product_id, func.count(Offer.id)).where(Offer.condition == Condition.new).group_by(Offer.product_id)
        ).all())
        for p in db.scalars(select(Product).where(Product.brand.is_not(None))):
            name = p.normalized_name.split(",")[0]  # specs after the first comma vary from store to store
            words = _model_words(name, p.brand)
            entry = (p, words, set(_tokens(name)))
            for c in set(codes(name)) & words:
                self.by_code.setdefault(c, []).append(entry)

    def match(self, name: str) -> Product | None:
        main = _main_code(name)
        if main is None:
            return None
        text = name.translate(_LOOKALIKES).lower()
        tokens = set(_tokens(name))
        colors = tokens & _COLORS
        capacity = {t for t in tokens if _CAPACITY.match(t)}
        head = _tokens(name.split("\\")[0])
        after = head[head.index(main) + 1:head.index(main) + 3] if main in head else []
        qualifiers = {t for t in after if t in _QUALIFIERS}
        best, best_score = None, None
        for p, model, words in self.by_code.get(main, []):
            if not model <= tokens or not qualifiers <= model or p.brand.lower().translate(_LOOKALIKES) not in text:
                continue
            if colors and words & _COLORS and not colors & words:
                continue  # "Black" card for a "White" row
            card_capacity = {t for t in words if _CAPACITY.match(t)}
            if capacity and card_capacity and not capacity & card_capacity:
                continue  # 250GB row, 1TB card
            score = (len(model), self.offers.get(p.id, 0), len(words & tokens) / len(words | tokens), -p.id)
            if best_score is None or score > best_score:
                best, best_score = p, score
        return best


def archive_store(db: Session, name: str) -> Store:
    """The archive source is a store marked is_archive; its user cannot log in (random password)."""
    email = f"archive-{re.sub(r'[^a-z0-9]+', '-', name.lower())}@example.com"
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, password_hash=hash_password(secrets.token_urlsafe(24)), role=UserRole.seller)
        db.add(user)
        db.flush()
    store = db.scalar(select(Store).where(Store.user_id == user.id))
    if store is None:
        store = Store(owner=user, name=name)
        db.add(store)
    store.is_archive = True
    db.flush()
    return store


def load_archive(db: Session, path: Path, store_name: str, price_date: date,
                 currency: Currency = Currency.USD) -> dict:
    """Loads all priced rows of all sheets into archive_prices (re-run updates them, no duplicates)."""
    import openpyxl

    store = archive_store(db, store_name)
    matcher = Matcher(db)
    existing = {(a.sheet, a.raw_name): a for a in db.scalars(
        select(ArchivePrice).where(ArchivePrice.store_id == store.id))}
    stats = {"rows": 0, "priced": 0, "matched": 0, "only_in_builds": 0, "notices": []}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        items, notices = block_items([list(r) for r in ws.iter_rows(values_only=True)])
        stats["notices"] += notices
        for it in items:
            stats["rows"] += 1
            if it.price is None:
                continue  # no price = not on sale then: nothing to remember
            stats["priced"] += 1
            row = existing.get((ws.title, it.name))
            if row is None:
                row = ArchivePrice(store_id=store.id, sheet=ws.title, raw_name=it.name)
                db.add(row)
                existing[(ws.title, it.name)] = row
            product = matcher.match(it.name)
            row.section, row.price, row.currency, row.note = it.section, it.price, currency, it.note
            row.condition, row.price_date = Condition.new, price_date
            row.product_id = product.id if product else None
            stats["matched"] += product is not None
            stats["only_in_builds"] += it.note is not None
    db.commit()
    return stats
