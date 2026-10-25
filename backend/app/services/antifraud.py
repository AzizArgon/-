"""Anti-Fraud: deterministic rules first, AI hints second.

Rules look only at what the seller really wrote: the original row, the article and the specs
confirmed by the row text. AI guesses (specs_guess) never take part. Wording is soft on purpose:
a flag is a reason to ask the seller, not an accusation.

Every flag: {"type", "level" (info / warning / danger), "reason", "source" (rule / ai)}.
"""

import re
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Currency, FlagLevel, FlagSource, FlagStatus, FraudFlag, Offer, Product
from app.services.exchange import to_usd

TYPES = ("spec_mismatch", "server_hardware", "mining", "used_as_new", "fake_capacity", "noname_psu", "price_below_market")
LEVEL_ORDER = {"info": 0, "warning": 1, "danger": 2}

# AI only names the type; the wording is ours, so it stays soft and the same every time
AI_REASONS = {
    "spec_mismatch": "ИИ заметил, что характеристики в строке, возможно, противоречат друг другу. Уточните у продавца.",
    "server_hardware": "ИИ заметил признаки серверного железа. Уточните у продавца, подойдёт ли оно для обычного ПК.",
    "mining": "ИИ заметил признаки того, что товар мог использоваться для майнинга. Уточните у продавца.",
    "used_as_new": "ИИ заметил признаки б/у или восстановленного товара. Уточните состояние у продавца.",
    "fake_capacity": "ИИ заметил, что заявленный объём, возможно, не соответствует реальному. Уточните у продавца.",
    "noname_psu": "ИИ заметил, что блок питания, возможно, без известного бренда. Уточните у продавца.",
}

# Market price check: at least this many offers from other stores, prices in USD
MARKET_MIN_OFFERS = 2
MARKET_WARNING = 0.6
MARKET_DANGER = 0.4

_DDR = re.compile(r"(?<![a-z])(?:ddr)\s?([2-5])(?!\d)", re.I)  # GDDR6 / LPDDR5 are not matched
_DDR_COMBO = re.compile(r"ddr\s?[2-5]\s*(?:/|\\|и|and|or|или)\s*ddr\s?[2-5]", re.I)
_GPU_MODEL = re.compile(r"\b(GTX|RTX)\s*-?\s*(\d{3,4})\b", re.I)
_XEON = re.compile(r"\bxeon\b", re.I)
_ECC = re.compile(r"\becc\b|\brdimm\b|\blrdimm\b|\bregistered\b|\breg\b", re.I)
_SERVER_SOCKET = re.compile(r"\blga\s?-?(2011(?:-?v?3)?|2066|3647|1356|1366)\b", re.I)
_X99 = re.compile(r"\b(x99|x79|c612)\b", re.I)
_CHINA_BOARD = re.compile(r"huananzhi|machinist|jingsha|kllisre|atermiter|qiyida|soyo|zsus|jginyue", re.I)
_KNOWN_BOARD = re.compile(r"\b(asus|msi|gigabyte|asrock|biostar|intel|supermicro)\b", re.I)
_MINING = re.compile(r"майнинг|mining|майнер|\bminer\b|\bcmp\s?\d{2,3}\s?hx\b|\bp10[246]\b|\bp104-100\b", re.I)
_MINING_GPU = re.compile(r"\brx\s?(470|480|570|580|5700)\b", re.I)
_MINING_PSU = re.compile(r"для\s+майнинга|mining|\bdps-\d{3,4}|серверн", re.I)
_USED = re.compile(r"б/у|\bб\.у\b|\bбу\b|\bused\b|восстановленн|refurb|\bref\b|уценк|после\s+ремонт|ex-?demo|витринн", re.I)
_CAPACITY = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(tb|тб|gb|гб)\b", re.I)
_FLASH = re.compile(r"флешк|флеш-?накопит|flash\s?drive|usb[\s-]?flash|usb[\s-]?накопит|micro\s?sd|\bsd\s?card|карта\s+памяти", re.I)
_NONAME = re.compile(r"no\s?-?name|ноунейм|без\s+бренда|noname", re.I)
_WATTS = re.compile(r"(\d{3,4})\s*(?:w|вт)\b", re.I)


def _flag(type_: str, level: str, reason: str, source: str = "rule") -> dict:
    return {"type": type_, "level": level, "reason": reason, "source": source}


def _text(row: dict) -> str:
    """What the seller wrote: original row, article and specs confirmed by the row. No AI guesses."""
    specs = " ".join(f"{k} {v}" for k, v in (row.get("specs") or {}).items())
    return " ".join(filter(None, [row.get("raw_name"), row.get("article"), specs]))


