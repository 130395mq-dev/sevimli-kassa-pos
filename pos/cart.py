"""
Chek — kassaning yuragi.

Bu modul ataylab Qt'ga ham, tarmoqqa ham, bazaga ham bog'liq emas.
Sabab: chekdagi arifmetika eng muhim narsa va uni sinash oson bo'lishi
kerak. Ekran o'zgaradi, tarmoq uziladi — arifmetika o'zgarmaydi.

Chegirma tartibi (MoySklad'dagidek):

    1. qator chegirmasi (agar bo'lsa)
    2. mijozning nakopitelniy yoki shaxsiy chegirmasi — qaysi biri katta
    3. chek chegirmasi (kassir qo'lda qo'yadi)
    4. ball bilan to'lash — bu chegirma emas, to'lovning bir qismi,
       lekin summani kamaytiradi

Yaxlitlash har bir qatorda emas, bitta joyda bo'ladi — `money.line_total`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .money import line_total


@dataclass
class Product:
    """Katalogdagi tovar — chekka tushadigan qismi."""

    id: int
    ms_id: str
    name: str
    price: int
    code: str = ""
    barcode: str = ""
    is_weight: bool = False
    plu: int | None = None
    tracked: bool = False
    stock: float = 0.0
    #: Hamma narx turlari: {narx_turi_id: tiyin}. `price` — joriy turdagisi.
    prices: dict = field(default_factory=dict)
    price_quote: str = ""

    def price_for(self, price_type_id: str | None) -> int:
        """Berilgan narx turidagi narx; u yo'q yoki 0 bo'lsa — asosiy narx."""
        if price_type_id:
            v = self.prices.get(price_type_id)
            if v:
                return int(v)
        return self.price


@dataclass
class Customer:
    id: int
    ms_id: str
    name: str
    phone: str = ""
    card: str = ""
    bonus_points: int = 0
    accumulation_discount: float = 0.0
    personal_discount: float = 0.0

    @property
    def discount_percent(self) -> float:
        """Ikkitasidan kattasi olinadi — mijozga foydaliroq variant."""
        return max(self.accumulation_discount, self.personal_discount)


@dataclass
class Line:
    product: Product
    quantity: Decimal = Decimal(1)
    #: Qator uchun qo'lda qo'yilgan chegirma, foizda
    discount_percent: float = 0.0
    #: Markirovka kodi — skanerdan
    mark_code: str = ""

    @property
    def gross(self) -> int:
        """Chegirmasiz qator summasi."""
        return line_total(self.product.price, self.quantity)

    def net(self, extra_percent: float = 0.0) -> int:
        """Chegirmalardan keyingi qator summasi.

        `extra_percent` — mijoz chegirmasi va chek chegirmasi qo'shilgani.
        """
        percent = min(self.discount_percent + extra_percent, 100.0)
        if percent <= 0:
            return self.gross
        keep = Decimal(100 - percent) / Decimal(100)
        return int((Decimal(self.gross) * keep).quantize(Decimal("1")))


class Cart:
    """Ochiq chek."""

    def __init__(self) -> None:
        self.lines: list[Line] = []
        self.customer: Customer | None = None
        #: Kassir qo'lda qo'ygan chek chegirmasi, foizda
        self.receipt_discount: float = 0.0
        #: Ball bilan to'lanadigan summa, tiyinda
        self.points_amount: int = 0

    # ------------------------------------------------------------ qatorlar

    def reprice(self, price_type_id: str | None, base_price_type_id: str | None = None) -> int:
        """Chekdagi hamma qatorni boshqa narx turiga o'tkazadi.

        Kassir chek yig'ib bo'lgach «Ulgurji» ni bossa ham, hamma qator
        yangi narxga o'tishi kerak — aks holda bitta chekda ikki xil narx
        aralashib ketadi. Qo'lda o'zgartirilgan narx (prices'da yo'q)
        o'zgarmaydi. Necha qator o'zgargani qaytadi.
        """
        changed = 0
        for line in self.lines:
            p = line.product
            if not p.prices:
                continue
            new = p.price_for(price_type_id)
            if new != p.price:
                p.price = new
                changed += 1
        return changed

    def add(self, product: Product, quantity: Decimal | int = 1) -> Line:
        """Tovar qo'shadi. Bir xil tovar qayta skanerlansa — miqdori oshadi.

        Vaznli tovar birlashtirilmaydi: har bir tortish alohida qator,
        chunki kassir qaysi biri noto'g'ri tortilganini ko'rishi kerak.
        """
        quantity = Decimal(quantity)

        if not product.is_weight:
            for i, line in enumerate(self.lines):
                if line.product.id == product.id and not line.mark_code:
                    line.quantity += quantity
                    # Oxirgi urilgan tovar ro'yxat oxiriga (ekranда tepaga)
                    # ko'chadi — kassir nimani urganini darhol ko'radi.
                    self.lines.append(self.lines.pop(i))
                    return line

        line = Line(product=product, quantity=quantity)
        self.lines.append(line)
        return line

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.lines):
            del self.lines[index]

    def set_quantity(self, index: int, quantity: Decimal) -> None:
        if not (0 <= index < len(self.lines)):
            return
        if quantity <= 0:
            del self.lines[index]
        else:
            self.lines[index].quantity = Decimal(quantity)

    def clear(self) -> None:
        self.lines.clear()
        self.customer = None
        self.receipt_discount = 0.0
        self.points_amount = 0

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def count(self) -> int:
        return len(self.lines)

    # ------------------------------------------------------------ summalar

    @property
    def extra_percent(self) -> float:
        """Mijoz chegirmasi + chek chegirmasi."""
        customer_percent = self.customer.discount_percent if self.customer else 0.0
        return customer_percent + self.receipt_discount

    @property
    def gross_total(self) -> int:
        return sum(line.gross for line in self.lines)

    @property
    def discount_total(self) -> int:
        extra = self.extra_percent
        return sum(line.gross - line.net(extra) for line in self.lines)

    @property
    def subtotal(self) -> int:
        """Chegirmalardan keyingi, balldan oldingi summa."""
        extra = self.extra_percent
        return sum(line.net(extra) for line in self.lines)

    @property
    def max_points(self) -> int:
        """Ball bilan qanchasini to'lash mumkin — tiyinda.

        Ikkita chegara: mijozning bali va chekning o'zi. 1 ball = 1 so'm.
        """
        if not self.customer:
            return 0
        return min(self.customer.bonus_points * 100, self.subtotal)

    @property
    def points_spent(self) -> int:
        """Ball soni (dona), tiyin emas."""
        return self.points_amount // 100

    @property
    def total(self) -> int:
        """To'lanadigan summa — ekrandagi «Jami:»."""
        return self.subtotal - self.points_amount

    def points_earned(self, per_som: int = 100) -> int:
        """Beriladigan ball. Sizda: har 100 so'mga 1 ball.

        Ball bilan to'langan qismga ball berilmaydi — aks holda ball
        o'zidan-o'zi ko'payib ketadi.
        """
        if not self.customer:
            return 0
        payable = self.total
        return payable // 100 // per_som

    def set_points_amount(self, tiyin: int) -> None:
        """Ball bilan to'lanadigan summani belgilaydi, chegaradan oshirmaydi."""
        self.points_amount = max(0, min(tiyin, self.max_points))


