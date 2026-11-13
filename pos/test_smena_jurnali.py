"""«Smena — kassaniki» testlari (1.19.0).

Egasining talabi (12.11.2026): smena ochilib-yopilganda kassada internet
bor-yo'qligidan qat'i nazar kassa BIR XIL ishlasin va o'zidagi cheklarni
xato bilan boshqa smenaga o'tkazmasin.

O'sha kuni internetsiz yopilgan smenaga dastur ertalab qayta kirib ketdi
(server «smena hali ochiq» degan), fon oqimi smenani serverda yopdi va
136 ta chek «Ochiq smena yo'q» deb rad etildi. Bu fayl o'sha holatni va
uning qarindoshlarini (ertalab ham internet yo'q, dastur qayta ochildi,
ikki kun internetsiz…) qadam-baqadam takrorlaydi.

`SoxtaServer` — serverning smena/chek qoidalari (api/views.py) nusxasi:
`himoya=False` — 12.11.2026 dagi server, `himoya=True` — himoyali server.
Kassa IKKALASI bilan ham to'g'ri ishlashi shart.

    python -m unittest pos.test_smena_jurnali
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pos.hub as hubmod
from pos.cart import Cart, PaymentPlan
from pos.hub import HubAuthError, HubConnError, HubError, LiveBackend
from pos.store import Store

METHODS = [{"code": "naqd", "name": "Naqd", "is_cash": True}]
PRODUCTS = [{"id": 1, "ms_id": "ms-1", "name": "Non", "code": "0001",
             "barcode": "478", "price": 5_000_00, "is_weight": False,
             "plu": None, "tracked": False, "stock": 100}]
GRACE = timedelta(minutes=5)


class Soat:
    """Qo'lda yuritiladigan soat: «kecha» va «bugun»ni ajratish uchun."""

    def __init__(self):
        self.t = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)     # 08:00 Toshkent

    def keyin(self, **kw):
        self.t += timedelta(**kw)

    def iso(self) -> str:
        return self.t.isoformat()


class SoxtaServer:
    """Serverning smena va chek qoidalari (qisqa nusxa)."""

    def __init__(self, soat: Soat, himoya: bool = True):
        self.soat, self.himoya = soat, himoya
        self.online = True
        self.shifts: list[dict] = []
        self.sales: dict[str, int] = {}      # chek belgisi -> smena id
        self.cash_ops: dict[str, int] = {}   # amal belgisi -> smena id
        self.calls: list[tuple] = []         # (amal, kod)
        self.reject_sales: set[str] = set()  # shu cheklar 400 bilan rad etiladi
        self.reject_open = ""                # bo'sh emas — smena ochish 409
        self.cash_status = 0                 # 0 — odatdagidek; aks holda shu kod
        self.fail_close = None               # istisno — smena yopish shu bilan rad etiladi

    # -- yordamchi
    def _net(self):
        if not self.online:
            raise HubConnError("Serverga ulanib bo'lmadi: internet yo'q")

    def _fail(self, what, text, status):
        self.calls.append((what, status))
        raise HubError(text, status=status)

    def _open(self):
        return next((s for s in self.shifts if s["status"] == "open"), None)

    def _by_uuid(self, key):
        return next((s for s in self.shifts if key and s["uuid"] == key), None)

    def _by_id(self, pk):
        return next((s for s in self.shifts if s["id"] == pk), None)

    def _json(self, s):
        return {"id": s["id"], "number": s["number"], "cashier": "Kassir",
                "opened_at": s["opened_at"].isoformat(), "opening_cash": s["opening_cash"],
                "next_receipt_number": len(s["sales"]) + 1}

    def _new(self, uuid_, opened_at, opening_cash, auto=False):
        s = {"id": 100 + len(self.shifts) + 1, "number": len(self.shifts) + 1,
             "status": "open", "uuid": uuid_, "sales": [], "cash": [], "closed_at": None,
             "opened_at": opened_at, "opening_cash": opening_cash, "auto": auto,
             "claimed": False}
        self.shifts.append(s)
        return s

    def codes(self, what):
        return [c for w, c in self.calls if w == what]

    # -- hello
    def hello(self, queue=None):
        self._net()
        s = self._open()
        return {"shift": self._json(s) if s else None, "payment_methods": METHODS}

    # -- shift/open
    def open_shift(self, cashier_id, opening_cash, local_uuid="", opened_at=""):
        self._net()
        if self.reject_open:
            self._fail("open", self.reject_open, 409)
        same = self._by_uuid(local_uuid)
        if same:
            self.calls.append(("open", 200))
            return {"shift": self._json(same)}
        when = datetime.fromisoformat(opened_at) if opened_at else self.soat.t
        cur = self._open()
        if cur:
            if self.himoya and cur["auto"] and not cur["claimed"]:
                cur.update(claimed=True, opening_cash=opening_cash)
                cur["uuid"] = cur["uuid"] or local_uuid
                self.calls.append(("open", 200))
                return {"shift": self._json(cur)}
            if local_uuid:                      # «allaqachon ochiq» — o'shani qabul qiladi
                cur["uuid"] = cur["uuid"] or local_uuid
                self.calls.append(("open", 200))
                return {"shift": self._json(cur)}
            self._fail("open", "Bu kassada ochiq smena bor", 409)
        s = self._new(local_uuid, when, opening_cash)
        self.calls.append(("open", 201))
        return {"shift": self._json(s)}

    # -- shift/close
    def close_shift(self, counted_cash, closed_at="", local_uuid="", shift_id=None):
        self._net()
        if self.fail_close is not None:
            self.calls.append(("close", self.fail_close.status))
            raise self.fail_close
        if local_uuid:
            s = self._by_uuid(local_uuid)
            if s is None:
                self._fail("close", "Bu smena kassada topilmadi", 409)
            if s["status"] == "closed":
                self.calls.append(("close", 200))
                return {"receipt_text": "Z", "shift_id": s["id"]}
        else:
            s = self._open()
            if not s:
                if self.himoya:
                    self.calls.append(("close", 200))
                    return {"receipt_text": "SMENA ALLAQACHON YOPILGAN", "already_closed": True}
                self._fail("close", "Ochiq smena yo'q", 409)
        at = datetime.fromisoformat(closed_at) if closed_at else None
        now = self.soat.t
        s["closed_at"] = at if (at and s["opened_at"] <= at <= now) else now
        s["status"] = "closed"
        self.calls.append(("close", 200))
        return {"receipt_text": "Z", "shift_id": s["id"]}

    # -- sales
    def send_sale(self, payload):
        self._net()
        key = payload["local_uuid"]
        if key in self.sales:
            self.calls.append(("sale", 200))
            return {"id": 1, "number": 1, "receipt_number": "OT-1", "duplicate": True}
        if key in self.reject_sales:
            self._fail("sale", "Narx eskirgan", 400)
        created = datetime.fromisoformat(payload["created_at"])
        late = False
        shift = None
        if payload.get("shift_id"):
            shift = self._by_id(payload["shift_id"])
            if shift is None:
                self._fail("sale", "Chek smenasi bu kassada topilmadi", 409)
        elif payload.get("shift_local_uuid"):
            shift = self._by_uuid(payload["shift_local_uuid"])
            if shift is None:
                self._fail("sale", "Chek smenasi bu kassada topilmadi", 409)
        else:
            cands = sorted((s for s in self.shifts if s["opened_at"] <= created),
                           key=lambda s: s["opened_at"], reverse=True)
            shift = cands[0] if cands else None
            if shift and shift["closed_at"] and created > shift["closed_at"]:
                shift = None
        if shift is not None and shift["closed_at"] and created > shift["closed_at"] + GRACE:
            cur = self._open()
            if cur and cur["id"] != shift["id"]:
                shift = cur                     # _shift_for_created_at
        if not shift:
            shift = self._open()
            late = True
        if not shift:
            if not self.himoya:
                self._fail("sale", "Ochiq smena yo'q", 409)
            shift = self._new("", created if created <= self.soat.t else self.soat.t, 0, auto=True)
            late = False
        if shift["status"] != "open":
            late = True
        shift["sales"].append((key, late))
        self.sales[key] = shift["id"]
        self.calls.append(("sale", 201))
        n = len(self.sales)
        return {"id": n, "number": n, "receipt_number": f"OT-{n:04d}"}

    # -- cash
    def cash(self, kind="", amount=0, comment="", local_uuid="", shift_id=None,
             created_at="", shift_local_uuid=""):
        self._net()
        if self.cash_status:
            self._fail("cash", "Pul amali qabul qilinmadi", self.cash_status)
        if local_uuid in self.cash_ops:
            self.calls.append(("cash", 200))
            return {"id": 1, "duplicate": True}
        shift = self._open()
        if self.himoya:
            if shift_id and (shift is None or shift["id"] != shift_id):
                shift = self._by_id(shift_id)
                if shift is None:
                    self._fail("cash", "Pul amali smenasi bu kassada topilmadi", 409)
            if shift is None:
                shift = self._new("", self.soat.t, 0, auto=True)
        else:
            if not shift:
                self._fail("cash", "Ochiq smena yo'q", 409)
            if shift_id and shift_id != shift["id"]:
                self._fail("cash", "Pul amali boshqa smenaga tegishli", 409)
        shift["cash"].append((local_uuid, kind, amount))
        self.cash_ops[local_uuid] = shift["id"]
        self.calls.append(("cash", 201))
        return {"id": len(self.cash_ops)}


