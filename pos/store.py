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
import logging
import sqlite3
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from . import qidiruv
from .cart import Product

logger = logging.getLogger(__name__)

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
    prices    TEXT NOT NULL DEFAULT '{}',
    -- Qidiruv kaliti: nom lotin/kichik harf/toza ko'rinishda (pos/qidiruv.py)
    search_key TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS products_plu     ON products(plu);
CREATE INDEX IF NOT EXISTS products_name    ON products(name);

-- Tovarning BARCHA shtrix-kodlari (dona, blok, quti, MoySklad o'zi
-- yaratgani…). products.barcode — asosiysi (eski kassalar uchun qoladi).
CREATE TABLE IF NOT EXISTS barcodes (
    code       TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    -- Upakovka (MoySklad «Упаковка») kodi bo'lsa — ichida nechta dona; oddiy kod 1
    quantity   REAL NOT NULL DEFAULT 1,
    PRIMARY KEY (code, product_id)
);
CREATE INDEX IF NOT EXISTS barcodes_product ON barcodes(product_id);

CREATE TABLE IF NOT EXISTS outbox (
    local_uuid TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    sent       INTEGER NOT NULL DEFAULT 0,
    -- Server bergan chek raqami (Sale.pk). MoySklad'da «SK-<raqam>» nomi
    -- ham shu. Yuborilгач to'ldiriladi; navbatда turganда NULL.
    check_no   INTEGER,
    -- Qaysi smenaга tegishli — tarixда «shu smenadagi cheklar» uchun.
    -- Smenaга kirilganda o'rnatiladi; oflayn/onlayn o'zgarishidan qat'i
    -- nazar smena davomida o'zgarmaydi.
    shift_tag  TEXT NOT NULL DEFAULT ''
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

-- Kassaga pul kiritish/chiqarish. Chek kabi: avval diskka, keyin serverga.
-- Internet yo'q paytda ham amal yo'qolmaydi va smena yopilishini to'smaydi.
CREATE TABLE IF NOT EXISTS cash_outbox (
    local_uuid TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent       INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    shift_tag  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS cash_pending ON cash_outbox(sent, created_at);

-- SMENA JURNALI (1.19.0) — «smena kassaniki».
--
-- Smena shu jadvalda ochiladi va yopiladi — internet bor-yo'qligidan qat'i
-- nazar bir xil. Server keyin, fonda xabardor qilinadi (cheklar kabi: avval
-- diskka, keyin serverga). Dastur ochilganda qaysi smenada turgani SHU
-- YERDAN olinadi, serverdan ham, keshdan ham emas.
--
-- 12.11.2026 gacha smena holati to'rt joyda (active_shift_id, local_shift,
-- closed_shifts, last_hello) va serverda yashardi. O'sha kuni internetsiz
-- yopilgan smenaga dastur ertalab qayta kirib ketdi (server «hali ochiq»
-- degan), fon oqimi smenani yopdi va 136 ta chek rad etildi.
CREATE TABLE IF NOT EXISTS shifts (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Smenaning o'zgarmas belgisi. Kassa beradi, hech qachon o'zgarmaydi.
    uuid         TEXT NOT NULL UNIQUE,
    -- Shu smena cheklarining outbox.shift_tag qiymati. Ham o'zgarmaydi.
    tag          TEXT NOT NULL,
    server_id    INTEGER,          -- serverdagi id (serverga ochilgach)
    number       INTEGER,          -- smena raqami (server beradi)
    cashier_id   INTEGER NOT NULL DEFAULT 0,
    cashier      TEXT NOT NULL DEFAULT '',
    opened_at    TEXT NOT NULL,
    opening_cash INTEGER NOT NULL DEFAULT 0,
    closed_at    TEXT,             -- NULL — smena ochiq
    counted_cash INTEGER,
    open_synced  INTEGER NOT NULL DEFAULT 0,
    close_synced INTEGER NOT NULL DEFAULT 0,
    -- 1 — eski versiyada (jurnalsiz, onlayn) ochilgan smena: server uni
    -- belgi (uuid) bilan emas, faqat `server_id` bilan taniydi.
    legacy       INTEGER NOT NULL DEFAULT 0
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

        if "price_quote" not in cols:
            self.db.execute("ALTER TABLE products ADD COLUMN price_quote TEXT NOT NULL DEFAULT ''")

        # Qidiruv kaliti (1.18.5): eski bazadagi tovarlarga bir marta yoziladi.
        # Kalit qoidasi o'zgarsa — «search_key_v1» ni v2 qilib, qayta yoziladi.
        if "search_key" not in cols:
            self.db.execute("ALTER TABLE products ADD COLUMN search_key TEXT NOT NULL DEFAULT ''")
        if not self.get("search_key_v1"):
            self.db.executemany(
                "UPDATE products SET search_key = ? WHERE id = ?",
                [(qidiruv.key(row["name"]), row["id"])
                 for row in self.db.execute("SELECT id, name FROM products")],
            )
            self.set("search_key_v1", "1")
        # Recover old receipts sidelined by temporary outages, once per upgrade.
        if not self.get("outbox_retry_v2"):
            self.db.execute("UPDATE outbox SET attempts=0 WHERE sent=0")
            self.set("outbox_retry_v2", "1")

        # Chek raqami va smena belgisi — eski bazaga qo'shamiz.
        ob_cols = {r[1] for r in self.db.execute("PRAGMA table_info(outbox)")}
        if "check_no" not in ob_cols:
            self.db.execute("ALTER TABLE outbox ADD COLUMN check_no INTEGER")
        if "shift_tag" not in ob_cols:
            self.db.execute("ALTER TABLE outbox ADD COLUMN shift_tag TEXT NOT NULL DEFAULT ''")

        # Upakovka kodlari (1.17.14): kod ichida nechta dona
        bc_cols = {r[1] for r in self.db.execute("PRAGMA table_info(barcodes)")}
        if "quantity" not in bc_cols:
            self.db.execute("ALTER TABLE barcodes ADD COLUMN quantity REAL NOT NULL DEFAULT 1")

        # 1.19.0: rad etilgan chek/pul amali o'zi qayta yuboriladi — keyingi
        # urinish vaqti (`retry_at`, UTC ISO). NULL — hozir yuborsa bo'ladi.
        if "retry_at" not in ob_cols:
            self.db.execute("ALTER TABLE outbox ADD COLUMN retry_at TEXT")
            # Yangilanishgacha tiqilib qolgan cheklar — birinchi navbatda
            # qayta yuboriladi (ilgari ular tugma bosilguncha turardi).
            self.db.execute(
                "UPDATE outbox SET retry_at = ? WHERE sent = 0 AND attempts >= ?",
                (self._now(), self.MAX_ATTEMPTS),
            )
        cash_cols = {r[1] for r in self.db.execute("PRAGMA table_info(cash_outbox)")}
        if "attempts" not in cash_cols:
            self.db.execute("ALTER TABLE cash_outbox ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        if "retry_at" not in cash_cols:
            self.db.execute("ALTER TABLE cash_outbox ADD COLUMN retry_at TEXT")

        # 1.19.0: eski smena holatini jurnalga ko'chiramiz.
        if not self.get("journal_v1"):
            self._adopt_legacy_shifts()
            self.set("journal_v1", "1")
        elif self._legacy_shift_state():
            # Jurnal bor, lekin eski kalitlar yana to'lgan: dastur eski
            # versiyaga QAYTARILGAN, u yerda smena ochilgan/yopilgan va endi
            # yana yangilangan. Eski versiya qoldirgan holat yangiroq.
            logger.warning("Eski versiya smena holati topildi (dastur orqaga "
                           "qaytarilgan edi) — jurnalga qo'shilmoqda")
            self._adopt_legacy_shifts()

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
                 stock, prices, price_quote, search_key)
            VALUES (:id, :ms_id, :name, :code, :barcode, :price,
                    :is_weight, :plu, :tracked, :stock, :prices, :price_quote,
                    :search_key)
            ON CONFLICT(id) DO UPDATE SET
                ms_id=excluded.ms_id, name=excluded.name, code=excluded.code,
                barcode=excluded.barcode, price=excluded.price,
                is_weight=excluded.is_weight, plu=excluded.plu,
                tracked=excluded.tracked, stock=excluded.stock,
                prices=excluded.prices, price_quote=excluded.price_quote,
                search_key=excluded.search_key
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
                    "price_quote": r.get("price_quote") or "",
                    "search_key": qidiruv.key(r["name"]),
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
                    pairs.append((c, r["id"], 1.0))
            # Upakovka kodlari: server «packs» [{barcode, quantity}] beradi —
            # skanerlansa shuncha dona qo'shiladi (6 talik upakovka → 6).
            for pk in r.get("packs") or []:
                c = str((pk or {}).get("barcode") or "").strip()
                try:
                    q = float((pk or {}).get("quantity") or 0)
                except (TypeError, ValueError):
                    q = 0
                if c and q > 0:
                    pairs.append((c, r["id"], q))
        if pairs:
            self.db.executemany(
                "INSERT OR REPLACE INTO barcodes (code, product_id, quantity) VALUES (?, ?, ?)", pairs
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
            prices=prices, price_quote=row["price_quote"],
        )
        # Joriy narx turi (ulgurji tanlangan bo'lsa) — narx shu yerda
        # almashadi; katalog ham, chek ham shu narxni ko'radi.
        p.price = p.price_for(self.price_type_id)
        return p

    def barcodes_of(self, product_id) -> list[str]:
        """Tovarning barcha shtrix-kodlari: asosiy + qo'shimcha (barcodes)."""
        codes = [r[0] for r in self.db.execute(
            "SELECT code FROM barcodes WHERE product_id = ?", (product_id,)
        ).fetchall()]
        row = self.db.execute(
            "SELECT barcode FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row and row[0] and row[0] not in codes:
            codes.append(row[0])
        return codes

    def by_barcode(self, code: str) -> Product | None:
        """Aynan shu kodli tovar — asosiy kod yoki qo'shimcha kodlardan biri."""
        found = self.by_barcode_qty(code)
        return found[0] if found else None

    def by_barcode_qty(self, code: str):
        """Kod → (tovar, nechta dona). Oddiy kod — 1; upakovka kodi —
        upakovkadagi dona soni (masalan 6). Topilmasa None.

        Avval AYNAN shu kod. Topilmasa va kodda harf bo'lsa (Code128,
        masalan «HT00026010093») — klaviatura tili yoki Caps Lock buzgan
        bo'lishi mumkin: kirill harflarni lotin tugmalariga qaytarib, keyin
        katta-kichik harfni farqlamay qidiramiz (2026-09-30). Raqamli
        kodlar (EAN-13, tarozi) bu yo'lga tushmaydi."""
        from .barcode import keyboard_to_latin

        code = (code or "").strip()
        if not code:
            return None
        found = self._barcode_qty(code)
        if found is None and any(ch.isalpha() for ch in code):
            latin = keyboard_to_latin(code)
            if latin != code:
                found = self._barcode_qty(latin)
            if found is None:
                found = self._barcode_qty(latin, nocase=True)
        return found

    def _barcode_qty(self, code: str, nocase: bool = False):
        eq = "= ? COLLATE NOCASE" if nocase else "= ?"
        row = self.db.execute(
            "SELECT p.*, b.quantity AS pack_qty FROM products p "
            f"JOIN barcodes b ON b.product_id = p.id WHERE b.code {eq} "
            "ORDER BY b.quantity LIMIT 1",
            (code,),
        ).fetchone()
        qty = float(row["pack_qty"] or 1) if row else 1.0
        if not row:
            row = self.db.execute(
                f"SELECT * FROM products WHERE barcode {eq}", (code,)
            ).fetchone()
            qty = 1.0
        if not row:
            return None
        return self._to_product(row), qty

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

    # ------------------------------------------- faqat kod bo'yicha

    def _code_rows(self, q: str, prefix: bool, limit: int):
        """Kod bo'yicha qatorlar: aniq (katta-kichik harf farqsiz), raqamli
        kod oldidagi nollarsiz («117» → «00117»), `prefix` bo'lsa — kodi
        shu bilan boshlanganlar ham. Natija: aniqlari oldin."""
        conds = ["code = ? COLLATE NOCASE"]
        params: list = [q]
        if q.isdigit() and int(q) > 0:
            conds.append("(code GLOB '[0-9]*' AND CAST(code AS INTEGER) = ?)")
            params.append(int(q))
        if prefix:
            esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conds.append("code LIKE ? ESCAPE '\\'")
            params.append(esc + "%")
        rows = self.db.execute(
            f"SELECT * FROM products WHERE code != '' AND ({' OR '.join(conds)})"
            " ORDER BY code LIMIT ?",
            (*params, limit * 3),
        ).fetchall()

        def exact(r) -> bool:
            code = (r["code"] or "")
            if code.lower() == q.lower():
                return True
            return q.isdigit() and code.isdigit() and int(code) == int(q)

        rows.sort(key=lambda r: (0 if exact(r) else 1, (r["code"] or "")))
        return rows[:limit], exact

    def search_by_code(self, text: str, limit: int = 50) -> list[Product]:
        """Qidiruv FAQAT tovar kodi bo'yicha (egasi, 2026-10-24: «kodi bilan
        qidirish bo'lsin, faqat kod bilan»). Nom bo'yicha qidirilmaydi —
        kassir o'xshash nomli boshqa tovarni (Cola 2 L / 2,5 L) bosib
        yubormasin. Qidiruv bo'sh bo'lsa — sevimlilar (avvalgidek)."""
        q = (text or "").strip()
        if not q:
            return self.search("")
        rows, _ = self._code_rows(q, prefix=True, limit=limit)
        return [self._to_product(r) for r in rows]

    def by_code(self, text: str) -> Product | None:
        """Aynan shu kodli bitta tovar (kassir kodni terib Enter bosganda)."""
        q = (text or "").strip()
        if not q:
            return None
        rows, exact = self._code_rows(q, prefix=False, limit=2)
        hits = [r for r in rows if exact(r)]
        return self._to_product(hits[0]) if len(hits) == 1 else None

    def search(self, text: str, limit: int = 200) -> list[Product]:
        """Nom yoki kod bo'yicha qidiruv.

        Nom bo'yicha — «kalit» orqali (pos/qidiruv.py): kirill/lotin,
        katta-kichik harf, so'z tartibi, apostrof farq qilmaydi; so'rovning
        har bir so'zi nomda uchrasa — topiladi («1 lit sut» → «Сут 1 литр»).
        Natija: nomi so'rov bilan boshlanganlar oldin, keyin so'z boshi
        mos kelganlar, keyin qolganlari — har guruh alifbo bo'yicha.
        """
        if text and text.strip():
            toks = qidiruv.tokens(text)
            if not toks:
                return []
            conds = " AND ".join("search_key LIKE ?" for _ in toks)
            params = [f"%{t}%" for t in toks]
            rows = self.db.execute(
                f"SELECT * FROM products WHERE ({conds}) OR code LIKE ?"
                " ORDER BY name LIMIT ?",
                (*params, f"%{text.strip()}%", limit * 3),
            ).fetchall()
            rows.sort(key=lambda r: (qidiruv.rank(r["search_key"], text),
                                     (r["name"] or "").lower()))
            return [self._to_product(r) for r in rows[:limit]]

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
        # Joriy smena belgisi — tarixда «shu smenadagi cheklar» uchun. Smenaга
        # kirilганда o'rnatiladi (main._enter_kassa). Bo'lmasa bo'sh — hamma
        # tarixда ko'rinadi (eski xatti-harakat).
        shift_tag = self.get("history_shift_tag") or ""
        self.db.execute(
            "INSERT OR IGNORE INTO outbox (local_uuid, payload, created_at, shift_tag)"
            " VALUES (?, ?, ?, ?)",
            (local_uuid, json.dumps(payload, ensure_ascii=False), created_at, shift_tag),
        )

    #: Chek shuncha marta rad etilsa — «tiqilib qolgan» deb chetga chiqadi:
    #: bitta yaroqsiz chek butun navbatni to'sib qo'ymaydi (server uni har
    #: safar rad etsa ham orqadagilar yuborilaveradi).
    #:
    #: 1.19.0 dan «chetga chiqdi» — «unutildi» degani EMAS: tiqilgan chek
    #: har `RETRY_EVERY` soniyada o'zi qayta yuboriladi. Ilgari u abadiy
    #: to'xtardi va faqat «Ma'lumotlarni yangilash» tugmasi qayta yuborardi
    #: (12.11.2026: kassa3 da 119 chek besh soat shunday turdi).
    MAX_ATTEMPTS = 20

    #: Tiqilgan chek/pul amali shuncha soniyada bir marta o'zi qayta yuboriladi
    RETRY_EVERY = 15 * 60

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _retry_at(cls) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=cls.RETRY_EVERY)).isoformat()

    def pending(self, limit: int = 50) -> list[sqlite3.Row]:
        """Hozir yuboriladigan cheklar: urinish limiti tugamaganlari va
        tiqilganlaridan qayta urinish vaqti kelganlari."""
        return self.db.execute(
            "SELECT * FROM outbox WHERE sent = 0 AND (attempts < ?"
            " OR (retry_at IS NOT NULL AND retry_at <= ?))"
            " ORDER BY created_at LIMIT ?",
            (self.MAX_ATTEMPTS, self._now(), limit),
        ).fetchall()

    def pending_count(self) -> int:
        """Hali yuborilmagan, urinish davom etayotgan cheklar soni."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox WHERE sent = 0 AND attempts < ?",
            (self.MAX_ATTEMPTS,),
        ).fetchone()[0]

    def stuck_count(self) -> int:
        """Ko'p marta rad etilib, tiqilib qolgan cheklar soni (odam qarashi
        kerak — server ularni qabul qilmayapti). Ular ham vaqti-vaqti bilan
        o'zi qayta yuboriladi (`RETRY_EVERY`)."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox WHERE sent = 0 AND attempts >= ?",
            (self.MAX_ATTEMPTS,),
        ).fetchone()[0]

    def rejected_count(self) -> int:
        """Server kamida bir marta RAD ETGAN, hali yuborilmagan cheklar.

        «Internet kutilyapti» dan farqi shu: aloqa uzilishi `attempts` ni
        oshirmaydi (note_outage), rad javobi oshiradi (mark_failed). Kassa
        ekranidagi qizil ogohlantirish shunga qaraydi."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox WHERE sent = 0 AND attempts > 0"
        ).fetchone()[0]

    def rejected_reason(self) -> str:
        row = self.db.execute(
            "SELECT last_error FROM outbox WHERE sent = 0 AND attempts > 0"
            " AND last_error <> '' ORDER BY created_at LIMIT 1"
        ).fetchone()
        return row["last_error"] if row else ""

    def mark_sent(self, local_uuid: str, check_no: int | None = None,
                  receipt_number: str | None = None) -> None:
        """Chek yuborildi; MoySklad bergan ОТ-* raqamni lokal tarixga yozadi."""
        if receipt_number:
            row = self.db.execute(
                "SELECT payload FROM outbox WHERE local_uuid = ?", (local_uuid,)
            ).fetchone()
            if row:
                try:
                    payload = json.loads(row["payload"])
                    payload["receipt_number"] = str(receipt_number)
                    self.db.execute(
                        "UPDATE outbox SET payload = ? WHERE local_uuid = ?",
                        (json.dumps(payload, ensure_ascii=False), local_uuid),
                    )
                except (ValueError, TypeError):
                    pass
        if check_no is not None:
            self.db.execute(
                "UPDATE outbox SET sent = 1, last_error = '', check_no = ?"
                " WHERE local_uuid = ?",
                (int(check_no), local_uuid),
            )
        else:
            self.db.execute(
                "UPDATE outbox SET sent = 1, last_error = '' WHERE local_uuid = ?",
                (local_uuid,),
            )

    def outbox_returns(self) -> list[dict]:
        """Navbatда turgan (hali serverга yetmagan) qaytarish payload'lari.

        Server bularni hali bilmaydi, lekin pul kassada allaqachon berilgan —
        shuning uchun keyingi qaytarishда bularни ham hisobga olamiz."""
        rows = self.db.execute(
            "SELECT payload FROM outbox WHERE sent = 0"
        ).fetchall()
        out = []
        for r in rows:
            try:
                pl = json.loads(r["payload"])
            except (ValueError, TypeError):
                continue
            if pl.get("kind") == "return":
                out.append(pl)
        return out

    def discard(self, local_uuid: str, error: str = "") -> None:
        """Bo'sh/yaroqsiz chekni navbatдан chiqaradi (yuborilmaydi, qayta
        urinilmaydi, sanoqqa kirmaydi). sent=2 — tarixda «bekor» ko'rinadi."""
        self.db.execute(
            "UPDATE outbox SET sent = 2, last_error = ? WHERE local_uuid = ? AND sent = 0",
            (error[:500], local_uuid),
        )

    def note_outage(self, local_uuid: str, error: str) -> None:
        """Temporary failures never consume the validation retry budget."""
        self.db.execute("UPDATE outbox SET last_error=? WHERE local_uuid=?",
                        (error[:500], local_uuid))

    def unsent_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM outbox WHERE sent=0").fetchone()[0]

    def hello_queue(self) -> dict:
        # One SQLite snapshot: checkout may enqueue an old-price receipt and
        # apply the new policy between two separate reads in this thread.
        row = self.db.execute(
            "SELECT COUNT(*) AS pending, COALESCE(SUM(attempts >= ?), 0) AS stuck,"
            " (SELECT value FROM meta WHERE key='price_policy_ack') AS ack,"
            " (SELECT local_uuid || ': ' || last_error FROM outbox"
            "  WHERE sent=0 AND last_error<>'' ORDER BY created_at LIMIT 1) AS error"
            " FROM outbox WHERE sent=0", (self.MAX_ATTEMPTS,),
        ).fetchone()
        result = {"local_pending": row["pending"], "local_stuck": row["stuck"],
                  "local_error": row["error"] or ""}
        if not row["pending"]:
            result["price_policy_ack"] = row["ack"] or ""
        return result

    def queue_error(self) -> str:
        row = self.db.execute("SELECT local_uuid, last_error FROM outbox WHERE sent=0 AND last_error<>'' ORDER BY created_at LIMIT 1").fetchone()
        return f"{row['local_uuid']}: {row['last_error']}" if row else ""

    def unsent_rows(self) -> list[sqlite3.Row]:
        """Tekshirish uchun barcha yuborilmaganlar, urinish limiti tugaganlari ham."""
        return self.db.execute(
            "SELECT local_uuid, payload FROM outbox WHERE sent=0 ORDER BY created_at"
        ).fetchall()

    def retry_stuck(self) -> None:
        """«Ma'lumotlarni yangilash»: tiqilgan cheklar va pul amallari HOZIR
        qayta yuboriladi (kutish vaqti bekor qilinadi, urinish sanog'i
        boshidan)."""
        self.db.execute("UPDATE outbox SET attempts=0, retry_at=NULL WHERE sent=0 AND attempts>=?",
                        (self.MAX_ATTEMPTS,))
        self.db.execute(
            "UPDATE cash_outbox SET attempts=0, retry_at=NULL WHERE sent=0 AND attempts>=?",
            (self.MAX_ATTEMPTS,))

    def mark_failed(self, local_uuid: str, error: str) -> None:
        """Server chekni RAD ETDI. Urinish limiti tugasa chek «tiqilgan»
        bo'ladi va shundan keyin `RETRY_EVERY` da bir marta o'zi qayta
        yuboriladi — hech qachon butunlay tashlab qo'yilmaydi."""
        self.db.execute(
            "UPDATE outbox SET attempts = attempts + 1, last_error = ?"
            " WHERE local_uuid = ?",
            (error[:500], local_uuid),
        )
        self.db.execute(
            "UPDATE outbox SET retry_at = ? WHERE local_uuid = ? AND attempts >= ?",
            (self._retry_at(), local_uuid, self.MAX_ATTEMPTS),
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

    # ------------------------------------------------ yopilgan smena cheklari
    #
    # Smena yopilganda printerda qog'oz tugab qolsa, Z-hisobot chiqmay qoladi.
    # Matn shu yerda saqlanadi — «Smena chekini qayta chiqarish» orqali istalgan
    # payt qayta chop etiladi (2026-09-25, egasining so'rovi).

    SHIFT_RECEIPTS_KEEP = 10

    def add_shift_receipt(self, shift_no, closed_at: str, text: str) -> None:
        """Yopilgan smena chekini saqlaydi (eng yangisi birinchi)."""
        items = self.shift_receipts()
        items.insert(0, {"shift_no": str(shift_no or "—"),
                         "closed_at": closed_at, "text": text})
        self.set("shift_receipts",
                 json.dumps(items[:self.SHIFT_RECEIPTS_KEEP], ensure_ascii=False))

    def shift_receipts(self) -> list[dict]:
        try:
            data = json.loads(self.get("shift_receipts") or "[]")
        except ValueError:
            return []
        return [d for d in data if isinstance(d, dict) and d.get("text")]

    # ------------------------------------------- internetsiz ochilgan smena

    # ------------------------------------------------ pul kiritish/chiqarish

    def queue_cash(self, local_uuid: str, payload: dict, created_at: str) -> None:
        """Pul amalini navbatga qo'yadi (chek bilan bir xil yo'l)."""
        self.db.execute(
            "INSERT OR IGNORE INTO cash_outbox"
            " (local_uuid, payload, created_at, shift_tag) VALUES (?, ?, ?, ?)",
            (local_uuid, json.dumps(payload, ensure_ascii=False), created_at,
             self.get("history_shift_tag") or ""),
        )

    def pending_cash(self) -> list[sqlite3.Row]:
        """Hozir yuboriladigan pul amallari (cheklar bilan bir xil qoida)."""
        return self.db.execute(
            "SELECT * FROM cash_outbox WHERE sent = 0 AND (attempts < ?"
            " OR (retry_at IS NOT NULL AND retry_at <= ?)) ORDER BY created_at",
            (self.MAX_ATTEMPTS, self._now()),
        ).fetchall()

    def unsent_cash_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM cash_outbox WHERE sent = 0").fetchone()[0]

    def rejected_cash_count(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM cash_outbox WHERE sent = 0 AND attempts > 0"
        ).fetchone()[0]

    def note_cash_rejected(self, local_uuid: str, error: str) -> None:
        """Server pul amalini RAD ETDI. O'chirilmaydi (1.19.0): pul kassadan
        allaqachon olingan/solingan — amal navbatda qoladi va chek kabi o'zi
        qayta yuboriladi. Ilgari rad etilgan amal jimgina o'chirilardi."""
        self.db.execute(
            "UPDATE cash_outbox SET attempts = attempts + 1, last_error = ?"
            " WHERE local_uuid = ?",
            (error[:400], local_uuid),
        )
        self.db.execute(
            "UPDATE cash_outbox SET retry_at = ? WHERE local_uuid = ? AND attempts >= ?",
            (self._retry_at(), local_uuid, self.MAX_ATTEMPTS),
        )

    def set_cash_payload(self, local_uuid: str, payload: dict) -> None:
        self.db.execute(
            "UPDATE cash_outbox SET payload = ? WHERE local_uuid = ?",
            (json.dumps(payload, ensure_ascii=False), local_uuid),
        )

    def mark_cash_sent(self, local_uuid: str) -> None:
        self.db.execute(
            "UPDATE cash_outbox SET sent = 1, last_error = '' WHERE local_uuid = ?",
            (local_uuid,),
        )

    def note_cash_error(self, local_uuid: str, error: str) -> None:
        """Xato yozib qo'yamiz, lekin navbatdan chiqarmaymiz."""
        self.db.execute(
            "UPDATE cash_outbox SET last_error = ? WHERE local_uuid = ?",
            (error[:400], local_uuid),
        )

    def discard_cash(self, local_uuid: str, error: str = "") -> None:
        """Server rad etdi — qayta urinmaymiz (aks holda navbat to'siladi)."""
        self.db.execute(
            "UPDATE cash_outbox SET sent = 2, last_error = ? WHERE local_uuid = ?",
            (error[:400], local_uuid),
        )

    def shift_cash(self, shift_tag: str) -> list[dict]:
        """Shu smenadagi pul amallari (yuborilgani ham, navbatdagisi ham).

        Smena yakunini kassaning o'zi hisoblaganda kerak: kiritilgan va
        chiqarilgan pul internetdan qat'i nazar hisobga olinishi kerak.
        """
        rows = self.db.execute(
            "SELECT payload FROM cash_outbox WHERE shift_tag = ? AND sent != 2"
            " ORDER BY created_at",
            (shift_tag,),
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def pending_for_tag(self, shift_tag: str) -> int:
        """Shu smenaning hali yuborilmagan (tiqilmagan) cheklari soni.
        Smena serverda shular ketgandan keyin yopiladi; tiqilgan chek smenani
        ushlab turmaydi — u o'z smenasining belgisi bilan keyin ham boradi."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox WHERE sent = 0 AND attempts < ?"
            " AND shift_tag = ?",
            (self.MAX_ATTEMPTS, shift_tag),
        ).fetchone()[0]

    def pending_cash_for_tag(self, shift_tag: str) -> int:
        """Shu smenaning hali yuborilmagan (tiqilmagan) pul amallari soni."""
        return self.db.execute(
            "SELECT COUNT(*) FROM cash_outbox WHERE sent = 0 AND attempts < ?"
            " AND shift_tag = ?",
            (self.MAX_ATTEMPTS, shift_tag),
        ).fetchone()[0]

    def unsent_for_tag(self, shift_tag: str) -> int:
        """Shu smenaning serverga hali yetmagan cheklari (rad etilgani ham)."""
        return self.db.execute(
            "SELECT COUNT(*) FROM outbox WHERE sent = 0 AND shift_tag = ?", (shift_tag,)
        ).fetchone()[0]

    def shift_receipt_count(self, shift_tag: str) -> int:
        """Shu smenada urilgan savdo cheklari soni (keyingi chek raqami uchun)."""
        n = 0
        for row in self.db.execute(
            "SELECT payload FROM outbox WHERE shift_tag = ? AND sent != 2", (shift_tag,)
        ):
            try:
                if json.loads(row["payload"]).get("kind") != "return":
                    n += 1
            except (ValueError, TypeError, AttributeError):
                n += 1
        return n

    # ------------------------------------------------------- smena jurnali
    #
    # «Smena — kassaniki» (egasi, 12.11.2026): smena ochilib-yopilganda
    # internet bor-yo'qligidan qat'i nazar kassa BIR XIL ishlaydi; chek urilgan
    # smenasida qoladi. Sxema boshidagi `shifts` jadvali izohiga qarang.

    _JOURNAL_COLS = ("uuid", "tag", "server_id", "number", "cashier_id", "cashier",
                     "opened_at", "opening_cash", "closed_at", "counted_cash",
                     "open_synced", "close_synced", "legacy")

    def _journal_insert(self, **row) -> None:
        cols = [c for c in self._JOURNAL_COLS if c in row]
        self.db.execute(
            f"INSERT INTO shifts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [row[c] for c in cols],
        )

    def journal_get(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM shifts WHERE uuid = ?", (key,)).fetchone()
        return dict(row) if row else None

    def journal_current(self) -> dict | None:
        """Hozir OCHIQ smena (bo'lsa). Dastur shu bilan ishlaydi."""
        row = self.db.execute(
            "SELECT * FROM shifts WHERE closed_at IS NULL ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def journal_open(self, cashier_id, cashier: str, opening_cash: int,
                     opened_at: str | None = None) -> dict:
        """Smenani ochadi — shu kassada, diskda. Internet kerak emas.

        Ochiq smena bo'lsa O'SHANI qaytaradi: bir kassada ikkita ochiq smena
        bo'lmaydi (tugma ikki marta bosilsa ham)."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.journal_current()
            if current is None:
                key = str(_uuid.uuid4())
                tag = f"loc:{key}"
                self._journal_insert(
                    uuid=key, tag=tag, cashier_id=int(cashier_id or 0), cashier=cashier or "",
                    opened_at=opened_at or self._now(), opening_cash=int(opening_cash or 0),
                )
                # Bundan keyingi cheklar shu smenaning belgisi bilan yoziladi.
                self.set("history_shift_tag", tag)
                current = self.journal_get(key)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return current

    def journal_close(self, key: str, closed_at: str | None = None,
                      counted_cash=None) -> dict | None:
        """Smenani yopadi — shu kassada, diskda. Internet kerak emas.
        Allaqachon yopilgan bo'lsa hech narsa o'zgarmaydi (vaqti saqlanadi)."""
        self.db.execute(
            "UPDATE shifts SET closed_at = ?, counted_cash = ?"
            " WHERE uuid = ? AND closed_at IS NULL",
            (closed_at or self._now(), counted_cash, key),
        )
        return self.journal_get(key)

    def journal_pending(self) -> list[dict]:
        """Serverga hali to'liq yetmagan smenalar — ochilgan tartibida."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM shifts WHERE open_synced = 0"
            " OR (closed_at IS NOT NULL AND close_synced = 0) ORDER BY seq"
        )]

    def journal_mark_open(self, key: str, server_id, number) -> None:
        self.db.execute(
            "UPDATE shifts SET open_synced = 1, server_id = ?, number = ? WHERE uuid = ?",
            (server_id, number, key),
        )

    def journal_mark_closed(self, key: str) -> None:
        self.db.execute("UPDATE shifts SET close_synced = 1 WHERE uuid = ?", (key,))

    #: Serverga to'liq yetgan eski smenalardan nechta saqlanadi
    JOURNAL_KEEP = 200

    def journal_trim(self) -> None:
        self.db.execute(
            "DELETE FROM shifts WHERE close_synced = 1 AND seq <= ("
            " SELECT COALESCE(MAX(seq), 0) - ? FROM shifts)", (self.JOURNAL_KEEP,),
        )

    def _legacy_shift_state(self) -> bool:
        """Eski versiya (≤1.18.21) o'z smena holatini yozib qo'yganmi.

        Yangi versiya bu kalitlarga HECH QACHON yozmaydi (jurnalga ko'chirgach
        tozalaydi). Demak ular bo'sh bo'lmasa — bazada eski versiya ishlagan."""
        if (self.get("active_shift_id") or "").strip():
            return True
        if isinstance(self.get_local_shift(), dict) and self.get_local_shift():
            return True
        return bool(self.closed_shifts())

    def _journal_find(self, key: str = "", server_id=None) -> dict | None:
        """Jurnal qatori — belgi (uuid) yoki serverdagi id bo'yicha."""
        if key:
            row = self.journal_get(key)
            if row is not None:
                return row
        try:
            sid = int(server_id) if server_id else 0
        except (TypeError, ValueError):
            sid = 0
        if sid:
            row = self.db.execute(
                "SELECT * FROM shifts WHERE server_id = ? ORDER BY seq DESC LIMIT 1", (sid,)
            ).fetchone()
            if row is not None:
                return dict(row)
        return None

    def _tag_taken(self, tag: str, but: str = "") -> bool:
        """`tag` jurnaldagi boshqa (`but` dan boshqa) smenaning belgisimi."""
        return bool(tag) and self.db.execute(
            "SELECT 1 FROM shifts WHERE tag = ? AND uuid != ? LIMIT 1", (tag, but)
        ).fetchone() is not None

    def _fold_tag(self, old: str, row: dict) -> int:
        """`old` belgili chek va pul amallarini jurnal smenasining o'zgarmas
        belgisiga yig'adi. Dastur eski versiyaga qaytarilganda u cheklarni
        «srv:<id>» belgisiga ko'chirib qo'yadi; jurnal esa o'z belgisini
        saqlaydi. Tranzaksiyani chaqiruvchi boshqaradi."""
        new = row["tag"]
        if not old or not new or old == new or self._tag_taken(old, row["uuid"]):
            return 0
        moved = self.db.execute(
            "UPDATE outbox SET shift_tag = ? WHERE shift_tag = ?", (new, old)).rowcount
        self.db.execute("UPDATE cash_outbox SET shift_tag = ? WHERE shift_tag = ?", (new, old))
        aliases = self._tag_aliases()
        if aliases.pop(new, None) is not None:
            self.set("shift_tag_aliases", json.dumps(aliases))
        if (self.get("history_shift_tag") or "") == old:
            self.set("history_shift_tag", new)
        return moved

    def _adopt_legacy_shifts(self) -> None:
        """Eski versiya (≤1.18.21) smena holatini jurnalga ko'chiradi.

        Birinchi yangilanishda jurnal bo'sh — eski holat shunchaki ko'chadi.
        Yangilanish smena o'rtasida kelishi mumkin: ochiq smena ochiq qoladi,
        internetsiz yopilib serverga yetmagan smenalar navbatda qoladi, cheklar
        o'z smenasida (belgisi o'zgarmaydi).

        Dastur eski versiyaga qaytarilib, yana yangilangan bo'lsa jurnal bo'sh
        emas. Unda eski versiya qoldirgan holat YANGIROQ:
          * u yopgan smena jurnalda ham yopiladi (o'sha vaqti bilan);
          * u davom ettirgan smena davom etadi (cheklari jurnal belgisiga
            qaytariladi);
          * u boshqa smena ochgan bo'lsa — jurnaldagi ochiq smena tugagan
            hisoblanadi va yangisi qo'shiladi. Serverga hammasi odatdagi
            tartibda yetkaziladi (`sync_shifts`).
        """
        self.db.execute("BEGIN IMMEDIATE")
        try:
            tag_now = self.get("history_shift_tag") or ""

            def end_current(when: str) -> None:
                # Jurnalda ochiq qolgan smena eski versiyada davom etmagan —
                # demak u tugagan (yangi smena boshlangan payt).
                cur = self.journal_current()
                if cur is not None:
                    self.db.execute(
                        "UPDATE shifts SET closed_at = ? WHERE uuid = ? AND closed_at IS NULL",
                        (when or self._now(), cur["uuid"]),
                    )

            def free_tag(tag: str, fallback: str) -> str:
                return tag if tag and not self._tag_taken(tag) else fallback

            # 1) Internetsiz yopilgan, serverga hali yetmagan smenalar (eskisidan).
            for rec in self.closed_shifts():
                if not isinstance(rec, dict) or not rec.get("closed_at"):
                    continue
                own = (rec.get("local_uuid") or "").strip()
                sid = rec.get("server_id") or None
                row = self._journal_find(own, sid)
                if row is not None:
                    # Shu smena jurnalda bor — eski versiya uni yopgan.
                    if row["closed_at"] is None:
                        self.db.execute(
                            "UPDATE shifts SET closed_at = ?, counted_cash = ?"
                            " WHERE uuid = ? AND closed_at IS NULL",
                            (rec["closed_at"], rec.get("counted_cash"), row["uuid"]),
                        )
                    self._fold_tag(rec.get("shift_tag") or "", row)
                    continue
                end_current(rec.get("opened_at") or rec["closed_at"])
                key = own or str(_uuid.uuid4())
                self._journal_insert(
                    uuid=key, tag=free_tag(rec.get("shift_tag") or "", f"loc:{key}"),
                    server_id=sid,
                    cashier_id=int(rec.get("cashier_id") or 0), cashier=rec.get("cashier") or "",
                    opened_at=rec.get("opened_at") or rec["closed_at"],
                    opening_cash=int(rec.get("opening_cash") or 0),
                    closed_at=rec["closed_at"], counted_cash=rec.get("counted_cash"),
                    open_synced=1 if sid else 0, legacy=0 if own else 1,
                )
            # 2) Hozir ochiq smena: internetsiz ochilgan yoki onlayn ochilgan.
            local = self.get_local_shift()
            if not isinstance(local, dict):
                local = {}
            active = (self.get("active_shift_id") or "").strip()
            if local.get("local_uuid") and not local.get("closed_at"):
                key = local["local_uuid"]
                sid = local.get("server_id") or None
                row = self._journal_find(key, sid)
                if row is None:
                    end_current(local.get("opened_at") or "")
                    self._journal_insert(
                        uuid=key, tag=free_tag(tag_now, f"loc:{key}"), server_id=sid,
                        cashier_id=int(local.get("cashier_id") or 0),
                        cashier=local.get("cashier") or "",
                        opened_at=local.get("opened_at") or self._now(),
                        opening_cash=int(local.get("opening_cash") or 0),
                        open_synced=1 if sid else 0,
                    )
                elif row["closed_at"] is None:
                    self._fold_tag(tag_now, row)      # o'sha smena davom etyapti
            elif active.isdigit():
                row = self._journal_find("", int(active))
                if row is None:
                    seen = {}
                    try:
                        seen = (json.loads(self.get("last_hello") or "{}") or {}).get("shift") or {}
                    except (ValueError, TypeError, AttributeError):
                        seen = {}
                    if not isinstance(seen, dict) or str(seen.get("id")) != active:
                        seen = {}
                    end_current(seen.get("opened_at") or "")
                    key = str(_uuid.uuid4())
                    number = seen.get("number")
                    self._journal_insert(
                        uuid=key, tag=free_tag(tag_now, f"srv:{active}"), server_id=int(active),
                        number=number if isinstance(number, int) else None,
                        cashier=seen.get("cashier") or "",
                        opened_at=seen.get("opened_at") or self._now(),
                        opening_cash=int(seen.get("opening_cash") or 0),
                        open_synced=1, legacy=1,
                    )
                elif row["closed_at"] is None:
                    self._fold_tag(tag_now, row)      # o'sha smena davom etyapti
                # Jurnalda YOPILGAN smena eski versiyada «ochiq» ko'ringan bo'lsa
                # (u server so'ziga ishonib kirgan) — jurnal haq: smena yopiq
                # qoladi, kassir yangisini ochadi.
            # Eski kalitlar endi ishlatilmaydi — ikki joyda ikki xil haqiqat bo'lmasin.
            self.set("closed_shifts", "")
            self.set("local_shift", "")
            self.set("active_shift_id", "")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    # -------------------------------------- internetsiz yopilgan smenalar

    def closed_shifts(self) -> list[dict]:
        """Mahalliy yopilgan, lekin serverga hali yetmagan smenalar.

        Ro'yxat — chunki internet uzoq yo'q bo'lsa kassir bir nechta
        smenani yopib ulgurishi mumkin. Tartib saqlanadi: eng eskisi
        birinchi bo'lib sinxronlanadi, aks holda serverda smenalar
        aralashib ketardi.
        """
        raw = self.get("closed_shifts")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []

    def set_closed_shifts(self, items: list[dict]) -> None:
        self.set("closed_shifts", json.dumps(items, ensure_ascii=False))

    def add_closed_shift(self, record: dict) -> None:
        items = self.closed_shifts()
        items.append(record)
        self.set_closed_shifts(items)

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

    def shift_sales(self, shift_tag: str, limit: int = 1000) -> list[sqlite3.Row]:
        """Faqat shu smenadagi cheklar (eng yangisi birinchi).

        `shift_tag` bo'sh bo'lsa (eski cheklar yoki smena belgilanmagan) —
        hamma tarixni beramiz, aks holda kassir hech narsa ko'rmay qolardi."""
        if not shift_tag:
            return self.recent_sales(limit)
        return self.db.execute(
            "SELECT * FROM outbox WHERE shift_tag = ? ORDER BY created_at DESC LIMIT ?",
            (shift_tag, limit),
        ).fetchall()

    # ------------------------------------------------ smena belgisi (tag)
    #
    # Har chek qaysi smenaga tegishli ekani `shift_tag` da: onlayn smena
    # «srv:<id>», internetsiz ochilgani «loc:<uuid>». Internetsiz ochilgan
    # smena keyin serverga o'tsa, u «srv:<id>» bo'ladi. Ilgari eski cheklar
    # «loc:» da qolib ketardi va dastur qayta ochilgach smena ikkiga
    # bo'linardi: 2026-10-28, unzavod3 #39 — internetsiz smena chekiga
    # 177 chekdan faqat 13:45 dan keyingi 42 tasi tushdi.

    #: Eslab qolinadigan eski→yangi belgilar soni (har oflayn smena — bitta)
    TAG_ALIASES_KEEP = 50

    def _tag_aliases(self) -> dict:
        try:
            data = json.loads(self.get("shift_tag_aliases") or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def retag_shift(self, old: str, new: str) -> int:
        """`old` belgili cheklar va pul amallarini `new` ga o'tkazadi.

        Bitta tranzaksiyada: joriy belgi ham (agar `old` bo'lsa) yangilanadi
        va «old → new» eslab qolinadi — parallel yozilib eski belgida qolgan
        chek bo'lsa, hisobotdan oldin `merge_shift_tags` uni ham olib keladi.
        Ko'chirilgan cheklar sonini qaytaradi."""
        if not old or not new or old == new:
            return 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            moved = self.db.execute(
                "UPDATE outbox SET shift_tag = ? WHERE shift_tag = ?", (new, old)
            ).rowcount
            self.db.execute(
                "UPDATE cash_outbox SET shift_tag = ? WHERE shift_tag = ?", (new, old)
            )
            if (self.get("history_shift_tag") or "") == old:
                self.set("history_shift_tag", new)
            aliases = self._tag_aliases()
            aliases.pop(old, None)
            aliases[old] = new
            keep = list(aliases.items())[-self.TAG_ALIASES_KEEP:]
            self.set("shift_tag_aliases", json.dumps(dict(keep)))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return moved

    def merge_shift_tags(self, tag: str) -> int:
        """Shu smenaning eski belgisi bilan qolib ketgan cheklarni ham
        shu belgiga yig'adi (hisobot va smenaga kirishdan oldin)."""
        if not tag:
            return 0
        moved = 0
        for old, new in list(self._tag_aliases().items()):
            if new == tag and old != tag:
                moved += self.retag_shift(old, tag)
        return moved

    def enter_shift_tag(self, new_tag: str, fresh: bool) -> str:
        """Smenaga kirilganda belgini o'rnatadi.

        `fresh` — smena hozir OCHILDI: oldingi belgi boshqa smenaniki,
        hech narsa ko'chirilmaydi. Aks holda (dastur qayta ochildi, kassir
        chiqib-kirdi, yangilanishdan keyin) — o'sha smenaga qaytilyapti.
        Agar u internetsiz ochilib («loc:»), endi serverda bo'lsa
        («srv:») — ertalabki cheklar ham shu smenaniki, ularni ko'chiramiz.
        Internetsiz yopilib hali serverga yetmagan smena (yoki hali
        serverga o'tmagan mahalliy smena) — tegilmaydi."""
        prev = self.get("history_shift_tag") or ""
        # Jurnaldagi (1.19.0) smenaning belgisi o'zgarmas — cheklari hech
        # qachon boshqa belgiga ko'chirilmaydi. Quyidagi ko'chirish faqat
        # eski versiyadan qolgan, jurnalga kirmagan belgilar uchun.
        in_journal = bool(prev) and self.db.execute(
            "SELECT 1 FROM shifts WHERE tag = ?", (prev,)).fetchone() is not None
        if (not fresh and not in_journal and prev != new_tag and prev.startswith("loc:")
                and new_tag.startswith("srv:")):
            pending_closed = any(r.get("shift_tag") == prev for r in self.closed_shifts())
            local = self.get_local_shift() or {}
            unsynced = bool(local.get("local_uuid") and not local.get("server_id")
                            and f"loc:{local['local_uuid']}" == prev)
            if not pending_closed and not unsynced:
                self.retag_shift(prev, new_tag)
        self.set("history_shift_tag", new_tag)
        self.merge_shift_tags(new_tag)
        return new_tag
