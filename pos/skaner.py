"""Shtrix-kodli tovarni faqat skaner bilan qo'shish.

Egasining qarori (2026-10-24): kassir chekni yopib keyingi mijozga o'tadi,
oldingi mijoz «buni ham urib ber» deydi — kassir pulni olib, tovarni nomi
bilan qidiradi va narxi bir xil BOSHQA tovarni uradi (Cola 2 L o'rniga
Cola 2,5 L — ikkalasi 18 000). Pul to'g'ri, lekin qoldiq buziladi.

Endi: qadog'ida shtrix-kodi bor tovar katalogdan nom bilan qo'shilmaydi —
skanerlanadi (yoki shtrix-kod raqami qo'lda teriladi). Nom bilan qidiruv
qadog'ida kodi yo'q tovarlar uchun qoladi: kilo tovarlar, sochma
konfet va h.k. — ularda faqat MoySklad o'zi yaratgan «2…» kodlar bor.

Panelda kassa sozlamasi: «Shtrix-kodli tovarni faqat skaner bilan
qo'shish». Katta huquqli kassir (boshqaruvchi) uchun cheklov yo'q.

Yulduzcha bilan belgilangan (sevimli) tovarlar ham avvalgidek bir bosishda
qo'shiladi — egasi: «yulduzcha bilan belgilab qo'yilganlar uchib ketmasin»
(2026-10-24). Ular kassaning tezkor tugmalari.
"""

from __future__ import annotations

from .i18n import tr


def is_package_barcode(code: str) -> bool:
    """Ishlab chiqaruvchi qadog'iga bosilgan kod (EAN-8/13, UPC).

    «2…» bilan boshlanadigan kodlar — do'kon ichki kodlari (GS1 200–299):
    MoySklad o'zi yaratadi yoki tarozi yorlig'i. Ular qadoqda yo'q, shuning
    uchun bunday tovarni nom bilan qo'shish mumkin bo'lib qoladi.
    """
    code = (code or "").strip()
    return len(code) >= 8 and code.isdigit() and not code.startswith("2")


def name_pick_problem(product, codes, settings: dict | None,
                      cashier: dict | None, favorite: bool = False) -> str:
    """Nom bilan qo'shib bo'lmasa — kassirga ko'rsatiladigan matn, aks holda "".

    `codes` — tovarning barcha shtrix-kodlari (asosiy + qo'shimcha).
    Sozlama kelmagan bo'lsa (eski server) — cheklov yo'q.
    """
    if not (settings or {}).get("scan_only_barcoded"):
        return ""
    if (cashier or {}).get("is_manager"):
        return ""
    if favorite:
        return ""
    if getattr(product, "is_weight", False) or getattr(product, "plu", None) is not None:
        return ""
    all_codes = set(codes or ())
    main = getattr(product, "barcode", "") or ""
    if main:
        all_codes.add(main)
    if not any(is_package_barcode(c) for c in all_codes):
        return ""
    return tr("«{name}» — shtrix-kodi bor. Tovarni skanerlang "
              "yoki shtrix-kod raqamini tering.").format(name=product.name)
