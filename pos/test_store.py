"""
Lokal baza va navbat testlari.

Eng muhimi — `test_internet_yoq_bolsa_chek_yoqolmaydi`. Kassaning butun
ma'nosi shunda: server o'chsa ham savdo davom etadi.

    python -m pos.test_store
"""

from __future__ import annotations

import json
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
        number = len(self.received)
        return {"id": number, "number": number, "receipt_number": f"ОТ-{number:04d}"}

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

    def test_qidiruv_kirill_lotin_katta_kichik(self):
        """Kassir aniq nomni yozmaydi: lotincha, kichik harf, so'z tartibi."""
        self.store.replace_products([
            {"id": 11, "ms_id": "m11", "name": "Сут 1 литр", "code": "", "barcode": "",
             "price": 12_500_00, "is_weight": False, "plu": None, "tracked": False, "stock": 3},
            {"id": 12, "ms_id": "m12", "name": "Гўшт мол (вазнли)", "code": "", "barcode": "",
             "price": 95_000_00, "is_weight": True, "plu": None, "tracked": False, "stock": 3},
            {"id": 13, "ms_id": "m13", "name": "Coca-Cola 1,5л", "code": "", "barcode": "",
             "price": 16_000_00, "is_weight": False, "plu": None, "tracked": False, "stock": 3},
            {"id": 14, "ms_id": "m14", "name": "Qatiq 500 ml", "code": "", "barcode": "",
             "price": 8_000_00, "is_weight": False, "plu": None, "tracked": False, "stock": 3},
        ])
        names = lambda q: [p.name for p in self.store.search(q)]
        # Kirillcha nom — lotincha so'rov (va aksincha), katta-kichik farqsiz
        self.assertEqual(names("sut"), ["Сут 1 литр"])
        self.assertEqual(names("СУТ"), ["Сут 1 литр"])
        self.assertEqual(names("Сут"), ["Сут 1 литр"])
        self.assertEqual(names("катик"), ["Qatiq 500 ml"])
        # So'z tartibi va qismi: "1 lit sut" → «Сут 1 литр»
        self.assertEqual(names("1 lit sut"), ["Сут 1 литр"])
        # Apostrof, ў, o'xshash harflar: go'sht / gosht / гўшт — ikkalasi ham
        # (setUp'dagi "Go'sht mol" ham bor); lotincha nom oldin, keyin kirillcha
        self.assertEqual(names("go'sht"), ["Go'sht mol", "Гўшт мол (вазнли)"])
        self.assertEqual(names("gosht mol"), ["Go'sht mol", "Гўшт мол (вазнли)"])
        self.assertEqual(names("vaznli gosht"), ["Гўшт мол (вазнли)"])
        self.assertEqual(names("kola"), ["Coca-Cola 1,5л"])
        self.assertEqual(names("cola 1.5"), ["Coca-Cola 1,5л"])
        self.assertEqual(names("katik"), ["Qatiq 500 ml"])
        # Bo'lmagan so'z — topilmaydi; faqat belgi — bo'sh
        self.assertEqual(names("kefir"), [])
        self.assertEqual(names("%%"), [])
        # Kod bo'yicha ham avvalgidek
        self.assertEqual(names("0007"), ["Go'sht mol"])

    def test_qidiruv_tartibi(self):
        """Nomi so'rov bilan boshlanganlar oldin turadi."""
        self.store.replace_products([
            {"id": 21, "ms_id": "m21", "name": "Qatiq sut aralash", "code": "", "barcode": "",
             "price": 1_00, "is_weight": False, "plu": None, "tracked": False, "stock": 1},
            {"id": 22, "ms_id": "m22", "name": "Сут 1 литр", "code": "", "barcode": "",
             "price": 1_00, "is_weight": False, "plu": None, "tracked": False, "stock": 1},
            {"id": 23, "ms_id": "m23", "name": "Asut", "code": "", "barcode": "",
             "price": 1_00, "is_weight": False, "plu": None, "tracked": False, "stock": 1},
        ])
        self.assertEqual([p.name for p in self.store.search("sut")],
                         ["Сут 1 литр", "Qatiq sut aralash", "Asut"])

    def test_qidiruv_kaliti(self):
        from .qidiruv import key
        self.assertEqual(key("Гўшт мол (вазнли)"), "gosht mol vaznli")
        self.assertEqual(key("Go'sht"), "gosht")
        self.assertEqual(key("Coca-Cola 1,5л"), "koka kola 1.5l")
        self.assertEqual(key("Xalva"), key("Ҳалва"))
        self.assertEqual(key("Choy 100 g"), key("Чой 100 г"))
        self.assertEqual(key("ПЕЧЕНЬЕ Юбилейное"), "pechene yubileynoe")
        self.assertEqual(key(""), "")

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

        self.assertEqual(len(hub.received), 1)
        self.assertEqual(backend.flush(), 0)
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
        # Eski bazaga qidiruv kaliti bir marta yoziladi (kichik harf ham topadi)
        self.assertEqual(s.search("eski")[0].price, 100)
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
             # Upakovka (MoySklad «Упаковка»): 6 talik blok kodi
             "packs": [{"barcode": "14780001000014", "quantity": 6}],
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

    def test_upakovka_kodi_6_dona(self):
        """MoySklad upakovka kodi skanerlansa — upakovkadagi dona soni."""
        product, qty = self.backend.find_by_barcode("14780001000014")
        self.assertEqual(product.name, "Suv 0.5")
        self.assertEqual(qty, Decimal(6))
        # Oddiy kodlari avvalgidek 1 dona
        for code in ("4780001000017", "4780001000024"):
            product, qty = self.backend.find_by_barcode(code)
            self.assertEqual((product.name, qty), ("Suv 0.5", Decimal(1)))

    def test_upakovka_yangilansa_eski_miqdor_qolmaydi(self):
        self.store.replace_products([
            {"id": 12, "ms_id": "ms-12", "name": "Suv 0.5", "code": "77",
             "barcode": "4780001000017", "barcodes": ["4780001000017"],
             "packs": [{"barcode": "14780001000014", "quantity": 12}],
             "price": 2_000_00, "is_weight": False, "plu": None, "tracked": False, "stock": 40},
        ])
        product, qty = self.backend.find_by_barcode("14780001000014")
        self.assertEqual(qty, Decimal(12))
        self.assertIsNone(self.backend.find_by_barcode("4780001000024"))   # o'chirilgan kod

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


