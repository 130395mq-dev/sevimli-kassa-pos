"""Tarixdagi saqlangan savdodan mijoz chekini qayta tiklash."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from shared.receipt import PaymentLine, SaleItem, SaleReceipt, render_sale

from .money import line_total, qty_str


def render_history_sale(payload: dict, *, market: str, point: str,
                        cashier: str, shift_no, methods: list[dict],
                        width: int) -> str:
    """Lokal outbox payloadidan asl raqam/summa bilan chek chizadi."""
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

    raw_when = str(payload.get("created_at") or "")
    try:
        when = datetime.fromisoformat(raw_when.replace("Z", "+00:00"))
    except ValueError:
        when = datetime.now()

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
    return render_sale(receipt, width)
