"""Smena yakunini kassaning O'ZIDA hisoblash (internet yo'q paytda).

Odatda smena hisobotini server chizadi — u hamma chekni ko'rib turadi va
raqam bitta joyda hisoblanadi. Lekin internet uzilib qolsa kassir smenani
yopa olmay qolardi: pulni topshira olmaydi, hisobot chiqmaydi.

Shu fayl o'sha bo'shliqni yopadi: kassaning o'z bazasidagi cheklardan
xuddi serverdagidek yakun yig'adi. Formulalar serverning
`sales/services.py:build_receipt` bilan bir xil — ikki xil raqam
chiqmasligi uchun ataylab bir xil tartibda yozilgan.

Muhim: bu yerda chek serverga yetgan-yetmagani AHAMIYATSIZ. Kassada
chekning hammasi turadi, demak yakun to'liq. Internet qaytganda server
o'zi qayta hisoblaydi va panelda o'sha raqam ko'rinadi.
"""

from __future__ import annotations

import json
from datetime import datetime

from shared.receipt import PaymentLine, ShiftReceipt, _center, _line


def offline_banner(text: str, width: int) -> str:
    """Internetsiz chizilgan hisobotga ogohlantirish qo'shadi.

    Chekning eng tepasida turadi — do'kon egasi qog'ozni qo'liga olganda
    birinchi bo'lib shuni ko'radi va raqamlar hali server bilan
    solishtirilmaganini biladi.
    """
    head = [
        _line("=", width),
        _center("INTERNETSIZ YOPILDI", width),
        _center("Raqamlar kassa hisobidan.", width),
        _center("Keyin serverga yuboriladi.", width),
        _line("=", width),
    ]
    return "\n".join(head) + "\n" + text


def _when(raw: str) -> datetime:
    """ISO vaqtni o'qiydi. Buzuq bo'lsa — hozirgi vaqt (chek chiqaverssin)."""
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return datetime.now().astimezone()


def _payload(row) -> dict:
    try:
        data = json.loads(row["payload"])
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_shift_receipt(
    store,
    methods: list[dict],
    *,
    market: str,
    point: str,
    register: str,
    cashier: str,
    shift_no,
    opened_at,
    closed_at,
    opening_cash: int,
    shift_tag: str,
    is_final: bool = True,
) -> ShiftReceipt:
    """Kassa bazasidagi cheklardan smena hisobotini yig'adi."""
    by_code = {m.get("code"): m for m in methods}

    def name_of(code) -> str:
        return by_code.get(code, {}).get("name") or str(code or "")

    def is_cash(code) -> bool:
        return bool(by_code.get(code, {}).get("is_cash"))

    receipts = 0
    gross = discount = pts_spent = pts_earned = 0
    returns_count = returns_total = returns_cash = 0
    # To'lov turlari chekda doim bir xil tartibda chiqsin — birinchi
    # uchragan tartibi saqlanadi (dict Python 3.7+ da tartibni eslaydi).
    pay_totals: dict = {}

    for row in store.shift_sales(shift_tag):
        # sent=2 — bekor qilingan (bo'sh yoki rad etilgan) chek: yakunga
        # kirmasligi kerak, aks holda pul to'g'ri chiqmaydi.
        if row["sent"] == 2:
            continue
        data = _payload(row)
        if not data:
            continue

        if data.get("kind") == "return":
            returns_count += 1
            returns_total += int(data.get("net_total") or 0)
            for pay in data.get("payments") or []:
                if is_cash(pay.get("method")):
                    returns_cash += int(pay.get("amount") or 0)
            continue

        receipts += 1
        gross += int(data.get("gross_total") or 0)
        discount += int(data.get("discount_total") or 0)
        pts_spent += int(data.get("points_spent") or 0)
        pts_earned += int(data.get("points_earned") or 0)
        for pay in data.get("payments") or []:
            code = pay.get("method")
            pay_totals[code] = pay_totals.get(code, 0) + int(pay.get("amount") or 0)

    cash_in = cash_out = 0
    for op in store.shift_cash(shift_tag):
        amount = int(op.get("amount") or 0)
        if op.get("kind") == "out":
            cash_out += amount
        else:
            cash_in += amount

    return ShiftReceipt(
        market=market,
        point=point,
        register=register,
        cashier=cashier,
        shift_no=shift_no,
        opened_at=_when(opened_at),
        closed_at=_when(closed_at),
        receipts_count=receipts,
        gross_total=gross,
        discount_total=discount,
        # Ball so'mga teng (1 ball = 1 so'm), chekda tiyin kutiladi
        paid_by_points=pts_spent * 100,
        payments=[
            PaymentLine(name=name_of(code), amount=total, is_cash=is_cash(code))
            for code, total in pay_totals.items()
        ],
        returns_count=returns_count,
        returns_total=returns_total,
        returns_cash=returns_cash,
        opening_cash=int(opening_cash or 0),
        cash_in=cash_in,
        cash_out=cash_out,
        counted_cash=None,
        points_earned=pts_earned,
        points_spent=pts_spent,
        doc_no="",
        is_final=is_final,
    )