class Kassa:
    """Kassa ilovasi: haqiqiy `Store` + `LiveBackend`, oyna o'rniga —
    pos/main.py qiladigan qadamlar."""

    def __init__(self, server, soat, folder=None):
        self.server, self.soat = server, soat
        self._own = folder is None
        self.folder = folder or tempfile.TemporaryDirectory()
        self.db = Path(self.folder.name) / "kassa.db"
        self._boot()

    def _boot(self):
        self.store = Store(self.db)
        if self.store.product_count() == 0:
            self.store.replace_products(PRODUCTS)
        self.backend = LiveBackend(self.server, self.store, METHODS)
        self.bg_store = Store(self.db)
        self.bg = LiveBackend(self.server, self.bg_store, METHODS)

    def close(self):
        self.store.close()
        self.bg_store.close()
        if self._own:
            self.folder.cleanup()

    def restart(self):
        """Dastur yopilib qayta ochildi (kompyuter o'chib-yondi)."""
        self.store.close()
        self.bg_store.close()
        self._boot()
        # pos/main.py: server HOZIR javob bergan bo'lsa (keshdan emas) — jurnaldagi
        # ochiq smena u yerda yopilgan-yopilmagani tekshiriladi.
        try:
            info = self.server.hello()
        except HubConnError:
            info = None
        if info is not None:
            self.backend.drop_shift_closed_elsewhere(info.get("shift"))
        return self.backend.current_shift()

    def open_shift(self, cash=100_000_00):
        return self.backend.open_shift({"id": 3, "name": "Kassir"}, cash)

    def fon(self, n=1):
        """Fon oqimining bir aylanishi (pos/main.py `_bg_loop`)."""
        sent = 0
        for _ in range(n):
            self.bg.sync_shift()
            sent += self.bg.flush()
            # ... va har 15 soniyadagi hello: smena boshqa joydan yopilganmi
            before = self.bg_store.journal_current()
            try:
                info = self.server.hello()
            except HubConnError:
                continue
            self.bg.note_server_shift(info.get("shift"), before)
        return sent

    def sell(self, n=1, gap=60):
        ids = []
        for _ in range(n):
            cart = Cart()
            cart.add(self.store.by_barcode("478"))
            plan = PaymentPlan(total=cart.total)
            plan.add_cash(cart.total)
            self.backend.submit(cart, plan)
            ids.append(self.store.recent_sales(1)[0]["local_uuid"])
            self.fon()
            self.soat.keyin(seconds=gap)
        return ids

    def close_shift(self):
        res = self.backend.finish_shift(None, "KASSA HISOBOTI")
        self.fon()
        return res


class JurnalBase(unittest.TestCase):
    HIMOYA = True

    def setUp(self):
        self.soat = Soat()
        soat = self.soat

        class _DT(datetime):
            @classmethod
            def now(cls, tz=None):
                return soat.t

        for target in ("pos.hub.datetime", "pos.store.datetime"):
            p = mock.patch(target, _DT)
            p.start()
            self.addCleanup(p.stop)
        self.server = SoxtaServer(self.soat, himoya=self.HIMOYA)
        self.k = Kassa(self.server, self.soat)
        self.addCleanup(self.k.close)

    # -- qulaylik
    def shift(self, n):
        return self.server.shifts[n - 1]

    def counts(self):
        return [len(s["sales"]) for s in self.server.shifts]


class BirXilIshlashTest(JurnalBase):
    """Talabning o'zi: internet bor-yo'qligidan qat'i nazar natija bir xil."""

    def _ikki_kun(self, online: bool):
        k, soat, server = self.k, self.soat, self.server
        server.online = online
        vaqtlar = []
        s1 = k.open_shift(100_000_00)
        vaqtlar.append(soat.iso())
        k.sell(5)
        k.backend.cash("out", 20_000_00, "inkassatsiya")
        soat.keyin(hours=12)
        k.close_shift()
        vaqtlar.append(soat.iso())
        soat.keyin(hours=9)
        k.restart()
        s2 = k.open_shift(150_000_00)
        vaqtlar.append(soat.iso())
        k.sell(2)
        soat.keyin(hours=12)
        k.close_shift()
        vaqtlar.append(soat.iso())
        server.online = True                      # (oflayn bo'lsa) internet keldi
        soat.keyin(minutes=30)
        k.fon(4)
        return s1, s2, vaqtlar

    def _server_holati(self):
        return [(s["status"], len(s["sales"]), len(s["cash"]), s["opening_cash"],
                 s["opened_at"].isoformat(), s["closed_at"].isoformat())
                for s in self.server.shifts]

    def test_onlayn_va_oflayn_natija_bir_xil(self):
        _, _, vaqt_onlayn = self._ikki_kun(online=True)
        onlayn = self._server_holati()
        chaqiruv_onlayn = [w for w, _ in self.server.calls if w in ("open", "close")]

        self.k.close()                            # yangi kassa, yangi server — oflayn kun
        self.soat.t = Soat().t
        self.server = SoxtaServer(self.soat, himoya=self.HIMOYA)
        self.k = Kassa(self.server, self.soat)
        self.addCleanup(self.k.close)
        _, _, vaqt_oflayn = self._ikki_kun(online=False)
        oflayn = self._server_holati()
        chaqiruv_oflayn = [w for w, _ in self.server.calls if w in ("open", "close")]

        self.assertEqual(vaqt_onlayn, vaqt_oflayn)
        self.assertEqual(onlayn, oflayn)          # smenalar, cheklar, razmen, vaqtlar
        self.assertEqual(len(onlayn), 2)
        self.assertEqual([row[:4] for row in onlayn],
                         [("closed", 5, 1, 100_000_00), ("closed", 2, 0, 150_000_00)])
        self.assertEqual(chaqiruv_onlayn, ["open", "close", "open", "close"])
        self.assertEqual(chaqiruv_oflayn, ["open", "close", "open", "close"])
        self.assertEqual(self.k.store.unsent_count(), 0)
        self.assertNotIn(409, [c for _, c in self.server.calls])

    def test_kassa_ekrani_ham_bir_xil(self):
        """Kassir ko'radigan narsa: ochish darhol, yopish darhol, keyingi
        ochish darhol — server bor-yo'qligiga qaramay."""
        for online in (True, False):
            with self.subTest(online=online):
                self.server.online = online
                sh = self.k.open_shift()
                self.assertEqual(self.k.backend.current_shift()["uuid"], sh["uuid"])
                res = self.k.backend.finish_shift(None, "HISOBOT")
                self.assertEqual(res["receipt_text"], "HISOBOT")
                self.assertIsNone(self.k.backend.current_shift())

    def test_ochish_va_yopish_tarmoqqa_murojaat_qilmaydi(self):
        """Oyna hech qachon serverni kutmaydi — server osilib qolsa ham."""
        class Osilgan:
            def __getattr__(self, name):
                raise AssertionError(f"oyna oqimida tarmoq so'rovi: {name}")

        self.k.backend.hub = Osilgan()
        sh = self.k.backend.open_shift({"id": 1, "name": "K"}, 50_000_00)
        self.assertEqual(sh["opening_cash"], 50_000_00)
        self.assertIsNotNone(self.k.backend.current_shift())
        self.k.backend.finish_shift(None, "x")
        self.assertIsNone(self.k.backend.current_shift())


