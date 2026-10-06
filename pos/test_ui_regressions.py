"""Regressions observed in the isolated Windows trial on 2026-09-29."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from .cart import Cart, PaymentPlan
from .hub import LiveBackend
from .store import Store
from .test_store import FakeHub, METHODS, PRODUCTS


class PanelPriceCheckoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_change_during_payment_keeps_paid_and_printed_amount(self):
        from .price_policy import bind_price_policy
        from .test_store import PriceTypeTest
        from .ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "kassa.db")
            store.replace_products(PriceTypeTest.ROWS)
            backend = LiveBackend(FakeHub(), store, METHODS)
            types = [{"id": "chk", "name": "Chakana"}, {"id": "ulg", "name": "Ulgurji"}]
            backend.setup_price_types(types, "chk")
            window = MainWindow(backend)
            policy = bind_price_policy(backend, window)
            policy.offer({"price_types": types, "default_price_type": "chk", "price_policy_revision": "a"})
            printed = []
            window.print_sale = lambda cart, plan: printed.append((cart.total, backend.price_type_id))
            window.cart.add(store.by_barcode("1"))
            window.refresh()
            plan = PaymentPlan(window.cart.total)
            plan.add_cash(window.cart.total)
            try:
                with patch("pos.ui.main_window.PaymentDialog") as dialog:
                    dialog.Accepted = 1
                    dialog.return_value.plan = plan
                    def while_paying():
                        policy.offer({"price_types": types, "default_price_type": "ulg", "price_policy_revision": "b"})
                        self.assertEqual(window.cart.total, 55_000_00)
                        self.assertEqual(window.price_btn.text(), "Chakana")
                        return 1
                    dialog.return_value.exec.side_effect = while_paying
                    window.open_payment()
                self.assertEqual(printed, [(55_000_00, "chk")])
                self.assertTrue(window.cart.is_empty)
                self.assertEqual(window.price_btn.text(), "Ulgurji")
                self.assertFalse(window.price_btn.isEnabled())
                self.assertEqual(store.by_barcode("1").price, 52_000_00)
                payload = json.loads(store.pending()[0]["payload"])
                self.assertEqual(payload["price_type_id"], "chk")
                self.assertEqual(payload["payments"][0]["amount"], 55_000_00)
            finally:
                policy.timer.stop()
                window.close()
                store.close()


class ParkedCartPriceTest(unittest.TestCase):
    """Kechiktirilgan (park) chek va panel narx turi (2026-09-29 ko'rib chiqish).

    1) `open_parked` `window.cart` ni YANGI obyektga almashtiradi. Siyosat eski
       obyektga qarab qolsa, ochiq chek paytida narx turi almashib ketardi.
    2) Park paytidagi narx turi hozirgisidan farq qilsa, chek joriy turdagi
       narxga o'tkazilishi kerak — aks holda server «narx katalogga mos emas»
       deb rad etadi va to'langan chek navbatda tiqilib qoladi.
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _setup(self, folder):
        from .price_policy import bind_price_policy
        from .test_store import PriceTypeTest
        from .ui.main_window import MainWindow
        store = Store(Path(folder) / "kassa.db")
        store.replace_products(PriceTypeTest.ROWS)
        backend = LiveBackend(FakeHub(), store, METHODS)
        types = [{"id": "chk", "name": "Chakana"}, {"id": "ulg", "name": "Ulgurji"}]
        backend.setup_price_types(types, "chk")
        window = MainWindow(backend)
        policy = bind_price_policy(backend, window)
        policy.offer({"price_types": types, "default_price_type": "chk", "price_policy_revision": "a"})
        return store, backend, window, policy, types

    def test_unparked_open_cart_keeps_price_type_until_finished(self):
        from .cart import cart_from_dict, cart_to_dict
        with tempfile.TemporaryDirectory() as folder:
            store, backend, window, policy, types = self._setup(folder)
            try:
                parked = Cart()
                parked.add(store.by_barcode("1"))
                window.cart = cart_from_dict(cart_to_dict(parked))   # open_parked bilan bir xil
                window.refresh()
                policy.offer({"price_types": types, "default_price_type": "ulg", "price_policy_revision": "b"})
                policy.apply_if_idle()
                self.assertEqual(backend.price_type_id, "chk")        # ochiq chek — eski tur
                window.cart.clear()
                window.refresh()
                policy.apply_if_idle()
                self.assertEqual(backend.price_type_id, "ulg")        # bo'sh — yangi tur
            finally:
                policy.timer.stop()
                window.close()
                store.close()

    def test_parked_cart_repriced_to_current_type_on_restore(self):
        from .cart import cart_to_dict
        from .price_policy import restore_parked
        with tempfile.TemporaryDirectory() as folder:
            store, backend, window, policy, types = self._setup(folder)
            try:
                parked = Cart()
                parked.add(store.by_barcode("1"))
                self.assertEqual(parked.total, 55_000_00)             # chakana
                data = cart_to_dict(parked)
                policy.offer({"price_types": types, "default_price_type": "ulg", "price_policy_revision": "b"})
                self.assertEqual(backend.price_type_id, "ulg")
                cart, changed = restore_parked(backend, data)
                self.assertEqual(changed, 1)
                self.assertEqual(cart.total, 52_000_00)               # joriy (ulgurji) narx
                plan = PaymentPlan(cart.total)
                plan.add_cash(cart.total)
                backend.submit(cart, plan)
                payload = json.loads(store.pending()[0]["payload"])
                self.assertEqual(payload["price_type_id"], "ulg")
                self.assertEqual(payload["items"][0]["price"], 52_000_00)
            finally:
                policy.timer.stop()
                window.close()
                store.close()


