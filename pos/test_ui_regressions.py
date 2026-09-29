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