class OnIkkinchiNoyabrTest(JurnalBase):
    """12.11.2026 hodisasi va qarindoshlari — yangi kassada."""

    def _kecha(self):
        k = self.k
        sh = k.open_shift()
        kechagi = k.sell(3, gap=1800)
        self.assertEqual(self.counts(), [3])
        self.soat.keyin(hours=13)                 # ~23:30
        self.server.online = False                # internet uzildi
        yopildi = self.soat.iso()
        k.close_shift()
        self.assertEqual(self.shift(1)["status"], "open")       # serverda hali ochiq
        self.soat.keyin(hours=8, minutes=40)      # ertalab
        return sh, kechagi, yopildi

    def test_ertalab_internet_bor(self):
        k = self.k
        sh, kechagi, yopildi = self._kecha()
        self.server.online = True
        # Dastur ochildi. Server «smena #1 ochiq» deydi — kassa unga QARAMAYDI.
        self.assertEqual(self.server.hello()["shift"]["id"], self.shift(1)["id"])
        self.assertIsNone(k.restart())            # yopilgan smenaga qayta kirmaydi
        k.fon()                                   # fon: kechagi smena o'z vaqti bilan yopiladi
        self.assertEqual(self.shift(1)["status"], "closed")
        self.assertEqual(self.shift(1)["closed_at"].isoformat(), yopildi)

        bugun = k.open_shift(120_000_00)          # «SMENA OCHISH» — razmen so'raladi
        self.assertNotEqual(bugun["uuid"], sh["uuid"])
        bugungi = k.sell(40)
        self.assertEqual(self.server.codes("sale"), [201] * 43)  # birorta rad yo'q
        self.assertEqual(self.counts(), [3, 40])
        self.assertEqual(self.shift(2)["opening_cash"], 120_000_00)
        self.assertEqual({self.server.sales[u] for u in kechagi}, {self.shift(1)["id"]})
        self.assertEqual({self.server.sales[u] for u in bugungi}, {self.shift(2)["id"]})
        self.assertEqual(k.store.unsent_count(), 0)
        self.assertEqual(k.store.stuck_count(), 0)
        k.close_shift()
        self.assertEqual(self.shift(2)["status"], "closed")
        self.assertFalse(any(s["auto"] for s in self.server.shifts))

    def test_ertalab_ham_internet_yoq(self):
        """B varianti: eski kassa bugungi savdoni kechagi smenaga yozardi."""
        k = self.k
        _, kechagi, yopildi = self._kecha()
        self.assertIsNone(k.restart())            # keshga ham qaramaydi
        k.open_shift()
        bugungi = k.sell(5, gap=600)
        self.assertEqual(k.store.unsent_count(), 5)
        self.server.online = True
        k.fon(3)
        self.assertEqual([w for w, _ in self.server.calls if w in ("open", "close")][-2:],
                         ["close", "open"])       # avval kechagisi yopildi, keyin yangisi ochildi
        self.assertEqual(self.counts(), [3, 5])   # kechagi smenaga bugungi chek TUSHMADI
        self.assertEqual(self.shift(1)["closed_at"].isoformat(), yopildi)
        self.assertEqual({self.server.sales[u] for u in bugungi}, {self.shift(2)["id"]})
        k.sell(25)
        self.assertEqual(self.counts(), [3, 30])
        self.assertNotIn(409, [c for _, c in self.server.calls])
        self.assertEqual(k.store.unsent_count(), 0)

    def test_onlayn_yopilib_darhol_ochirilsa(self):
        """C varianti: kesh eskirgan («smena ochiq») — kassa unga qaramaydi."""
        k = self.k
        k.open_shift()
        k.sell(3)
        k.store.set("last_hello", json.dumps(self.server.hello()))   # keshda smena ochiq
        self.soat.keyin(hours=13)
        k.close_shift()                           # onlayn: fon serverda ham yopdi
        self.assertEqual(self.shift(1)["status"], "closed")
        self.assertIsNotNone(json.loads(k.store.get("last_hello"))["shift"])
        self.soat.keyin(hours=9)
        self.server.online = False
        self.assertIsNone(k.restart())            # arvoh smena yo'q
        k.open_shift()
        k.sell(4)
        self.server.online = True
        k.fon(2)
        self.assertEqual(self.counts(), [3, 4])
        self.assertFalse(any(late for s in self.server.shifts for _, late in s["sales"]))

    def test_smena_ortasida_qayta_ochilsa_davom_etadi(self):
        k = self.k
        sh = k.open_shift(80_000_00)
        k.sell(4)
        self.server.online = False
        k.sell(2)
        again = k.restart()                       # tok o'chib-yondi, internet yo'q
        self.assertEqual(again["uuid"], sh["uuid"])
        self.assertEqual(again["opening_cash"], 80_000_00)
        self.assertEqual(again["next_receipt_number"], 7)
        k.sell(3)
        self.server.online = True
        k.fon(2)
        self.assertEqual(self.counts(), [9])
        self.assertEqual(len(self.server.shifts), 1)

    def test_ikki_kun_internetsiz(self):
        k = self.k
        self.server.online = False
        for kun, n in enumerate((4, 6), 1):
            k.restart()
            k.open_shift(100_000_00 * kun)
            k.sell(n)
            self.soat.keyin(hours=12)
            k.close_shift()
            self.soat.keyin(hours=11)
        self.assertEqual(self.server.shifts, [])
        self.server.online = True
        k.fon(5)
        self.assertEqual([w for w, _ in self.server.calls if w in ("open", "close")],
                         ["open", "close", "open", "close"])
        self.assertEqual(self.counts(), [4, 6])
        self.assertEqual([s["opening_cash"] for s in self.server.shifts],
                         [100_000_00, 200_000_00])
        self.assertTrue(all(s["status"] == "closed" for s in self.server.shifts))
        self.assertLess(self.shift(1)["closed_at"], self.shift(2)["opened_at"])
        self.assertEqual(k.store.journal_pending(), [])

    def test_kech_yetgan_chek_oz_smenasida_qoladi(self):
        """Chek o'z smenasi YOPILGANDAN keyin serverga yetsa ham — o'sha
        smenaga yoziladi, hozir ochiq smenaga emas."""
        k = self.k
        k.open_shift()
        birinchi = k.sell(2)
        self.server.online = False
        kechikkan = k.sell(3)                     # internet yo'q — navbatda
        # Smena yopildi, yangisi ochildi; eski smenaning cheklari hali kassada.
        # Ular ataylab «tiqilgan» qilinadi — smena ularni kutmasdan yopilsin.
        for u in kechikkan:
            for _ in range(Store.MAX_ATTEMPTS):
                k.store.mark_failed(u, "sinov: vaqtincha rad")
        self.soat.keyin(hours=12)
        k.close_shift()
        self.soat.keyin(hours=10)
        k.open_shift()
        self.assertEqual(k.store.stuck_count(), 3)
        self.server.online = True
        k.fon(3)                                  # tiqilganlar vaqti kelib, o'zi ketdi
        yangi = k.sell(2)
        self.assertEqual(self.shift(1)["status"], "closed")
        self.assertEqual(self.counts(), [5, 2])   # o'z smenasiga, yangi smenaga emas
        self.assertEqual({self.server.sales[u] for u in kechikkan + birinchi},
                         {self.shift(1)["id"]})
        self.assertEqual({self.server.sales[u] for u in yangi}, {self.shift(2)["id"]})
        self.assertEqual(k.store.unsent_count(), 0)


class EskiServerBilanTest(OnIkkinchiNoyabrTest, BirXilIshlashTest):
    """Xuddi shu ssenariylar — 12.11.2026 dagi (himoyasiz) server bilan.
    Kassa serverdan oldin ham, keyin ham chiqarilishi mumkin."""

    HIMOYA = False


class SmenaTayyorEmasTest(JurnalBase):
    """Smena hali serverga ochilmagan bo'lsa cheklari kutadi — rad etilmaydi."""

    def test_server_smenani_rad_etsa_cheklar_kutadi(self):
        k = self.k
        self.server.reject_open = "«Kassa-1» uchun ombor tanlanmagan."
        k.open_shift()
        k.sell(3)
        self.assertEqual(self.server.codes("sale"), [])         # serverga yuborilmadi
        self.assertEqual(k.store.unsent_count(), 3)
        self.assertEqual(k.store.rejected_count(), 0)           # urinish sanalmadi
        self.assertEqual(k.store.stuck_count(), 0)
        self.assertIn("ombor", k.store.get("shift_sync_error"))
        self.assertIsNotNone(k.backend.current_shift())         # savdo davom etadi
        self.server.reject_open = ""                            # sozlama tuzatildi
        k.fon(2)
        self.assertEqual(self.counts(), [3])
        self.assertEqual(k.store.unsent_count(), 0)
        self.assertEqual(k.store.get("shift_sync_error"), "")

    def test_tolov_paytidagi_yuborish_avval_smenani_ochadi(self):
        """To'lov oynasi chekni shu zahoti yuboradi (`_deliver`) — smena
        hali serverda bo'lmasa avval uni ochadi."""
        k = self.k
        k.open_shift()                                          # fon hali aylanmadi
        cart = Cart()
        cart.add(k.store.by_barcode("478"))
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(cart.total)
        k.backend.submit(cart, plan)
        row = k.store.pending()[0]
        number, outage = k.backend._deliver(row["local_uuid"], json.loads(row["payload"]))
        self.assertFalse(outage)
        self.assertEqual(number, "OT-0001")
        self.assertEqual(self.server.calls, [("open", 201), ("sale", 201)])

    def test_tolov_paytida_internet_yoq_bolsa_chek_navbatda(self):
        k = self.k
        self.server.online = False
        k.open_shift()
        cart = Cart()
        cart.add(k.store.by_barcode("478"))
        plan = PaymentPlan(total=cart.total)
        plan.add_cash(cart.total)
        k.backend.submit(cart, plan)
        row = k.store.pending()[0]
        number, outage = k.backend._deliver(row["local_uuid"], json.loads(row["payload"]))
        self.assertIsNone(number)
        self.assertTrue(outage)
        self.assertEqual(k.store.rejected_count(), 0)
        self.assertTrue(k.store.queue_error().endswith(hubmod.SHIFT_NOT_READY))

    def test_ikki_oqim_bir_vaqtda_moslasa_bittasi_ishlaydi(self):
        k = self.k
        k.open_shift()
        self.assertTrue(hubmod._SHIFT_SYNC_LOCK.acquire(blocking=False))
        try:
            self.assertIsNone(k.bg.sync_shifts())               # band — kutmaydi
            self.assertEqual(self.server.calls, [])
        finally:
            hubmod._SHIFT_SYNC_LOCK.release()
        self.assertIsNotNone(k.bg.sync_shifts())
        self.assertEqual(self.server.codes("open"), [201])


