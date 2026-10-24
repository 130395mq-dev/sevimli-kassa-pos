"""Shtrix-kodli tovar faqat skaner bilan (egasi, 2026-10-24) va panelda
yoqib-o'chiriladigan «Chekni keyinga qoldirish»."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from .cart import Product
from .hub import LiveBackend
from .skaner import is_package_barcode, name_pick_problem
from .store import Store
from .test_store import FakeHub, METHODS

ON = {"scan_only_barcoded": True}
CASHIER = {"id": 5, "name": "Dilnoza", "is_manager": False}
MANAGER = {"id": 6, "name": "Boshqaruvchi", "is_manager": True}

ROWS = [
    # Qadog'ida kodi bor (ishlab chiqaruvchi) — Cola 2 L va 2,5 L, narxi bir xil
    {"id": 1, "ms_id": "ms-1", "name": "напиток Coca-Cola 2 л", "code": "c2",
     "barcode": "2000003171163", "barcodes": ["2000003171163", "4780069000161"],
     "price": 18_000_00, "is_weight": False, "plu": None, "tracked": False, "stock": 10},
    {"id": 2, "ms_id": "ms-2", "name": "напиток Coca-Cola 2.5 л", "code": "c25",
     "barcode": "4780069000178", "price": 18_000_00, "is_weight": False,
     "plu": None, "tracked": False, "stock": 10},
    # Faqat MoySklad yaratgan «2…» kod — sochma konfet (kg): nom bilan qo'shiladi
    {"id": 3, "ms_id": "ms-3", "name": "КГКонфет-шоколад LARAN (кг)", "code": "k1",
     "barcode": "2000002171058", "price": 60_000_00, "is_weight": False,
     "plu": None, "tracked": False, "stock": 3},
    # Tarozi tovari (PLU) — nom bilan qo'shiladi
    {"id": 4, "ms_id": "ms-4", "name": "Banan (кг)", "code": "00117",
     "barcode": "4600000000017", "price": 25_000_00, "is_weight": False,
     "plu": 117, "tracked": False, "stock": 30},
]


def product(**kw):
    base = dict(id=1, ms_id="m", name="Tovar", price=100)
    base.update(kw)
    return Product(**base)


class PackageBarcodeTest(unittest.TestCase):
    def test_kod_turlari(self):
        self.assertTrue(is_package_barcode("4780069000161"))   # EAN-13, O'zbekiston
        self.assertTrue(is_package_barcode("5000112545326"))
        self.assertTrue(is_package_barcode("46012345"))        # EAN-8
        self.assertFalse(is_package_barcode("2000003171163"))  # MoySklad o'zi yaratgan
        self.assertFalse(is_package_barcode("2912345012345"))  # tarozi yorlig'i
        self.assertFalse(is_package_barcode("HT00026010093"))  # Code128 — harfli
        self.assertFalse(is_package_barcode("1234"))
        self.assertFalse(is_package_barcode(""))


class NamePickRuleTest(unittest.TestCase):
    def test_qadoq_kodli_tovar_bloklanadi(self):
        p = product(name="Cola 2 л")
        msg = name_pick_problem(p, ["2000003171163", "4780069000161"], ON, CASHIER)
        self.assertIn("Cola 2 л", msg)
        self.assertIn("skanerlang", msg)

    def test_faqat_ichki_kod_bolsa_ruxsat(self):
        p = product(barcode="2000002171058")
        self.assertEqual(name_pick_problem(p, ["2000002171058"], ON, CASHIER), "")

    def test_kodsiz_tovar_ruxsat(self):
        self.assertEqual(name_pick_problem(product(), [], ON, CASHIER), "")

    def test_tarozi_va_vaznli_tovar_ruxsat(self):
        self.assertEqual(name_pick_problem(product(plu=117), ["4600000000017"], ON, CASHIER), "")
        self.assertEqual(
            name_pick_problem(product(is_weight=True), ["4600000000017"], ON, CASHIER), "")

    def test_asosiy_kod_ham_hisoblanadi(self):
        p = product(barcode="4780069000178")
        self.assertNotEqual(name_pick_problem(p, [], ON, CASHIER), "")

    def test_sevimli_tovarga_cheklov_yoq(self):
        p = product(barcode="4780069000178")
        self.assertEqual(name_pick_problem(p, [], ON, CASHIER, favorite=True), "")

    def test_boshqaruvchiga_cheklov_yoq(self):
        p = product(barcode="4780069000178")
        self.assertEqual(name_pick_problem(p, ["4780069000178"], ON, MANAGER), "")

    def test_sozlama_ochiq_yoki_kelmagan(self):
        p = product(barcode="4780069000178")
        self.assertEqual(name_pick_problem(p, [], {"scan_only_barcoded": False}, CASHIER), "")
        # Eski server sozlamani yubormaydi — avvalgidek ishlaydi
        self.assertEqual(name_pick_problem(p, [], {}, CASHIER), "")
        self.assertEqual(name_pick_problem(p, [], None, CASHIER), "")


class CatalogPickTest(unittest.TestCase):
    """Katalogdan nom bilan bosish: bloklangan tovar chekka tushmaydi."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from .ui.main_window import MainWindow
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / "kassa.db")
        self.store.replace_products(ROWS)
        self.backend = LiveBackend(FakeHub(), self.store, METHODS)
        self.kset = dict(ON)
        self.cashier = dict(CASHIER)
        # main.py dagi bilan bir xil ulanish
        self.backend.name_pick_problem = lambda p: name_pick_problem(
            p, self.store.barcodes_of(p.id), self.kset, self.cashier,
            favorite=self.store.is_favorite(p.id))
        self.window = MainWindow(self.backend)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.store.close()
        self.folder.cleanup()

    def pick(self, name_query, product_id):
        from PySide6.QtCore import Qt
        self.window.fill_catalog(self.store.search(name_query))
        lst = self.window.catalog_list
        for i in range(lst.count()):
            item = lst.item(i)
            if item.data(Qt.UserRole).id == product_id:
                with patch("PySide6.QtWidgets.QMessageBox.warning") as warn:
                    self.window.on_catalog_pick(item)
                return warn
        self.fail(f"#{product_id} katalogda yo'q")

    def ids(self):
        return [line.product.id for line in self.window.cart.lines]

    def test_barcodes_of_hammasini_qaytaradi(self):
        self.assertEqual(sorted(self.store.barcodes_of(1)),
                         ["2000003171163", "4780069000161"])
        self.assertEqual(self.store.barcodes_of(2), ["4780069000178"])

    def test_cola_nom_bilan_qoshilmaydi(self):
        warn = self.pick("cola", 2)
        self.assertEqual(self.ids(), [])
        warn.assert_called_once()
        self.assertIn("2.5", warn.call_args[0][2])
        self.assertIn("skanerlang", self.window.status_label.text())

    def test_skaner_bilan_qoshiladi(self):
        self.window.scan_input.setText("4780069000161")
        self.window.on_scan()
        self.assertEqual(self.ids(), [1])

    def test_kodsiz_va_tarozi_tovari_nom_bilan_qoshiladi(self):
        warn = self.pick("конфет", 3)
        warn.assert_not_called()
        warn = self.pick("банан", 4)
        warn.assert_not_called()
        self.assertEqual(self.ids(), [3, 4])

    def test_boshqaruvchi_nom_bilan_qosha_oladi(self):
        self.cashier["is_manager"] = True
        warn = self.pick("cola", 2)
        warn.assert_not_called()
        self.assertEqual(self.ids(), [2])

    def test_yulduzchali_tovar_bir_bosishda_qoshiladi(self):
        # Egasi: «yulduzcha bilan belgilab qo'yilganlar uchib ketmasin»
        self.store.toggle_favorite(1)
        self.window.fill_catalog(self.store.search(""))   # bo'sh qidiruv — sevimlilar
        from PySide6.QtCore import Qt
        item = self.window.catalog_list.item(0)
        self.assertEqual(item.data(Qt.UserRole).id, 1)
        with patch("PySide6.QtWidgets.QMessageBox.warning") as warn:
            self.window.on_catalog_pick(item)
        warn.assert_not_called()
        self.assertEqual(self.ids(), [1])

    def test_yulduzchalar_katalog_yangilanganda_saqlanadi(self):
        self.store.toggle_favorite(1)
        self.store.toggle_favorite(3)
        self.store.replace_products(ROWS)                 # serverdan yangilanish
        self.assertEqual(sorted(self.store.favorites()), [1, 3])

    def test_panelda_ochirilsa_avvalgidek(self):
        self.kset["scan_only_barcoded"] = False
        self.pick("cola", 2)
        self.assertEqual(self.ids(), [2])


