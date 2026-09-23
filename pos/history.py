"""Tarixdagi saqlangan savdodan mijoz chekini qayta tiklash.

Vaqt haqida: outbox'da chek vaqti UTC bilan saqlanadi (…+00:00) — server
va MoySklad shuni kutadi. Ekranda va qog'ozda esa kassaning MAHALLIY
vaqti bo'lishi kerak; ilgari UTC to'g'ridan-to'g'ri chiqarilib, tarixda
chek 5 soat «oldin» urilgandek ko'rinardi (2026-09-23, egasining xabari).
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from decimal import Decimal

from shared.receipt import (PaymentLine, SaleItem, SaleReceipt, _center,
                            _line, _pair, render_sale, sum_str)

from .money import line_total, qty_str

#: Qayta chop etilgan chekning tepasidagi belgi — asl chek bilan
#: adashtirilmasin (mijozga ikkinchi marta berilgani ko'rinib tursin).
#: Faqat ASCII: printer cp866 da «—» kabi belgini «?» qilib chiqaradi.
COPY_MARK = "* NUSXA (qayta chop etildi) *"


def local_when(raw: str, tz: tzinfo | None = None) -> datetime:
    """Saqlangan vaqt (ISO, odatda UTC) → mahalliy vaqt.

    `tz` berilmasa kompyuterning o'z vaqt mintaqasi olinadi (kassalarda
    Toshkent). Mintaqasiz (eski/mahalliy) yozuv o'zgartirilmaydi;
    o'qib bo'lmasa — hozirgi vaqt.
    """
    try:
        when = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz) if tz else datetime.now()
    if when.tzinfo is None:
        return when
    return when.astimezone(tz)


def local_hhmm(raw: str, tz: tzinfo | None = None) -> str:
    """Tarix ro'yxati uchun «14:54» ko'rinishi (mahalliy vaqt)."""
    return local_when(raw, tz).strftime("%H:%M")


def render_history_sale(payload: dict, *, market: str, point: str,
                        cashier: str, shift_no, methods: list[dict],
                        width: int, tz: tzinfo | None = None) -> str:
    """Lokal outbox payloadidan asl raqam/summa bilan chek chizadi.

    Qaytarish cheki (`kind == "return"`) alohida chiziladi — savdo cheki
    ko'rinishida chiqsa mijoz/kassir uni yangi savdo deb o'ylab qolardi.
    Tepasida NUSXA belgisi bo'ladi.
    """
    if payload.get("kind") == "return":
        return render_history_return(
            payload, market=market, point=point, cashier=cashier,
            shift_no=shift_no, methods=methods, width=width, tz=tz,
        )
    items = payload.get("items") or []
    payments = payload.get("payments") or []
    method_names = {m.get("code"): m for m in methods}

    gross = int(payload.get("gross_total") or sum(
        line_total(int(i.get("price") or 0), Decimal(str(i.get("quantity") or 0)))
        for i in items
    ))
    discount = int(payload.get("discount_total") or 0)
    points_spent = int(payload.get("points_spent") or 0)
    net = max(0, gross - discount - points_spent * 100)

    when = local_when(str(payload.get("created_at") or ""), tz)

    receipt = SaleReceipt(
        market=market,
        point=point,
        cashier=cashier,
        shift_no=shift_no,
        number=payload.get("receipt_number") or "MoySklad: kutilmoqda",
        when=when,
        items=[
            SaleItem(
                name=str(item.get("name") or ""),
                qty=qty_str(item.get("quantity") or 0),
                price=int(item.get("price") or 0),
                total=int(item.get("total") or 0),
            )
            for item in items
        ],
        gross_total=gross,
        discount_total=discount,
        net_total=net,
        payments=[
            PaymentLine(
                name=(method_names.get(pay.get("method"), {}).get("name")
                      or str(pay.get("method") or "")),
                amount=int(pay.get("amount") or 0),
                is_cash=bool(method_names.get(pay.get("method"), {}).get("is_cash")),
            )
            for pay in payments
        ],
        change=sum(int(pay.get("change") or 0) for pay in payments),
        price_type=str(payload.get("price_type") or ""),
        points_spent=points_spent,
        points_earned=int(payload.get("points_earned") or 0),
    )
    return _center(COPY_MARK, width) + "\n" + render_sale(receipt, width)


def render_history_return(payload: dict, *, market: str, point: str,
                          cashier: str, shift_no, methods: list[dict],
                          width: int, tz: tzinfo | None = None,
                          copy: bool = True) -> str:
    """Qaytarish cheki: qaysi tovar, qancha, qaysi usulda qaytarildi.
    Savdo chekidan farqli — «QAYTARISH» deb aniq yozilgan.

    `copy=True` — tarixdan qayta chop etilgan nusxa (tepasida NUSXA);
    `copy=False` — qaytarish paytida mijozga beriladigan asl chek."""
    w = width
    method_names = {m.get("code"): m for m in methods}
    items = payload.get("items") or []
    payments = payload.get("payments") or []
    total = int(payload.get("net_total") or payload.get("gross_total")
                or sum(int(p.get("amount") or 0) for p in payments))
    when = local_when(str(payload.get("created_at") or ""), tz)
    number = payload.get("receipt_number") or "MoySklad: kutilmoqda"
    origin = payload.get("origin_number") or ""

    out: list[str] = []
    add = out.append
    if copy:
        add(_center(COPY_MARK, w))
    add(_center(market.upper(), w))
    if point:
        add(_center(point, w))
    add(_line("=", w))
    add(_center("QAYTARISH CHEKI", w))
    add(_pair("Kassir", cashier, w, indent=0))
    add(_pair("Chek", str(number), w, indent=0))
    if origin:
        add(_pair("Asl chek", str(origin), w, indent=0))
    add(_pair(f"Smena #{shift_no}", when.strftime("%d.%m.%Y %H:%M"), w, indent=0))
    add(_line("-", w))
    for item in items:
        name = str(item.get("name") or "")
        for i in range(0, max(len(name), 1), w):
            add(name[i:i + w])
        add(_pair(f"{qty_str(item.get('quantity') or 0)} x {sum_str(int(item.get('price') or 0))}",
                  sum_str(int(item.get("total") or 0)), w))
    add(_line("-", w))
    add(_pair("QAYTARILDI", sum_str(total) + " so'm", w, indent=0))
    for pay in payments:
        name = (method_names.get(pay.get("method"), {}).get("name")
                or str(pay.get("method") or ""))
        add(_pair(name, sum_str(int(pay.get("amount") or 0)), w, indent=0))
    add(_line("=", w))
    add("")
    return "\n".join(out)