class SaleQueueOnlyTest(unittest.TestCase):
    def test_checkout_never_waits_for_network_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "kassa.db"
            store = Store(path)
            store.replace_products(PRODUCTS)
            hub = FakeHub()
            backend = LiveBackend(hub, store, METHODS)
            cart = Cart()
            cart.add(store.by_barcode("4780001000017"), 1)
            plan = PaymentPlan(cart.total)
            plan.add_cash(cart.total)
            try:
                with patch.object(hub, "send_sale", side_effect=TimeoutError("unresponsive server")) as send:
                    backend.submit(cart, plan)
                    send.assert_not_called()
                row = store.pending()[0]
                uid = row["local_uuid"]
                payload = json.loads(row["payload"])
                self.assertEqual(payload["gross_total"], 300000)
                self.assertIn(uid[:8].upper(), backend.last_receipt_number)
            finally:
                store.close()
            reopened = Store(path)
            try:
                backend = LiveBackend(hub, reopened, METHODS)
                self.assertEqual(backend.flush(), 1)
                self.assertEqual(backend.flush(), 0)
                self.assertEqual([x["local_uuid"] for x in hub.received], [uid])
                self.assertEqual(reopened.pending_count(), 0)
            finally:
                reopened.close()


class ReturnTimezoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_list_and_detail_match_local_history_across_midnight(self):
        from PySide6.QtWidgets import QLabel
        from . import history
        from .ui.dialogs import ReturnSaleListDialog, ReturnDetailDialog
        tz = timezone(timedelta(hours=5))
        real_datetime = datetime
        class LocalClock(datetime):
            @classmethod
            def fromisoformat(cls, value):
                parsed = real_datetime.fromisoformat(value)
                return cls(parsed.year, parsed.month, parsed.day, parsed.hour,
                           parsed.minute, parsed.second, tzinfo=parsed.tzinfo)

            def astimezone(self, zone=None):
                return super().astimezone(zone or tz)

        sale = {"created_at": "2026-09-29T21:21:00Z", "number": 1,
                "customer": "", "is_cash": True, "net_total": 300000,
                "shift": {"number": 1, "closed": False}, "items": []}
        with patch.object(history, "datetime", LocalClock):
            listing = ReturnSaleListDialog([sale])
            detail = ReturnDetailDialog(sale)
            try:
                labels = [w.text() for w in listing.findChildren(QLabel)]
                self.assertIn("02:21", labels)
                labels = [w.text() for w in detail.findChildren(QLabel)]
                self.assertIn("2026-09-30  02:21", labels)
            finally:
                listing.close(); detail.close()


class SessionEventsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_queued_old_rejection_cannot_log_out_resumed_cashier(self):
        import threading
        from types import SimpleNamespace
        from .session_events import SessionEvents
        hub = SimpleNamespace(session="before-resume")
        lost, renewed = [], []
        events = SessionEvents(hub, renewed.append, lost.append)
        thread = threading.Thread(target=lambda: events.lost.emit("expired", "before-resume"))
        thread.start(); thread.join()
        hub.session = "after-resume"
        self.app.processEvents()
        self.assertEqual(lost, [])
        events.renewed.emit("obsolete-renewal", "before-resume")
        self.assertEqual(renewed, [])
        events.renewed.emit("valid-renewal", "after-resume")
        self.assertEqual(renewed, ["valid-renewal"])
        events.lost.emit("revoked", "after-resume")
        self.assertEqual(lost, ["revoked"])

    def test_reply_after_logout_cannot_restore_session(self):
        from types import SimpleNamespace
        from .session_events import SessionEvents
        hub = SimpleNamespace(session="")
        renewed, lost = [], []
        events = SessionEvents(hub, renewed.append, lost.append)
        events.renewed.emit("old-renewal", "previous-login")
        events.lost.emit("old-error", "previous-login")
        self.assertEqual((renewed, lost), ([], []))


class WeightCommaTest(unittest.TestCase):
    """Vaznli tovar miqdori: vergul bilan kiloda terish (2026-10-06)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, weight=True):
        from decimal import Decimal
        from types import SimpleNamespace
        from .ui.dialogs import QuantityDialog
        product = SimpleNamespace(name="kolbasa", price=5999000, is_weight=weight)
        return QuantityDialog(SimpleNamespace(product=product, quantity=Decimal("1")))

    def type(self, d, keys):
        for k in keys:
            if k == ",":
                d.on_comma()
            elif k == "<":
                d.on_backspace()
            else:
                d.on_digit(k)
        return d.quantity

    def test_vergulsiz_gramm_avvalgidek(self):
        from decimal import Decimal
        self.assertEqual(self.type(self.dialog(), "734"), Decimal("0.734"))
        self.assertEqual(self.type(self.dialog(), "1500"), Decimal("1.5"))

    def test_vergul_bilan_kilo(self):
        from decimal import Decimal
        d = self.dialog()
        self.assertEqual(self.type(d, "1,5"), Decimal("1.5"))
        self.assertEqual(d.display.text(), "1.500 kg")
        self.assertEqual(self.type(self.dialog(), "0,734"), Decimal("0.734"))
        self.assertEqual(self.type(self.dialog(), ",25"), Decimal("0.25"))      # boshida vergul = 0,
        self.assertEqual(self.type(self.dialog(), "12,"), Decimal("12"))        # 12 kg
        self.assertEqual(self.type(self.dialog(), "2,050"), Decimal("2.05"))

    def test_grammdan_mayda_va_ikkinchi_vergul_etiborsiz(self):
        from decimal import Decimal
        self.assertEqual(self.type(self.dialog(), "1,2345"), Decimal("1.234"))   # 4-xona olinmaydi
        self.assertEqual(self.type(self.dialog(), "1,,5"), Decimal("1.5"))
        self.assertEqual(self.type(self.dialog(), "1,5,7"), Decimal("1.57"))

    def test_nol_va_bosh_qiymat_saqlanmaydi(self):
        for keys in ("", ",", "0,", "0,000", "0"):
            self.assertIsNone(self.type(self.dialog(), keys), keys)

    def test_ochirish_vergulni_ham_ochiradi(self):
        from decimal import Decimal
        d = self.dialog()
        self.assertEqual(self.type(d, "1,5<<"), Decimal("0.001"))                # yana gramm: 1
        self.assertEqual(self.type(d, "50"), Decimal("0.15"))                    # 150 g

    def test_katta_gramm_sonidan_keyin_vergul_etiborsiz(self):
        from decimal import Decimal
        self.assertEqual(self.type(self.dialog(), "1500,5"), Decimal("15.005"))  # 15005 g — vergul olinmadi

    def test_donali_tovarda_vergul_yoq(self):
        from decimal import Decimal
        from .ui.keypad import Keypad
        d = self.dialog(weight=False)
        self.assertEqual(self.type(d, "3,5"), Decimal("35"))                     # vergul e'tiborsiz
        pads = d.findChildren(Keypad)
        self.assertEqual(len(pads), 1)
        from PySide6.QtWidgets import QPushButton
        texts = [b.text() for b in pads[0].findChildren(QPushButton)]
        self.assertNotIn(",", texts)
        vaznli = self.dialog()                                                   # oyna tirik tursin
        wpad = vaznli.findChildren(Keypad)[0]
        self.assertIn(",", [b.text() for b in wpad.findChildren(QPushButton)])

    def test_oyna_kassa_ekraniga_sigadi(self):
        d = self.dialog()
        d.adjustSize()
        self.assertLessEqual(d.sizeHint().height(), 700)                         # 1366x768 da ~720 px joy
