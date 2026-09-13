import tempfile
import unittest
from pathlib import Path
from pos.store import Store
from pos.hub import LiveBackend, HubConnError, HubError, is_junk_receipt


def _real_receipt(uuid_: str) -> dict:
    """Haqiqiy (bo'sh bo'lmagan) chek — tovari ham, to'lovi ham bor."""
    return {
        "local_uuid": uuid_,
        "shift_id": 7,
        "net_total": 5000,
        "items": [{"product_id": 1, "name": "Non", "quantity": "1",
                   "price": 5000, "total": 5000}],
        "payments": [{"method": "naqd", "amount": 5000}],
    }


class OutboxRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "kassa.db")
        self.store.queue("receipt-1", _real_receipt("receipt-1"), "2026-09-12")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_long_outage_does_not_strand_receipt(self):
        class Hub:
            online = False
            def send_sale(self, payload):
                if not self.online:
                    raise HubConnError("offline")
                return {"id": 1}
        hub = Hub()
        backend = LiveBackend(hub, self.store, [])
        for _ in range(60):
            backend.flush()
        self.assertEqual(self.store.pending_count(), 1)
        self.assertEqual(self.store.stuck_count(), 0)
        hub.online = True
        self.assertEqual(backend.flush(), 1)
        self.assertEqual(self.store.unsent_count(), 0)

    def test_stuck_receipts_remain_visible(self):
        for _ in range(20):
            self.store.mark_failed("receipt-1", "invalid price")
        self.assertEqual(self.store.unsent_count(), 1)
        self.assertEqual(self.store.pending_count(), 0)
        self.store.retry_stuck()
        self.assertEqual(self.store.pending_count(), 1)

    def test_offline_shift_is_bound_before_queue(self):
        self.store.set_local_shift({"local_uuid": "offline-shift"})
        payload = {}
        LiveBackend(None, self.store, [])._bind_shift(payload)
        self.assertEqual(payload["shift_local_uuid"], "offline-shift")

    def test_online_shift_is_bound_before_queue(self):
        self.store.set("active_shift_id", "7")
        payload = {}
        LiveBackend(None, self.store, [])._bind_shift(payload)
        self.assertEqual(payload["shift_id"], 7)


class JunkReceiptTest(unittest.TestCase):
    """0 summali bo'sh chek navbatni to'smasin (qaytarishdan qolgan artefakt)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "kassa.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_junk_detektor(self):
        self.assertTrue(is_junk_receipt({"items": [], "payments": []}))
        self.assertTrue(is_junk_receipt(
            {"items": [{"x": 1}], "net_total": 0,
             "payments": [{"method": "naqd", "amount": 0}]}))
        self.assertFalse(is_junk_receipt(_real_receipt("r")))
        # Faqat ball bilan to'langan chek — bo'sh EMAS
        self.assertFalse(is_junk_receipt(
            {"items": [{"x": 1}], "net_total": 0, "points_spent": 500,
             "payments": []}))

    def test_flush_bosh_chekni_yubormaydi_va_navbatdan_chiqaradi(self):
        sent_payloads = []

        class Hub:
            def send_sale(self, payload):
                sent_payloads.append(payload)
                return {"id": 1}

        self.store.queue("junk-1", {"local_uuid": "junk-1", "net_total": 0,
                                    "items": [], "payments": []}, "2026-09-13")
        self.store.queue("real-1", _real_receipt("real-1"), "2026-09-13")
        backend = LiveBackend(Hub(), self.store, [])
        sent = backend.flush()
        # Faqat haqiqiy chek yuboriladi
        self.assertEqual(sent, 1)
        self.assertEqual([p["local_uuid"] for p in sent_payloads], ["real-1"])
        # Bo'sh chek ham, haqiqiy chek ham navbatда qolmaydi
        self.assertEqual(self.store.unsent_count(), 0)
        self.assertEqual(self.store.pending_count(), 0)

    def test_server_bosh_chekni_rad_etsa_qayta_urinmaydi(self):
        class Hub:
            def send_sale(self, payload):
                raise HubError("Chek bo'sh")

        self.store.queue("junk-2", {"local_uuid": "junk-2", "net_total": 0,
                                    "items": [], "payments": []}, "2026-09-13")
        backend = LiveBackend(Hub(), self.store, [])
        backend.flush()
        # Chetга chiqarilgan — endi navbatда ham, «tiqilib qolgan»да ham yo'q
        self.assertEqual(self.store.unsent_count(), 0)
        self.assertEqual(self.store.stuck_count(), 0)

    def test_haqiqiy_chek_rad_etilsa_qayta_uriniladi(self):
        class Hub:
            def send_sale(self, payload):
                raise HubError("Narx eskirgan")

        self.store.queue("real-2", _real_receipt("real-2"), "2026-09-13")
        backend = LiveBackend(Hub(), self.store, [])
        backend.flush()
        # Haqiqiy chek YO'QOLMAYDI — navbatда qoladi, keyin qayta uriniladi
        self.assertEqual(self.store.unsent_count(), 1)

    def test_0_summali_qaytarish_saqlanmaydi(self):
        class Hub:
            pass
        backend = LiveBackend(Hub(), self.store, [])
        origin = {"id": 1, "number": 5}
        lines = [{"item": {"product_id": 1, "name": "Non", "price": 0}, "qty": 1}]
        with self.assertRaises(HubError):
            backend.submit_return(origin, lines, "naqd")
        self.assertEqual(self.store.unsent_count(), 0)


if __name__ == "__main__":
    unittest.main()