def _capacity_gb(text: str) -> float | None:
    sizes = [float(n.replace(",", ".")) * (1024 if u.lower() in ("tb", "тб") else 1) for n, u in _CAPACITY.findall(text)]
    return max(sizes) if sizes else None


def _usd(row: dict, usd_rate: float | None) -> float | None:
    return to_usd(row.get("price"), Currency(row.get("currency") or "USD"), usd_rate)


def _spec_mismatch(text: str) -> list[dict]:
    flags = []
    gens = sorted({g for g in _DDR.findall(text)})
    if len(gens) > 1 and not _DDR_COMBO.search(text):
        names = " и ".join(f"DDR{g}" for g in gens)
        flags.append(_flag(
            "spec_mismatch", "warning",
            f"В описании одновременно указаны {names}. Возможно, это ошибка в прайсе — уточните у продавца "
            "тип памяти: модули разных поколений не взаимозаменяемы.",
        ))
    for line, num in _GPU_MODEL.findall(text):
        n = int(num)
        line = line.upper()
        # GTX ended with the 16xx series; RTX started with 20xx
        if (line == "GTX" and n >= 2000) or (line == "RTX" and n < 2000):
            other = "RTX" if line == "GTX" else "GTX"
            flags.append(_flag(
                "spec_mismatch", "warning",
                f"Видеокарты {line} {num} не существует (возможно, имелась в виду {other} {num}). "
                "Уточните у продавца точную модель.",
            ))
            break
    return flags


def _server_hardware(text: str, category: str) -> list[dict]:
    xeon, china, x99 = _XEON.search(text), _CHINA_BOARD.search(text), _X99.search(text)
    parts = []
    if xeon:
        parts.append("процессор Xeon — серверный, такие часто продаются б/у после работы в дата-центрах")
    if china or (x99 and not _KNOWN_BOARD.search(text)):
        parts.append("плата на чипсете X99/X79 — обычно китайская сборка под серверные процессоры, гарантия и BIOS бывают ненадёжны")
    if category in ("ram", "other") and _ECC.search(text):
        parts.append("память ECC/REG — серверная, в обычных платах может не заработать")
    elif not parts and category in ("cpu", "motherboard") and _SERVER_SOCKET.search(text):
        parts.append(f"сокет LGA{_SERVER_SOCKET.search(text).group(1)} — серверная/старая платформа")
    if not parts:
        return []
    # A Xeon in a workstation is normal: just inform
    level = "info" if category in ("desktop", "laptop") else "warning"
    if xeon and x99:
        parts = ["комплект X99 + Xeon — китайская плата и серверный процессор, часто б/у"]
    reason = "Возможно, это серверное железо: " + "; ".join(parts) + ". Уточните у продавца состояние и совместимость."
    return [_flag("server_hardware", level, reason)]


def _mining(text: str, category: str, condition: str) -> list[dict]:
    if _MINING.search(text):
        if category == "psu":
            return [_flag("mining", "warning", "Возможно, это блок питания для майнинг-ферм или серверный: "
                          "обычно без нужных разъёмов и шумный. Уточните у продавца.")]
        return [_flag("mining", "warning", "В описании есть признаки майнинга: карта могла долго работать под нагрузкой. "
                      "Уточните у продавца историю и гарантию.")]
    if category == "psu" and _MINING_PSU.search(text):
        return [_flag("mining", "warning", "Возможно, это серверный блок питания или БП для майнинга. "
                      "Уточните у продавца, подходит ли он для обычного ПК.")]
    if category == "gpu" and condition != "new" and _MINING_GPU.search(text):
        return [_flag("mining", "info", "Б/у видеокарты этой серии часто продаются после майнинга. "
                      "Уточните у продавца, где карта использовалась.")]
    return []


def _used_as_new(text: str, condition: str) -> list[dict]:
    if condition == "new" and _USED.search(text):
        word = _USED.search(text).group(0)
        return [_flag("used_as_new", "danger", f"Товар отмечен как новый, но в описании есть «{word}». "
                      "Возможно, он б/у или восстановленный — уточните у продавца.")]
    return []