class ParkToggleMenuTest(unittest.TestCase):
    """«Chekni keyinga qoldirish» — panel sozlamasi `allow_park` bilan."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def codes(self, **kw):
        from PySide6.QtWidgets import QPushButton
        from .ui.dialogs import MenuDialog
        dialog = MenuDialog(**kw)
        try:
            return [b.property("code") for b in dialog.findChildren(QPushButton)
                    if b.property("code")]
        finally:
            dialog.deleteLater()

    def test_standart_ochiq_emas(self):
        self.assertNotIn("park", self.codes())

    def test_ruxsat_bolsa_menyuda_bor(self):
        codes = self.codes(allow_park=True)
        self.assertEqual(codes[:2], ["park", "parked"])

    def test_oyna_backenddan_ruxsatni_oladi(self):
        from .test_store import PRODUCTS
        from .ui.dialogs import MenuDialog
        from .ui.main_window import MainWindow
        from PySide6.QtWidgets import QPushButton
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "kassa.db")
            store.replace_products(PRODUCTS)
            backend = LiveBackend(FakeHub(), store, METHODS)
            backend.allow_park = lambda: True
            window = MainWindow(backend)
            seen = {}

            def fake_exec(dialog):
                seen["codes"] = [b.property("code") for b in dialog.findChildren(QPushButton)
                                 if b.property("code")]
                return MenuDialog.Rejected

            with patch.object(MenuDialog, "exec", fake_exec):
                window.on_menu()
                self.assertIn("park", seen["codes"])
                backend.allow_park = lambda: False
                window.on_menu()
                self.assertNotIn("park", seen["codes"])
            window.close()
            window.deleteLater()
            store.close()


class CodeOnlySearchTest(unittest.TestCase):
    """Panel: «Kassada qidiruv faqat tovar kodi bo'yicha» (egasi, 2026-10-24:
    «kodi bilan qidirish bo'lsin, faqat kod bilan»)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from .ui.main_window import MainWindow
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / "kassa.db")
        self.store.replace_products(ROWS)
        self.backend = LiveBackend(FakeHub(), self.store, METHODS)
        self.backend.search_code_only = True
        self.kset = dict(ON)
        self.backend.name_pick_problem = lambda p: name_pick_problem(
            p, self.store.barcodes_of(p.id), self.kset, CASHIER,
            favorite=self.store.is_favorite(p.id))
        self.window = MainWindow(self.backend)
        self.window.set_search_mode(True)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.store.close()
        self.folder.cleanup()

    def ids(self, products):
        return [p.id for p in products]

    def test_nom_bilan_topilmaydi(self):
        self.assertEqual(self.backend.search("cola"), [])
        self.assertEqual(self.backend.search("банан"), [])
        self.backend.search_code_only = False                 # panelda o'chirilsa
        # Eski nom qidiruvi: «cola» Cola'lar bilan birga «шоКОЛАд»ni ham topadi
        self.assertLessEqual({1, 2}, set(self.ids(self.backend.search("cola"))))

    def test_kod_boshi_va_aniq_moslik_oldin(self):
        self.assertEqual(self.ids(self.backend.search("C2")), [1, 2])   # c2 aniq, c25 keyin
        self.assertEqual(self.ids(self.backend.search("c25")), [2])
        self.assertEqual(self.ids(self.backend.search("117")), [4])     # 00117 — nolsiz ham
        self.assertEqual(self.ids(self.backend.search("00117")), [4])

    def test_bosh_qidiruv_sevimlilar(self):
        self.store.toggle_favorite(3)
        self.assertEqual(self.ids(self.backend.search("")), [3])

    def test_aniq_kod_bitta_tovar(self):
        self.assertEqual(self.store.by_code("C2").id, 1)
        self.assertEqual(self.store.by_code("117").id, 4)
        self.assertIsNone(self.store.by_code("c"))                     # aniq moslik yo'q
        self.assertIsNone(self.store.by_code("cola"))

    def test_kod_terib_enter(self):
        from unittest.mock import patch
        self.window.scan_input.setText("00117")
        self.window.on_scan()
        self.assertEqual([l.product.id for l in self.window.cart.lines], [4])
        # Shtrix-kodli tovar kodi bilan ham qo'shilmaydi — skanerlanadi
        self.window.scan_input.setText("c25")
        with patch("PySide6.QtWidgets.QMessageBox.warning") as warn:
            self.window.on_scan()
        warn.assert_called_once()
        self.assertEqual([l.product.id for l in self.window.cart.lines], [4])

    def test_qisqa_raqam_qidiriladi_skaner_kodi_emas(self):
        self.window.on_search("00117")
        self.assertTrue(self.window._search_timer.isActive())
        self.window._search_timer.stop()
        self.window._run_search()
        from PySide6.QtCore import Qt
        lst = self.window.catalog_list
        self.assertEqual([lst.item(i).data(Qt.UserRole).id for i in range(lst.count())], [4])
        # Skaner kodi (13 raqam) — ro'yxatga tegilmaydi
        self.window.on_search("4780069000161")
        self.assertFalse(self.window._search_timer.isActive())

    def test_maydon_yozuvi(self):
        self.assertIn("tovar kodi", self.window.scan_input.placeholderText())
        self.window.set_search_mode(False)
        self.assertIn("nomi", self.window.scan_input.placeholderText())


if __name__ == "__main__":
    unittest.main()
