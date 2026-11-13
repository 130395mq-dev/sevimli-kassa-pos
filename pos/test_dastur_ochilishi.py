"""Butun dastur — haqiqiy `main()` — smena bo'yicha (1.19.0).

Ro'yxatdagi 13-band: 200 dan ortiq test bor edi, lekin birortasi «dastur
qayta ochildi — qaysi smenaga kiradi» qismini tekshirmasdi; 12.11.2026
xatosi aynan o'sha yerda edi. Bu yerda dastur alohida jarayonda, haqiqiy
oynalari bilan (ekransiz) ochiladi va mahalliy soxta serverga HTTP orqali
ulanadi — xuddi do'kondagidek: kechqurun yopiladi, ertalab qayta ochiladi.

Sekin test (har ochilish — alohida jarayon), shuning uchun kam, lekin
eng muhim yo'llar.

    python -m unittest pos.test_dastur_ochilishi
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pos.hub import HubError
from pos.test_smena_jurnali import METHODS, PRODUCTS, SoxtaServer
from pos.version import VERSION

try:
    import PySide6  # noqa: F401
    QT = True
except ImportError:                                   # pragma: no cover
    QT = False

ROOT = Path(__file__).resolve().parent.parent


class _HozirgiSoat:
    """SoxtaServer uchun haqiqiy soat (kassa alohida jarayonda ishlaydi)."""

    @property
    def t(self):
        return datetime.now(timezone.utc)


class _Server:
    """`SoxtaServer` qoidalari — HTTP orqali (haqiqiy `Hub._call` uchun)."""

    def __init__(self, himoya: bool):
        self.rules = SoxtaServer(_HozirgiSoat(), himoya=himoya)
        self.lock = threading.Lock()
        self.reject_next = 0
        self.paths: list[tuple[str, int]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):               # jim
                pass

            def _reply(self, code, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self, method):
                url = urlparse(self.path)
                path = url.path
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}") if size else {}
                with outer.lock:
                    code, obj = outer.route(method, path, body, parse_qs(url.query))
                    if not path.startswith("/__"):
                        outer.paths.append((path.replace("/api/v1/", ""), code))
                self._reply(code, obj)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def codes(self, path):
        return [c for p, c in self.paths if p == path]

    def route(self, method, path, body, query):
        r = self.rules
        if path == "/__control":
            if "online" in body:
                r.online = bool(body["online"])
            if "reject_next" in body:
                self.reject_next = int(body["reject_next"])
            return 200, {}
        if not r.online:
            return 503, {"error": "Server vaqtincha ishlamayapti"}
        who = {"id": 3, "name": "Kassir", "login": "kassir", "is_manager": True}
        name = path.replace("/api/v1/", "")
        try:
            if name == "hello":
                return 200, {
                    "register": {"code": "kassa-1", "name": "Kassa-1"}, "point": "Sinov",
                    "market": "Sevimli Market", "receipt_width": 48,
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "shift": r.hello()["shift"], "payment_methods": METHODS, "cashiers": [],
                    "settings": {}, "price_types": [], "default_price_type": "",
                    "price_policy_revision": "", "links": {"moysklad": {"state": "ok", "text": ""}},
                    "login_session": {"mine": True, "session": "sess-1"},
                }
            if name in ("login", "session/resume"):
                return 200, {"cashier": who, "session": "sess-1"}
            if name == "logout":
                return 200, {"ok": True}
            if name == "version":
                return 200, {"version": VERSION}
            if name == "catalog":
                return 200, {"products": PRODUCTS, "next_after": None,
                             "server_time": datetime.now(timezone.utc).isoformat()}
            if name == "catalog/refresh":
                return 200, {}
            if name == "shift/open":
                return 200, r.open_shift(body.get("cashier_id"), int(body.get("opening_cash") or 0),
                                         local_uuid=body.get("local_uuid") or "",
                                         opened_at=body.get("opened_at") or "")
            if name == "shift/close":
                return 200, r.close_shift(body.get("counted_cash"),
                                          closed_at=body.get("closed_at") or "",
                                          local_uuid=body.get("local_uuid") or "",
                                          shift_id=body.get("shift_id"))
            if name == "shift/report":
                return 409, {"error": "Ochiq smena yo'q"}     # yangi kassa buni so'ramasligi kerak
            if name == "sales":
                if self.reject_next > 0:
                    self.reject_next -= 1
                    return 400, {"error": "Narx eskirgan"}
                return 201, r.send_sale(body)
            if name == "cash":
                return 201, r.cash(**{k: body.get(k) for k in (
                    "kind", "amount", "comment", "local_uuid", "shift_id", "created_at")
                    if body.get(k) is not None})
        except HubError as e:
            return e.status or 400, {"error": str(e)}
        return 404, {"error": f"noma'lum yo'l: {name}"}


@unittest.skipUnless(QT, "PySide6 o'rnatilmagan")
@unittest.skipIf(sys.platform.startswith("win"),
                 "ekransiz to'liq ochilish Linux'da yurgiziladi (CI: build.yml)")
class DasturOchilishiTest(unittest.TestCase):
    HIMOYA = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = _Server(self.HIMOYA)
        self.addCleanup(self.server.stop)
        conf = Path(self.tmp.name) / "SevimliKassa"
        conf.mkdir()
        (conf / "config.json").write_text(json.dumps({
            "server_url": self.server.url, "token": "sinov-token", "auto_print": False,
            "outbox_interval": 1, "catalog_interval": 120, "language": "uz",
        }), encoding="utf-8")
        self.runs = 0

    def kassa(self, *actions, razmen=100_000) -> dict:
        """Dasturni ochadi, amallarni bajaradi, yopadi. Natijani qaytaradi."""
        self.runs += 1
        out = Path(self.tmp.name) / f"natija-{self.runs}.json"
        plan = Path(self.tmp.name) / f"reja-{self.runs}.json"
        plan.write_text(json.dumps({"actions": list(actions), "razmen": razmen,
                                    "out": str(out)}), encoding="utf-8")
        env = dict(os.environ, APPDATA=self.tmp.name, QT_QPA_PLATFORM="offscreen",
                   PYTHONPATH=str(ROOT), HOME=self.tmp.name, XDG_RUNTIME_DIR=self.tmp.name)
        proc = subprocess.run([sys.executable, "-m", "pos.sinov_haydovchi", str(plan)],
                              cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=180)
        self.assertTrue(out.exists(), f"natija yo'q (kod {proc.returncode}):\n{proc.stderr[-3000:]}")
        result = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(result["errors"], [], proc.stderr[-2000:])
        result["step"] = {s["at"]: s for s in result["steps"]}
        return result

    def test_kechqurun_internetsiz_yopilib_ertalab_ochilsa(self):
        """12.11.2026 hodisasi — haqiqiy dastur, haqiqiy oynalar bilan."""
        rules = self.server.rules

        # ---- KECHA: kirish, smena, savdo, oraliq hisobot; kechqurun internet uzildi
        kecha = self.kassa("state:boshida", "login", "state:kirgach", "sell:3", "report",
                           "wait_synced", "offline", "close", "state:yopgach")
        self.assertTrue(kecha["step"]["boshida"]["login_visible"])
        ish = kecha["step"]["kirgach"]
        self.assertTrue(ish["enabled"])
        self.assertFalse(ish["login_visible"])
        self.assertIn("Smena", ish["shift_label"])
        yopgach = kecha["step"]["yopgach"]
        self.assertFalse(yopgach["enabled"])              # «SMENA OCHISH» ekrani
        self.assertTrue(yopgach["resume_mode"])
        self.assertIsNone(yopgach["current"])
        nomlar = [name for name, _ in kecha["printed"]]
        self.assertEqual(nomlar, ["oraliq", "smena"])     # ikkalasi ham kassaning o'zidan
        self.assertNotIn("shift/report", [p for p, _ in self.server.paths])
        self.assertEqual(kecha["boxes"], [])              # hech qanday xato oynasi chiqmadi
        (s1,) = rules.shifts
        self.assertEqual((s1["status"], len(s1["sales"]), s1["opening_cash"]),
                         ("open", 3, 100_000_00))         # serverda hali OCHIQ
        (j1,) = kecha["journal"]
        self.assertEqual((j1["open_synced"], j1["close_synced"]), (1, 0))
        self.assertIsNotNone(j1["closed_at"])

        # ---- ERTALAB: internet bor, server «smena ochiq» deydi
        rules.online = True
        self.assertIsNotNone(rules.hello()["shift"])
        bugun = self.kassa("state:ochilganda", "resume", "state:smena_ochgach", "sell:2",
                           "wait_synced", "close", "wait_synced", "state:oxirida",
                           razmen=150_000)
        ochilganda = bugun["step"]["ochilganda"]
        # ENG MUHIMI: dastur kechagi (yopilgan) smenaga kirib KETMADI.
        self.assertFalse(ochilganda["enabled"])
        self.assertTrue(ochilganda["login_visible"])
        self.assertTrue(ochilganda["resume_mode"])
        self.assertIsNone(ochilganda["current"])
        self.assertTrue(bugun["step"]["smena_ochgach"]["enabled"])
        self.assertNotEqual(bugun["step"]["smena_ochgach"]["current"], j1["uuid"])

        s1, s2 = rules.shifts
        self.assertEqual([len(s["sales"]) for s in rules.shifts], [3, 2])
        self.assertEqual([s["status"] for s in rules.shifts], ["closed", "closed"])
        self.assertEqual(s2["opening_cash"], 150_000_00)
        self.assertEqual(s1["closed_at"].isoformat(), j1["closed_at"])     # o'z vaqti bilan
        self.assertLess(s1["closed_at"], s2["opened_at"])
        self.assertEqual(set(self.server.codes("sales")), {201})           # birorta rad yo'q
        self.assertNotIn(409, [c for _, c in self.server.paths])
        self.assertFalse(any(s["auto"] for s in rules.shifts))
        self.assertEqual((bugun["unsent"], bugun["rejected"]), (0, 0))
        self.assertEqual(bugun["step"]["oxirida"]["alert"], "")
        self.assertEqual(bugun["boxes"], [])
        self.assertTrue(all(row["close_synced"] for row in bugun["journal"]))

    def test_butunlay_internetsiz_kun(self):
        """Internet umuman yo'q: kirish (saqlangan kassir), smena, savdo,
        hisobot, yopish — hammasi ishlaydi; internet kelgach hammasi serverda."""
        rules = self.server.rules
        # Kassir shu kassada bir marta (internet borida) kirgan — smena ochib-yopgan.
        self.kassa("login", "state:kirgach", "wait_synced", "close", "wait_synced")
        self.assertEqual([s["status"] for s in rules.shifts], ["closed"])
        rules.online = False
        kun = self.kassa("state:ochilganda", "resume", "state:ichida", "sell:4", "cash:20000",
                         "report", "close", "state:yopgach", razmen=200_000)
        self.assertTrue(kun["step"]["ichida"]["enabled"])
        self.assertIn("oflayn", kun["step"]["ichida"]["shift_label"].lower())
        self.assertEqual([n for n, _ in kun["printed"]], ["oraliq", "smena"])
        smena_cheki = kun["printed"][1][1]
        self.assertIn("4 TA CHEK SERVERGA YETMAGAN", smena_cheki)
        self.assertEqual(kun["unsent"], 4)
        self.assertEqual(kun["boxes"], [])
        self.assertEqual(len(rules.shifts), 1)            # server hali bilmaydi
        rules.online = True
        ertasi = self.kassa("wait_synced", "state:oxirida")
        self.assertEqual([len(s["sales"]) for s in rules.shifts], [0, 4])
        self.assertEqual([len(s["cash"]) for s in rules.shifts], [0, 1])
        self.assertEqual(rules.shifts[1]["opening_cash"], 200_000_00)
        self.assertEqual([s["status"] for s in rules.shifts], ["closed", "closed"])
        self.assertEqual((ertasi["unsent"], ertasi["unsent_cash"]), (0, 0))
        self.assertFalse(ertasi["step"]["oxirida"]["enabled"])      # ochiq smena yo'q

    def test_rad_etilgan_chek_qizil_ogohlantirish(self):
        self.kassa("login", "reject:25", "sell:1", "wait:300")
        ochilganda = self.kassa("state:ochilganda")["step"]["ochilganda"]
        self.assertTrue(ochilganda["enabled"])            # smena ochiq — davom etadi
        self.assertIn("1 ta chekni server qabul qilmadi", ochilganda["alert"])
        self.assertIn("Narx eskirgan", ochilganda["alert"])


class EskiServerBilanDasturTest(DasturOchilishiTest):
    """Xuddi shu — hozir ishlab turgan (himoyasiz) server qoidalari bilan."""

    HIMOYA = False


if __name__ == "__main__":
    unittest.main()
