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