class TiqilganChekTest(JurnalBase):
    """Rad etilgan chek tashlab qo'yilmaydi (ro'yxatdagi 4-band)."""

    def test_tiqilgan_chek_ozi_qayta_yuboriladi(self):
        k = self.k
        k.open_shift()
        self.server.online = False
        (u,) = k.sell(1)
        self.server.online = True
        self.server.reject_sales = {u}
        for _ in range(Store.MAX_ATTEMPTS):
            k.fon()
        self.assertEqual(k.store.stuck_count(), 1)
        self.assertEqual(k.store.rejected_count(), 1)
        self.assertEqual(k.store.rejected_reason(), "Narx eskirgan")
        urinish = len(self.server.codes("sale"))
        k.fon(5)                                                # darhol qayta urinmaydi
        self.assertEqual(len(self.server.codes("sale")), urinish)

        self.server.reject_sales = set()                        # sabab tuzatildi
        self.soat.keyin(seconds=Store.RETRY_EVERY + 5)          # tugma BOSILMADI
        k.fon()
        self.assertEqual(self.counts(), [1])
        self.assertEqual(k.store.unsent_count(), 0)
        self.assertEqual(k.store.rejected_count(), 0)

    def test_hali_ham_rad_etilsa_keyingi_safargacha_kutadi(self):
        k = self.k
        k.open_shift()
        self.server.online = False
        (u,) = k.sell(1)
        self.server.online = True
        self.server.reject_sales = {u}
        for _ in range(Store.MAX_ATTEMPTS):
            k.fon()
        for _ in range(3):
            before = len(self.server.codes("sale"))
            self.soat.keyin(seconds=Store.RETRY_EVERY + 5)
            k.fon(4)
            self.assertEqual(len(self.server.codes("sale")), before + 1)   # 15 daqiqada bitta
        self.assertEqual(k.store.unsent_count(), 1)             # yo'qolmadi

    def test_tiqilgan_chek_boshqalarni_va_smenani_toxtatmaydi(self):
        k = self.k
        k.open_shift()
        self.server.online = False
        (u,) = k.sell(1)
        self.server.online = True
        self.server.reject_sales = {u}
        for _ in range(Store.MAX_ATTEMPTS):
            k.fon()
        k.sell(3)
        self.assertEqual(self.counts(), [3])
        self.soat.keyin(hours=10)
        k.close_shift()
        self.assertEqual(self.shift(1)["status"], "closed")     # tiqilgan chek ushlab turmadi
        k.open_shift()
        k.sell(1)
        self.assertEqual(self.counts(), [3, 1])

    def test_yangilanishgacha_tiqilgan_cheklar_ham_qayta_yuboriladi(self):
        """Eski versiyada tiqilib qolgan chek (retry_at yo'q) yangilanishdan
        keyin birinchi navbatda o'zi ketadi."""
        k = self.k
        k.open_shift()
        self.server.online = False
        (u,) = k.sell(1)
        k.store.db.execute("UPDATE outbox SET attempts = ?, retry_at = NULL", (Store.MAX_ATTEMPTS,))
        k.store.db.execute("ALTER TABLE outbox DROP COLUMN retry_at")      # eski baza
        k.restart()                                             # yangi versiya ochildi
        self.server.online = True
        k.fon(2)
        self.assertEqual(self.counts(), [1])


class PulAmaliTest(JurnalBase):
    """Pul kiritish/chiqarish smena sababli yo'qolmaydi (8-band)."""

    HIMOYA = False                 # eski server: «Ochiq smena yo'q» / «boshqa smena»

    def test_holat_xatosida_amal_ochirilmaydi(self):
        k = self.k
        k.open_shift()
        k.fon()
        self.server.cash_status = 409
        res = k.backend.cash("out", 50_000_00, "inkassatsiya")
        self.assertTrue(res["queued"])
        self.assertTrue(res["rejected"])
        self.assertEqual(k.store.unsent_cash_count(), 1)        # ilgari: o'chirilardi
        self.assertEqual(len(k.store.shift_cash(k.store.journal_current()["tag"])), 1)
        self.server.cash_status = 0
        k.fon()
        self.assertEqual(k.store.unsent_cash_count(), 0)
        self.assertEqual(len(self.shift(1)["cash"]), 1)

    def test_huquq_yoq_bolsa_amal_haqiqiy_emas(self):
        k = self.k
        k.open_shift()
        k.fon()
        self.server.cash_status = 403
        with self.assertRaises(HubError):
            k.backend.cash("out", 50_000_00)
        self.assertEqual(k.store.unsent_cash_count(), 0)
        self.assertEqual(k.store.shift_cash(k.store.journal_current()["tag"]), [])

    def test_internetsiz_amal_oz_smenasiga_yoziladi(self):
        k = self.k
        self.server.online = False
        k.open_shift()
        k.sell(2)
        self.assertTrue(k.backend.cash("out", 30_000_00)["offline"])
        self.soat.keyin(hours=12)
        k.close_shift()
        self.soat.keyin(hours=10)
        k.open_shift()
        k.backend.cash("in", 10_000_00)
        self.server.online = True
        k.fon(4)
        self.assertEqual([[c[1] for c in s["cash"]] for s in self.server.shifts],
                         [["out"], ["in"]])
        self.assertEqual(k.store.unsent_cash_count(), 0)

    def test_navbatdagi_rad_amal_ham_saqlanadi(self):
        k = self.k
        self.server.online = False
        k.open_shift()
        k.backend.cash("out", 30_000_00)
        self.server.online = True
        self.server.cash_status = 409
        k.fon(2)
        self.assertEqual(k.store.unsent_cash_count(), 1)
        self.assertEqual(k.store.rejected_cash_count(), 1)
        self.server.cash_status = 0
        k.fon()
        self.assertEqual(len(self.shift(1)["cash"]), 1)


