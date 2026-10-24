import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
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

    owner: Mapped[User] = relationship(back_populates="stores")
    offers: Mapped[list["Offer"]] = relationship(back_populates="store")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
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
    specs_json: Mapped[dict] = mapped_column(JSON, default=dict)

    category: Mapped[Category | None] = relationship(back_populates="products")
    offers: Mapped[list["Offer"]] = relationship(back_populates="product")


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    raw_name: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    is_in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    condition: Mapped[Condition] = mapped_column(str_enum(Condition), default=Condition.new)
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
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    offer: Mapped[Offer] = relationship(back_populates="price_history")


class FraudFlag(Base):
    __tablename__ = "fraud_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    level: Mapped[FlagLevel] = mapped_column(str_enum(FlagLevel))
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[FlagSource] = mapped_column(str_enum(FlagSource))
    status: Mapped[FlagStatus] = mapped_column(str_enum(FlagStatus), default=FlagStatus.active)

    offer: Mapped[Offer] = relationship(back_populates="fraud_flags")
