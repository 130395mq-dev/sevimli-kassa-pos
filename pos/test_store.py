"""
Lokal baza va navbat testlari.

Eng muhimi — `test_internet_yoq_bolsa_chek_yoqolmaydi`. Kassaning butun
ma'nosi shunda: server o'chsa ham savdo davom etadi.

    python -m pos.test_store
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

from .cart import Cart, PaymentPlan, Product
from .hub import HubConnError, HubError, LiveBackend, sale_payload
from .store import Store

METHODS = [{"code": "naqd", "name": "Naqd", "is_cash": True}]

PRODUCTS = [
    {"id": 1, "ms_id": "ms-1", "name": "Buhanka S", "code": "0001",
     "barcode": "4780001000017", "price": 3_000_00, "is_weight": False,
     "plu": None, "tracked": False, "stock": 12},
    {"id": 2, "ms_id": "ms-2", "name": "Go'sht mol", "code": "0007",
     "barcode": "", "price": 95_000_00, "is_weight": True,
     "plu": 123, "tracked": False, "stock": 4.5},
]


class FakeHub:
    """Serverni taqlid qiladi. `online=False` — internet yo'q."""

    def __init__(self, online=True):
        self.online = online
        self.received: list[dict] = []

    def send_sale(self, payload):
        if not self.online:
            raise HubConnError("Serverga ulanib bo'lmadi")
        self.received.append(payload)
        return {"id": len(self.received), "number": len(self.received)}

    def open_shift(self, cashier_id, opening_cash, local_uuid="", opened_at=""):
        if not self.online:
            raise HubConnError("Serverga ulanib bo'lmadi")
        self.opened = {"cashier_id": cashier_id, "opening_cash": opening_cash,
                       "local_uuid": local_uuid, "opened_at": opened_at}
        return {"shift": {"id": 7, "number": 42, "cashier": "kassa",
                          "opened_at": opened_at, "opening_cash": opening_cash,
                          "next_receipt_number": 1}}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "kassa.db")
        self.store.replace_products(PRODUCTS)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_shtrix_kod_boyicha_topiladi(self):
        p = self.store.by_barcode("4780001000017")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "Buhanka S")
        self.assertEqual(p.price, 3_000_00)

    def test_plu_boyicha_topiladi(self):
        p = self.store.by_plu(123)
        self.assertIsNotNone(p)
        self.assertTrue(p.is_weight)

    def test_topilmasa_none(self):
        self.assertIsNone(self.store.by_barcode("0000000000000"))

    def test_nom_boyicha_qidiruv(self):
        self.assertEqual(len(self.store.search("buhan")), 1)
        # Qidiruv bo'sh -> FAQAT sevimlilar. Sevimli yo'q ekan -> bo'sh.
        self.assertEqual(len(self.store.search("")), 0)
        # Bittasini sevimli qilsak -> bo'sh qidiruvда faqat o'sha ko'rinadi.
        p = self.store.search("buhan")[0]
        self.store.toggle_favorite(p.id)
        self.assertEqual(len(self.store.search("")), 1)

    def test_qayta_yuklash_nusxa_yaratmaydi(self):
        self.store.replace_products(PRODUCTS)
        self.assertEqual(self.store.product_count(), 2)

    def test_narx_ozgarsa_yangilanadi(self):
        changed = dict(PRODUCTS[0], price=3_500_00)
        self.store.replace_products([changed])
        self.assertEqual(self.store.by_barcode("4780001000017").price, 3_500_00)

    def test_buxgalter_ochirgan_tovar_kassadan_yoqoladi(self):
        """Delta'da `archived: true` kelsa — tovar lokal bazadan o'chadi."""
        stats = self.store.replace_products([dict(PRODUCTS[0], archived=True)])
        self.assertEqual(stats["gone"], 1)
        self.assertIsNone(self.store.by_barcode("4780001000017"))
        self.assertEqual(self.store.product_count(), 1)

    def test_faqat_ochirilganlar_kelsa_ham_ishlaydi(self):
        # `rows` bo'sh qolganda executemany chaqirilmasligi kerak
        stats = self.store.replace_products([{"id": 2, "archived": True}])
        self.assertEqual(stats["gone"], 1)
        self.assertEqual(self.store.product_count(), 1)

    def test_yangi_va_yangilangan_alohida_sanaladi(self):
        new_row = dict(PRODUCTS[0], id=3, ms_id="ms-3", barcode="1")
        stats = self.store.replace_products([dict(PRODUCTS[0], price=1), new_row])
        self.assertEqual(stats, {"new": 1, "updated": 1, "gone": 0})


class OutboxTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "kassa.db"
        self.store = Store(self.path)
        self.store.replace_products(PRODUCTS)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def make_cart(self):
        cart = Cart()
        cart.add(self.store.by_barcode("4780001000017"), 2)
        return cart

    def test_internet_yoq_bolsa_chek_yoqolmaydi(self):
        """Server o'chgan. Chek diskda qolishi kerak."""
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)

        cart = self.make_cart()
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(10_000_00)

        backend.submit(cart, plan)  # xato ko'tarmasligi kerak

        self.assertEqual(self.store.pending_count(), 1)
        self.assertEqual(hub.received, [])

    def test_internet_qaytganda_navbat_boshaydi(self):
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)

        for _ in range(3):
            cart = self.make_cart()
            plan = PaymentPlan(total=cart.total)
            plan.add_cash(cart.total)
            backend.submit(cart, plan)

        self.assertEqual(self.store.pending_count(), 3)

        hub.online = True
        sent = backend.flush()

        self.assertEqual(sent, 3)
        self.assertEqual(self.store.pending_count(), 0)
        self.assertEqual(len(hub.received), 3)

    def test_baza_qayta_ochilsa_navbat_joyida(self):
        """Tok o'chib, kassa qayta yoqilsa — cheklar turibdi."""
        hub = FakeHub(online=False)
        LiveBackend(hub, self.store, METHODS).submit(
            self.make_cart(), self._paid_plan()
        )
        self.store.close()

        reopened = Store(self.path)
        self.assertEqual(reopened.pending_count(), 1)
        reopened.close()
        self.store = Store(self.path)

    def test_bitta_chek_otmasa_qolgani_kutadi(self):
        """Xato umumiy bo'lsa, serverni bir xil so'rov bilan urmaymiz."""
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)
        for _ in range(3):
            backend.submit(self.make_cart(), self._paid_plan())

        sent = backend.flush()
        self.assertEqual(sent, 0)
        self.assertEqual(self.store.pending_count(), 3)

        rows = self.store.pending()
        self.assertEqual(rows[0]["attempts"], 0)
        self.assertIn("ulanib bo'lmadi", rows[0]["last_error"])

    def test_yuborilgan_chek_qayta_yuborilmaydi(self):
        hub = FakeHub(online=True)
        backend = LiveBackend(hub, self.store, METHODS)
        backend.submit(self.make_cart(), self._paid_plan())

        self.assertEqual(len(hub.received), 0)
        self.assertEqual(backend.flush(), 1)
        self.assertEqual(backend.flush(), 0)
        self.assertEqual(len(hub.received), 1)

    def _paid_plan(self) -> PaymentPlan:
        cart = self.make_cart()
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(cart.total)
        return plan

    # -------- yangi: navbat bloki va ikki marta pul tuzatishlari --------

    def test_bitta_rad_etilgan_chek_qolganini_bloklamaydi(self):
        """Server BITTA chekni rad etsa (validatsiya), orqasidagilar
        baribir yuborilishi kerak — bosh-blok bo'lmasin."""
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)
        for _ in range(3):
            backend.submit(self.make_cart(), self._paid_plan())
        self.assertEqual(self.store.pending_count(), 3)

        first_uuid = self.store.pending()[0]["local_uuid"]
        rej = _RejectingHub(reject={first_uuid})
        backend.hub = rej

        sent = backend.flush()
        self.assertEqual(sent, 2)                        # 2 tasi o'tdi
        self.assertEqual(len(rej.received), 2)
        self.assertEqual(self.store.pending_count(), 1)  # faqat rad etilgani
        self.assertEqual(self.store.pending()[0]["local_uuid"], first_uuid)

    def test_takror_rad_etilgan_chek_navbatni_tark_etadi(self):
        """Har safar rad etilaversa — MAX_ATTEMPTS dan keyin navbatni
        chetlab o'tadi (tiqilib qolganlarga o'tadi), boshqalarni bloklamaydi."""
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)
        backend.submit(self.make_cart(), self._paid_plan())
        uuid0 = self.store.pending()[0]["local_uuid"]
        backend.hub = _RejectingHub(reject={uuid0})

        for _ in range(Store.MAX_ATTEMPTS):
            backend.flush()

        self.assertEqual(self.store.pending_count(), 0)  # navbatда emas
        self.assertEqual(self.store.stuck_count(), 1)    # tiqilib qolgan

    def test_saqlangan_chek_kutilmagan_xatoda_ham_qayta_urilmaydi(self):
        """send_sale HubError EMAS xato bersa ham (masalan buzuq JSON),
        submit yuqoriga chiqarmaydi — kassir «Saqlanmadi» ko'rib ikki
        marta urmasin. Chek diskда qoladi."""
        class CrashHub(FakeHub):
            def send_sale(self, payload):
                raise ValueError("server buzuq javob berdi")

        backend = LiveBackend(CrashHub(), self.store, METHODS)
        # Xato KO'TARMASLIGI kerak:
        backend.submit(self.make_cart(), self._paid_plan())
        self.assertEqual(self.store.pending_count(), 1)