class JurnalTest(unittest.TestCase):
    """Jurnalning o'zi (pos/store.py)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kassa.db"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_tugma_ikki_marta_bosilsa_bitta_smena(self):
        a = self.store.journal_open(1, "K", 100)
        b = self.store.journal_open(1, "K", 999)
        self.assertEqual(a["uuid"], b["uuid"])
        self.assertEqual(b["opening_cash"], 100)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM shifts").fetchone()[0], 1)

    def test_belgi_va_teg_ozgarmaydi(self):
        a = self.store.journal_open(1, "K", 100)
        self.assertEqual(a["tag"], f"loc:{a['uuid']}")
        self.assertEqual(self.store.get("history_shift_tag"), a["tag"])
        self.store.journal_mark_open(a["uuid"], 555, 12)
        b = self.store.journal_get(a["uuid"])
        self.assertEqual((b["uuid"], b["tag"]), (a["uuid"], a["tag"]))   # serverga o'tsa ham
        self.assertEqual((b["server_id"], b["number"], b["open_synced"]), (555, 12, 1))

    def test_yopilgan_smena_joriy_emas_va_vaqti_ozgarmaydi(self):
        a = self.store.journal_open(1, "K", 100)
        self.store.journal_close(a["uuid"], "2026-11-11T18:29:00+00:00", None)
        self.assertIsNone(self.store.journal_current())
        self.store.journal_close(a["uuid"], "2026-11-12T03:09:00+00:00", None)   # takror
        self.assertEqual(self.store.journal_get(a["uuid"])["closed_at"],
                         "2026-11-11T18:29:00+00:00")

    def test_qayta_ochilganda_joyida(self):
        a = self.store.journal_open(7, "Nilufar", 300_000_00)
        self.store.close()
        self.store = Store(self.path)
        b = self.store.journal_current()
        self.assertEqual((b["uuid"], b["cashier"], b["opening_cash"]),
                         (a["uuid"], "Nilufar", 300_000_00))

    def test_navbat_tartibi_va_tozalash(self):
        keys = []
        for i in range(3):
            row = self.store.journal_open(1, "K", i)
            keys.append(row["uuid"])
            self.store.journal_close(row["uuid"], f"2026-11-1{i}T18:00:00+00:00")
        self.assertEqual([r["uuid"] for r in self.store.journal_pending()], keys)
        self.store.journal_mark_open(keys[0], 1, 1)
        self.store.journal_mark_closed(keys[0])
        self.assertEqual([r["uuid"] for r in self.store.journal_pending()], keys[1:])
        with mock.patch.object(Store, "JOURNAL_KEEP", 1):
            self.store.journal_trim()
        self.assertIsNone(self.store.journal_get(keys[0]))       # to'liq yetgani tozalandi
        self.assertIsNotNone(self.store.journal_get(keys[1]))    # yetmagani — hech qachon


class EskiHolatdanKochishTest(unittest.TestCase):
    """Yangilanish smena o'rtasida kelsa ham hech narsa yo'qolmaydi:
    1.18.21 holati (active_shift_id / local_shift / closed_shifts) jurnalga
    ko'chadi."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Windows ochiq faylni o'chirtirmaydi: papka FAQAT hamma baza yopilgandan
        # keyin tozalanadi. Shuning uchun tozalash eng birinchi ro'yxatga olinadi
        # (addCleanup teskari tartibda bajariladi — demak eng oxirida).
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "kassa.db"
        store = Store(self.path)                   # yangi baza — keyin «eskiga» aylantiramiz
        self.addCleanup(store.close)
        store.db.execute("DELETE FROM shifts")
        store.set("journal_v1", "")
        self.old = store

    def _upgrade(self) -> Store:
        self.old.close()
        store = Store(self.path)
        self.addCleanup(store.close)
        return store

    def test_onlayn_ochilgan_smena_davom_etadi(self):
        self.old.set("active_shift_id", "110")
        self.old.set("history_shift_tag", "srv:110")
        self.old.set("last_hello", json.dumps({"shift": {
            "id": 110, "number": 57, "cashier": "Nilufar",
            "opened_at": "2026-11-12T03:00:00+00:00", "opening_cash": 200_000_00}}))
        self.old.queue("eski-chek", {"local_uuid": "eski-chek", "shift_id": 110,
                                     "payments": [], "items": []}, "2026-11-12T04:00:00+00:00")
        store = self._upgrade()
        cur = store.journal_current()
        self.assertEqual((cur["server_id"], cur["number"], cur["tag"], cur["legacy"]),
                         (110, 57, "srv:110", 1))
        self.assertEqual((cur["cashier"], cur["opening_cash"], cur["open_synced"]),
                         ("Nilufar", 200_000_00, 1))
        self.assertEqual(store.get("active_shift_id"), "")
        # Yangi chek o'sha smenaga, server tushunadigan ko'rinishda muhrlanadi
        payload = {}
        LiveBackend(None, store, METHODS)._bind_shift(payload)
        self.assertEqual(payload, {"shift_id": 110})
        self.assertEqual(store.get("history_shift_tag"), "srv:110")
        self.assertEqual(len(store.shift_sales("srv:110")), 1)   # eski cheki shu smenada

    def test_onlayn_ochilgan_smena_idsi_bilan_yopiladi(self):
        self.old.set("active_shift_id", "110")
        self.old.set("history_shift_tag", "srv:110")
        store = self._upgrade()

        class Hub:
            closed = []
            open_id = 110

            def hello(self, queue=None):
                return {"shift": {"id": self.open_id} if self.open_id else None}

            def close_shift(self, counted, closed_at="", local_uuid="", shift_id=None):
                self.closed.append((local_uuid, shift_id, closed_at))
                return {}

        backend = LiveBackend(Hub(), store, METHODS)
        res = backend.finish_shift(None, "x")
        backend.sync_shifts()
        self.assertEqual(Hub.closed, [("", 110, res["closed_at"])])
        self.assertEqual(store.journal_pending(), [])

    def test_onlayn_ochilgan_smena_serverda_ochiq_bolmasa_boshqasi_yopilmaydi(self):
        """Belgisiz (eski) smenani server faqat «hozir ochiq turgani» sifatida
        yopa oladi. U yerda hozir BOSHQA smena ochiq bo'lsa (yoki hech biri) —
        yopish so'rovi yuborilmaydi: begona smena adashib yopilmasin."""
        for open_id in (222, None):
            with self.subTest(open_id=open_id):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                old = Store(Path(tmp.name) / "kassa.db")
                old.db.execute("DELETE FROM shifts")
                old.set("journal_v1", "")
                old.set("active_shift_id", "110")
                old.close()
                store = Store(Path(tmp.name) / "kassa.db")
                self.addCleanup(store.close)

                class Hub:
                    closed = []

                    def hello(self, queue=None):
                        return {"shift": {"id": open_id} if open_id else None}

                    def close_shift(self, counted, closed_at="", local_uuid="", shift_id=None):
                        self.closed.append((local_uuid, shift_id))
                        return {}

                backend = LiveBackend(Hub(), store, METHODS)
                backend.finish_shift(None, "x")
                backend.sync_shifts()
                self.assertEqual(Hub.closed, [])
                self.assertEqual(store.journal_pending(), [])

    def test_internetsiz_ochilgan_smena_davom_etadi(self):
        self.old.set_local_shift({"local_uuid": "u-oflayn", "cashier_id": 3, "cashier": "Kassir",
                                  "opening_cash": 100_000_00,
                                  "opened_at": "2026-11-12T03:00:00+00:00", "offline": True})
        self.old.set("history_shift_tag", "loc:u-oflayn")
        store = self._upgrade()
        cur = store.journal_current()
        self.assertEqual((cur["uuid"], cur["tag"], cur["open_synced"], cur["legacy"]),
                         ("u-oflayn", "loc:u-oflayn", 0, 0))
        self.assertIsNone(store.get_local_shift())
        payload = {}
        LiveBackend(None, store, METHODS)._bind_shift(payload)
        self.assertEqual(payload, {"shift_local_uuid": "u-oflayn"})

    def test_yopilib_kutayotgan_smenalar_navbatda_qoladi(self):
        """12.11.2026 kechasidagi holat: onlayn ochilgan smena internetsiz
        yopilgan, serverga hali yetmagan."""
        self.old.set_closed_shifts([
            {"local_uuid": "", "server_id": 110, "opened_at": "", "opening_cash": 0,
             "closed_at": "2026-11-11T18:29:00+00:00", "counted_cash": None,
             "shift_tag": "srv:110"},
            {"local_uuid": "u-2", "server_id": None, "cashier_id": 3, "cashier": "K",
             "opened_at": "2026-11-11T19:00:00+00:00", "opening_cash": 50_000_00,
             "closed_at": "2026-11-11T19:40:00+00:00", "counted_cash": None,
             "shift_tag": "loc:u-2"},
        ])
        self.old.set("history_shift_tag", "loc:u-2")
        store = self._upgrade()
        self.assertIsNone(store.journal_current())               # ERTALAB: ochiq smena yo'q
        rows = store.journal_pending()
        self.assertEqual([(r["server_id"], r["legacy"], r["open_synced"], r["tag"]) for r in rows],
                         [(110, 1, 1, "srv:110"), (None, 0, 0, "loc:u-2")])
        self.assertEqual(store.closed_shifts(), [])

        soat = Soat()
        soat.t = datetime(2026, 11, 12, 3, 9, tzinfo=timezone.utc)
        server = SoxtaServer(soat, himoya=False)
        eski = server._new("", datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc), 100_000_00)
        eski["id"] = 110
        backend = LiveBackend(server, store, METHODS)
        backend.sync_shifts()
        self.assertEqual([w for w, _ in server.calls], ["close", "open", "close"])
        self.assertEqual(eski["closed_at"].isoformat(), "2026-11-11T18:29:00+00:00")
        self.assertEqual(server.shifts[1]["closed_at"].isoformat(), "2026-11-11T19:40:00+00:00")
        self.assertEqual(store.journal_pending(), [])

    def test_kochirish_bir_marta(self):
        self.old.set("active_shift_id", "110")
        store = self._upgrade()
        first = store.journal_current()["uuid"]
        store.close()
        again = Store(self.path)
        self.addCleanup(again.close)
        self.assertEqual(again.journal_current()["uuid"], first)
        self.assertEqual(again.db.execute("SELECT COUNT(*) FROM shifts").fetchone()[0], 1)

    def test_toza_kassada_hech_narsa_paydo_bolmaydi(self):
        store = self._upgrade()
        self.assertIsNone(store.journal_current())
        self.assertEqual(store.journal_pending(), [])



