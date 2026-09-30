"""
Shtrix-kodni o'qish.

Ikki xil kod keladi:

1. **Oddiy** — tovarning o'z shtrix-kodi. Bazadan qidiriladi.

2. **Tarozi kodi** — Штрих-ПРИНТ tarozisi bosib chiqaradi. EAN-13:

       P PPPPP VVVVV C
       │ │     │     └─ nazorat raqami
       │ │     └─────── vazn (gramm) yoki narx (so'm)
       │ └───────────── PLU — tovar raqami tarozida
       └─────────────── prefiks: 29 = vazn (Sevimli — yagona tarozi prefiksi)

   Sevimli tarozilari 29 prefiksiga sozlangan (egasi, 2026-09-28).
   Narxli yorliq (21/24) ishlatilmaydi — 21… kodlar donali tovarlarniki.

Nazorat raqami tekshiriladi. Skaner ba'zan yarim o'qiydi, va noto'g'ri
vazn — bu noto'g'ri pul.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Tarozi prefikslari. Sevimli tarozilar MoySklad'da PREFIKS 29 ga sozlangan
# (vaznli): 29 + PLU(5) + vazn_gramm(5) + nazorat. Tarozi sozlamasi
# o'zgarsa — shu yer o'zgaradi.
#
# «20» ATAYLAB YO'Q. MoySklad o'zi yaratadigan shtrix-kodlar «2000…» bilan
# boshlanadi (masalan 2000003296927 — donali tovar). Ular tarozi kodiga
# aynan o'xshaydi: 20 + «00003» + «29692» → PLU 3, 29.692 kg. 2026-09 da
# shunday kod tarozi deb o'qilib, donali tovar kilo bilan sotilgan.
# MoySklad bilan ishlaydigan do'konda 20 prefiksini tarozi uchun ishlatib
# bo'lmaydi; tarozi 20 ga sozlangan bo'lsa — uni 29 ga o'tkazish kerak.
#
# FAQAT «29» (2026-09-28, kassa3 hodisasi). Sevimli'da kiloli tovar yorlig'i
# faqat 29 bilan boshlanadi (egasi tasdiqlagan). 21 bilan boshlanadigan
# kodlar esa DONALI tovarlarning zavod/MoySklad kodlari. Ilgari 21/24 «narxli
# yorliq» deb o'qilardi: katalogda yo'q zavod kodi (jo'ja) PLU'si tasodifan
# mos kelgan «колбаса ТК SEVIMLI»ga aylanib, kod ichidagi raqamlar narx deb
# olingan (1 032 so'm) — noto'g'ri tovar noto'g'ri miqdorda sotilgan. 22/23
# ham ishlatilmaydi. Endi katalogda bo'lmagan 21/22/23/24 kod — «topilmadi».
# Katalogdagi 21… donali kodlar avvalgidek aniq moslik bilan topiladi
# (hub.find_by_barcode 1-qadam, tarozi taxminidan oldin).
WEIGHT_PREFIXES = ("29",)
PRICE_PREFIXES: tuple[str, ...] = ()

# Ishonchlilik chegaralari. Do'kon tarozisi 50 kg dan og'ir yorliq
# bosmaydi; PLU 0 bo'lmaydi. Bundan tashqarisi — tarozi kodi emas, balki
# tasodifan tarozi prefiksiga o'xshagan oddiy shtrix-kod.
MAX_SCALE_WEIGHT_KG = Decimal("50")

# Skaner kodni KLAVIATURA tugmalari sifatida «yozadi». Raqamlar har qanday
# tilda bir xil chiqadi, harflar esa Windows tiliga bog'liq: ruscha tartibda
# H tugmasi «Р», T tugmasi «Е» bo'lib yoziladi. 2026-09-30: Code128 kod
# «HT00026010093» kassaga «РЕ00026010093» bo'lib kelib, tovar topilmagan —
# monoblokda klaviatura yo'q, kassir tilni almashtira olmaydi. Kirill harfini
# o'sha tugmadagi lotin harfiga qaytaramiz (ruscha ЙЦУКЕН; o'zbek kirill
# tartibida Щ o'rnida Ў, Ы o'rnida Қ). Б/Ю — vergul va nuqta tugmalari.
_LATIN_KEYS = "qwertyuiopasdfghjklzxcvbnm"
_RU_KEYS = "йцукенгшщзфывапролдячсмить"
_KEY_MAP = {c: l for c, l in zip(_RU_KEYS, _LATIN_KEYS)}
_KEY_MAP.update({"ў": "o", "қ": "s"})
_KEY_MAP.update({c.upper(): l.upper() for c, l in list(_KEY_MAP.items())})
_KEY_MAP.update({"б": ",", "Б": "<", "ю": ".", "Ю": ">"})


def keyboard_to_latin(code: str) -> str:
    """Kirill tartibida «yozilgan» kodni lotin tugmalariga qaytaradi.

    «РЕ00026010093» → «HT00026010093». Raqamlar va lotin harflari
    o'zgarmaydi — oddiy EAN-13 kodlarga ta'sir yo'q."""
    return "".join(_KEY_MAP.get(ch, ch) for ch in code)


@dataclass
class Scan:
    """O'qilgan kod."""

    raw: str

    #: Tarozi kodi bo'lsa — PLU, aks holda None
    plu: int | None = None
    #: Tarozi kodidagi vazn (kg)
    weight: Decimal | None = None
    #: Tarozi kodidagi narx (tiyin)
    price: int | None = None

    @property
    def is_scale(self) -> bool:
        return self.plu is not None


def ean13_check_digit(digits: str) -> int:
    """EAN-13 nazorat raqami — birinchi 12 ta raqamdan hisoblanadi."""
    total = 0
    for i, ch in enumerate(digits[:12]):
        total += int(ch) * (3 if i % 2 else 1)
    return (10 - total % 10) % 10


def valid_ean13(code: str) -> bool:
    if len(code) != 13 or not code.isdigit():
        return False
    return int(code[12]) == ean13_check_digit(code)


def parse(code: str) -> Scan:
    """Kodni tahlil qiladi.

    Tarozi kodi bo'lmasa — `Scan(raw=code)` qaytadi va tovar oddiy
    shtrix-kod bo'yicha qidiriladi.
    """
    code = (code or "").strip()

    if len(code) != 13 or not code.isdigit():
        return Scan(raw=code)

    prefix = code[:2]
    if prefix not in WEIGHT_PREFIXES and prefix not in PRICE_PREFIXES:
        return Scan(raw=code)

    # Nazorat raqami buzuq bo'lsa — bu tarozi kodi deb hisoblamaymiz.
    # Noto'g'ri vazn bilan sotgandan ko'ra «topilmadi» degan yaxshi.
    if not valid_ean13(code):
        return Scan(raw=code)

    plu = int(code[2:7])
    value = int(code[7:12])
    if plu <= 0 or value <= 0:
        return Scan(raw=code)

    if prefix in WEIGHT_PREFIXES:
        # Beshta raqam gramm: 00734 → 0.734 kg
        weight = Decimal(value) / 1000
        if weight > MAX_SCALE_WEIGHT_KG:
            return Scan(raw=code)
        return Scan(raw=code, plu=plu, weight=weight)

    # Narx so'mda: 01250 → 1 250 so'm → 125 000 tiyin
    return Scan(raw=code, plu=plu, price=value * 100)