@dataclass
class PaymentPart:
    """To'lovning bir qismi."""

    method: str
    amount: int
    tendered: int | None = None
    change: int | None = None


@dataclass
class PaymentPlan:
    """Bitta chek uchun to'lovlar to'plami."""

    total: int
    parts: list[PaymentPart] = field(default_factory=list)

    @property
    def paid(self) -> int:
        return sum(p.amount for p in self.parts)

    @property
    def remaining(self) -> int:
        return self.total - self.paid

    @property
    def is_complete(self) -> bool:
        return self.remaining == 0

    def add_cash(self, tendered: int) -> PaymentPart:
        """Naqd qabul qiladi va qaytimni hisoblaydi.

        Berilgan summa qolgandan ko'p bo'lsa — farqi qaytim.
        Kam bo'lsa — qanchasi berilsa, o'shancha yoziladi (aralash to'lov).
        """
        amount = min(tendered, self.remaining)
        change = tendered - amount
        part = PaymentPart(
            method="naqd", amount=amount, tendered=tendered, change=change
        )
        self.parts.append(part)
        return part

    def add(self, method: str, amount: int | None = None) -> PaymentPart:
        """Naqdsiz to'lov. Summa berilmasa — qolganining hammasi."""
        amount = self.remaining if amount is None else min(amount, self.remaining)
        part = PaymentPart(method=method, amount=amount)
        self.parts.append(part)
        return part

    def undo(self) -> None:
        if self.parts:
            self.parts.pop()