class OynaShartlariTest(unittest.TestCase):
    """pos/main.py dagi oyna kodi «smena — kassaniki» qoidasini buzmasin.

    `main()` — bitta katta funksiya, uni testda to'liq yurgizib bo'lmaydi.
    12.11.2026 xatosi aynan shu yerda edi (`shift = info.get("shift")`),
    shuning uchun eng muhim shartlar manba matni bo'yicha tekshiriladi.
    """

    @classmethod
    def setUpClass(cls):
        raw = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
        # Izohlar tekshiruvga kirmaydi — faqat ishlaydigan kod.
        cls.code = "\n".join(
            line.split("  # ")[0] for line in raw.splitlines()
            if not line.strip().startswith("#")
        )
        hub_raw = (Path(__file__).parent / "hub.py").read_text(encoding="utf-8")
        cls.hub_code = "\n".join(
            line for line in hub_raw.splitlines() if not line.strip().startswith("#")
        )

    def _body(self, start: str, end: str) -> str:
        i = self.code.index(start)
        return self.code[i:self.code.index(end, i)]

    def test_smena_faqat_jurnaldan_olinadi(self):
        self.assertIn("shift = backend.current_shift()", self.code)
        # Server javobidagi smena hech qachon kassani smenaga KIRITMAYDI. U faqat
        # ikki joyda o'qiladi va ikkalasida ham faqat «jurnaldagi ochiq smena
        # serverda yopilganmi» degan savolga javob beradi.
        self.assertEqual(self.code.count('info.get("shift")'), 1)
        self.assertIn('backend.drop_shift_closed_elsewhere(info.get("shift"))', self.code)
        self.assertEqual(self.code.count('fresh.get("shift")'), 1)
        self.assertIn('bg_backend.note_server_shift(fresh.get("shift"), shift_before)', self.code)
        self.assertNotIn('info["shift"]', self.code)
        self.assertNotIn('fresh["shift"]', self.code)
        # Bu tekshiruv faqat server HOZIR javob bergan bo'lsa ishlaydi (keshdan emas).
        i = self.code.index("backend.drop_shift_closed_elsewhere(")
        self.assertIn("if not offline:", self.code[i - 120:i])

    def test_server_javobi_smena_ochmaydi_va_almashtirmaydi(self):
        """Server javobi bilan ishlaydigan ikki funksiya jurnalga faqat
        «yopish» yoki belgi qo'yish bilan tegadi — smena ochmaydi."""
        i = self.hub_code.index("def shift_closed_elsewhere(")
        body = self.hub_code[i:self.hub_code.index("def sync_shifts(", i)]
        for banned in ("journal_open(", "journal_mark_open(", "_journal_insert(", "open_shift("):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, body)

    def test_eski_holat_kalitlari_ishlatilmaydi(self):
        for key in ("active_shift_id", "get_local_shift", "set_local_shift", "closed_shifts",
                    "enter_shift_tag", "retag_shift"):
            with self.subTest(key=key):
                self.assertNotIn(key, self.code)
                self.assertNotIn(key, self.hub_code)

    def test_smena_ochish_va_yopish_oynada_tarmoqsiz(self):
        yopish = self._body("def close_shift() -> None:", "backend.close_shift = close_shift")
        self.assertIn("backend.finish_shift(", yopish)
        self.assertIn("_local_shift_report(", yopish)           # hisobot — kassadagi cheklardan
        for call in ("backend.flush(", "hub.close_shift(", "hub.shift_report(", "hub.hello("):
            with self.subTest(call=call):
                self.assertNotIn(call, yopish)
        self.assertNotIn("hub.shift_report(", self.code)        # oraliq hisobot ham mahalliy
        ochish = self._body("def open_shift(backend, cashier", "EXIT_OK = 0")
        self.assertIn("backend.open_shift(", ochish)
        self.assertNotIn("hub.", ochish)

    def test_backend_smena_amallari_tarmoqqa_chiqmaydi(self):
        import inspect

        for name in ("open_shift", "finish_shift", "current_shift", "_bind_shift"):
            with self.subTest(name=name):
                src = inspect.getsource(getattr(LiveBackend, name))
                self.assertNotIn("self.hub.", src)

    def test_rad_etilgan_cheklar_uchun_doimiy_ogohlantirish(self):
        self.assertIn("window.set_alert(", self.code)
        self.assertIn("store.rejected_count()", self.code)


class OgohlantirishOynasiTest(unittest.TestCase):
    """Katta qizil ogohlantirish — modal emas, muammo yechilmaguncha turadi."""

    @classmethod
    def setUpClass(cls):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:                              # pragma: no cover
            raise unittest.SkipTest("PySide6 o'rnatilmagan")
        cls.app = QApplication.instance() or QApplication([])

    def test_korinadi_va_yashirinadi(self):
        from pos.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "kassa.db")
            try:
                window = MainWindow(LiveBackend(None, store, METHODS))
                self.assertTrue(window.alert_bar.isHidden())
                window.set_alert("DIQQAT: 3 ta chekni server qabul qilmadi.")
                self.assertFalse(window.alert_bar.isHidden())
                self.assertIn("3 ta chekni", window.alert_bar.text())
                window.flash("Katalog yangilandi")        # oddiy xabar uni o'chirmaydi
                self.assertFalse(window.alert_bar.isHidden())
                window.set_alert("")
                self.assertTrue(window.alert_bar.isHidden())
            finally:
                store.close()


class BegonaSmenaTest(JurnalBase):
    """Serverda O'ZIMIZ OCHMAGAN smena ochiq turibdi: kassa kompyuteri
    almashgan, dastur qayta o'rnatilgan (baza yangi) yoki shu login bilan
    boshqa kompyuter ishlagan. Server `shift/open` ga o'sha ochiq smenani
    qaytaradi, bizning belgimizni (uuid) esa yozib qo'ymaydi.

    Tuzatishgacha: cheklar faqat belgi bilan ketardi va server ularni «Chek
    smenasi bu kassada topilmadi» deb abadiy rad etardi."""

    def _begona(self, uuid_="boshqa-kompyuter"):
        s = self.server._new(uuid_, self.soat.t, 50_000_00)
        self.soat.keyin(minutes=30)
        return s

    def test_cheklar_rad_etilmaydi(self):
        begona = self._begona()
        k = self.k
        k.open_shift()
        ids = k.sell(3)
        self.assertEqual(self.server.codes("sale"), [201, 201, 201])
        self.assertEqual({self.server.sales[u] for u in ids}, {begona["id"]})
        self.assertEqual(k.store.unsent_count(), 0)
        self.assertEqual(k.store.rejected_count(), 0)
        self.assertEqual(len(self.server.shifts), 1)      # ikkinchi smena paydo bo'lmadi
        self.assertEqual(k.store.get("shift_stale"), "")

    def test_diskdagi_chek_ozgarmaydi(self):
        """Serverdagi id faqat yuborilayotgan nusxaga qo'shiladi."""
        self._begona()
        k = self.k
        self.server.online = False
        sh = k.open_shift()
        k.sell(1)
        oldin = k.store.unsent_rows()[0]["payload"]
        self.assertEqual(json.loads(oldin)["shift_local_uuid"], sh["uuid"])
        self.assertNotIn("shift_id", json.loads(oldin))
        self.server.online = True
        seen = []
        asl = self.server.send_sale
        with mock.patch.object(self.server, "send_sale",
                               side_effect=lambda p: (seen.append(dict(p)), asl(p))[1]):
            k.fon(2)
        self.assertEqual([p.get("shift_id") for p in seen], [self.shift(1)["id"]])
        self.assertEqual(seen[0]["shift_local_uuid"], sh["uuid"])
        saved = json.loads(k.store.db.execute("SELECT payload FROM outbox").fetchone()["payload"])
        saved.pop("receipt_number", None)           # yuborilgach server bergan raqam yoziladi
        self.assertEqual(saved, json.loads(oldin))

    def test_internetsiz_ochilgan_bolsa_ham(self):
        begona = self._begona()
        k = self.k
        self.server.online = False
        k.open_shift()
        ids = k.sell(2)
        self.assertEqual(k.store.unsent_count(), 2)
        self.server.online = True
        k.fon(2)
        self.assertEqual({self.server.sales[u] for u in ids}, {begona["id"]})
        self.assertNotIn(409, self.server.codes("sale"))
        self.assertEqual(k.store.unsent_count(), 0)

    def test_yopilganda_serverda_ham_yopiladi_keyingisi_yangi_ochiladi(self):
        begona = self._begona()
        k = self.k
        k.open_shift()
        k.sell(2)
        yopildi = self.soat.iso()
        k.close_shift()
        self.assertEqual(begona["status"], "closed")
        self.assertEqual(begona["closed_at"].isoformat(), yopildi)
        self.assertEqual(k.store.journal_pending(), [])
        self.assertEqual(k.store.get("shift_sync_error"), "")
        self.soat.keyin(hours=10)
        k.open_shift()
        bugungi = k.sell(4)
        self.assertEqual(self.counts(), [2, 4])
        self.assertEqual({self.server.sales[u] for u in bugungi}, {self.shift(2)["id"]})
        self.assertEqual(k.store.unsent_count(), 0)

    def test_begona_yangi_smenaga_tegilmaydi(self):
        """Biz ulangan smenani boshqa kompyuter yopib, o'zinikini ochgan.
        Bizning «yopish» o'sha YANGI begona smenani yopib qo'ymasligi kerak."""
        self._begona()
        k = self.k
        k.open_shift()
        k.sell(1)
        self.server.close_shift(None, local_uuid="boshqa-kompyuter")
        yangi = self.server._new("boshqa-kompyuter-2", self.soat.t, 0)
        self.soat.keyin(minutes=20)
        k.close_shift()
        self.assertEqual(yangi["status"], "open")
        self.assertEqual(k.store.journal_pending(), [])