class _RejectingHub(FakeHub):
    """Ba'zi cheklarni (local_uuid bo'yicha) validatsiya bilan rad etadi."""

    def __init__(self, reject=None):
        super().__init__(online=True)
        self.reject = set(reject or ())

    def send_sale(self, payload):
        if payload.get("local_uuid") in self.reject:
            raise HubError("Server rad etdi: chegirma chegaradan oshdi")
        return super().send_sale(payload)


class PayloadTest(unittest.TestCase):
    def test_tolovlar_chek_summasiga_teng(self):
        """Server aynan shuni tekshiradi — bu yerda ham tekshiramiz."""
        cart = Cart()
        cart.add(Product(1, "ms-1", "Non", 3_000_00), 2)
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(10_000_00)

        payload = sale_payload(cart, plan, str(uuid.uuid4()), "2026-08-31T12:00:00Z")

        lines = sum(i["total"] for i in payload["items"])
        pays = sum(p["amount"] for p in payload["payments"])
        self.assertEqual(lines, pays)
        self.assertEqual(payload["payments"][0]["change"], 4_000_00)

    def test_vaznli_tovar_miqdori_matn_sifatida(self):
        """Kasr son JSON'da float bo'lib ketmasin — aniqlik yo'qoladi."""
        cart = Cart()
        cart.add(Product(1, "ms-1", "Go'sht", 95_000_00, is_weight=True),
                 Decimal("0.734"))
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(cart.total)

        payload = sale_payload(cart, plan, "u", "2026-08-31T12:00:00Z")
        self.assertEqual(payload["items"][0]["quantity"], "0.734")
        self.assertIsInstance(payload["items"][0]["quantity"], str)

    def test_qaytarish_summasi_savdo_bilan_bir_xil_yaxlitlanadi(self):
        """Qaytarish pulи Decimal (ROUND_HALF_UP) bilan hisoblanadi —
        float emas. Vaznли tovarда asl savdo qatori bilan bir xil chiqadi."""
        from decimal import Decimal as D

        from .hub import return_payload
        from .money import line_total

        price = 12_345_00  # 12 345 so'm/kg
        qty = 0.734
        origin = {"id": 1, "number": 5}
        item = {"name": "Olma", "price": price,
                "product_id": 1, "ms_product_id": "ms-x"}
        payload = return_payload(origin, [{"item": item, "qty": qty}],
                                 "naqd", "u", "2026-01-01T00:00:00Z")

        expected = line_total(price, D(str(qty)))  # savdodagi bilan bir xil
        self.assertEqual(payload["items"][0]["total"], expected)
        self.assertEqual(payload["net_total"], expected)
        self.assertIsInstance(payload["items"][0]["total"], int)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class PriceTypeTest(unittest.TestCase):
    """Chakana ↔ ulgurji: kassa tanlagan turda sotadi, chek qayta narxlanadi."""

    ROWS = [
        {"id": 1, "ms_id": "ms-1", "name": "AAA BONA", "code": "S6181", "barcode": "1",
         "price": 55_000_00, "prices": {"ulg": 52_000_00, "chk": 55_000_00}},
        {"id": 2, "ms_id": "ms-2", "name": "Faqat chakana", "code": "S2", "barcode": "2",
         "price": 10_000_00, "prices": {"chk": 10_000_00}},
    ]

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "kassa.db"
        self.store = Store(self.path)
        self.store.replace_products(self.ROWS)
        self.backend = LiveBackend(FakeHub(), self.store, METHODS)
        self.backend.setup_price_types(
            [{"id": "chk", "name": "Чакана нарх"}, {"id": "ulg", "name": "Улугржи нархи"}], "chk"
        )

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_asosiy_tur_chakana(self):
        self.assertEqual(self.backend.price_type_name, "Чакана нарх")
        self.assertTrue(self.backend.price_type_is_default)
        self.assertEqual(self.store.by_barcode("1").price, 55_000_00)

    def test_ulgurjiga_otganda_narx_almashadi(self):
        self.backend.set_price_type("ulg")
        self.assertEqual(self.store.by_barcode("1").price, 52_000_00)
        # Ulgurji narxi yo'q tovar — asosiy narxda qoladi
        self.assertEqual(self.store.by_barcode("2").price, 10_000_00)
        self.assertFalse(self.backend.price_type_is_default)

    def test_tanlov_qayta_ochilganda_saqlanadi(self):
        self.backend.set_price_type("ulg")
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.price_type_id, "ulg")
        self.assertEqual(self.store.by_barcode("1").price, 52_000_00)

    def test_ochirilgan_tur_asosiysiga_qaytadi(self):
        self.backend.set_price_type("ulg")
        self.backend.setup_price_types([{"id": "chk", "name": "Чакана нарх"}], "chk")
        self.assertEqual(self.backend.price_type_id, "chk")

    def test_chek_qayta_narxlanadi(self):
        cart = Cart()
        cart.add(self.store.by_barcode("1"), 2)
        cart.add(self.store.by_barcode("2"), 1)
        self.assertEqual(cart.total, 2 * 55_000_00 + 10_000_00)
        changed = cart.reprice("ulg")
        self.assertEqual(changed, 1)
        self.assertEqual(cart.total, 2 * 52_000_00 + 10_000_00)

    def test_chekda_narx_turi_nomi_ketadi(self):
        self.backend.set_price_type("ulg")
        cart = Cart()
        cart.add(self.store.by_barcode("1"), 1)
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(cart.total)
        self.backend.submit(cart, plan)
        self.backend.flush()
        self.assertEqual(self.backend.hub.received[0]["price_type"], "Улугржи нархи")
        self.assertEqual(self.backend.hub.received[0]["items"][0]["price"], 52_000_00)

    def test_eski_baza_prices_ustunisiz_ochiladi(self):
        import sqlite3

        old = Path(self.dir.name) / "old.db"
        con = sqlite3.connect(old)
        con.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, ms_id TEXT NOT NULL,"
                    " name TEXT NOT NULL, code TEXT, barcode TEXT, price INTEGER NOT NULL,"
                    " is_weight INTEGER NOT NULL DEFAULT 0, plu INTEGER,"
                    " tracked INTEGER NOT NULL DEFAULT 0, stock REAL NOT NULL DEFAULT 0)")
        con.execute("INSERT INTO products (id, ms_id, name, price) VALUES (9, 'x', 'Eski', 100)")
        con.commit(); con.close()
        s = Store(old)
        self.assertEqual(s.search("Eski")[0].price, 100)
        s.close()


