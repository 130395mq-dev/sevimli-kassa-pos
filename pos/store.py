"""
Kassaning lokal bazasi.

Ikkita vazifasi bor:

1. **Katalog keshi** — internet uzilsa ham tovarlarni topish uchun.
2. **Navbat (outbox)** — yuborilmagan cheklar shu yerda kutadi.

Ikkinchisi muhimroq. Chek avval shu bazaga yoziladi, keyin serverga
yuborilishga urinadi. Internet yo'q bo'lsa — chek diskda qoladi va
kassir ishlashda davom etadi. Internet qaytganda navbat o'zi bo'shaydi.

Chek diskka yozilmaguncha kassirga «yakunlandi» deb ko'rsatilmaydi.
Aks holda tok o'chsa savdo yo'qoladi.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from .cart import Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id        INTEGER PRIMARY KEY,
    ms_id     TEXT NOT NULL,
    name      TEXT NOT NULL,
    code      TEXT,
    barcode   TEXT,
    price     INTEGER NOT NULL,
    is_weight INTEGER NOT NULL DEFAULT 0,
    plu       INTEGER,
    tracked   INTEGER NOT NULL DEFAULT 0,
    stock     REAL NOT NULL DEFAULT 0,
    prices    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS products_plu     ON products(plu);
CREATE INDEX IF NOT EXISTS products_name    ON products(name);

-- Tovarning BARCHA shtrix-kodlari (dona, blok, quti, MoySklad o'zi
-- yaratgani…). products.barcode — asosiysi (eski kassalar uchun qoladi).
CREATE TABLE IF NOT EXISTS barcodes (
    code       TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    PRIMARY KEY (code, product_id)
);
CREATE INDEX IF NOT EXISTS barcodes_product ON barcodes(product_id);

CREATE TABLE IF NOT EXISTS outbox (
    local_uuid TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    sent       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(sent, created_at);

CREATE TABLE IF NOT EXISTS parked (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    summary    TEXT NOT NULL,
    total      INTEGER NOT NULL,
    payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: fon oqimi o'z Store nusxasini ochadi
        # (o'z ulanishi bilan). Ikki ulanish bitta faylga WAL orqali
        # xavfsiz ishlaydi; busy_timeout «database is locked» ni oldini oladi.
        self.db = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        # Tok o'chganda baza buzilmasligi uchun
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)
        self._migrate()
        #: Joriy narx turi (MoySklad id). None — tovarning asosiy narxi.
        self.price_type_id: str | None = self.get("price_type_id") or None

    def _migrate(self) -> None:
        """Eski bazaga yangi ustunlarni qo'shadi (CREATE IF NOT EXISTS
        mavjud jadvalni o'zgartirmaydi)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(products)")}
        if "prices" not in cols:
            self.db.execute(
                "ALTER TABLE products ADD COLUMN prices TEXT NOT NULL DEFAULT '{}'"
            )

    def set_price_type(self, price_type_id: str | None) -> None:
        """Kassa qaysi narx turida sotadi — saqlanadi, qayta ochilganda ham
        shu qoladi (kassir smena boshida bir marta tanlaydi)."""
        self.price_type_id = price_type_id or None
        self.set("price_type_id", price_type_id or "")

    def close(self) -> None:
        self.db.close()

    # ---------------------------------------------------------- katalog

    def replace_products(self, rows: list[dict]) -> dict:
        """Kelgan tovarlarni yozadi. Bor bo'lsa yangilaydi.

        `archived: true` kelganlar (buxgalter o'chirgan/arxivlagan) —
        lokal bazadan O'CHIRILADI, kassir ularni ko'rmaydi va sota olmaydi.

        Qaytaradi: {"new": yangi, "updated": yangilangan, "gone": o'chirilgan}
        — yangilanish oynasida kassirga ko'rsatiladi.
        """
        gone = [r["id"] for r in rows if r.get("archived")]
        rows = [r for r in rows if not r.get("archived")]
        stats = {"new": 0, "updated": 0, "gone": 0}

        if gone:
            self.db.executemany(
                "DELETE FROM products WHERE id = ?", [(i,) for i in gone]
            )
            self.db.executemany(
                "DELETE FROM barcodes WHERE product_id = ?", [(i,) for i in gone]
            )
            stats["gone"] = len(gone)
        if not rows:
            return stats

        # Qaysilari yangi, qaysilari bor — hisobot uchun
        ids = [r["id"] for r in rows]
        existing: set[int] = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            existing.update(
                row[0] for row in self.db.execute(
                    f"SELECT id FROM products WHERE id IN ({marks})", chunk
                )
            )
        stats["updated"] = len(existing)
        stats["new"] = len(ids) - len(existing)

        self.db.executemany(
            """
            INSERT INTO products
                (id, ms_id, name, code, barcode, price, is_weight, plu, tracked,
                 stock, prices)
            VALUES (:id, :ms_id, :name, :code, :barcode, :price,
                    :is_weight, :plu, :tracked, :stock, :prices)
            ON CONFLICT(id) DO UPDATE SET
                ms_id=excluded.ms_id, name=excluded.name, code=excluded.code,
                barcode=excluded.barcode, price=excluded.price,
                is_weight=excluded.is_weight, plu=excluded.plu,
                tracked=excluded.tracked, stock=excluded.stock,
                prices=excluded.prices
            """,
            [
                {
                    "id": r["id"],
                    "ms_id": r["ms_id"],
                    "name": r["name"],
                    "code": r.get("code") or "",
                    "barcode": r.get("barcode") or "",
                    "price": r["price"],
                    "is_weight": int(bool(r.get("is_weight"))),
                    "plu": r.get("plu"),
                    "tracked": int(bool(r.get("tracked"))),
                    "stock": float(r.get("stock") or 0),
                    "prices": json.dumps(r.get("prices") or {}),
                }
                for r in rows
            ],
        )
        # Barcha shtrix-kodlar: server «barcodes» ro'yxatini beradi (yangi),
        # bermasa — bitta «barcode» (eski server). Tovarning eski kodlari
        # o'chirilib, yangilari yoziladi.
        self.db.executemany("DELETE FROM barcodes WHERE product_id = ?", [(r["id"],) for r in rows])
        pairs = []
        for r in rows:
            codes = r.get("barcodes")
            if not isinstance(codes, list):
                codes = [r.get("barcode") or ""]
            if r.get("barcode") and r["barcode"] not in codes:
                codes.append(r["barcode"])
            for c in codes:
                c = str(c or "").strip()
                if c:
                    pairs.append((c, r["id"]))
        if pairs:
            self.db.executemany(
                "INSERT OR IGNORE INTO barcodes (code, product_id) VALUES (?, ?)", pairs
            )
        return stats

    def product_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def _to_product(self, row: sqlite3.Row) -> Product:
        try:
            prices = json.loads(row["prices"] or "{}")
        except (ValueError, TypeError, IndexError, KeyError):
            prices = {}
        p = Product(
            id=row["id"], ms_id=row["ms_id"], name=row["name"],
            price=row["price"], code=row["code"] or "",
            barcode=row["barcode"] or "",
            is_weight=bool(row["is_weight"]), plu=row["plu"],
            tracked=bool(row["tracked"]), stock=row["stock"],
            prices=prices,
        )
        # Joriy narx turi (ulgurji tanlangan bo'lsa) — narx shu yerda
        # almashadi; katalog ham, chek ham shu narxni ko'radi.
        p.price = p.price_for(self.price_type_id)
        return p

    def by_barcode(self, code: str) -> Product | None:
        """Aynan shu kodli tovar — asosiy kod yoki qo'shimcha kodlardan biri."""
        code = (code or "").strip()
        if not code:
            return None
        row = self.db.execute(
            "SELECT * FROM products WHERE barcode = ?", (code,)
        ).fetchone()
        if not row:
            row = self.db.execute(
                "SELECT p.* FROM products p JOIN barcodes b ON b.product_id = p.id "
                "WHERE b.code = ? LIMIT 1",
                (code,),
            ).fetchone()
        return self._to_product(row) if row else None

    def by_plu(self, plu: int) -> Product | None:
        # Tarozi yorlig'idagi PLU -> tovar. Ikki yo'l bilan qidiramiz:
        #   1) plu ustuni (server to'ldirgan bo'lsa)
        #   2) tovar kodining raqamli qiymati (MoySklad kod = tarozi PLU;
        #      "650", "0650", "00650" — hammasi 650 ga teng)
        # Vaznli tovar birinchi bo'lsin (ORDER BY is_weight DESC).
        row = self.db.execute(
            "SELECT * FROM products "
            "WHERE plu = ? OR CAST(code AS INTEGER) = ? "
            "ORDER BY is_weight DESC LIMIT 1",
            (plu, plu),
        ).fetchone()
        return self._to_product(row) if row else None

    def search(self, text: str, limit: int = 200) -> list[Product]:
        if text:
            like = f"%{text}%"
            rows = self.db.execute(
                "SELECT * FROM products WHERE name LIKE ? OR code LIKE ?"
                " ORDER BY name LIMIT ?",
                (like, like, limit),
            ).fetchall()
            return [self._to_product(r) for r in rows]

        # Qidiruv bo'sh — FAQAT sevimlilar (yulduzcha bosilganlar) ko'rinadi.
        # Qolgan tovarlar ko'rsatilmaydi; kassir ularni qidiruv orqali topadi.
        # Shu bilan ekran toza va tez — kunlik ko'p ketadigan tovarlar bir
        # bosishда, minglab tovar bekorga chizilmaydi.
        favs = self.favorites()
        if not favs:
            return []
        marks = ",".join("?" * len(favs))
        rows = self.db.execute(
            f"SELECT * FROM products WHERE id IN ({marks}) ORDER BY name",
            tuple(favs),
        ).fetchall()
        return [self._to_product(r) for r in rows]

    # ------------------------------------------------------------ navbat

    def queue(self, local_uuid: str, payload: dict, created_at: str) -> None:
        """Chekni navbatga qo'yadi. Bu yozuv diskka tushgach chek xavfsiz."""
        self.db.execute(
            "INSERT OR IGNORE INTO outbox (local_uuid, payload, created_at)"
            " VALUES (?, ?, ?)",
            (local_uuid, json.dumps(payload, ensure_ascii=False), created_at),
        )

    #: Chek shuncha marta rad etilsa — «tiqilib qolgan» deb chetga chiqadi.
    #: Bu bitta yaroqsiz chek butun navbatni to'sib qo'yishining oldini
    #: oladi (server uni har safar rad etsa, orqadagilar yubprilaveradi).
    MAX_ATTEMPTS = 20

    def pending(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM outbox WHERE sent = 0 AND attempts < ?"
            " ORDER BY created_at LIMIT ?",
            (self.MAX_ATTEMPTS, limit),
        ).fetchall()

    def pending_count(self) -> int:
        """Hali yuborilmagan, urinish davom etayotgan cheklar soni."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox WHERE sent = 0 AND attempts < ?",
            (self.MAX_ATTEMPTS,),
        ).fetchone()[0]

    def stuck_count(self) -> int:
        """Ko'p marta rad etilib, tiqilib qolgan cheklar soni (odam
        aralashuvi kerak — server ularni qabul qilmayapti)."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox WHERE sent = 0 AND attempts >= ?",
            (self.MAX_ATTEMPTS,),
        ).fetchone()[0]

    def mark_sent(self, local_uuid: str) -> None:
        self.db.execute(
            "UPDATE outbox SET sent = 1, last_error = '' WHERE local_uuid = ?",
            (local_uuid,),
        )

    def mark_failed(self, local_uuid: str, error: str) -> None:
        self.db.execute(
            "UPDATE outbox SET attempts = attempts + 1, last_error = ?"
            " WHERE local_uuid = ?",
            (error[:500], local_uuid),
        )

    def forget_sent(self, keep_days: int = 30) -> None:
        """Yuborilgan cheklarni tozalaydi — baza cheksiz o'smasin."""
        self.db.execute(
            "DELETE FROM outbox WHERE sent = 1"
            " AND created_at < datetime('now', ?)",
            (f"-{keep_days} days",),
        )

    # ------------------------------------------------- kassir (oflayn kirish)
    #
    # Internet uzilganda ham kassir kira olishi kerak — aks holda savdo
    # to'xtaydi. Buning uchun muvaffaqiyatli kirishdan keyin parolning
    # XESHI shu kassada saqlanadi (parolning o'zi emas). Oflaynda parol
    # o'sha xesh bilan tekshiriladi — ya'ni tekshiruv haqiqiy, «hamma
    # kira oladi» degani emas.

    _KDF_ROUNDS = 120_000

    @staticmethod
    def _kdf(password: str, salt: bytes) -> str:
        import hashlib

        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, Store._KDF_ROUNDS
        ).hex()

    def remember_cashier(self, login: str, password: str, cashier: dict) -> None:
        import os

        salt = os.urandom(16)
        self.set(
            f"cashier:{login.lower()}",
            json.dumps({
                "salt": salt.hex(),
                "hash": self._kdf(password, salt),
                "cashier": cashier,
            }, ensure_ascii=False),
        )

    def offline_cashier(self, login: str, password: str) -> dict | None:
        """Oflayn kirish: saqlangan xesh bo'yicha tekshiradi.

        None qaytsa — bu kassada bu login hech qachon kirmagan yoki parol
        noto'g'ri.
        """
        import hmac

        raw = self.get(f"cashier:{login.lower()}")
        if not raw:
            return None
        try:
            data = json.loads(raw)
            salt = bytes.fromhex(data["salt"])
        except (ValueError, KeyError, TypeError):
            return None
        if not hmac.compare_digest(self._kdf(password, salt), data.get("hash", "")):
            return None
        return data.get("cashier")

    # -------------------------------------------------------------- meta

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ------------------------------------------- internetsiz ochilgan smena

    def set_local_shift(self, data: dict | None) -> None:
        """Internetsiz ochilgan smenani saqlaydi (yoki tozalaydi).

        Diskda turadi: dastur qayta ochilsa ham (hali internet yo'q)
        smena joyida qoladi, kassir qaytadan razmen so'ramaydi.
        """
        self.set("local_shift", json.dumps(data, ensure_ascii=False) if data else "")

    def get_local_shift(self) -> dict | None:
        raw = self.get("local_shift")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    # ------------------------------------------------- sevimli (pin) tovarlar

    def favorites(self) -> set[int]:
        """Kassir yulduzcha bosgan tovarlar (id lar). Ular katalog
        ro'yxatida tepada turadi — kunlik ko'p ketadigan tovarlar tez
        topilsin."""
        raw = self.get("favorites")
        if not raw:
            return set()
        try:
            return {int(x) for x in json.loads(raw)}
        except (ValueError, TypeError):
            return set()

    def is_favorite(self, product_id) -> bool:
        return int(product_id) in self.favorites()

    def toggle_favorite(self, product_id) -> bool:
        """Sevimliga qo'shadi yoki oladi. Yangi holatni qaytaradi."""
        favs = self.favorites()
        pid = int(product_id)
        if pid in favs:
            favs.discard(pid)
            on = False
        else:
            favs.add(pid)
            on = True
        self.set("favorites", json.dumps(sorted(favs)))
        return on

    # ------------------------------------------- qoldirilgan cheklar

    def park(self, summary: str, total: int, payload: dict) -> int:
        """Chekni keyinga qoldiradi.

        Diskka yoziladi, xotiraga emas: kassa o'chib qolsa ham chek
        joyida qoladi. Bozorda odatiy holat — mijoz biror narsani
        unutgan, navbatni to'sib turmasin deb chek chetga qo'yiladi.
        """
        from datetime import datetime

        cur = self.db.execute(
            "INSERT INTO parked (created_at, summary, total, payload)"
            " VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), summary, total,
             json.dumps(payload, ensure_ascii=False)),
        )
        return cur.lastrowid

    def parked(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM parked ORDER BY created_at DESC"
        ).fetchall()

    def parked_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM parked").fetchone()[0]

    def unpark(self, parked_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT payload FROM parked WHERE id = ?", (parked_id,)
        ).fetchone()
        if not row:
            return None
        self.db.execute("DELETE FROM parked WHERE id = ?", (parked_id,))
        return json.loads(row["payload"])

    # ------------------------------------------------------- tarix

    def recent_sales(self, limit: int = 30) -> list[sqlite3.Row]:
        """Oxirgi cheklar — tarix uchun."""
        return self.db.execute(
            "SELECT * FROM outbox ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
