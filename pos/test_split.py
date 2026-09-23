"""
«Aralash to'lov» oynasi — ekransiz (offscreen) Qt bilan.

    QT_QPA_PLATFORM=offscreen python -m unittest pos.test_split
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

METHODS = [
    {"code": "naqd", "name": "Naqd", "is_cash": True},
    {"code": "uzcard", "name": "UzCard", "is_cash": False},
    {"code": "humo", "name": "Humo", "is_cash": False},
    {"code": "click", "name": "Click", "is_cash": False},
    {"code": "karta", "name": "Karta", "is_cash": False},
]


class SplitDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, total=200_000_00):
        from .ui.split_payment import SplitPaymentDialog

        return SplitPaymentDialog(total, METHODS)

    def type_(self, dlg, digits: str):
        for d in digits:
            dlg.on_digit(d)

    @staticmethod
    def plain(text: str) -> str:
        """Uzilmaydigan probelni oddiy probelga — solishtirish oson bo'lsin."""
        return text.replace("\u00a0", " ").replace("\u202f", " ")

    def test_naqd_birinchi_va_tanlangan(self):
        dlg = self.dialog()
        self.assertEqual([m["code"] for m in dlg.methods][0], "naqd")
        self.assertEqual(dlg.selected, "naqd")
        self.assertFalse(dlg.finish.isEnabled())
        self.assertEqual(dlg.status_title.text(), "QOLDI")

    def test_yarmi_naqd_qolganini_click(self):
        dlg = self.dialog()
        self.type_(dlg, "100000")
        self.assertEqual(dlg.rows["naqd"].amount_label.text().replace(" ", " "), "100 000")
        self.assertFalse(dlg.finish.isEnabled())

        dlg.select("click")
        dlg.put_rest()
        self.assertEqual(dlg.typed["click"], "100000")
        self.assertTrue(dlg.finish.isEnabled())
        self.assertEqual(dlg.status_title.text(), "HAMMASI YOPILDI")

        dlg._finish()
        self.assertEqual([(p.method, p.amount) for p in dlg.parts],
                         [("naqd", 100_000_00), ("click", 100_000_00)])

    def test_qaytim_korsatiladi(self):
        dlg = self.dialog()
        dlg.select("humo")
        self.type_(dlg, "150000")
        dlg.select("naqd")
        self.type_(dlg, "60000")
        self.assertEqual(dlg.status_title.text(), "QAYTIM")
        self.assertIn("10", dlg.status_value.text())
        self.assertTrue(dlg.finish.isEnabled())
        dlg._finish()
        self.assertEqual(dlg.change, 10_000_00)

    def test_karta_kop_bolsa_xato_va_yakunlanmaydi(self):
        dlg = self.dialog()
        dlg.select("click")
        self.type_(dlg, "150000")
        dlg.select("humo")
        self.type_(dlg, "100000")
        self.assertIn("chekdan ko'p", dlg.status_title.text())
        self.assertFalse(dlg.finish.isEnabled())
        dlg._finish()  # bosilsa ham hech narsa bo'lmaydi
        self.assertEqual(dlg.parts, [])

    def test_qolganini_tugmasi_yopilganda_ochadi(self):
        dlg = self.dialog()
        dlg.put_rest()  # naqdga hammasi
        self.assertEqual(dlg.typed["naqd"], "200000")
        dlg.select("click")
        self.assertFalse(dlg.rest_btn.isEnabled())

    def test_ochirish_va_orqaga(self):
        dlg = self.dialog()
        self.type_(dlg, "12345")
        dlg.on_backspace()
        self.assertEqual(dlg.typed["naqd"], "1234")
        dlg.on_clear()
        self.assertEqual(dlg.typed["naqd"], "")

    # ---------------------------------- vaznli tovar: chek tiyinli (16 001,20)

    KILOLI = 1_600_120

    def test_kiloli_chek_karta_keyin_naqd_qolganini(self):
        dlg = self.dialog(self.KILOLI)
        self.assertEqual(self.plain(dlg.total_label.text()), "16 001,20")
        dlg.select("uzcard")
        self.type_(dlg, "10000")
        dlg.select("naqd")
        dlg.put_rest()
        self.assertEqual(self.plain(dlg.rows["naqd"].amount_label.text()), "6 001,20")
        self.assertEqual(dlg.status_title.text(), "HAMMASI YOPILDI")
        self.assertTrue(dlg.finish.isEnabled())
        dlg._finish()
        self.assertEqual([(p.method, p.amount) for p in dlg.parts],
                         [("naqd", 600_120), ("uzcard", 1_000_000)])
        self.assertEqual(sum(p.amount for p in dlg.parts), self.KILOLI)
        self.assertEqual(dlg.change, 0)

    def test_kiloli_chek_naqd_keyin_karta_qolganini(self):
        dlg = self.dialog(self.KILOLI)
        self.type_(dlg, "6001")
        dlg.select("click")
        dlg.put_rest()
        self.assertEqual(self.plain(dlg.rows["click"].amount_label.text()), "10 000,20")
        self.assertTrue(dlg.finish.isEnabled())
        dlg._finish()
        self.assertEqual([(p.method, p.amount) for p in dlg.parts],
                         [("naqd", 600_100), ("click", 1_000_020)])

    def test_kiloli_chek_faqat_karta_qolganini(self):
        dlg = self.dialog(self.KILOLI)
        dlg.select("humo")
        dlg.put_rest()
        self.assertTrue(dlg.finish.isEnabled())
        dlg._finish()
        self.assertEqual([(p.method, p.amount) for p in dlg.parts],
                         [("humo", self.KILOLI)])

    def test_kiloli_chek_qoldi_nol_deb_aldamaydi(self):
        dlg = self.dialog(self.KILOLI)
        dlg.select("uzcard")
        self.type_(dlg, "10000")
        dlg.select("naqd")
        self.type_(dlg, "6001")          # butun so'm — 20 tiyin yetmaydi
        self.assertEqual(dlg.status_title.text(), "QOLDI")
        self.assertEqual(dlg.status_value.text(), "0,20")
        self.assertFalse(dlg.finish.isEnabled())
        dlg.on_backspace()
        self.type_(dlg, "2")             # 6 002 — qaytim 80 tiyin
        self.assertEqual(dlg.status_title.text(), "QAYTIM")
        self.assertEqual(dlg.status_value.text(), "0,80")
        self.assertTrue(dlg.finish.isEnabled())
        dlg._finish()
        self.assertEqual(dlg.change, 80)
        self.assertEqual(sum(p.amount for p in dlg.parts), self.KILOLI)

    def test_qolganini_dan_keyin_terish_aniq_summani_bekor_qiladi(self):
        dlg = self.dialog(self.KILOLI)
        dlg.put_rest()
        self.assertEqual(dlg.typed["naqd"], "16001")
        self.assertEqual(dlg.exact["naqd"], self.KILOLI)
        dlg.on_backspace()
        self.assertIsNone(dlg.exact["naqd"])
        self.assertEqual(dlg.typed["naqd"], "1600")
        self.assertEqual(dlg.status_title.text(), "QOLDI")
        dlg.put_rest()
        self.assertEqual(dlg.exact["naqd"], self.KILOLI)
        dlg.on_clear()
        self.assertIsNone(dlg.exact["naqd"])
        self.assertEqual(dlg.typed["naqd"], "")

    def test_butun_chekda_hech_narsa_ozgarmadi(self):
        dlg = self.dialog(200_000_00)
        self.assertEqual(self.plain(dlg.total_label.text()), "200 000")
        dlg.put_rest()
        self.assertEqual(self.plain(dlg.rows["naqd"].amount_label.text()), "200 000")
        self.assertEqual(dlg.status_title.text(), "HAMMASI YOPILDI")
        self.assertEqual(dlg.status_value.text(), "0")

    def test_tolov_oynasidan_aralash_qismlar_qoshiladi(self):
        from .ui.payment_dialog import PaymentDialog
        from .cart import PaymentPart

        pd = PaymentDialog(200_000_00, METHODS)
        self.assertTrue(pd.split_btn.isEnabled())
        pd.apply_split([
            PaymentPart("naqd", 100_000_00, tendered=100_000_00, change=0),
            PaymentPart("click", 100_000_00),
        ])
        self.assertTrue(pd.plan.is_complete)
        self.assertEqual(pd.result(), PaymentDialog.Accepted)
        self.assertIn("Click", pd.parts_label.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