class StockGuardTest(unittest.TestCase):
    """«Qoldiqlarni hisobga olish» — omborda yo'q tovar sotilmaydi."""

    ROWS = [
        {"id": 1, "ms_id": "a", "name": "Coca-Cola", "barcode": "1",
         "price": 10_000_00, "stock": 5},
        {"id": 2, "ms_id": "b", "name": "Non", "barcode": "2",
         "price": 3_000_00, "stock": 0},
    ]

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "kassa.db")
        self.store.replace_products(self.ROWS)
        self.backend = LiveBackend(FakeHub(), self.store, METHODS)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_ochiq_bolsa_hech_narsa_toxtatmaydi(self):
        cola = self.store.by_barcode("1")
        self.assertEqual(self.backend.check_stock(cola, 999), "")

    def test_qoldiq_yetmasa_toxtatadi(self):
        self.backend.track_stock = True
        cola = self.store.by_barcode("1")
        self.assertEqual(self.backend.check_stock(cola, 5), "")
        self.assertIn("omborda 5", self.backend.check_stock(cola, 6))

    def test_qoldiq_yoq_tovar(self):
        self.backend.track_stock = True
        non = self.store.by_barcode("2")
        self.assertIn("yo'q", self.backend.check_stock(non, 1))


class OfflineShiftTest(unittest.TestCase):
    """Internetsiz smena ochish va internet qaytganda sinxronlash."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "k.db")

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_internetsiz_ochiladi_va_saqlanadi(self):
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)
        sh = backend.open_shift({"id": 0, "name": "kassa"}, 500000)
        # Mahalliy smena: raqam yo'q, lekin ochiq
        self.assertIsNone(sh["id"])
        self.assertEqual(sh["opening_cash"], 500000)
        # Diskda saqlangan — dastur qayta ochilsa ham turadi
        local = self.store.get_local_shift()
        self.assertTrue(local and local["offline"])
        self.assertEqual(local["opening_cash"], 500000)

    def test_internet_qaytganda_serverga_ochiladi(self):
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)
        backend.open_shift({"id": 0, "name": "kassa"}, 300000)

        # Internet qaytdi
        hub.online = True
        sh = backend.sync_shift()
        self.assertIsNotNone(sh)
        self.assertEqual(sh["number"], 42)
        # local_uuid bilan ochilgan (idempotentlik uchun)
        self.assertTrue(hub.opened["local_uuid"])
        self.assertEqual(hub.opened["opening_cash"], 300000)
        # Sinxronlangach mahalliy belgi tozalanadi
        self.assertIsNone(self.store.get_local_shift())

    def test_onlayn_ochilsa_mahalliy_saqlanmaydi(self):
        hub = FakeHub(online=True)
        backend = LiveBackend(hub, self.store, METHODS)
        sh = backend.open_shift({"id": 0, "name": "kassa"}, 100000)
        self.assertEqual(sh["number"], 42)
        self.assertIsNone(self.store.get_local_shift())

    def test_server_rad_etsa_mahalliy_ochilmaydi(self):
        """Server RAD etsa (ombor yo'q) — mahalliy smena YARATILMAYDI.
        Aks holda hech qachon sinxronlanmaydigan smena qolardi."""
        class Rejecting(FakeHub):
            def open_shift(self, *a, **k):
                raise HubError("ombor tanlanmagan")

        backend = LiveBackend(Rejecting(online=True), self.store, METHODS)
        with self.assertRaises(HubError):
            backend.open_shift({"id": 0, "name": "kassa"}, 100000)
        self.assertIsNone(self.store.get_local_shift())


class BarcodeLookupTest(unittest.TestCase):
    """Shtrix-kod → tovar: aniq moslik har doim tarozi taxminidan ustun.

    2026-09 dagi xato: MoySklad o'zi yaratgan kod «2000003296927» (donali
    tovar) tarozi prefiksi «20» ga o'xshagani uchun tarozi kodi deb
    o'qilib, tovar «96.927 kg» qilib sotilgan.
    """

    MS_CODE = "2000003296927"  # haqiqiy holat: MoySklad yaratgan, nazorat raqami to'g'ri

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "kassa.db")
        self.store.replace_products([
            # Donali tovar, kodi S32 (Sevimli'da donali kodlar «S…») —
            # MoySklad yaratgan shtrix-kod bilan
            {"id": 10, "ms_id": "ms-10", "name": "Shampun", "code": "S32",
             "barcode": self.MS_CODE, "price": 25_000_00, "is_weight": False,
             "plu": None, "tracked": False, "stock": 5},
            # Vaznli tovar, PLU 123
            {"id": 11, "ms_id": "ms-11", "name": "Go'sht", "code": "123",
             "barcode": "", "price": 95_000_00, "is_weight": True,
             "plu": 123, "tracked": False, "stock": 4.5},
            # Bir nechta shtrix-kodli tovar (dona + blok)
            {"id": 12, "ms_id": "ms-12", "name": "Suv 0.5", "code": "77",
             "barcode": "4780001000017", "barcodes": ["4780001000017", "4780001000024"],
             "price": 2_000_00, "is_weight": False, "plu": None, "tracked": False, "stock": 40},
        ])
        self.backend = LiveBackend(FakeHub(), self.store, METHODS)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_moysklad_kodi_donali_tovar_1_dona(self):
        product, qty = self.backend.find_by_barcode(self.MS_CODE)
        self.assertEqual(product.name, "Shampun")
        self.assertEqual(qty, Decimal(1))

    def test_moysklad_kodi_katalogda_bolmasa_ham_kilo_qilib_sotilmaydi(self):
        """Kod katalogda yo'q: tarozi deb o'qilsa PLU 32 → «Shampun» 96.927 kg
        bo'lardi. Endi: vazn 50 kg dan katta → tarozi kodi emas → topilmadi."""
        self.store.replace_products([{"id": 10, "archived": True}])
        self.store.replace_products([
            {"id": 13, "ms_id": "ms-13", "name": "Shampun", "code": "S32",
             "barcode": "", "price": 25_000_00, "is_weight": False,
             "plu": None, "tracked": False, "stock": 5},
        ])
        self.assertIsNone(self.backend.find_by_barcode(self.MS_CODE))

    def test_tarozi_yorligi_vaznli_tovar(self):
        from .barcode import ean13_check_digit
        code = "290012300734"
        code += str(ean13_check_digit(code))
        product, qty = self.backend.find_by_barcode(code)
        self.assertEqual(product.name, "Go'sht")
        self.assertEqual(qty, Decimal("0.734"))

    def test_tarozi_yorligi_kodi_raqamli_tovar_vaznli_belgisiz_ham_sotiladi(self):
        """Haqiqiy holat (2026-09): MoySklad'da kilo tovar kodi «00843»,
        birligi «шт» → server is_weight=0, plu=None. Tarozi yorlig'i
        29 00843 01250 → «гуруч ЛАЗЕР» 1.250 kg sotilishi kerak, va qator
        vaznli bo'lsin (kg ko'rinadi, tortishlar birlashmaydi)."""
        from .barcode import ean13_check_digit
        self.store.replace_products([
            {"id": 14, "ms_id": "ms-14", "name": "гуруч ЛАЗЕР ОЛИЙ НАВЛИ кг",
             "code": "00843", "barcode": "2000002171928", "price": 21_990_00,
             "is_weight": False, "plu": None, "tracked": False, "stock": 120},
        ])
        code = "290084301250"
        code += str(ean13_check_digit(code))
        product, qty = self.backend.find_by_barcode(code)
        self.assertEqual(product.name, "гуруч ЛАЗЕР ОЛИЙ НАВЛИ кг")
        self.assertEqual(qty, Decimal("1.250"))
        self.assertTrue(product.is_weight)
        # Katalogdagi asl yozuv o'zgarmaydi
        self.assertFalse(self.store.by_plu(843).is_weight)
        # MoySklad yaratgan o'z shtrix-kodi esa 1 dona
        product, qty = self.backend.find_by_barcode("2000002171928")
        self.assertEqual(product.name, "гуруч ЛАЗЕР ОЛИЙ НАВЛИ кг")
        self.assertEqual(qty, Decimal(1))

    def test_tarozi_yorligi_kodi_raqamsiz_tovarga_tushsa_sotilmaydi(self):
        """PLU 32 — «Shampun» kodi «S32» (raqam emas), vaznli belgisi yo'q.
        Tarozi yorlig'i unga ma'nosiz, «topilmadi»."""
        from .barcode import ean13_check_digit
        code = "290003200734"
        code += str(ean13_check_digit(code))
        self.assertIsNone(self.backend.find_by_barcode(code))

    def test_ikkinchi_shtrix_kod_ham_topadi(self):
        product, qty = self.backend.find_by_barcode("4780001000024")
        self.assertEqual(product.name, "Suv 0.5")
        self.assertEqual(qty, Decimal(1))
        self.assertEqual(self.store.by_barcode("4780001000017").name, "Suv 0.5")

    def test_eski_server_barcodes_bermasa_ham_ishlaydi(self):
        self.assertEqual(self.store.by_barcode(self.MS_CODE).name, "Shampun")

    def test_kod_ozgarsa_eskisi_qoladi_emas(self):
        self.store.replace_products([
            {"id": 12, "ms_id": "ms-12", "name": "Suv 0.5", "code": "77",
             "barcode": "4780001000017", "barcodes": ["4780001000017"],
             "price": 2_000_00, "is_weight": False, "plu": None, "tracked": False, "stock": 40},
        ])
        self.assertIsNone(self.store.by_barcode("4780001000024"))

    def test_ochirilgan_tovar_kodlari_ham_ochadi(self):
        self.store.replace_products([{"id": 12, "archived": True}])
        self.assertIsNone(self.store.by_barcode("4780001000024"))