# ------------------------------------------------ aralash to'lov
#
# Mijoz 200 mingning yarmini naqd, yarmini Click bilan to'laydi. Kassir
# «Aralash to'lov» oynasida har to'lov turiga summani teradi; bu yerda
# o'sha summalardan to'lov qismlari yasaladi. Qoidalar:
#
#   * karta/onlayn summalari chekdan oshmaydi — kartadan qaytim yo'q;
#   * naqd qolganini yopadi; ortiqcha naqd — qaytim;
#   * karta chekni to'liq yopgan bo'lsa, naqd summasi ortiqcha (xato) —
#     kassir bilmay ikki marta pul olib qo'ymasin.


@dataclass
class SplitEntry:
    """Aralash to'lovda bitta qator: to'lov turi va kassir kiritgan summa."""

    method: str
    is_cash: bool
    amount: int = 0  # tiyin


@dataclass
class SplitResult:
    parts: list[PaymentPart] = field(default_factory=list)
    #: Hali yopilmagan summa (0 bo'lsa to'lov to'liq)
    remaining: int = 0
    #: Naqddan qaytim
    change: int = 0
    #: Bo'sh bo'lsa — hammasi joyida
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.remaining == 0 and bool(self.parts)


def split_payment(total: int, entries: list[SplitEntry]) -> SplitResult:
    """Kiritilgan summalardan to'lov qismlarini yasaydi (yoki xatoni aytadi)."""
    res = SplitResult()
    cashless = sum(e.amount for e in entries if not e.is_cash and e.amount > 0)
    cash = sum(e.amount for e in entries if e.is_cash and e.amount > 0)

    if cashless > total:
        res.error = "Karta/onlayn summasi chekdan ko'p"
        res.remaining = 0
        return res

    need_cash = total - cashless
    if need_cash == 0 and cash > 0:
        res.error = "Karta/onlayn chekni to'liq yopdi — naqd summasini o'chiring"
        return res

    if cash < need_cash:
        res.remaining = need_cash - cash
        return res

    left = need_cash
    for e in entries:
        if e.amount <= 0:
            continue
        if e.is_cash:
            amount = min(e.amount, left)
            left -= amount
            res.parts.append(PaymentPart(
                method=e.method, amount=amount,
                tendered=e.amount, change=e.amount - amount,
            ))
        else:
            res.parts.append(PaymentPart(method=e.method, amount=e.amount))
    res.change = sum(p.change or 0 for p in res.parts)
    return res


# ------------------------------------------------ saqlash va tiklash


def cart_to_dict(cart: Cart) -> dict:
    """Chekni saqlash uchun oddiy ko'rinishga o'tkazadi.

    Miqdor matn sifatida saqlanadi: `float` ga o'tkazilsa 0.734 kg
    aniqligini yo'qotadi.
    """
    return {
        "lines": [
            {
                "product": vars(line.product),
                "quantity": str(line.quantity),
                "discount_percent": line.discount_percent,
                "mark_code": line.mark_code,
            }
            for line in cart.lines
        ],
        "customer": vars(cart.customer) if cart.customer else None,
        "receipt_discount": cart.receipt_discount,
        "points_amount": cart.points_amount,
    }


def cart_from_dict(data: dict) -> Cart:
    """Saqlangan chekni qaytadan tiklaydi."""
    cart = Cart()
    for raw in data.get("lines", []):
        cart.lines.append(
            Line(
                product=Product(**raw["product"]),
                quantity=Decimal(raw["quantity"]),
                discount_percent=raw.get("discount_percent", 0.0),
                mark_code=raw.get("mark_code", ""),
            )
        )
    if data.get("customer"):
        cart.customer = Customer(**data["customer"])
    cart.receipt_discount = data.get("receipt_discount", 0.0)
    cart.points_amount = data.get("points_amount", 0)
    return cart
