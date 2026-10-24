"""Starter reference data: a short list of categories with MXIK codes.

Codes were looked up manually on tasnif.soliq.uz (October 2026).
The AI only picks a category slug; the MXIK code always comes from here.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Category

# slug, Russian name, MXIK code (None = no fitting code found yet)
CATEGORIES = [
    ("cpu", "Процессоры", "08542001013000000"),
    ("motherboard", "Материнские платы", "08473003002000000"),
    ("gpu", "Видеокарты", "08473003003000000"),
    ("ram", "Оперативная память", "08523001010000000"),
    ("ssd", "SSD-накопители", "08523002010000000"),
    ("hdd", "Жёсткие диски (HDD)", "08523002999000000"),
    ("flash", "Флешки и карты памяти", "08523001001000000"),
    ("psu", "Блоки питания", "08504003009000000"),
    ("ups", "ИБП", "08504006002000000"),
    ("case", "Корпуса", "08473003005000000"),
    ("cooling", "Охлаждение", "08473003005000000"),
    ("monitor", "Мониторы", "08528002007000000"),
    ("laptop", "Ноутбуки", "08471001001000000"),
    ("aio", "Моноблоки", "08471010009000000"),
    ("desktop", "Системные блоки", "08471010011000000"),
    ("keyboard", "Клавиатуры", "08471012004000000"),
    ("mouse", "Мыши", "08471012005000000"),
    ("headphones", "Наушники", "08518002001000000"),
    ("speakers", "Колонки", "08518003003000000"),
    ("printer", "Принтеры и МФУ", "08443001001000000"),
    ("projector", "Проекторы", "08528003001000000"),
    ("chair", "Игровые кресла", "09401001003000000"),
    ("other", "Прочее", None),
]

CATEGORY_SLUGS = [slug for slug, _, _ in CATEGORIES]


def seed_categories(db: Session) -> None:
    existing = set(db.scalars(select(Category.slug)))
    for slug, name, mxik in CATEGORIES:
        if slug not in existing:
            db.add(Category(slug=slug, name=name, mxik_code=mxik))
    db.commit()
