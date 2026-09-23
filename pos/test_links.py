"""Paneldan o'zgarish kassaga darhol yetishi va aloqa chiroqlari.

1. `settings_fingerprint` — 15 soniyalik hello javobida panel sozlamalari
   o'zgarganini sezish: to'lov turi qo'shilsa/nomi o'zgarsa/chegirma
   chegarasi o'zgarsa — farq bor; smena yoki server vaqti o'zgarsa — yo'q.
2. `LinkLights` — pastki qatordagi dumaloq chiroqlar: rang, yozuv va
   yonib-o'chish.
"""

from __future__ import annotations

import os
import unittest

from .hub import SETTINGS_KEYS, settings_fingerprint

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _hello(**over) -> dict:
    base = {
        "register": {"code": "k1", "name": "Kassa-1"},
        "point": "Chilonzor",
        "market": "Sevimli Market",
        "receipt_width": 42,
        "server_time": "2026-09-10T10:00:00+05:00",
        "shift": {"id": 7, "number": 3, "cashier": "Nilufar"},
        "payment_methods": [
            {"code": "naqd", "name": "Naqd", "is_cash": True},
            {"code": "uzcard", "name": "UzCard", "is_cash": False},
        ],
        "settings": {"max_discount": 10, "track_stock": True},
        "price_types": [{"id": "a", "name": "Chakana"}],
        "default_price_type": "a",
        "links": {"moysklad": {"state": "ok", "text": "aloqa yaxshi"}},
    }
    base.update(over)
    return base


class FingerprintTest(unittest.TestCase):
    def test_bir_xil_sozlama_bir_xil_iz(self):
        self.assertEqual(settings_fingerprint(_hello()), settings_fingerprint(_hello()))

    def test_smena_va_vaqt_ozgarsa_iz_ozgarmaydi(self):
        a = settings_fingerprint(_hello())
        b = settings_fingerprint(_hello(
            shift=None, server_time="2026-09-10T10:00:15+05:00",
            links={"moysklad": {"state": "bad", "text": "x"}},
        ))
        self.assertEqual(a, b, "smena/vaqt/chiroq sozlama emas — qayta qo'llanmasin")

    def test_tolov_turi_qoshilsa_iz_ozgaradi(self):
        a = settings_fingerprint(_hello())
        methods = _hello()["payment_methods"] + [{"code": "karta", "name": "Karta", "is_cash": False}]
        b = settings_fingerprint(_hello(payment_methods=methods))
        self.assertNotEqual(a, b)

    def test_tolov_turi_nomi_ozgarsa_iz_ozgaradi(self):
        a = settings_fingerprint(_hello())
        methods = [dict(m) for m in _hello()["payment_methods"]]
        methods[1]["name"] = "UZCART"
        self.assertNotEqual(a, settings_fingerprint(_hello(payment_methods=methods)))

    def test_tolov_turi_tartibi_ozgarsa_iz_ozgaradi(self):
        a = settings_fingerprint(_hello())
        methods = list(reversed(_hello()["payment_methods"]))
        self.assertNotEqual(a, settings_fingerprint(_hello(payment_methods=methods)))

    def test_panel_sozlamasi_ozgarsa_iz_ozgaradi(self):
        a = settings_fingerprint(_hello())
        b = settings_fingerprint(_hello(settings={"max_discount": 15, "track_stock": True}))
        self.assertNotEqual(a, b)

    def test_narx_turi_ozgarsa_iz_ozgaradi(self):
        a = settings_fingerprint(_hello())
        b = settings_fingerprint(_hello(default_price_type="b"))
        self.assertNotEqual(a, b)

    def test_kalit_tartibi_ahamiyatsiz(self):
        s1 = {"max_discount": 10, "track_stock": True}
        s2 = {"track_stock": True, "max_discount": 10}
        self.assertEqual(
            settings_fingerprint(_hello(settings=s1)), settings_fingerprint(_hello(settings=s2))
        )

    def test_eski_server_maydon_bermasa_ham_ishlaydi(self):
        h = _hello()
        for k in SETTINGS_KEYS:
            h.pop(k, None)
        self.assertIsInstance(settings_fingerprint(h), str)
        self.assertIsInstance(settings_fingerprint({}), str)
        self.assertIsInstance(settings_fingerprint(None), str)


class LinkLightsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def lights(self):
        from .ui.link_lights import LinkLights

        return LinkLights()

    def test_boshida_nomalum(self):
        w = self.lights()
        self.assertEqual(w.state("server"), "unknown")
        self.assertEqual(w.state("moysklad"), "unknown")

    def test_yashil_yozuv_faqat_nom(self):
        w = self.lights()
        w.set_state("server", "ok", "ulangan")
        self.assertEqual(w.state("server"), "ok")
        self.assertEqual(w._labels["server"].text(), "Server")

    def test_qizil_yozuv_izoh_bilan(self):
        w = self.lights()
        w.set_state("moysklad", "bad", "45 daqiqadan beri javob yo'q")
        self.assertEqual(w._labels["moysklad"].text(), "MoySklad · 45 daqiqadan beri javob yo'q")

    def test_notogri_holat_nomalum_deb_olinadi(self):
        w = self.lights()
        w.set_state("server", "qandaydir")
        self.assertEqual(w.state("server"), "unknown")
        w.set_state("yoq-chiroq", "ok")  # xato bermasin

    def test_qizil_yonib_ochadi_yashil_tinch(self):
        w = self.lights()
        w.set_state("server", "bad", "aloqa yo'q")
        w.set_state("moysklad", "ok")
        seen_off = False
        for _ in range(8):
            w._blink()
            if not w._dots["server"].lit:
                seen_off = True
            self.assertTrue(w._dots["moysklad"].lit, "yashil hech qachon o'chmaydi")
        self.assertTrue(seen_off, "qizil o'chib-yonishi kerak")

    def test_sariq_qizildan_sekinroq(self):
        w = self.lights()
        w.set_state("server", "bad")
        w.set_state("moysklad", "warn")
        red = amber = 0
        prev_r = prev_a = True
        for _ in range(16):
            w._blink()
            r, a = w._dots["server"].lit, w._dots["moysklad"].lit
            red += r != prev_r
            amber += a != prev_a
            prev_r, prev_a = r, a
        self.assertGreater(red, amber)

    def test_holat_ozgarganda_darhol_yonadi(self):
        w = self.lights()
        w.set_state("server", "bad")
        for _ in range(2):
            w._blink()
        w.set_state("server", "ok")
        self.assertTrue(w._dots["server"].lit)


class ReceiptRowTest(unittest.TestCase):
    """Chek qatori: uzun nom summani o'ngga surib ekrandan chiqarmasin."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_wrap_lines(self):
        from PySide6.QtGui import QFont, QFontMetrics

        from .ui.main_window import _wrap_lines

        font = QFont()
        font.setPixelSize(16)
        fm = QFontMetrics(font)
        long = "Televizor Samsung 65 dyuym 4K Smart TV QLED yangi model 2026 yil"
        lines = _wrap_lines(long, fm, 280, 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))
        for ln in lines:
            self.assertLessEqual(fm.horizontalAdvance(ln), 280)
        self.assertEqual(_wrap_lines("Non", fm, 280, 2), ["Non"])
        self.assertEqual(_wrap_lines("", fm, 280, 2), [""])

    def test_qator_kengligi_panelga_sigadi(self):
        from .ui import theme as t
        from .ui.main_window import MainWindow

        long = "Coca-Cola gazlangan ichimlik 1.5 litr plastik butilka original klassik ta'm"
        w = MainWindow._row_widget(long, "1 × 12 500", "15 990 000")
        # Minimal kenglik panel kengligidan oshmasin — aks holda summa
        # o'ng chetga kirib ketadi (gorizontal skroll yo'q)
        self.assertLessEqual(w.minimumSizeHint().width(), t.RECEIPT_WIDTH)
        self.assertGreaterEqual(w.minimumHeight(), 64)
        short = MainWindow._row_widget("Non", "2 × 3 000", "6 000")
        self.assertEqual(short.minimumHeight(), 64)   # barmoq uchun
        self.assertGreater(w.minimumHeight(), short.minimumHeight())  # 2 qator

if __name__ == "__main__":
    unittest.main()


class SetupDialogFitTest(unittest.TestCase):
    """«Kassani ulash» oynasi kichik ekranga sig'sin (2026-09-17: ULASH
    tugmasi ekran ostiga tushib ketgan edi)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, screen_height):
        from pos.ui.dialogs import SetupDialog
        d = SetupDialog("https://x", lambda *a: None, screen_height=screen_height)
        d.adjustSize()
        return d

    def test_kichik_ekranda_ixcham_va_sigadi(self):
        d = self._dialog(576)             # 1366×768 @125% → 614, panel bilan ~576
        self.assertTrue(d.compact)
        self.assertLessEqual(d.sizeHint().height(), 576)

    def test_katta_ekranda_oddiy(self):
        d = self._dialog(1040)
        self.assertFalse(d.compact)
        self.assertLessEqual(d.sizeHint().height(), 1040)

    def test_ixcham_oddiydan_past(self):
        self.assertLess(self._dialog(576).sizeHint().height(),
                        self._dialog(1040).sizeHint().height())