class EskiServerBilanBegonaTest(BegonaSmenaTest):
    """Xuddi shu — 12.11.2026 dagi (himoyasiz) server bilan."""
    HIMOYA = False


class YopishDalilTest(JurnalBase):
    """Smena «serverda yopildi» deb FAQAT DALIL bilan belgilanadi.

    Tuzatishgacha serverning har qanday rad javobi (hatto «kassa tokeni
    noto'g'ri») yopildi deb hisoblanardi: smena serverda ochiq qolar, ertangi
    smena esa unga qo'shilib ketardi."""

    def _kecha(self, xato):
        k = self.k
        k.open_shift()
        k.sell(2)
        self.soat.keyin(hours=12)
        self.server.fail_close = xato
        k.close_shift()

    def test_token_rad_etilsa_yopildi_deb_belgilanmaydi(self):
        self._kecha(HubAuthError("Kassa tokeni noto'g'ri", status=401))
        k = self.k
        self.assertEqual(self.shift(1)["status"], "open")
        self.assertEqual(len(k.store.journal_pending()), 1)        # hali navbatda
        self.assertIn("token", k.store.get("shift_sync_error"))
        # Ertalab: yangi smena kassada ochiladi va savdo boradi. Serverga esa
        # oldingisi yopilmaguncha ochilmaydi — kechagi smenaga qo'shilmaydi.
        self.soat.keyin(hours=9)
        k.open_shift()
        bugungi = k.sell(3)
        self.assertEqual(self.counts(), [2])
        self.assertEqual(k.store.unsent_count(), 3)
        self.assertEqual(k.store.rejected_count(), 0)              # rad emas — kutyapti
        self.assertEqual(k.store.stuck_count(), 0)
        self.server.fail_close = None                              # aloqa tiklandi
        k.fon(3)
        self.assertEqual(self.shift(1)["status"], "closed")
        self.assertEqual(self.counts(), [2, 3])
        self.assertEqual({self.server.sales[u] for u in bugungi}, {self.shift(2)["id"]})
        self.assertEqual(k.store.get("shift_sync_error"), "")
        self.assertEqual(k.store.unsent_count(), 0)

    def test_notogri_sorov_javobida_ham_belgilanmaydi(self):
        self._kecha(HubError("Server xatosi 400", status=400))
        self.assertEqual(self.shift(1)["status"], "open")
        self.assertEqual(len(self.k.store.journal_pending()), 1)
        self.assertIn("400", self.k.store.get("shift_sync_error"))

    def test_belgi_bilan_yopish_xatosida_id_bilan_yopishga_otilmaydi(self):
        """Faqat 409 («bu belgi serverda yo'q») id bo'yicha yopishga o'tkazadi.
        Boshqa rad javobi — sabab noma'lum: belgisiz so'rov bilan «ochiq
        smenani» yopib yuborish mumkin emas."""
        k = self.k
        k.open_shift()
        k.sell(1)
        asl = self.server.close_shift

        def faqat_belgili_rad(counted_cash, closed_at="", local_uuid="", shift_id=None):
            if local_uuid:
                raise HubError("Server xatosi 400", status=400)
            return asl(counted_cash, closed_at=closed_at, local_uuid=local_uuid, shift_id=shift_id)

        with mock.patch.object(self.server, "close_shift", side_effect=faqat_belgili_rad):
            k.close_shift()
        self.assertEqual(self.shift(1)["status"], "open")
        self.assertEqual(len(k.store.journal_pending()), 1)
        k.fon()                                     # server tuzaldi
        self.assertEqual(self.shift(1)["status"], "closed")
        self.assertEqual(k.store.journal_pending(), [])

    def test_server_band_bolsa_jim_kutadi(self):
        self._kecha(HubConnError("Server vaqtincha band: 503", status=503))
        self.assertEqual(len(self.k.store.journal_pending()), 1)
        self.assertEqual(self.k.store.get("shift_sync_error"), "")   # bu ogohlantirish emas
        self.server.fail_close = None
        self.k.fon()
        self.assertEqual(self.shift(1)["status"], "closed")
        self.assertEqual(self.k.store.journal_pending(), [])

    def test_tushunarsiz_ochish_javobi_ochildi_deb_belgilanmaydi(self):
        k = self.k
        with mock.patch.object(self.server, "open_shift", return_value={"shift": {}}):
            k.open_shift()
            k.fon()
        row = k.store.journal_current()
        self.assertEqual((row["open_synced"], row["server_id"]), (0, None))
        k.fon()
        self.assertEqual(k.store.journal_current()["open_synced"], 1)


class BoshqaJoydanYopilganTest(JurnalBase):
    """Jurnaldagi OCHIQ smena serverda yopilgan: dastur eski versiyaga
    qaytarilib smena o'sha yerda yopilgan yoki shu login bilan boshqa kompyuter
    ishlagan. Shu smenada sotish davom etsa bugungi cheklar kechagi (yopiq)
    smenaga yozilardi."""

    def _yopilgan(self):
        k = self.k
        sh = k.open_shift()
        kechagi = k.sell(2)
        self.soat.keyin(hours=12)
        self.server.close_shift(None)              # BOSHQA joydan yopildi
        self.soat.keyin(hours=9)
        return sh, kechagi

    def test_dastur_ochilganda_yopiq_smenaga_kirilmaydi(self):
        k = self.k
        sh, _ = self._yopilgan()
        self.assertIsNone(k.restart())             # kassir «SMENA OCHISH» ni ko'radi
        k.fon()
        self.assertEqual(k.store.journal_pending(), [])
        bugun = k.open_shift()
        self.assertNotEqual(bugun["uuid"], sh["uuid"])
        bugungi = k.sell(5)
        self.assertEqual(self.counts(), [2, 5])    # yopiq smenaga bugungi chek tushmadi
        self.assertEqual({self.server.sales[u] for u in bugungi}, {self.shift(2)["id"]})
        self.assertNotIn(409, [c for _, c in self.server.calls])
        self.assertEqual(k.store.get("shift_stale"), "")

    def test_serverda_boshqa_smena_ochiq_bolsa_ham_kirilmaydi(self):
        """Bizning smena yopilgan, serverda esa BOSHQA (begona) smena ochiq."""
        k = self.k
        sh, _ = self._yopilgan()
        begona = self.server._new("boshqa-kompyuter", self.soat.t, 0)
        self.soat.keyin(minutes=10)
        k.fon()
        self.assertEqual(k.store.get("shift_stale"), sh["uuid"])   # ish paytida: ogohlantirish
        self.assertIsNone(k.restart())                              # ochilganda: kirmaydi
        k.open_shift()
        bugungi = k.sell(2)
        self.assertEqual(self.counts(), [2, 2])
        self.assertEqual({self.server.sales[u] for u in bugungi}, {begona["id"]})
        self.assertNotIn(409, self.server.codes("sale"))

    def test_kassada_yopilgan_smena_tekshiruvga_tushmaydi(self):
        row = {"uuid": "u", "closed_at": "2026-11-12T18:00:00+00:00", "open_synced": 1,
               "server_id": 5}
        self.assertFalse(self.k.backend.shift_closed_elsewhere(None, row))
        self.assertFalse(self.k.backend.shift_closed_elsewhere({"id": 9}, row))
        self.assertFalse(self.k.backend.shift_closed_elsewhere(None, None))

    def test_internet_yoq_bolsa_smenaga_tegilmaydi(self):
        k = self.k
        sh, _ = self._yopilgan()
        self.server.online = False
        self.assertEqual(k.restart()["uuid"], sh["uuid"])    # dalil yo'q — jurnal o'zgarmaydi

    def test_ish_paytida_faqat_ogohlantirish(self):
        k = self.k
        sh, _ = self._yopilgan()
        k.fon()                                     # fon: hello → smena serverda yopiq
        self.assertEqual(k.store.get("shift_stale"), sh["uuid"])
        self.assertEqual(k.backend.current_shift()["uuid"], sh["uuid"])   # smenaga tegilmadi
        k.close_shift()                             # kassir yopadi va yangisini ochadi
        k.open_shift()
        k.fon()
        self.assertEqual(k.store.get("shift_stale"), "")
        self.assertEqual(k.store.journal_pending(), [])

    def test_oddiy_ishda_hech_narsa_ozgarmaydi(self):
        k = self.k
        sh = k.open_shift()
        k.sell(3)
        self.assertEqual(k.restart()["uuid"], sh["uuid"])
        self.assertEqual(k.store.get("shift_stale"), "")
        self.server.online = False
        k.close_shift()
        self.soat.keyin(hours=9)
        self.assertIsNone(k.restart())
        k.open_shift()
        self.server.online = True
        self.assertIsNotNone(k.restart())           # server «kechagi ochiq» deydi — tegilmaydi
        k.sell(2)
        self.assertEqual(self.counts(), [3, 2])
        self.assertEqual(k.store.get("shift_stale"), "")

    def test_internetsiz_ochilgan_smena_hech_qachon_yopilmaydi(self):
        k = self.k
        self.server.online = False
        sh = k.open_shift()
        k.sell(1)
        # Server bu smenani bilmaydi («ochiq smena yo'q») — bu dalil EMAS.
        self.assertIsNone(k.backend.drop_shift_closed_elsewhere(None))
        self.assertEqual(k.backend.current_shift()["uuid"], sh["uuid"])
        self.assertFalse(k.bg.note_server_shift(None, k.store.journal_current()))
        self.assertEqual(k.store.get("shift_stale"), "")

    def test_eski_javob_dalil_emas(self):
        """Poyga: hello so'ralganda smena hali serverga ochilmagan edi, javob
        kelguncha ochildi. O'sha eski javob («ochiq smena yo'q») dalil emas."""
        k = self.k
        self.server.online = False
        k.open_shift()
        oldin = k.store.journal_current()           # so'rovdan OLDIN o'qilgan holat
        self.server.online = True
        k.fon()
        self.assertEqual(k.store.journal_current()["open_synced"], 1)
        self.assertFalse(k.bg.note_server_shift(None, oldin))
        self.assertEqual(k.store.get("shift_stale"), "")


