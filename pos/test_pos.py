"""
Kassa mantiqining testlari — Qt'siz, tarmoqsiz.

Bu yerda tekshiriladigan narsa: pul to'g'ri hisoblanadimi. Ekran
o'zgarishi mumkin, arifmetika o'zgarmasligi kerak.

    python -m pos.test_pos
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from .barcode import Scan, ean13_check_digit, parse, valid_ean13
from .cart import Cart, Customer, PaymentPlan, Product, SplitEntry, split_payment
from .money import line_total, parse_som, qty_str, som


def make_product(price=3_000_00, weight=False, pid=1):
    return Product(
        id=pid, ms_id=f"0000-{pid}", name=f"Tovar-{pid}",
        price=price, is_weight=weight,
    )


class MoneyTest(unittest.TestCase):
    def test_som(self):
        # Ajratgich — uzilmaydigan probel, shuning uchun oddiy probelga
        # almashtirib solishtiramiz
        self.assertEqual(som(1_382_960_000).replace("\u00a0", " "), "13 829 600")
        self.assertEqual(som(0), "0")
        self.assertEqual(som(-8_400_000).replace("\u00a0", " "), "-84 000")

    def test_qty(self):
        self.assertEqual(qty_str(Decimal("2.000")), "2")
        self.assertEqual(qty_str(Decimal("0.750")), "0.75")
        self.assertEqual(qty_str(Decimal("0.734")), "0.734")

    def test_line_total_vaznli(self):
        # 0.734 kg × 12 500 so'm = 9 175 so'm
        self.assertEqual(line_total(12_500_00, Decimal("0.734")), 917_500)

    def test_line_total_yarim_tiyin_yaxlitlanadi(self):
        # 0.005 × 1 = 0.005 tiyin → 0 emas, yaxlitlanadi
        self.assertEqual(line_total(1, Decimal("0.5")), 1)
        self.assertEqual(line_total(1, Decimal("0.4")), 0)

    def test_parse_som(self):
        self.assertEqual(parse_som("300 000"), 300_000_00)
        self.assertEqual(parse_som("300000"), 300_000_00)
        self.assertEqual(parse_som("300.000"), 300_000_00)
        self.assertEqual(parse_som(""), None)
        self.assertEqual(parse_som("abc"), None)


class BarcodeTest(unittest.TestCase):
    def ean(self, first12: str) -> str:
        return first12 + str(ean13_check_digit(first12))

    def test_nazorat_raqami(self):
        # Ma'lum EAN-13: 4600051000057
        self.assertTrue(valid_ean13("4600051000057"))
        self.assertFalse(valid_ean13("4600051000058"))

    def test_oddiy_kod(self):
        scan = parse("4600051000057")
        self.assertFalse(scan.is_scale)
        self.assertEqual(scan.raw, "4600051000057")

    def test_vazn_kodi(self):
        # 29 + PLU 00123 + 00734 gramm (Sevimli tarozilari 29 ga sozlangan)
        code = self.ean("290012300734")
        scan = parse(code)
        self.assertTrue(scan.is_scale)
        self.assertEqual(scan.plu, 123)
        self.assertEqual(scan.weight, Decimal("0.734"))
        self.assertIsNone(scan.price)

    def test_narx_kodi(self):
        # 21 + PLU 00123 + 01250 so'm
        code = self.ean("210012301250")
        scan = parse(code)
        self.assertTrue(scan.is_scale)
        self.assertEqual(scan.plu, 123)
        self.assertEqual(scan.price, 1_250_00)
        self.assertIsNone(scan.weight)

    def test_buzuq_nazorat_raqami_tarozi_deb_qabul_qilinmaydi(self):
        """Noto'g'ri vazn bilan sotgandan ko'ra «topilmadi» yaxshi."""
        code = "290012300734" + "9"  # ataylab noto'g'ri
        if valid_ean13(code):
            self.skipTest("tasodifan to'g'ri chiqdi")
        self.assertFalse(parse(code).is_scale)

    def test_qisqa_kod(self):
        self.assertFalse(parse("12345").is_scale)
        self.assertFalse(parse("").is_scale)

    def test_moysklad_yaratgan_kod_tarozi_emas(self):
        """2000003296927 — MoySklad o'zi yaratgan kod (donali tovar).
        Tarozi deb o'qilsa: PLU 3, «29.692 kg» bo'lardi. «20» prefiksi
        tarozi uchun ishlatilmaydi."""
        self.assertTrue(valid_ean13("2000003296927"))
        self.assertFalse(parse("2000003296927").is_scale)
        # Umuman «20…» kodlar tarozi emas
        self.assertFalse(parse(self.ean("200012300734")).is_scale)

    def test_50_kg_gacha_tarozi_kodi(self):
        self.assertTrue(parse(self.ean("290012349999")).is_scale)   # 49.999 kg
        self.assertFalse(parse(self.ean("290012350001")).is_scale)  # 50.001 kg

    def test_plu_nol_tarozi_emas(self):
        self.assertFalse(parse(self.ean("290000000734")).is_scale)


