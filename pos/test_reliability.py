import json
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

    def test_exhausted_empty_receipt_recovers_after_restart(self):
        payload = {"local_uuid": "old-empty", "items": [], "net_total": 0,
                   "payments": []}
        self.store.queue("old-empty", payload, "2026-09-12")
        for _ in range(self.store.MAX_ATTEMPTS):
            self.store.mark_failed("old-empty", "Chek bo'sh")
        self.assertEqual(self.store.pending_count(), 0)
        self.assertEqual(self.store.unsent_count(), 1)
        path = self.store.path
        self.store.close()
        self.store = Store(path)

        class Hub:
            def send_sale(self, payload):
                raise AssertionError("Empty receipts must not reach the server")

        backend = LiveBackend(Hub(), self.store, [])
        self.assertEqual(backend.flush(), 0)
        self.assertEqual(self.store.unsent_count(), 0)
        self.assertEqual(self.store.stuck_count(), 0)
        row = self.store.db.execute("SELECT * FROM outbox WHERE local_uuid='old-empty'").fetchone()
        self.assertEqual(row["sent"], 2)
        self.assertEqual(json.loads(row["payload"]), payload)
        self.assertTrue(row["last_error"])
        self.assertEqual(backend.flush(), 0)

    def test_empty_cleanup_does_not_wait_for_network_or_batch(self):
        self.store.queue("real-first", _real_receipt("real-first"), "2026-09-12")
        self.store.queue("empty-later", {"items": [], "net_total": 0}, "2026-09-13")

        class Hub:
            def send_sale(self, payload):
                raise HubConnError("offline")

        self.assertEqual(LiveBackend(Hub(), self.store, []).flush(limit=1), 0)
        self.assertEqual(self.store.unsent_count(), 1)
        row = self.store.db.execute("SELECT sent FROM outbox WHERE local_uuid='real-first'").fetchone()
        self.assertEqual(row["sent"], 0)

    def test_cleanup_preserves_stock_money_points_and_uncertain_records(self):
        stock = {"items": [{"product_id": 1, "quantity": "1", "price": 0,
                            "total": 0}], "net_total": 0, "payments": []}
        payloads = [
            stock,
            {**stock, "gross_total": 5000, "discount_total": 5000},
            {**stock, "points_spent": 5000},
            {"items": [], "net_total": 0, "payments": [{"amount": 5000}]},
            {"items": [], "net_total": 5000},
            {"items": [], "net_total": "invalid"},
            {"items": [{"quantity": "invalid"}], "net_total": 0},
            {"items": {}},
            {"payments": {}},
        ]
        for i, payload in enumerate(payloads):
            self.store.queue(str(i), payload, "2026-09-12")
        self.store.queue("broken-json", {}, "2026-09-12")
        self.store.db.execute("UPDATE outbox SET payload='{' WHERE local_uuid='broken-json'")
        self.store.db.execute("UPDATE outbox SET attempts=?", (self.store.MAX_ATTEMPTS,))

        self.assertEqual(LiveBackend(None, self.store, []).flush(), 0)
        self.assertEqual(self.store.unsent_count(), len(payloads) + 1)
        for i, payload in enumerate(payloads):
            row = self.store.db.execute("SELECT payload, sent FROM outbox WHERE local_uuid=?", (str(i),)).fetchone()
            self.assertEqual(json.loads(row["payload"]), payload)
            self.assertEqual(row["sent"], 0)

    def test_cleanup_never_changes_already_sent_receipt(self):
        self.store.queue("delivered", {"items": [], "net_total": 0}, "2026-09-12")
        self.store.mark_sent("delivered", 42)
        self.store.discard("delivered", "stale cleanup")
        row = self.store.db.execute("SELECT sent, check_no, last_error FROM outbox").fetchone()
        self.assertEqual(tuple(row), (1, 42, ""))

    def test_junk_detektor(self):
        self.assertTrue(is_junk_receipt({"items": [], "payments": []}))
        self.assertTrue(is_junk_receipt(
            {"items": [{"quantity": "0", "total": 0}], "net_total": 0,
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

    def test_qaytarish_400_bilan_rad_etilsa_saqlanadi(self):
        """A rejected real return stays visible with its original payload."""
        class Hub:
            def send_sale(self, payload):
                raise HubError("Qaytarish asl chekdan oshib ketdi", status=400)

        ret = _real_receipt("ret-1")
        ret["kind"] = "return"
        self.store.queue("ret-1", ret, "2026-09-13")
        backend = LiveBackend(Hub(), self.store, [])
        backend.flush()
        self.assertEqual(self.store.unsent_count(), 1)
        self.assertEqual(self.store.stuck_count(), 0)

        row = self.store.db.execute("SELECT sent, payload, last_error FROM outbox").fetchone()
        self.assertEqual(row["sent"], 0)
        self.assertEqual(json.loads(row["payload"]), ret)
        self.assertIn("oshib", row["last_error"])

    def test_qaytarish_409_smena_yoq_bolsa_qayta_uriniladi(self):
        """Qaytarish 409 (smena hali ochilmagan) — keyin tuzaladi, YO'QOLMAYDI."""
        class Hub:
            def send_sale(self, payload):
                raise HubError("Ochiq smena yo'q", status=409)

        ret = _real_receipt("ret-2")
        ret["kind"] = "return"
        self.store.queue("ret-2", ret, "2026-09-13")
        backend = LiveBackend(Hub(), self.store, [])
        backend.flush()
        self.assertEqual(self.store.unsent_count(), 1)

    def test_haqiqiy_chek_rad_etilsa_qayta_uriniladi(self):
        class Hub:
            def send_sale(self, payload):
                raise HubError("Narx eskirgan")

        self.store.queue("real-2", _real_receipt("real-2"), "2026-09-13")
        backend = LiveBackend(Hub(), self.store, [])
        backend.flush()
        # Haqiqiy chek YO'QOLMAYDI — navbatда qoladi, keyin qayta uriniladi
        self.assertEqual(self.store.unsent_count(), 1)

    def test_navbatdagi_qaytarish_qaytadan_qaytarilmaydi(self):
        """Navbatда turgan qaytarish (serverга hali yetmagan) keyingi
        qaytarishда ayiriladi — bir tovar ikki marta qaytmasin."""
        backend = LiveBackend(type("H", (), {})(), self.store, [])
        # 3 dona sotilgan chekdan 3 tasi navbatда qaytarilgan
        ret = {
            "local_uuid": "r-1", "kind": "return", "origin_id": 42,
            "net_total": 15000,
            "items": [{"ms_product_id": "ms-1", "name": "Non",
                       "quantity": "3", "price": 5000, "total": 15000}],
            "payments": [{"method": "naqd", "amount": 15000}],
        }
        self.store.queue("r-1", ret, "2026-09-13")
        agg = backend.local_returned(42)
        self.assertEqual(agg.get("ms-1"), 3.0)
        # Boshqa chek uchun — bo'sh
        self.assertEqual(backend.local_returned(99), {})

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


class SubmitFlushRaceTest(unittest.TestCase):
    """`submit` yuborayotgan paytda fon `flush` o'sha chekni IKKINCHI marta
    yubormasin (2026-09-16: server logida ~200 ms farq bilan 2 ta POST)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "kassa.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_flush_yuborilayotgan_chekni_otkazib_yuboradi(self):
        store = self.store
        calls: list[str] = []

        class Hub:
            def __init__(self, bg):
                self.bg = bg

            def send_sale(self, payload):
                calls.append(payload["local_uuid"])
                if self.bg is not None:
                    # Yuborish o'rtasida fon oqimi flush qildi (o'sha store)
                    self.assertEqual_flush = self.bg.flush()
                return {"id": 1, "number": 1, "receipt_number": "1163"}

        bg_hub = Hub(None)
        bg = LiveBackend(bg_hub, store, [])
        bg.sync_shift = lambda: None
        front = LiveBackend(Hub(bg), store, [])
        front.sync_shift = lambda: None

        store.queue("u1", _real_receipt("u1"), "2026-09-16")
        front._send_now("u1", _real_receipt("u1"))

        self.assertEqual(calls, ["u1"])                 # faqat BIR marta
        self.assertEqual(front.last_receipt_number, "1163")
        self.assertEqual(store.pending_count(), 0)
        # Yuborish tugagach belgi olib tashlanadi — keyingi flush oddiy
        from pos import hub as hubmod
        self.assertNotIn("u1", hubmod._INFLIGHT)

    def test_xato_bolsa_ham_belgi_olib_tashlanadi(self):
        class Hub:
            def send_sale(self, payload):
                raise HubConnError("internet yo'q")

        backend = LiveBackend(Hub(), self.store, [])
        self.store.queue("u2", _real_receipt("u2"), "2026-09-16")
        backend._send_now("u2", _real_receipt("u2"))
        from pos import hub as hubmod
        self.assertNotIn("u2", hubmod._INFLIGHT)
        self.assertEqual(self.store.pending_count(), 1)   # navbatda qoldi, fon yuboradi


# ---------------------------------------------- internetsiz kun (smena)

METHODS = [{"code": "naqd", "name": "Naqd", "is_cash": True},
           {"code": "uzcard", "name": "UzCard", "is_cash": False}]


def _sale(uuid_: str, *, cash: int = 0, card: int = 0, tag: str,
          shift_uuid: str = "") -> dict:
    pays = []
    if cash:
        pays.append({"method": "naqd", "amount": cash})
    if card:
        pays.append({"method": "uzcard", "amount": card})
    return {
        "local_uuid": uuid_,
        "shift_local_uuid": shift_uuid,
        "gross_total": cash + card,
        "discount_total": 0,
        "points_spent": 0,
        "points_earned": 0,
        "items": [{"product_id": 1, "name": "Non", "quantity": "1",
                   "price": cash + card, "total": cash + card}],
        "payments": pays,
    }


class OfflineHub:
    """Internet uzilishini taqlid qiladi. `online=False` — tarmoq yo'q."""

    def __init__(self):
        self.online = False
        self.opened = []
        self.closed = []
        self.cash_ops = []
        self.sales = []
        self.events = []          # ketma-ketlikni tekshirish uchun
        self._next_id = 100

    def _check(self):
        if not self.online:
            raise HubConnError("internet yo'q")

    def open_shift(self, cashier_id, opening_cash, local_uuid="", opened_at=""):
        self._check()
        self._next_id += 1
        self.opened.append({"local_uuid": local_uuid, "opened_at": opened_at})
        self.events.append(("open", local_uuid))
        return {"shift": {"id": self._next_id, "number": len(self.opened),
                          "cashier": "Kassir", "opened_at": opened_at,
                          "opening_cash": opening_cash,
                          "next_receipt_number": 1}}

    def close_shift(self, counted_cash, closed_at="", local_uuid=""):
        self._check()
        self.closed.append({"closed_at": closed_at, "local_uuid": local_uuid})
        self.events.append(("close", local_uuid))
        return {"receipt_text": "SERVER HISOBOTI"}

    def cash(self, **payload):
        self._check()
        self.cash_ops.append(payload)
        return {"id": len(self.cash_ops)}

    def send_sale(self, payload):
        self._check()
        self.sales.append(payload)
        return {"id": len(self.sales), "receipt_number": str(1000 + len(self.sales))}


class OfflineShiftDayTest(unittest.TestCase):
    """Kun bo'yi internet yo'q, kechqurun keldi — hammasi joyiga tushsin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "kassa.db")
        self.hub = OfflineHub()
        self.backend = LiveBackend(self.hub, self.store, METHODS)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _offline_day(self):
        """Smenani internetsiz ochadi, sotadi, pul chiqaradi."""
        shift = self.backend.open_shift({"id": 3, "name": "Kassir"}, 100_000_00)
        tag = "loc:" + self.store.get_local_shift()["local_uuid"]
        self.store.set("history_shift_tag", tag)
        self.backend.submit = None  # to'g'ridan-to'g'ri navbatga yozamiz
        for i, (cash, card) in enumerate([(50_000_00, 0), (0, 30_000_00),
                                          (20_000_00, 0)]):
            uid = f"chek-{i}"
            self.store.queue(uid, _sale(uid, cash=cash, card=card, tag=tag,
                                        shift_uuid=self.store.get_local_shift()["local_uuid"]),
                             f"2026-09-21T1{i}:00:00+00:00")
        self.backend.cash("out", 10_000_00)
        return shift, tag

    def test_shift_opens_without_internet(self):
        shift, _ = self._offline_day()
        self.assertIsNone(shift["id"])
        self.assertEqual(shift["number"], "—")
        self.assertTrue(self.store.get_local_shift()["offline"])

    def test_cash_move_does_not_block_anything(self):
        self._offline_day()
        # Eski xatti-harakat: bayroq qolib, smena yopilmay qolardi
        self.assertFalse(self.store.get("pending_cash_operation"))

    def test_local_report_counts_everything(self):
        from pos.smena import build_shift_receipt
        _, tag = self._offline_day()
        r = build_shift_receipt(
            self.store, METHODS, market="Sevimli", point="Shahar",
            register="Kassa-1", cashier="Kassir", shift_no="—",
            opened_at="2026-09-21T08:00:00+00:00",
            closed_at="2026-09-21T20:00:00+00:00",
            opening_cash=100_000_00, shift_tag=tag)
        self.assertEqual(r.receipts_count, 3)
        self.assertEqual(r.gross_total, 100_000_00)
        self.assertEqual(r.cash_total, 70_000_00)
        self.assertEqual(r.cashless_total, 30_000_00)
        self.assertEqual(r.cash_out, 10_000_00)
        # Razmen + naqd savdo - chiqarilgan
        self.assertEqual(r.expected_cash, 160_000_00)
        self.assertEqual(r.to_hand_over, 60_000_00)

    def test_close_offline_then_sync_in_the_evening(self):
        _, tag = self._offline_day()
        result = self.backend.close_shift(None, local_text="MAHALLIY HISOBOT")
        self.assertTrue(result["offline"])
        self.assertEqual(result["receipt_text"], "MAHALLIY HISOBOT")
        self.assertEqual(len(self.store.closed_shifts()), 1)

        # --- kechqurun internet keldi
        self.hub.online = True
        for _ in range(4):           # bir necha fon aylanishi
            self.backend.flush()

        self.assertEqual(len(self.hub.opened), 1)
        self.assertEqual(len(self.hub.sales), 3)
        self.assertEqual(len(self.hub.cash_ops), 1)
        self.assertEqual(len(self.hub.closed), 1)
        # Smena O'Z vaqti bilan yopildi, ulanish tiklangan vaqt bilan emas
        self.assertEqual(self.hub.closed[0]["closed_at"], result["closed_at"])
        # Navbat bo'sh, mahalliy belgilar tozalandi
        self.assertEqual(self.store.closed_shifts(), [])
        self.assertIsNone(self.store.get_local_shift())
        self.assertEqual(self.store.unsent_count(), 0)

    def test_shift_closes_before_the_next_one_opens(self):
        """Ikki kun internetsiz: smenalar serverda aralashib ketmasin."""
        _, tag1 = self._offline_day()
        self.backend.close_shift(None, local_text="1")
        # Ertasiga yana internetsiz ochildi
        self.backend.open_shift({"id": 3, "name": "Kassir"}, 100_000_00)
        self.store.set("history_shift_tag",
                       "loc:" + self.store.get_local_shift()["local_uuid"])
        self.assertIsNotNone(self.store.get_local_shift())

        self.hub.online = True
        for _ in range(4):
            self.backend.flush()
        self.assertEqual(len(self.hub.closed), 1)
        self.assertEqual(len(self.hub.opened), 2)
        # ENG MUHIMI: eski smena yangisidan OLDIN yopilgan bo'lsin.
        # Aks holda server yangi smena deb eskisini qaytarib yuborardi.
        kinds = [kind for kind, _ in self.hub.events]
        self.assertEqual(kinds, ["open", "close", "open"])
        self.assertEqual(self.store.closed_shifts(), [])

    def test_online_shift_closed_offline_syncs_too(self):
        """Smena onlayn ochilgan, kunduzi internet uzildi, oqshom yopildi."""
        self.hub.online = True
        self.backend.open_shift({"id": 3, "name": "Kassir"}, 100_000_00)
        self.assertEqual(self.store.get("active_shift_id"), "101")
        self.hub.online = False
        self.backend.close_shift(None, local_text="MAHALLIY")
        record = self.store.closed_shifts()[0]
        self.assertEqual(record["server_id"], 101)

        self.hub.online = True
        self.backend.flush()
        self.assertEqual(len(self.hub.closed), 1)
        self.assertEqual(len(self.hub.opened), 1)   # qayta ochilmadi
