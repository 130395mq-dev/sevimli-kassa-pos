import tempfile
import unittest
from pathlib import Path
from pos.store import Store
from pos.hub import LiveBackend, HubConnError

class OutboxRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "kassa.db")
        self.store.queue("receipt-1", {"local_uuid":"receipt-1", "shift_id":7}, "2026-09-12")
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def test_long_outage_does_not_strand_receipt(self):
        class Hub:
            online = False
            def send_sale(self, payload):
                if not self.online:
                    raise HubConnError("offline")
                return {"id":1}
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
        self.store.set_local_shift({"local_uuid":"offline-shift"})
        payload = {}
        LiveBackend(None, self.store, [])._bind_shift(payload)
        self.assertEqual(payload["shift_local_uuid"], "offline-shift")
    def test_online_shift_is_bound_before_queue(self):
        self.store.set("active_shift_id", "7")
        payload = {}
        LiveBackend(None, self.store, [])._bind_shift(payload)
        self.assertEqual(payload["shift_id"], 7)

if __name__ == "__main__":
    unittest.main()
