from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StoreIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    inn_stir: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=32)
    telegram: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=128)


class StoreOut(StoreIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_verified: bool


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    mxik_code: str | None


class FlagOut(BaseModel):
    """Anti-Fraud flag: the soft text is the frontend translation flags.reason.<reason_key> with params."""

    type: str
    level: Literal["info", "warning", "danger"]
    reason_key: str
    params: dict[str, str | int | float] = {}
    source: Literal["rule", "ai"]


class PreviewRow(BaseModel):
    """One parsed row in the editable preview table."""

    row: int
    raw_name: str
    section: str = ""
    category: str
    brand: str | None = None
    model: str | None = None
    name: str = Field(min_length=1, max_length=512)
    price: float | None = Field(default=None, ge=0)
    condition: Literal["new", "used", "refurbished"] = "new"
    # Dictionary values ("DDR5", 16, true) + "_inferred": {key: rule} for values added by inference rules
    specs: dict[str, bool | int | float | str | dict[str, str]] = {}
    # AI specs not found in the row text: shown to the seller, never saved to the product
    specs_guess: dict[str, str] = {}
    is_in_stock: bool = True
    # Anti-Fraud: AI hints (types only) and the resulting flags
    ai_risks: list[str] = []
    flags: list[FlagOut] = []
    # Filled by the parser: where the row came from and how to find it in the parse cache
    sheet: str = ""
    article: str | None = None
    ai_text: str | None = None
    cache_key: str | None = None
    source: Literal["cache", "rule", "ai", "failed", "seller"] = "ai"


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    source: str = "file"  # file / text / manual
    currency: str
    status: str
    chunks_total: int
    chunks_done: int
    error: str | None
    stats: dict = Field(default_factory=dict, validation_alias="stats_json")
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite drops the timezone; we always store UTC
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class ImportDetail(ImportOut):
    rows: list[PreviewRow] = Field(validation_alias="rows_json")


class PublishRequest(BaseModel):
    rows: list[PreviewRow]


class CheckResult(BaseModel):
    flags: list[list[FlagOut]]


class TextImportIn(BaseModel):
    """A pasted post (e.g. from Telegram); rows without a currency get `currency`."""

    text: str = Field(min_length=3, max_length=20000)
    currency: Literal["USD", "UZS"]


class OfferIn(BaseModel):
    product_id: int
    price: float = Field(gt=0)
    currency: Literal["USD", "UZS"]
    condition: Literal["new", "used", "refurbished"] = "new"
    is_in_stock: bool = True
    # The store already has an offer on this card: False -> 409 with it, True -> update its price
    replace: bool = False


class ProductIn(BaseModel):
    category: str
    brand: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=512)
    specs: dict[str, bool | int | float | str | None] = {}


class PublishResult(BaseModel):
    created: int
    updated: int
    out_of_stock: int


class RateOut(BaseModel):
    currency: str
    rate: float
    rate_date: date
