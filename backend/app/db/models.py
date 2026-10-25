import enum
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def str_enum(enum_cls):
    # Store enum values as plain strings so the DB stays readable
    return Enum(enum_cls, native_enum=False, values_callable=lambda e: [m.value for m in e])


class UserRole(str, enum.Enum):
    buyer = "buyer"
    seller = "seller"
    master = "master"
    admin = "admin"


class Condition(str, enum.Enum):
    new = "new"
    used = "used"
    refurbished = "refurbished"
    new_openbox = "new_openbox"  # new, the box was opened
    unknown = "unknown"  # a post did not say: the seller is asked to choose


class Currency(str, enum.Enum):
    USD = "USD"
    UZS = "UZS"


class ImportStatus(str, enum.Enum):
    processing = "processing"
    ready = "ready"
    failed = "failed"
    published = "published"


class FlagLevel(str, enum.Enum):
    info = "info"
    warning = "warning"
    danger = "danger"


class FlagSource(str, enum.Enum):
    rule = "rule"
    ai = "ai"


class FlagStatus(str, enum.Enum):
    active = "active"
    disputed = "disputed"
    dismissed = "dismissed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), default=UserRole.buyer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    stores: Mapped[list["Store"]] = relationship(back_populates="owner")


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    inn_stir: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(32))
    telegram: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(255))
    district: Mapped[str | None] = mapped_column(String(128))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Archive source (an old price list of a shop, e.g. Gshop, Dec 2022): its prices go only to the price history
    is_archive: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    owner: Mapped[User] = relationship(back_populates="stores")
    offers: Mapped[list["Offer"]] = relationship(back_populates="store")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    mxik_code: Mapped[str | None] = mapped_column(String(32), index=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    """Reference product: one card that groups offers from many stores."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), index=True)
    brand: Mapped[str | None] = mapped_column(String(128), index=True)
    model: Mapped[str | None] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    # Lowercased brand+model used to merge the same product from different stores
    match_key: Mapped[str] = mapped_column(String(512), index=True)
    specs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # Set when a seller created the card by hand (not from a price list): to be moderated later
    manual_store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))

    category: Mapped[Category | None] = relationship(back_populates="products")
    offers: Mapped[list["Offer"]] = relationship(back_populates="product")


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    raw_name: Mapped[str] = mapped_column(Text)
    # Price is kept in the seller's original currency
    price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[Currency] = mapped_column(str_enum(Currency), default=Currency.USD)
    is_in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    condition: Mapped[Condition] = mapped_column(str_enum(Condition), default=Condition.new)
    # The seller's own words next to the price: "Подписчикам 13$", "(только в сборках)"
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    product: Mapped[Product] = relationship(back_populates="offers")
    store: Mapped[Store] = relationship(back_populates="offers")
    price_history: Mapped[list["PriceHistory"]] = relationship(back_populates="offer", cascade="all, delete-orphan")
    fraud_flags: Mapped[list["FraudFlag"]] = relationship(back_populates="offer", cascade="all, delete-orphan")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[Currency] = mapped_column(str_enum(Currency), default=Currency.USD)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # Invented history of the demo stores (scripts/seed_demo.py): deleted with one query
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)

    offer: Mapped[Offer] = relationship(back_populates="price_history")


class ArchivePrice(Base):
    """One row of an old price list (archive source): only history, never a current offer or a catalog card.

    Matched to a reference card when the model is the same; unmatched rows stay here as they were.
    """

    __tablename__ = "archive_prices"
    __table_args__ = (UniqueConstraint("store_id", "sheet", "raw_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    sheet: Mapped[str] = mapped_column(String(128))
    section: Mapped[str | None] = mapped_column(String(255))
    raw_name: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[Currency] = mapped_column(str_enum(Currency), default=Currency.USD)
    condition: Mapped[Condition] = mapped_column(str_enum(Condition), default=Condition.new)
    # A note that makes the price not comparable ("only in a PC build")
    note: Mapped[str | None] = mapped_column(String(64))
    price_date: Mapped[date] = mapped_column(Date)


class FraudFlag(Base):
    __tablename__ = "fraud_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    level: Mapped[FlagLevel] = mapped_column(str_enum(FlagLevel))
    # Translation key (flags.reason.<key> in the frontend) + its parameters: texts stay out of the DB
    reason_key: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[FlagSource] = mapped_column(str_enum(FlagSource))
    status: Mapped[FlagStatus] = mapped_column(str_enum(FlagStatus), default=FlagStatus.active)

    offer: Mapped[Offer] = relationship(back_populates="fraud_flags")


class PriceImport(Base):
    """One uploaded price list: parsed rows wait here until the seller publishes them."""

    __tablename__ = "price_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    # Where the rows came from: a price list file, a pasted text (Telegram post) or one offer added by hand.
    # Only a file is the full price list: missing items become "out of stock" only after a file
    source: Mapped[str] = mapped_column(String(16), default="file", server_default="file")
    # Pasted text as the seller sent it: to see later why a post was parsed the way it was
    text: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[Currency] = mapped_column(str_enum(Currency))
    status: Mapped[ImportStatus] = mapped_column(str_enum(ImportStatus), default=ImportStatus.processing)
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    chunks_done: Mapped[int] = mapped_column(Integer, default=0)
    rows_json: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    # How the rows were parsed: counts by source, AI requests, seconds (for the parser experiment)
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParseCache(Base):
    """Already parsed names: the same row is never sent to the AI twice.

    Seller corrections from the preview overwrite AI answers (source = "seller").
    """

    __tablename__ = "parse_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExchangeRate(Base):
    """Official CBU rate: how many UZS one unit of the currency costs on a given day."""

    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("currency", "rate_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    rate: Mapped[float] = mapped_column(Float)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    # When we last asked cbu.uz: on weekends rate_date lags behind, so it can't tell freshness
    fetched_on: Mapped[date] = mapped_column(Date, default=date.today)
