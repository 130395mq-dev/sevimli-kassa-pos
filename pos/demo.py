"""
Ekranlarni ko'rish uchun namuna ishga tushirish.

Serversiz, tarmoqsiz — o'ylab topilgan tovarlar bilan. Ko'rinishni
tekshirish uchun:

    python -m pos.demo             # oynani ochadi
    python -m pos.demo --shot      # rasmga oladi (ekransiz mashinada ham)
"""

from __future__ import annotations

import sys
from decimal import Decimal

from .barcode import parse
from .cart import Customer, Product

CATALOG = [
    Product(1, "ms-1", "Buhanka S", 3_000_00, code="0001", barcode="4780001000017"),
    Product(2, "ms-2", "Sut 1 l Nestle", 12_000_00, code="0002", barcode="4780001000024"),
    Product(3, "ms-3", "Shakar 1 kg", 10_000_00, code="0003", barcode="4780001000031"),
    Product(4, "ms-4", "Choy Akbar 250 g", 6_000_00, code="0004", barcode="4780001000048"),
    Product(5, "ms-5", "Yog' Oleyna 1 l", 25_000_00, code="0005", barcode="4780001000055"),
    Product(6, "ms-6", "Tuxum 10 dona", 18_000_00, code="0006", barcode="4780001000062"),
    Product(7, "ms-7", "Go'sht mol (kg)", 95_000_00, code="0007", is_weight=True, plu=123),
    Product(8, "ms-8", "Tvorog (kg)", 32_000_00, code="0008", is_weight=True, plu=124),
    Product(9, "ms-9", "Makaron 400 g", 8_500_00, code="0009", barcode="4780001000093"),
    Product(10, "ms-10", "Guruch Lazer 1 kg", 22_000_00, code="0010", barcode="4780001000109"),
]

METHODS = [
    {"code": "naqd", "name": "Naqd", "is_cash": True},
    {"code": "terminal-1", "name": "Terminal-1", "is_cash": False},
    {"code": "terminal-2", "name": "Terminal-2", "is_cash": False},
    {"code": "click", "name": "Click", "is_cash": False},
    {"code": "payme", "name": "Payme", "is_cash": False},
]


class DemoBackend:
    """Hech qayerga yozmaydi. Faqat ko'rsatish uchun."""

    methods = METHODS

    def find_by_barcode(self, code):
        scan = parse(code)
        if scan.is_scale:
            product = next((p for p in CATALOG if p.plu == scan.plu), None)
            if not product:
                return None
            if scan.weight is not None:
                return product, scan.weight
            # Narxli kod: miqdorni narxdan chiqaramiz
            return product, Decimal(scan.price) / Decimal(product.price)

        product = next((p for p in CATALOG if p.barcode == code), None)
        return (product, Decimal(1)) if product else None

    def search(self, text):
        if not text:
            return CATALOG
        low = text.lower()
        return [p for p in CATALOG if low in p.name.lower() or low in p.code]

    def ask_quantity(self, line):
        return None

    def ask_customer(self):
        return Customer(
            id=1, ms_id="ms-c1", name="Aliyev Sardor", phone="998901234567",
            bonus_points=1240, accumulation_discount=5.0,
        )

    def ask_discount(self, current):
        return None

    def submit(self, cart, plan):
        print("Chek yakunlandi:", cart.total, [p.method for p in plan.parts])


def build_window():
    from .ui.main_window import MainWindow

    window = MainWindow(DemoBackend())
    window.fill_catalog(CATALOG)
    return window


def fill_sample(window):
    """Ekran bo'sh ko'rinmasin — bir nechta tovar qo'shamiz."""
    window.cart.add(CATALOG[0], 2)
    window.cart.add(CATALOG[1])
    window.cart.add(CATALOG[6], Decimal("0.734"))
    window.cart.add(CATALOG[4])
    window.cart.customer = Customer(
        id=1, ms_id="ms-c1", name="Aliyev Sardor",
        bonus_points=1240, accumulation_discount=5.0,
    )
    window.refresh()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = build_window()
    fill_sample(window)

    if "--shot" in sys.argv:
        from .ui.payment_dialog import PaymentDialog

        window.show()
        app.processEvents()
        window.grab().save("pos-asosiy.png")

        dialog = PaymentDialog(window.cart.total, METHODS, window)
        dialog.tendered.setText("300 000")
        dialog.refresh()
        dialog.show()
        app.processEvents()
        dialog.grab().save("pos-tolov.png")

        print("pos-asosiy.png va pos-tolov.png yozildi")
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
