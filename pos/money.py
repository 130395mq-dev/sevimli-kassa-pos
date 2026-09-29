"""
Pul va miqdor bilan ishlash.

Butun loyihada pul **tiyinda, butun son**. So'mga aylantirish faqat
ekranga chiqarishda bo'ladi. Float bilan pul hisoblash — yaxlitlash
xatolarining eng keng tarqalgan sababi, shuning uchun bu yerda ham yo'q.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Ko'rsatishda ishlatiladigan ajratgich. Oddiy probel emas, uzilmaydigan
# probel — raqam qatorning oxirida ikkiga bo'linib ketmasin.
THIN = " "


def som(tiyin: int, *, sep: str = THIN) -> str:
    """1382960000 → '13 829 600'."""
    value = tiyin // 100
    sign = "-" if value < 0 else ""
    return sign + f"{abs(value):,}".replace(",", sep)


def som_exact(tiyin: int, *, sep: str = THIN) -> str:
    """Tiyini bo'lsa ko'rsatadi: 1600120 → '16 001,20', 1600000 → '16 000'.

    Vaznli tovarda chek 16 001,20 so'm chiqishi mumkin. Odatda tiyin
    yashiriladi (`som`), lekin to'lovni tiyinigacha yopish kerak bo'lgan
    joyda kassir «QOLDI 0» degan bema'ni yozuvni ko'rmasligi kerak.
    """
    sign = "-" if tiyin < 0 else ""
    whole, rest = divmod(abs(tiyin), 100)
    body = f"{whole:,}".replace(",", sep)
    return sign + body + (f",{rest:02d}" if rest else "")


def qty_str(quantity: Decimal) -> str:
    """Miqdor: butun bo'lsa '2', kasr bo'lsa '0.750'."""
    q = Decimal(quantity)
    if q == q.to_integral_value():
        return str(int(q))
    return f"{q:.3f}".rstrip("0").rstrip(".")


def line_total(price: int, quantity: Decimal) -> int:
    """Qator summasi — tiyinda, butun son.

    Vaznli tovarda 0.734 kg × 12 500 so'm = 917,5 so'm chiqadi.
    Yarim tiyin bo'lmaydi, shuning uchun yaxlitlaymiz — va yaxlitlashni
    aynan shu yerda, bitta joyda qilamiz.
    """
    exact = Decimal(price) * Decimal(quantity)
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_som(text: str) -> int | None:
    """Kassir kiritgan matnni tiyinga aylantiradi.

    '300 000', '300000', '300.000', '300,000' — hammasi 300 000 so'm.
    Nuqta va vergul bu yerda **ajratgich**, kasr belgisi emas: so'mda
    tiyin ishlatilmaydi, kassir hech qachon '300,50' deb yozmaydi.
    """
    cleaned = "".join(ch for ch in text if ch.isdigit())
    if not cleaned:
        return None
    return int(cleaned) * 100


#: Server va MoySklad miqdorni 3 kasr xonasigacha (gramm) saqlaydi
QTY_STEP = Decimal("0.001")


def label_quantity(label_price: int, unit_price: int) -> Decimal | None:
    """Narxli tarozi yorlig'i: yorliq summasi ÷ tovar narxi → miqdor, GRAMMGACHA.

    Ilgari 1 000 ÷ 3 000 = 0,33333… kg to'g'ridan-to'g'ri chekka tushardi,
    server esa 3 xonadan ko'p kasrni rad etib chek navbatda tiqilib qolardi
    (I01/I02, 2026-09-27). Tarozi summani «vazn × narx» dan chiqaradi,
    shuning uchun grammgacha yaxlitlash asl vaznni qaytaradi; chek summasi
    = narx × shu vazn (yorliqdan farq faqat tarozidagi narx eskirgan
    bo'lsa chiqadi — unda katalog narxi to'g'ri). 1 grammdan kam — None.
    """
    if unit_price <= 0 or label_price <= 0:
        return None
    qty = (Decimal(label_price) / Decimal(unit_price)).quantize(QTY_STEP, rounding=ROUND_HALF_UP)
    return qty if qty > 0 else None


def refund_total(item: dict, quantity) -> int:
    """Use the server's original net allocation, including earlier refunds."""
    qty = Decimal(str(quantity))
    if qty == 0:
        return 0
    if "refund_total" not in item:
        return line_total(int(item["price"]), qty)
    sold = Decimal(str(item["sold_qty"]))
    already = Decimal(str(item.get("returned_qty") or 0))
    if qty < 0 or sold <= 0 or already + qty > sold:
        raise ValueError("Qaytarish miqdori qolgan miqdordan oshib ketdi")
    target = (Decimal(item["refund_total"]) * (already + qty) / sold)
    amount = int(target.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) - int(item.get("returned_total") or 0)
    if amount < 0:
        raise ValueError("Qaytarish hisobini menejer tekshirishi kerak")
    return amount
