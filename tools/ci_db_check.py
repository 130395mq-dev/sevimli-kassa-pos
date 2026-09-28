"""CI tekshiruvi (audit 2026-09-28): kassa lokal bazasi versiyalar orasida.

Bitta haqiqiy SQLite fayl (kassa.db) ustida, ALOHIDA jarayonlarda:

  1. ESKI kod (--old papka, masalan 1.18.6) bazani yaratadi, navbatga
     cheklar va pul amalini qo'yadi, keyin jarayon os._exit bilan «o'ldiriladi»
     (close() chaqirilmaydi — tok o'chgandek).
  2. YANGI kod (joriy papka) o'sha bazani ochadi: hamma chek navbatda,
     payload bayt-baayt o'zgarmagan; yangi chek qo'shadi; yana «o'ldiriladi».
  3. ESKI kod qayta ochadi (orqaga qaytish): hammasi o'qiladi, yangi kod
     qo'shgan chek ham; PRAGMA integrity_check = ok.

Haqiqiy kassa bazasiga tegmaydi: hammasi vaqtinchalik papkada.
Ishga tushirish:  python tools/ci_db_check.py --old <eski_kod_papkasi>

EXE sinovi uchun (Windows CI): --seed <db> eski kod bilan navbatli baza
yaratadi; --verify <db> EXE'lar ishlab bo'lgach navbat o'z joyidami, deb
tekshiradi (sqlite3 bilan, faqat SELECT).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

RECEIPTS = {
    # Eski kassa narxli yorliq: uzun kasr (I01/I02)
    "11111111-1111-4111-8111-111111111111": {"items": [{"quantity": "0.3333333333333333333333333333",
                                                         "price": 300000, "total": 100000}]},
    # Yangi kassa: grammgacha
    "22222222-2222-4222-8222-222222222222": {"items": [{"quantity": "0.333", "price": 300000, "total": 99900}]},
    # Dona va upakovka
    "33333333-3333-4333-8333-333333333333": {"items": [{"quantity": "16.000", "price": 300000, "total": 4800000}]},
}
NEW_RECEIPT = ("44444444-4444-4444-8444-444444444444",
               {"items": [{"quantity": "1", "price": 300000, "total": 300000}]})
CASH = ("55555555-5555-4555-8555-555555555555", {"kind": "in", "amount": 10000})

STEP = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
from pos.store import Store
db, mode, data = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
s = Store(db)
out = {"pending": s.pending_count(),
       "payloads": {r["local_uuid"]: json.loads(r["payload"]) for r in s.unsent_rows()},
       "cash": [r["local_uuid"] for r in s.pending_cash()],
       "integrity": s.db.execute("PRAGMA integrity_check").fetchone()[0]}
for uuid, payload in data.get("queue", {}).items():
    s.queue(uuid, payload, "2026-09-28T10:00:00+05:00")
for uuid, payload in data.get("cash", {}).items():
    s.queue_cash(uuid, payload, "2026-09-28T10:00:01+05:00")
print(json.dumps(out))
sys.stdout.flush()
os._exit(0)      # close() yo'q — jarayon keskin to'xtadi
'''


def step(code_dir: Path, db: Path, data: dict) -> dict:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(code_dir))
    r = subprocess.run([sys.executable, "-c", STEP, str(db), "x", json.dumps(data)],
                       cwd=code_dir, env=env, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise SystemExit(f"{code_dir} xato:\n{r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def verify(db: Path) -> int:
    import sqlite3
    con = sqlite3.connect(db)      # CI'dagi vaqtinchalik nusxa; faqat SELECT
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    rows = dict(con.execute("SELECT local_uuid, payload FROM outbox WHERE sent = 0").fetchall())
    for uuid, payload in RECEIPTS.items():
        assert uuid in rows, f"navbatdan yo'qoldi: {uuid}"
        assert json.loads(rows[uuid]) == payload, f"payload o'zgardi: {uuid}"
    cash = [r[0] for r in con.execute("SELECT local_uuid FROM cash_outbox WHERE sent = 0")]
    assert CASH[0] in cash, "pul amali navbatdan yo'qoldi"
    con.close()
    print(f"OK: {len(RECEIPTS)} chek va 1 pul amali navbatda, payload o'zgarmagan, integrity_check=ok")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", type=Path, help="eski versiya kodi (pos/ bilan)")
    ap.add_argument("--seed", type=Path, help="eski kod bilan navbatli baza yaratish")
    ap.add_argument("--verify", type=Path, help="bazadagi navbatni tekshirish")
    args = ap.parse_args()
    if args.verify:
        return verify(args.verify)
    if not args.old:
        ap.error("--old kerak")
    old, new = args.old.resolve(), HERE
    if args.seed:
        step(old, args.seed.resolve(), {"queue": RECEIPTS, "cash": dict([CASH])})
        print(f"Navbatli baza yaratildi: {args.seed}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "kassa.db"
        first = step(old, db, {"queue": RECEIPTS, "cash": dict([CASH])})
        assert first["pending"] == 0, first

        upgraded = step(new, db, {"queue": dict([NEW_RECEIPT])})
        assert upgraded["integrity"] == "ok", upgraded
        assert upgraded["pending"] == len(RECEIPTS), upgraded
        assert upgraded["payloads"] == RECEIPTS, "yangi kod eski navbatni o'zgartirdi"
        assert upgraded["cash"] == [CASH[0]], upgraded

        rolled_back = step(old, db, {})
        assert rolled_back["integrity"] == "ok", rolled_back
        expected = dict(RECEIPTS, **dict([NEW_RECEIPT]))
        assert rolled_back["pending"] == len(expected), rolled_back
        assert rolled_back["payloads"] == expected, "eski kod navbatni o'qiy olmadi"
        assert rolled_back["cash"] == [CASH[0]], rolled_back

    print("OK: eski->yangi->eski, navbat to'liq saqlandi "
          f"({len(expected)} chek, 1 pul amali), integrity_check=ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