def _fake_capacity(text: str, category: str, price_usd: float | None) -> list[dict]:
    gb = _capacity_gb(text)
    if gb is None:
        return []
    if category == "flash" or _FLASH.search(text):
        if gb >= 1024:
            return [_flag("fake_capacity", "danger", f"Флешка или карта памяти на {gb / 1024:g} ТБ — такие часто оказываются "
                          "подделкой: реальный объём намного меньше. Проверьте накопитель программой (например, H2testw) при покупке.")]
        return []
    if category == "ssd" and price_usd and gb >= 240 and price_usd / (gb / 1024) < 25:
        return [_flag("fake_capacity", "warning", f"Цена около ${price_usd / (gb / 1024):.0f} за ТБ — подозрительно низкая для SSD. "
                      "Возможно, реальный объём меньше заявленного — уточните у продавца.")]
    return []


def _noname_psu(row: dict, text: str, category: str, price_usd: float | None) -> list[dict]:
    if category != "psu":
        return []
    watts = max((int(w) for w in _WATTS.findall(text)), default=0)
    brand = (row.get("brand") or "").strip()
    if _NONAME.search(text) or _NONAME.search(brand):
        return [_flag("noname_psu", "warning", "Блок питания без бренда: реальная мощность может быть ниже заявленной, "
                      "защиты часто нет. Уточните у продавца модель и сертификат.")]
    if watts >= 500 and price_usd and price_usd < 20:
        return [_flag("noname_psu", "warning", f"Блок питания на {watts} Вт за ${price_usd:.0f} — подозрительно дёшево. "
                      "Возможно, реальная мощность ниже заявленной.")]
    if not brand:
        return [_flag("noname_psu", "info", "Бренд блока питания не указан. Уточните у продавца производителя.")]
    return []


def _price_below_market(price_usd: float | None, market_usd: list[float] | None) -> list[dict]:
    if not price_usd or not market_usd or len(market_usd) < MARKET_MIN_OFFERS:
        return []
    mid = median(market_usd)
    ratio = price_usd / mid
    if ratio >= MARKET_WARNING:
        return []
    level = "danger" if ratio < MARKET_DANGER else "warning"
    return [_flag("price_below_market", level, f"Цена на {(1 - ratio) * 100:.0f}% ниже средней по рынку (${mid:.0f} у "
                  f"{len(market_usd)} магазинов). Возможно, это ошибка или товар отличается — уточните у продавца.")]


def check_offer(row: dict, market_usd: list[float] | None = None, usd_rate: float | None = None) -> list[dict]:
    """Rules first; AI hints (row["ai_risks"]) only add types the rules did not find."""
    text = _text(row)
    category = row.get("category") or "other"
    condition = row.get("condition") or "new"
    price_usd = _usd(row, usd_rate)
    flags = [
        *_spec_mismatch(text),
        *_server_hardware(text, category),
        *_mining(text, category, condition),
        *_used_as_new(text, condition),
        *_fake_capacity(text, category, price_usd),
        *_noname_psu(row, text, category, price_usd),
        *_price_below_market(price_usd, market_usd),
    ]
    found = {f["type"] for f in flags}
    for risk in row.get("ai_risks") or []:
        # The AI already marked used goods as used: that is honest, not a flag
        if risk == "used_as_new" and condition != "new":
            continue
        if risk in AI_REASONS and risk not in found:
            flags.append(_flag(risk, "info", AI_REASONS[risk], "ai"))
            found.add(risk)
    return sorted(flags, key=lambda f: -LEVEL_ORDER[f["level"]])


def market_prices(db: Session, match_keys: set[str], store_id: int | None, usd_rate: float | None) -> dict[str, list[float]]:
    """USD prices of in-stock offers from other stores, by product match_key."""
    if not match_keys:
        return {}
    q = (
        select(Product.match_key, Offer.price, Offer.currency)
        .join(Offer.product)
        .where(Product.match_key.in_(match_keys), Offer.is_in_stock.is_(True), Offer.price.is_not(None))
    )
    if store_id is not None:
        q = q.where(Offer.store_id != store_id)
    result: dict[str, list[float]] = {}
    for key, price, currency in db.execute(q):
        usd = to_usd(price, currency, usd_rate)
        if usd:
            result.setdefault(key, []).append(usd)
    return result


def save_offer_flags(offer: Offer, flags: list[dict]) -> None:
    """Replaces active flags; a type the seller disputed or the admin dismissed is not raised again."""
    kept = [f for f in offer.fraud_flags if f.status != FlagStatus.active]
    closed = {f.type for f in kept}
    offer.fraud_flags = kept + [
        FraudFlag(type=f["type"], level=FlagLevel(f["level"]), reason=f["reason"], source=FlagSource(f["source"]))
        for f in flags if f["type"] not in closed
    ]