class CartTest(unittest.TestCase):
    def test_bir_xil_tovar_birlashadi(self):
        cart = Cart()
        p = make_product()
        cart.add(p)
        cart.add(p)
        self.assertEqual(cart.count, 1)
        self.assertEqual(cart.lines[0].quantity, 2)
        self.assertEqual(cart.total, 6_000_00)

    def test_vaznli_tovar_birlashmaydi(self):
        """Har bir tortish alohida qator — kassir xatoni ko'rsin."""
        cart = Cart()
        p = make_product(price=12_500_00, weight=True)
        cart.add(p, Decimal("0.734"))
        cart.add(p, Decimal("1.200"))
        self.assertEqual(cart.count, 2)

    def test_mijoz_chegirmasi(self):
        cart = Cart()
        cart.add(make_product(price=100_000_00))
        cart.customer = Customer(
            id=1, ms_id="x", name="Aliyev", accumulation_discount=5.0
        )
        self.assertEqual(cart.subtotal, 95_000_00)
        self.assertEqual(cart.discount_total, 5_000_00)

    def test_kattaroq_chegirma_olinadi(self):
        cart = Cart()
        cart.add(make_product(price=100_000_00))
        cart.customer = Customer(
            id=1, ms_id="x", name="A",
            accumulation_discount=5.0, personal_discount=12.0,
        )
        self.assertEqual(cart.subtotal, 88_000_00)

    def test_chek_chegirmasi_qoshiladi(self):
        cart = Cart()
        cart.add(make_product(price=100_000_00))
        cart.customer = Customer(id=1, ms_id="x", name="A",
                                 accumulation_discount=5.0)
        cart.receipt_discount = 5.0
        self.assertEqual(cart.subtotal, 90_000_00)

    def test_ball_chegaradan_oshmaydi(self):
        cart = Cart()
        cart.add(make_product(price=10_000_00))
        cart.customer = Customer(id=1, ms_id="x", name="A", bonus_points=50_000)

        # Mijozda 50 000 ball bor, lekin chek 10 000 so'm
        self.assertEqual(cart.max_points, 10_000_00)
        cart.set_points_amount(99_999_00)
        self.assertEqual(cart.points_amount, 10_000_00)
        self.assertEqual(cart.total, 0)

    def test_ball_mijozdagidan_oshmaydi(self):
        cart = Cart()
        cart.add(make_product(price=100_000_00))
        cart.customer = Customer(id=1, ms_id="x", name="A", bonus_points=1_240)
        self.assertEqual(cart.max_points, 1_240_00)

    def test_mijozsiz_ball_yoq(self):
        cart = Cart()
        cart.add(make_product())
        self.assertEqual(cart.max_points, 0)
        self.assertEqual(cart.points_earned(), 0)

    def test_ball_bilan_tolangan_qismga_ball_berilmaydi(self):
        cart = Cart()
        cart.add(make_product(price=100_000_00))
        cart.customer = Customer(id=1, ms_id="x", name="A", bonus_points=10_000)
        cart.set_points_amount(10_000_00)

        # To'lanadigan 90 000 so'm → 900 ball
        self.assertEqual(cart.total, 90_000_00)
        self.assertEqual(cart.points_earned(), 900)

    def test_bosh_chek(self):
        cart = Cart()
        self.assertTrue(cart.is_empty)
        self.assertEqual(cart.total, 0)


class PaymentTest(unittest.TestCase):
    def test_qaytim(self):
        """Mijoz 250 minglik savdoga 300 ming berdi."""
        plan = PaymentPlan(total=250_000_00)
        part = plan.add_cash(300_000_00)

        self.assertEqual(part.amount, 250_000_00)
        self.assertEqual(part.change, 50_000_00)
        self.assertTrue(plan.is_complete)
        self.assertEqual(plan.remaining, 0)

    def test_aniq_summa(self):
        plan = PaymentPlan(total=250_000_00)
        part = plan.add_cash(250_000_00)
        self.assertEqual(part.change, 0)
        self.assertTrue(plan.is_complete)

    def test_kam_berilsa_qolgani_qoladi(self):
        plan = PaymentPlan(total=100_000_00)
        part = plan.add_cash(40_000_00)
        self.assertEqual(part.amount, 40_000_00)
        self.assertEqual(part.change, 0)
        self.assertFalse(plan.is_complete)
        self.assertEqual(plan.remaining, 60_000_00)

    def test_aralash_tolov(self):
        plan = PaymentPlan(total=100_000_00)
        plan.add_cash(40_000_00)
        plan.add("terminal-1")
        self.assertTrue(plan.is_complete)
        self.assertEqual(len(plan.parts), 2)
        self.assertEqual(plan.parts[1].amount, 60_000_00)

    def test_karta_qolganini_oladi(self):
        plan = PaymentPlan(total=100_000_00)
        plan.add("click")
        self.assertEqual(plan.parts[0].amount, 100_000_00)

    def test_ortiqcha_karta_qabul_qilinmaydi(self):
        """Kartadan qaytim bo'lmaydi — ortiqchasi yozilmaydi."""
        plan = PaymentPlan(total=100_000_00)
        plan.add("click", 150_000_00)
        self.assertEqual(plan.parts[0].amount, 100_000_00)
        self.assertTrue(plan.is_complete)

    def test_bekor_qilish(self):
        plan = PaymentPlan(total=100_000_00)
        plan.add_cash(40_000_00)
        plan.undo()
        self.assertEqual(plan.paid, 0)
        self.assertEqual(plan.remaining, 100_000_00)