class OrqagaQaytishTest(JurnalBase):
    """Dastur eski versiyaga (1.18.21) QAYTARILIB, keyin yana yangilangan.

    Eski versiya jurnalni bilmaydi: smena holatini o'z kalitlariga yozadi
    (active_shift_id / local_shift / closed_shifts) va cheklarni «srv:<id>»
    belgisiga ko'chiradi. Qayta yangilanganda jurnal o'sha holatni qabul
    qiladi — aks holda kassa eski versiyada yopilgan smenaga qayta kirardi."""

    def setUp(self):
        super().setUp()
        self.sh = self.k.open_shift(200_000_00)
        self.birinchi = self.k.sell(2)
        self.row = self.k.store.journal_current()
        self.sid = self.row["server_id"]

    def _eski_versiya_kirdi(self):
        """1.18.21: serverdagi ochiq smenaga kiradi, cheklarni «srv:» ga ko'chiradi."""
        s = self.k.store
        s.retag_shift(self.row["tag"], f"srv:{self.sid}")
        s.set("history_shift_tag", f"srv:{self.sid}")
        s.set("active_shift_id", str(self.sid))

    def test_eski_versiya_smenani_davom_ettirgan(self):
        k = self.k
        self._eski_versiya_kirdi()
        k.sell(1)                                   # eski versiyada urilgan chek («srv:» belgili)
        again = k.restart()
        self.assertEqual(again["uuid"], self.sh["uuid"])            # o'sha smena davom etadi
        store = k.store
        self.assertEqual(len(store.shift_sales(self.row["tag"])), 3)   # cheklari yana birga
        self.assertEqual(store.get("history_shift_tag"), self.row["tag"])
        self.assertEqual(store.get("active_shift_id"), "")
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM shifts").fetchone()[0], 1)
        k.sell(2)
        self.assertEqual(self.counts(), [5])
        self.assertEqual(len(store.shift_sales(self.row["tag"])), 5)

    def test_eski_versiya_yopib_yangi_smena_ochgan(self):
        k, server = self.k, self.server
        self._eski_versiya_kirdi()
        self.soat.keyin(hours=12)
        server.close_shift(None)                    # eski versiya onlayn yopdi
        self.soat.keyin(hours=9)
        yangi = server._new("", self.soat.t, 150_000_00)     # ... va onlayn yangisini ochdi
        s = k.store
        s.set("active_shift_id", str(yangi["id"]))
        s.set("history_shift_tag", f"srv:{yangi['id']}")
        s.set("last_hello", json.dumps({"shift": server._json(yangi)}))
        eski_chek = k.sell(1)                       # eski versiyada, yangi smenada urilgan
        again = k.restart()
        self.assertEqual(again["id"], yangi["id"])                  # shu smena davom etadi
        self.assertEqual(again["opening_cash"], 150_000_00)
        cur = k.store.journal_current()
        self.assertEqual((cur["legacy"], cur["tag"]), (1, f"srv:{yangi['id']}"))
        old = k.store.journal_get(self.sh["uuid"])
        self.assertIsNotNone(old["closed_at"])                      # oldingisi tugagan
        k.fon(2)
        self.assertEqual(k.store.journal_pending(), [])
        self.assertEqual(yangi["status"], "open")                   # yangisi yopilib ketmadi
        bugungi = k.sell(3)
        self.assertEqual({server.sales[u] for u in eski_chek + bugungi}, {yangi["id"]})
        self.assertEqual(self.counts(), [2, 4])
        self.assertEqual(len(k.store.shift_sales(cur["tag"])), 4)
        k.close_shift()
        self.assertEqual(yangi["status"], "closed")
        self.assertEqual(k.store.unsent_count(), 0)

    def test_eski_versiya_internetsiz_yopgan(self):
        k, server = self.k, self.server
        self._eski_versiya_kirdi()
        self.soat.keyin(hours=12)
        yopildi = self.soat.iso()
        for qolgan_kalit in ("", str(self.sid)):
            with self.subTest(active_shift_id=qolgan_kalit):
                s = k.store
                s.set_closed_shifts([{"local_uuid": "", "server_id": self.sid, "opened_at": "",
                                      "opening_cash": 0, "closed_at": yopildi,
                                      "counted_cash": 777, "shift_tag": f"srv:{self.sid}"}])
                s.set("active_shift_id", qolgan_kalit)
                server.online = False
                self.assertIsNone(k.restart())      # ertalab: ochiq smena yo'q
                old = k.store.journal_get(self.sh["uuid"])
                self.assertEqual((old["closed_at"], old["counted_cash"], old["close_synced"]),
                                 (yopildi, 777, 0))
                self.assertEqual(len(k.store.shift_sales(self.row["tag"])), 2)
                self.assertEqual(k.store.closed_shifts(), [])
        server.online = True
        self.soat.keyin(hours=9)
        k.fon()
        self.assertEqual(self.shift(1)["status"], "closed")
        self.assertEqual(self.shift(1)["closed_at"].isoformat(), yopildi)
        self.assertEqual(k.store.journal_pending(), [])

    def test_jurnal_yopgan_smenaga_eski_versiya_kirgan_bolsa_jurnal_haq(self):
        """Smena kassada (internetsiz) yopilgan, keyin dastur eski versiyaga
        qaytarilgan. Eski versiya server so'ziga ishonib o'sha smenaga kiradi
        (12.11.2026 dagi xato). Qayta yangilanganda smena YOPIQ qoladi."""
        k = self.k
        self.server.online = False
        k.close_shift()
        self._eski_versiya_kirdi()
        self.assertIsNone(k.restart())
        self.assertEqual(len(k.store.journal_pending()), 1)

    def test_eski_versiya_internetsiz_yangi_smena_ochgan(self):
        """Jurnaldagi smena hali serverga yetmagan; eski versiya uni bilmaydi
        va internetsiz o'zinikini ochadi."""
        soat = self.soat
        server = SoxtaServer(soat, himoya=self.HIMOYA)
        server.online = False
        k = Kassa(server, soat)
        self.addCleanup(k.close)
        sh = k.open_shift()
        birinchi = k.sell(1)
        soat.keyin(hours=6)
        ochildi = soat.iso()
        s = k.store
        s.set_local_shift({"local_uuid": "u-eski", "cashier_id": 3, "cashier": "Nilufar",
                           "opening_cash": 90_000_00, "opened_at": ochildi,
                           "offline": True, "next_receipt": 1})
        s.set("history_shift_tag", "loc:u-eski")
        again = k.restart()
        self.assertEqual(again["uuid"], "u-eski")
        self.assertEqual(again["opening_cash"], 90_000_00)
        self.assertEqual([(r["uuid"], r["closed_at"]) for r in k.store.journal_pending()],
                         [(sh["uuid"], ochildi), ("u-eski", None)])
        ikkinchi = k.sell(2)
        server.online = True
        k.fon(3)
        self.assertEqual([len(x["sales"]) for x in server.shifts], [1, 2])
        self.assertEqual(server.shifts[0]["closed_at"].isoformat(), ochildi)
        self.assertEqual({server.sales[u] for u in birinchi}, {server.shifts[0]["id"]})
        self.assertEqual({server.sales[u] for u in ikkinchi}, {server.shifts[1]["id"]})
        self.assertNotIn(409, [c for _, c in server.calls])

    def test_oddiy_qayta_ochilishda_kochirish_ishlamaydi(self):
        with mock.patch.object(Store, "_adopt_legacy_shifts") as adopt:
            self.k.restart()
        adopt.assert_not_called()


class EskiServerBilanOrqagaQaytishTest(OrqagaQaytishTest):
    HIMOYA = False


if __name__ == "__main__":
    unittest.main()