class HistoryNumberTest(unittest.TestCase):
    """MoySklad bergan ОТ-* raqami tarixda saqlanishi."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "kassa.db")
        self.store.replace_products(PRODUCTS)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def _sell(self, backend):
        cart = Cart()
        cart.add(self.store.by_barcode("4780001000017"), 1)
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(cart.total)
        backend.submit(cart, plan)

    def test_flush_server_bergan_raqamni_saqlaydi(self):
        """Yuborilgach server bergan chek raqami (id) diskda saqlanadi."""
        hub = FakeHub(online=True)
        backend = LiveBackend(hub, self.store, METHODS)
        self._sell(backend)
        self.assertEqual(backend.flush(), 0)
        row = self.store.recent_sales(1)[0]
        self.assertEqual(row["sent"], 1)
        self.assertEqual(row["check_no"], 1)  # FakeHub id = 1
        self.assertEqual(json.loads(row["payload"])["receipt_number"], "ОТ-0001")

    def test_navbatdagi_chekda_raqam_yoq(self):
        """Hali yuborilmagan chekда raqam bo'lmaydi (NULL)."""
        backend = LiveBackend(FakeHub(online=False), self.store, METHODS)
        self._sell(backend)
        row = self.store.recent_sales(1)[0]
        self.assertIsNone(row["check_no"])

    def test_shu_smenadagi_cheklar_ajratiladi(self):
        """Har chek qaysi smenaга tegishli bo'lsa, o'sha belgi bilan yoziladi."""
        backend = LiveBackend(FakeHub(online=False), self.store, METHODS)

        self.store.set("history_shift_tag", "srv:10")
        self._sell(backend)
        self._sell(backend)

        self.store.set("history_shift_tag", "srv:11")
        self._sell(backend)

        smena10 = self.store.shift_sales("srv:10")
        smena11 = self.store.shift_sales("srv:11")
        self.assertEqual(len(smena10), 2)
        self.assertEqual(len(smena11), 1)

    def test_belgisiz_bolsa_hamma_tarix(self):
        """Smena belgisi bo'sh bo'lsa — hamma tarix qaytadi (eski cheklar)."""
        backend = LiveBackend(FakeHub(online=False), self.store, METHODS)
        self._sell(backend)
        self._sell(backend)
        self.assertEqual(len(self.store.shift_sales("")), 2)

    def test_raqam_boyicha_qidiruv(self):
        """HistoryDialog chek raqami bo'yicha filtrlaydi."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from .ui.dialogs import HistoryDialog

        app = QApplication.instance() or QApplication([])
        rows = [
            {"check_no": 101, "time": "10:00", "total_text": "3 000",
             "state": "yuborildi", "is_return": False},
            {"check_no": 102, "time": "10:05", "total_text": "5 000",
             "state": "yuborildi", "is_return": False},
            {"check_no": None, "time": "10:06", "total_text": "1 000",
             "state": "navbatda", "is_return": False},
        ]
        called = []

        def on_reprint(row):
            called.append(row)
            return "Chek qayta chop etildi"

        dlg = HistoryDialog(rows, on_reprint=on_reprint)
        self.assertEqual(dlg.list.count(), 3)   # boshda hammasi
        dlg.list.setCurrentRow(0)
        self.assertTrue(dlg.reprint.isEnabled())
        dlg._reprint_current()
        self.assertEqual(called[0]["check_no"], 101)
        self.assertEqual(dlg.note.text(), "Chek qayta chop etildi")   # oynada ko'rinadi
        dlg._type("101")
        self.assertEqual(dlg.list.count(), 1)   # faqat 101
        dlg._type("9")                          # 1019 — mos yo'q
        self.assertEqual(dlg.list.count(), 0)
        dlg._clear()
        self.assertEqual(dlg.list.count(), 3)
        dlg.deleteLater()

    def test_tarix_oynasi_kassa_ekraniga_sigadi(self):
        """Tarix oynasi 1366×768 ekranga sig'sin — «Qayta chop etish»
        tugmasi ekran ostiga tushib ketmasin (2026-09-23)."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from .ui.dialogs import HistoryDialog

        app = QApplication.instance() or QApplication([])
        rows = [
            {"check_no": 100 + i, "time": f"10:{i:02d}", "total_text": "3 000",
             "state": "yuborildi", "is_return": False}
            for i in range(40)
        ]
        dlg = HistoryDialog(rows, shift_caption="Smena #12 · Kassir", on_reprint=None)
        dlg.adjustSize()
        # 1366×768 @125% da bo'sh joy ~576 px; @100% da ~720 px
        self.assertLessEqual(dlg.sizeHint().height(), 560)
        self.assertLessEqual(dlg.minimumSizeHint().height(), 560)
        self.assertLessEqual(dlg.minimumSizeHint().width(), 1000)
        self.assertTrue(dlg.reprint.isVisibleTo(dlg))
        dlg.deleteLater()

    def test_tarixdan_asl_chek_qayta_chiziladi(self):
        from .history import render_history_sale

        payload = {
            "created_at": "2026-09-14T10:25:00+05:00",
            "receipt_number": "ОТ-0208",
            "gross_total": 350000,
            "discount_total": 50000,
            "points_spent": 0,
            "points_earned": 3,
            "items": [{"name": "Non", "quantity": "1", "price": 350000,
                       "total": 300000}],
            "payments": [{"method": "naqd", "amount": 300000,
                          "tendered": 500000, "change": 200000}],
        }
        text = render_history_sale(
            payload, market="Sevimli", point="Shahar", cashier="Ali",
            shift_no=7, methods=METHODS, width=48,
        )
        self.assertIn("ОТ-0208", text)
        self.assertIn("Non", text)
        self.assertIn("3 000 so'm", text)
        self.assertIn("Qaytim", text)
        self.assertTrue(text.startswith(" ") or text.startswith("NUSXA"))
        self.assertIn("NUSXA", text.splitlines()[0])   # tepasida nusxa belgisi

    def test_tarix_vaqti_mahalliy(self):
        """Outbox'da UTC (09:54+00:00) — Toshkentda 14:54 ko'rinsin."""
        from datetime import timedelta, timezone
        from .history import local_hhmm, local_when, render_history_sale

        tashkent = timezone(timedelta(hours=5))
        self.assertEqual(local_hhmm("2026-09-23T09:54:03.123456+00:00", tashkent), "14:54")
        self.assertEqual(local_hhmm("2026-09-23T09:54:03Z", tashkent), "14:54")
        # Yarim tundan o'tib ketadigan holat: 22:30 UTC → ertasi 03:30
        self.assertEqual(local_when("2026-09-23T22:30:00+00:00", tashkent)
                         .strftime("%d.%m %H:%M"), "24.09 03:30")
        # Mintaqasiz yozuv o'zgarmaydi, buzuq yozuv yiqitmaydi
        self.assertEqual(local_hhmm("2026-09-23T10:00:00", tashkent), "10:00")
        self.assertTrue(local_hhmm("bema'ni", tashkent))
        text = render_history_sale(
            {"created_at": "2026-09-23T09:54:03+00:00", "receipt_number": "ОТ-1",
             "gross_total": 100000, "items": [{"name": "Non", "quantity": "1",
             "price": 100000, "total": 100000}],
             "payments": [{"method": "naqd", "amount": 100000}]},
            market="Sevimli", point="", cashier="Ali", shift_no=7,
            methods=METHODS, width=48, tz=tashkent,
        )
        self.assertIn("23.09.2026 14:54", text)
        self.assertNotIn("09:54", text)

    def test_qaytarish_cheki_qayta_chiziladi(self):
        """Tarixdan qaytarish cheki QAYTARISH deb chiqsin, savdo emas."""
        from datetime import timedelta, timezone
        from .history import render_history_sale

        payload = {
            "kind": "return", "origin_id": 55, "origin_number": "ОТ-0208",
            "receipt_number": "ОТ-0301",
            "created_at": "2026-09-23T09:54:03+00:00",
            "gross_total": 300000, "net_total": 300000,
            "items": [{"name": "Non", "quantity": "1", "price": 300000,
                       "total": 300000}],
            "payments": [{"method": "naqd", "amount": 300000}],
        }
        text = render_history_sale(
            payload, market="Sevimli", point="Shahar", cashier="Ali",
            shift_no=7, methods=METHODS, width=48,
            tz=timezone(timedelta(hours=5)),
        )
        self.assertIn("QAYTARISH CHEKI", text)
        self.assertIn("NUSXA", text)
        self.assertIn("ОТ-0301", text)
        self.assertIn("Asl chek", text)
        self.assertIn("ОТ-0208", text)
        self.assertIn("QAYTARILDI", text)
        self.assertIn("3 000 so'm", text)
        self.assertIn("Naqd", text)
        self.assertIn("23.09.2026 14:54", text)
        self.assertNotIn("JAMI", text)      # savdo cheki emas
        self.assertNotIn("Qaytim", text)