class SplitPaymentTest(unittest.TestCase):
    """«Aralash to'lov» oynasining hisobi — har turga summa."""

    def entries(self, naqd=0, click=0, humo=0):
        return [
            SplitEntry("naqd", True, naqd),
            SplitEntry("click", False, click),
            SplitEntry("humo", False, humo),
        ]

    def test_yarmi_naqd_yarmi_click(self):
        res = split_payment(200_000_00, self.entries(naqd=100_000_00, click=100_000_00))
        self.assertTrue(res.ok)
        self.assertEqual([(p.method, p.amount) for p in res.parts],
                         [("naqd", 100_000_00), ("click", 100_000_00)])
        self.assertEqual(res.change, 0)
        self.assertEqual(res.remaining, 0)

    def test_uch_tur(self):
        res = split_payment(200_000_00, self.entries(naqd=50_000_00, click=100_000_00, humo=50_000_00))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.parts), 3)

    def test_naqd_ortiqcha_qaytim(self):
        """150 ming click, naqd 60 ming berildi — 50 ming yoziladi, 10 ming qaytim."""
        res = split_payment(200_000_00, self.entries(naqd=60_000_00, click=150_000_00))
        self.assertTrue(res.ok)
        naqd = res.parts[0]
        self.assertEqual((naqd.amount, naqd.tendered, naqd.change), (50_000_00, 60_000_00, 10_000_00))
        self.assertEqual(res.change, 10_000_00)

    def test_kam_bolsa_qoldi(self):
        res = split_payment(200_000_00, self.entries(naqd=50_000_00, click=100_000_00))
        self.assertFalse(res.ok)
        self.assertEqual(res.remaining, 50_000_00)
        self.assertEqual(res.error, "")

    def test_karta_chekdan_kop_xato(self):
        res = split_payment(200_000_00, self.entries(click=150_000_00, humo=100_000_00))
        self.assertFalse(res.ok)
        self.assertIn("chekdan ko'p", res.error)

    def test_karta_yopdi_naqd_ortiqcha_xato(self):
        """Karta chekni to'liq yopdi, kassir naqd ham terdi — ikki marta pul olmasin."""
        res = split_payment(200_000_00, self.entries(naqd=20_000_00, click=200_000_00))
        self.assertFalse(res.ok)
        self.assertIn("naqd", res.error)

    def test_faqat_karta_ham_boladi(self):
        res = split_payment(200_000_00, self.entries(click=200_000_00))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.parts), 1)

    def test_bosh_qatorlar_yozilmaydi(self):
        res = split_payment(100_000_00, self.entries(naqd=100_000_00))
        self.assertEqual([p.method for p in res.parts], ["naqd"])

    def test_hech_narsa_kiritilmasa(self):
        res = split_payment(100_000_00, self.entries())
        self.assertFalse(res.ok)
        self.assertEqual(res.remaining, 100_000_00)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class PrinterHeadTest(unittest.TestCase):
    """Chekda koreys/xitoy harflari chiqmasin (2026-09-18): printer «Chinese
    mode» da bo'lsa kirill baytlari ieroglifga aylanadi. Har chekdan oldin
    FS «.» yuborib shu rejimni o'chiramiz."""

    def test_cjk_ochiriladi_va_kod_sahifasi(self):
        from pos import printer

        h = printer.head_bytes()
        self.assertTrue(h.startswith(printer.INIT))
        self.assertIn(b"\x1c\x2e", h)                  # FS . — CJK rejimi o'chdi
        self.assertTrue(h.endswith(b"\x1bt\x11"))      # PC866 (kirill)
        self.assertLess(h.index(b"\x1c\x2e"), h.index(b"\x1bt\x11"))

    def test_kirill_cp866_da_yuboriladi(self):
        from pos import printer

        self.assertEqual(printer._encode("гуруч"), "гуруч".encode("cp866"))
