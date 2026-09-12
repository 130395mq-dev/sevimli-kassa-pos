"""
Hub bilan aloqa.

Qoida: **chek avval diskka, keyin serverga.** Kassir «yakunlash» ni
bosganda chek lokal navbatga yoziladi va shu zahoti «bo'ldi» deyiladi.
Serverga yuborish keyin, fonda bo'ladi. Internet uzilsa kassir buni
sezmaydi — faqat status qatorida navbat soni ko'payadi.

Takroriy yuborish xavfsiz: har chekning `local_uuid` si bor va server
o'sha kalit bo'yicha takrorni rad etadi.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from .cart import Cart, Customer, PaymentPlan, Product
from .config import Config
from .store import Store
from . import device
from .version import VERSION

logger = logging.getLogger(__name__)

TIMEOUT = 15

#: `ask_customer` natijasi: kassir oynani BEKOR qildi (hech nima
#: o'zgartirmaymiz). None esa — «Mijozsiz» (mijozni olib tashlash).
ASK_CANCEL = object()

#: `hello` javobining PANELDAN boshqariladigan qismi. Kassa har 15
#: soniyada hello qiladi; shu maydonlar o'zgargan bo'lsa (masalan panelda
#: to'lov turi qo'shildi yoki chegirma chegarasi o'zgardi) — kassa qayta
#: ochilmasdan darhol qo'llaydi. `shift` va `server_time` bu yerga
#: kirmaydi: ular har so'rovda o'zgaradi, sozlama emas.
SETTINGS_KEYS = (
    "payment_methods", "settings", "price_types", "default_price_type",
    "receipt_width", "market", "point",
)


def settings_fingerprint(info: dict) -> str:
    """Panel sozlamalarining «barmoq izi» — solishtirish uchun qisqa matn."""
    part = {k: (info or {}).get(k) for k in SETTINGS_KEYS}
    return json.dumps(part, sort_keys=True, ensure_ascii=False, default=str)


class HubError(Exception):
    """Server bilan gaplashib bo'lmadi yoki so'rovni rad etdi."""


class HubAuthError(HubError):
    """Kassa tokeni noto'g'ri (401) — panelda «Aloqani uzish» bosilgan yoki
    kassa o'chirilgan. Bu tarmoq xatosi EMAS: oflayn davom etib bo'lmaydi,
    qayta ulanish (login-parol) kerak."""


class HubBusyError(HubError):
    """Bu login hozir boshqa kompyuterda ishlayapti (409). Kirish
    ekranida serverdan kelgan xabar ko'rsatiladi."""


class HubConnError(HubError):
    """Serverga UMUMAN ulanib bo'lmadi (internet yo'q, timeout).

    Serverning rad javobidan (masalan «ombor tanlanmagan» 409) farqi bor:
    tarmoq xatosida oflayn davom etamiz (smena mahalliy ochiladi), rad
    javobida esa xatoni ko'rsatamiz — aks holda tuzatib bo'lmaydigan
    mahalliy smena yaratib qo'yardik."""


class Hub:
    """Hub API'ning yupqa klienti. Kutubxonasiz — EXE yengil bo'lsin."""

    def __init__(self, config: Config):
        self.config = config
        # Login'da olinadigan imzolangan sessiya tokeni. Manager-only
        # amallar (kassaga pul kiritish/chiqarish) shu bilan tekshiriladi.
        self.session = ""

    def _call(self, method: str, path: str, payload: dict | None = None,
              params: dict | None = None, timeout: float = TIMEOUT) -> dict:
        url = f"{self.config.base}/api/v1/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.config.token}")
        request.add_header("Content-Type", "application/json")
        # Panel «qaysi kassa qaysi versiyada» ni shu sarlavhadan biladi
        request.add_header("X-Kassa-Version", VERSION)
        # Qaysi kompyuter — «bir login bir vaqtda bitta kassada» uchun
        request.add_header("X-Device", device.device_id())
        request.add_header("X-Device-Name", device.device_name())
        # Imzolangan sessiya tokeni (login'dan) — manager-only amallar uchun
        if self.session:
            request.add_header("X-Session", self.session)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read()).get("error", "")
            except Exception:
                pass
            if e.code == 401 and "connect" not in path:
                raise HubAuthError(detail or "Kassa tokeni noto'g'ri") from e
            if e.code == 409 and ("login" in path or "session/resume" in path):
                # Bu login boshqa kompyuterda ishlayapti — xabar serverdan
                raise HubBusyError(detail or "Bu login boshqa kassada ishlayapti") from e
            if e.code >= 500 or e.code in (408, 429):
                raise HubConnError(detail or f"Server vaqtincha band: {e.code}") from e
            raise HubError(detail or f"Server xatosi {e.code}") from e
        except urllib.error.URLError as e:
            raise HubConnError(f"Serverga ulanib bo'lmadi: {e.reason}") from e
        except TimeoutError as e:
            raise HubConnError("Server javob bermadi") from e

    # ------------------------------------------------------------ so'rovlar

    def hello(self) -> dict:
        return self._call("GET", "hello")

    def login(self, login: str, password: str) -> dict:
        """Kassir kirishi: login + parol. Kassirlar ro'yxati so'ralmaydi —
        xodim o'z loginini ham o'zi teradi."""
        res = self._call(
            "POST", "login", {"login": login, "password": password}
        )
        # Imzolangan sessiya tokenini eslab qolamiz — keyingi manager-only
        # so'rovlarга (kassaga pul) shu yuboriladi.
        self.session = res.get("session", "") or ""
        return res

    def resume_session(self, cashier_id: int) -> dict:
        """Parolsiz davom etish: kassir «Chiqish» ni bosmagan, login shu
        kompyuterda saqlangan. Server «bir login bir kompyuter» qoidasini
        tekshiradi (409 → HubBusyError)."""
        res = self._call("POST", "session/resume", {"cashier_id": int(cashier_id or 0)})
        self.session = res.get("session", "") or ""
        return res

    def logout(self) -> dict:
        """«Chiqish» — login shu kompyuterdan bo'shatiladi."""
        self.session = ""
        return self._call("POST", "logout", {})

    def connect(self, login: str, password: str) -> dict:
        """Kassani ulaydi: login-parol evaziga token oladi.

        Yagona so'rov tokensiz ketadi — uning vazifasi tokenni olish.
        """
        return self._call(
            "POST", "connect", {"login": login, "password": password}
        )

    def catalog_page(self, since: str = "", after: int | None = None) -> dict:
        params = {}
        if since:
            params["since"] = since
        if after:
            params["after"] = after
        return self._call("GET", "catalog", params=params or None)

    def check_version(self) -> dict:
        """Serverdagi eng yangi ilova versiyasi:
        {version, url, notes, mandatory, size, sha256}."""
        return self._call("GET", "version")

    def download(self, url: str, dest, progress=None, expected_sha256: str = "") -> None:
        """Faylni `dest` ga yuklab oladi. `progress(done, total)` chaqiriladi.

        Avval `dest.part` ga yoziladi, SHA-256 tekshirilgach `dest` ga
        ko'chiriladi — yarim yuklangan fayl hech qachon «tayyor» bo'lib
        qolmaydi. Serverdagi yuklab olish manzili ham tokenni talab qiladi.
        """
        import hashlib
        from pathlib import Path

        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")

        request = urllib.request.Request(url, method="GET")
        request.add_header("Authorization", f"Bearer {self.config.token}")
        request.add_header("X-Kassa-Version", VERSION)

        digest = hashlib.sha256()
        done = 0
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                total = int(response.headers.get("Content-Length") or 0)
                with open(part, "wb") as fh:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
        except urllib.error.HTTPError as e:
            raise HubError(f"Yuklab olinmadi: server {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise HubError(f"Yuklab olinmadi: {e}") from e

        if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
            part.unlink(missing_ok=True)
            raise HubError("Yuklangan fayl buzuq (nazorat summasi mos emas)")
        if done < 1_000_000:
            part.unlink(missing_ok=True)
            raise HubError("Yuklangan fayl juda kichik — bu dastur emas")

        if dest.exists():
            dest.unlink()
        part.replace(dest)

    def refresh_catalog(self) -> dict:
        """Serverga «MoySklad'dan hozir tort» deydi.

        Server delta'ni tortib bo'lgach javob beradi (odatda 1-3 soniya,
        ko'p o'zgarish bo'lsa ko'proq) — shuning uchun uzunroq timeout.
        Keyin `catalog_page` bilan farq olinadi.
        """
        return self._call("POST", "catalog/refresh", {}, timeout=90)

    def find_customers(self, query: str) -> list[dict]:
        return self._call("GET", "customers", params={"q": query})["customers"]

    def find_customers_by_card(self, card: str) -> list[dict]:
        """Nakopitelniy karta shtrix-kodi bo'yicha ANIQ moslik.

        Telefon/ism bilan qidirmaydi — faqat karta kodi teng kelgan mijoz.
        """
        return self._call(
            "GET", "customers", params={"card": card}
        )["customers"]

    def create_customer(self, name: str, phone: str, card: str = "") -> dict:
        return self._call(
            "POST", "customers/create",
            {"name": name, "phone": phone, "card": card},
        )["customer"]

    def open_shift(self, cashier_id: int, opening_cash: int,
                   local_uuid: str = "", opened_at: str = "") -> dict:
        return self._call(
            "POST", "shift/open",
            {
                "cashier_id": cashier_id,
                "opening_cash": opening_cash,
                "local_uuid": local_uuid,
                "opened_at": opened_at,
            },
        )

    def close_shift(self, counted_cash: int | None) -> dict:
        return self._call("POST", "shift/close", {"counted_cash": counted_cash})

    def shift_report(self) -> dict:
        return self._call("GET", "shift/report")

    def cash(self, kind: str, amount: int, comment: str = "") -> dict:
        return self._call(
            "POST", "cash", {"kind": kind, "amount": amount, "comment": comment}
        )

    def send_sale(self, payload: dict) -> dict:
        return self._call("POST", "sales", payload)

    def returnable_sales(self) -> list[dict]:
        return self._call("GET", "sales/returnable")["sales"]


def sale_payload(cart: Cart, plan: PaymentPlan, local_uuid: str,
                 created_at: str) -> dict:
    """Chekni serverga yuboriladigan ko'rinishga o'tkazadi."""
    extra = cart.extra_percent
    return {
        "local_uuid": local_uuid,
        "created_at": created_at,
        "customer_id": cart.customer.id if cart.customer else None,
        "gross_total": cart.gross_total,
        "discount_total": cart.discount_total,
        "points_spent": cart.points_spent,
        "points_earned": cart.points_earned(),
        "items": [
            {
                "product_id": line.product.id,
                "ms_product_id": line.product.ms_id,
                "name": line.product.name,
                "barcode": line.product.barcode,
                "quantity": str(line.quantity),
                "price": line.product.price,
                "price_quote": line.product.price_quote,
                "total": line.net(extra),
                "mark_code": line.mark_code,
            }
            for line in cart.lines
        ],
        "payments": [
            {
                "method": part.method,
                "amount": part.amount,
                "tendered": part.tendered,
                "change": part.change,
            }
            for part in plan.parts
        ],
    }


def return_payload(origin: dict, lines: list[dict], refund_method: str,
                   local_uuid: str, created_at: str) -> dict:
    """Qaytarish chekini serverga yuboriladigan ko'rinishga o'tkazadi.

    `lines` — qaytariladigan qatorlar: har biri {item, qty}.
    Pul asl to'lov emas, qaytariladigan summa: bitta usul bilan.
    """
    from .money import line_total as _line_total

    items = []
    total = 0
    for row in lines:
        item = row["item"]
        qty = row["qty"]
        # Pul float bilan hisoblanmaydi — savdodagi bilan bir xil yaxlitlash
        # (Decimal, ROUND_HALF_UP). Aks holda vaznli tovarda bir tiyin farq
        # chiqib, qaytarish summasi asl chek qatoridan farq qilardi.
        line_total = _line_total(int(item["price"]), Decimal(str(qty)))
        total += line_total
        items.append({
            "product_id": item.get("product_id"),
            "ms_product_id": item.get("ms_product_id"),
            "name": item["name"],
            "barcode": item.get("barcode", ""),
            "quantity": str(qty),
            "price": item["price"],
            "total": line_total,
        })

    return {
        "local_uuid": local_uuid,
        "kind": "return",
        "origin_id": origin["id"],
        "created_at": created_at,
        "customer_id": None,  # server asl chekdan oladi
        "gross_total": total,
        "net_total": total,
        "items": items,
        "payments": [{"method": refund_method, "amount": total}],
    }


class LiveBackend:
    """`MainWindow` kutadigan interfeys — lokal baza va Hub ustida."""

    def __init__(self, hub: Hub, store: Store, methods: list[dict]):
        self.hub = hub
        self.store = store
        self.methods = methods
        #: Oyna shu funksiyalarni almashtirib qo'yadi (dialoglar uchun)
        self.quantity_asker = None
        self.customer_asker = None
        self.discount_asker = None
        self.points_asker = None
        #: Narx turlari [{id, name}], asosiysi va joriysi
        self.price_types: list[dict] = []
        self.default_price_type: str = ""

    # --------------------------------------------------------- narx turi

    def setup_price_types(self, price_types: list[dict], default_id: str) -> None:
        """Serverdan kelgan ro'yxatni o'rnatadi. Saqlangan tanlov ro'yxatda
        bo'lmasa (tur o'chirilgan) — asosiysiga qaytadi."""
        self.price_types = list(price_types or [])
        self.default_price_type = (default_id or "").lower()
        ids = {p["id"] for p in self.price_types}
        current = self.store.price_type_id
        if current not in ids:
            self.store.set_price_type(self.default_price_type if self.default_price_type in ids else None)

    @property
    def price_type_id(self) -> str:
        return self.store.price_type_id or self.default_price_type

    @property
    def price_type_name(self) -> str:
        for p in self.price_types:
            if p["id"] == self.price_type_id:
                return p["name"]
        return ""

    @property
    def price_type_is_default(self) -> bool:
        return not self.default_price_type or self.price_type_id == self.default_price_type

    def set_price_type(self, price_type_id: str) -> None:
        self.store.set_price_type(price_type_id)

    # ------------------------------------------------------------ katalog

    def find_by_barcode(self, code: str):
        from .barcode import parse

        code = (code or "").strip()

        # 1) AVVAL aynan shu kod katalogda bormi. Bo'lsa — bu oddiy tovar,
        #    1 dona. MoySklad o'zi yaratgan shtrix-kodlar «2000…» bilan
        #    boshlanadi va tarozi prefiksiga o'xshaydi; ilgari ular tarozi
        #    kodi deb o'qilib, donali tovar «96.927 kg» bo'lib sotilardi
        #    (2026-09, kod 2000003296927). Katalogdagi aniq moslik har
        #    doim tarozi taxminidan ustun.
        product = self.store.by_barcode(code)
        if product:
            return product, Decimal(1)

        # 2) Katalogda yo'q — tarozi yorlig'imi? (prefiks + PLU + vazn)
        scan = parse(code)
        if scan.is_scale:
            product = self.store.by_plu(scan.plu)
            if not product:
                return None
            if scan.weight is not None:
                # Tarozi yorlig'i faqat VAZNLI tovar uchun ma'noli. PLU
                # donali tovarga to'g'ri kelsa — bu tasodif, sotmaymiz.
                if not product.is_weight:
                    return None
                return product, scan.weight
            if product.price > 0:
                # Narxli yorliq: miqdorni narxdan chiqaramiz
                return product, Decimal(scan.price) / Decimal(product.price)
            return None

        return None

    def search(self, text: str) -> list[Product]:
        return self.store.search(text)

    # --------------------------------------------------- sevimli (pin) tovarlar

    def is_favorite(self, product_id) -> bool:
        return self.store.is_favorite(product_id)

    def toggle_favorite(self, product_id) -> bool:
        return self.store.toggle_favorite(product_id)

    # ---------------------------------------------------------- qoldiq

    #: Panelda «Qoldiqlarni hisobga olish» yoqilganmi (hello'dan keladi)
    track_stock = False

    def check_stock(self, product, quantity) -> str:
        """Sotish mumkinmi? Muammo bo'lsa — kassirga ko'rsatiladigan matn.

        Qoldiq serverdan keladi va bir necha daqiqa eskirgan bo'lishi
        mumkin, shuning uchun bu «qattiq qulf» emas: maqsad — omborda
        yo'q tovarni bexosdan sotib qo'ymaslik.
        """
        from .i18n import tr

        if not self.track_stock:
            return ""
        stock = float(getattr(product, "stock", 0) or 0)
        if stock <= 0:
            return tr("«{name}» omborda yo'q").format(name=product.name)
        if float(quantity) > stock:
            return tr("«{name}»: omborda {n} ta").format(
                name=product.name, n=("%g" % stock)
            )
        return ""

    # ------------------------------------------------------------ dialoglar

    def ask_quantity(self, line):
        return self.quantity_asker(line) if self.quantity_asker else None

    def ask_customer(self):
        return self.customer_asker() if self.customer_asker else None

    def ask_discount(self, current):
        return self.discount_asker(current) if self.discount_asker else None

    def ask_points(self, balance, max_balls, current):
        """Ball ishlatish oynasi. Kassir kiritgan ball sonini (dona)
        qaytaradi, bekor qilса None."""
        if not self.points_asker:
            return None
        return self.points_asker(balance, max_balls, current)

    # --------------------------------------------------------------- chek

    def submit(self, cart: Cart, plan: PaymentPlan) -> None:
        """Chekni saqlaydi.

        Avval diskka — shundan keyingina kassirga «bo'ldi» deyiladi.
        Serverga yuborish `flush` da, fonda.
        """
        local_uuid = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        payload = sale_payload(cart, plan, local_uuid, created_at)
        payload["price_type"] = self.price_type_name
        payload["price_type_id"] = self.price_type_id
        self._bind_shift(payload)

        self.store.queue(local_uuid, payload, created_at)

        # Background flush owns the network. The cashier never waits for HTTP.

    def _bind_shift(self, payload: dict) -> None:
        local = self.store.get_local_shift()
        if local:
            payload["shift_local_uuid"] = local["local_uuid"]
        else:
            shift_id = self.store.get("active_shift_id")
            if shift_id:
                payload["shift_id"] = int(shift_id)

    def submit_return(self, origin: dict, lines: list[dict],
                      refund_method: str) -> int:
        """Qaytarishni saqlaydi. Qaytarilgan summani (tiyin) qaytaradi.

        Savdo bilan bir xil yo'l: avval diskka, keyin serverga. Shu tufayli
        internet yo'q bo'lsa ham qaytarish yo'qolmaydi.
        """
        local_uuid = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        payload = return_payload(origin, lines, refund_method, local_uuid, created_at)
        self._bind_shift(payload)

        self.store.queue(local_uuid, payload, created_at)
        return payload["net_total"]

    def returnable_sales(self) -> list[dict]:
        return self.hub.returnable_sales()

    # ---------------------------------------------------- smena (oflayn ham)

    def open_shift(self, cashier: dict, opening_cash: int) -> dict:
        """Smena ochadi. Internet bo'lsa — serverда, bo'lmasa MAHALLIY.

        Qaytaradi: oyna kutadigan smena dict'i
        ({id, number, cashier, opened_at, opening_cash, next_receipt_number}).

        Mahalliy ochilganda `id=None`, `number="—"` bo'ladi — internet
        qaytganda `sync_shift()` uni serverга ochib, haqiqiy raqamни oladi.
        """
        opened_at = datetime.now(timezone.utc).isoformat()
        try:
            sh = self.hub.open_shift(cashier.get("id", 0), opening_cash)["shift"]
            self.store.set("active_shift_id", str(sh["id"]))
            self.store.set_local_shift(None)  # onlayn — mahalliy kerak emas
            return sh
        except HubConnError as e:
            # Internet yo'q — mahalliy ochamiz (pastda).
            logger.info("Smena internetsiz ochilyapti (server yo'q: %s)", e)
        # HubError (server RAD etdi, masalan «ombor tanlanmagan») — bu yerda
        # ushlamaymiz: yuqoriga ketadi va kassirga xato ko'rsatiladi. Mahalliy
        # smena yaratsak, u hech qachon sinxronlanmasdi.

        local = {
            "local_uuid": str(uuid.uuid4()),
            "cashier_id": cashier.get("id", 0),
            "cashier": cashier.get("name", ""),
            "opening_cash": int(opening_cash),
            "opened_at": opened_at,
            "offline": True,
            "next_receipt": 1,
        }
        self.store.set_local_shift(local)
        return {
            "id": None,
            "number": "—",
            "cashier": local["cashier"],
            "opened_at": opened_at,
            "opening_cash": int(opening_cash),
            "next_receipt_number": 1,
        }

    def current_local_shift(self) -> dict | None:
        """Diskda saqlangan, hali serverга ochilmagan smena (bo'lsa)."""
        return self.store.get_local_shift()

    def sync_shift(self) -> dict | None:
        """Internet qaytganda: mahalliy ochilgan smenani serverga ochadi.

        Idempotent — `local_uuid` tufayli necha marta chaqirilsa ham bitta
        smena bo'ladi. Muvaffaqiyatli bo'lsa serverdagi smena dict'ini
        qaytaradi (oyna raqamni yangilashi mumkin), aks holda None.
        """
        local = self.store.get_local_shift()
        if not local:
            return None
        try:
            sh = self.hub.open_shift(
                local.get("cashier_id", 0),
                int(local.get("opening_cash") or 0),
                local_uuid=local.get("local_uuid", ""),
                opened_at=local.get("opened_at", ""),
            )["shift"]
        except HubConnError as e:
            logger.info("Smena hali sinxronlanmadi (server yo'q: %s)", e)
            return None
        except HubError as e:
            # Server rad etdi (masalan ombor tanlanmagan). Mahalliy smenani
            # SAQLAB qolamiz — sozlama tuzatilгач o'zi sinxronlanadi.
            logger.warning("Smena sinxronlanmadi (server rad etdi): %s", e)
            return None
        # Serverga ochildi — endi mahalliy belgini olib tashlaymiz.
        # Navbatdagi cheklar shu ochiq smenaga tushadi.
        self.store.set("active_shift_id", str(sh["id"]))
        self.store.set_local_shift(None)
        logger.info("Internetsiz ochilgan smena serverга sinxronlandi: #%s",
                    sh.get("number"))
        return sh

    def flush(self, limit: int = 50) -> int:
        """Navbatdagi cheklarni yuboradi. Yuborilganlar sonini qaytaradi.

        Avval mahalliy smena bo'lsa uni serverга ochamiz — aks holda
        cheklar «ochiq smena yo'q» bilan qaytadi.
        """
        self.sync_shift()
        sent = 0
        for row in self.store.pending(limit):
            try:
                self.hub.send_sale(json.loads(row["payload"]))
            except (HubConnError, HubAuthError) as e:
                # Ulanish yoki token xatosi — sabab UMUMIY (internet yo'q
                # yoki kassa uzilgan). Qolganini urinishning ma'nosi yo'q,
                # to'xtaymiz.
                self.store.note_outage(row["local_uuid"], str(e))
                break
            except HubError as e:
                # Server AYNAN shu chekni rad etdi (masalan validatsiya
                # xatosi). Bu bitta chekning muammosi — orqasidagilarni
                # bloklamasin. Belgilaymiz va KEYINGISIGA o'tamiz.
                # (Ko'p marta rad etilsa `pending` uni o'zi chetlab o'tadi.)
                self.store.mark_failed(row["local_uuid"], str(e))
                continue
            else:
                self.store.mark_sent(row["local_uuid"])
                sent += 1
        return sent

    def sync_catalog(self, force: bool = False, progress=None) -> int:
        """Katalogni yangilaydi. O'zgargan tovarlar sonini qaytaradi."""
        st = self.sync_catalog_detailed(force, progress)
        return st["new"] + st["updated"] + st["gone"]

    def sync_catalog_detailed(self, force: bool = False, progress=None) -> dict:
        """Katalogni yangilaydi, tafsilotli hisobot qaytaradi:

            {"new": 3, "updated": 12, "gone": 1, "server": {...}|None}

        `force=True` — avval serverdan MoySklad'ni DARHOL tortishni
        so'raydi (kassir «Ma'lumotlarni yangilash» ni bosganda). Server
        «hozirgina tortilgan» yoki «band» desa — bu xato emas, shunchaki
        mavjud delta olinadi.

        `progress(stage)` — bosqich xabari (yangilanish oynasi uchun):
            0 — serverga so'rov ketdi, 1 — MoySklad tortildi, 2 — bazaga
            yozilmoqda. Fon oqimidan chaqiriladi.
        """
        def step(i: int) -> None:
            if progress:
                try:
                    progress(i)
                except Exception:
                    pass

        server = None
        if force:
            step(0)
            try:
                server = self.hub.refresh_catalog()
                logger.info("Server yangilanishi: %s", server)
            except HubError as e:
                # Server tortolmadi (MoySklad limiti, tarmoq) — baribir
                # cron tortgan so'nggi holatni olamiz.
                logger.warning("Serverdan darhol tortish bo'lmadi: %s", e)
        step(1)

        since = self.store.get("catalog_since") if self.store.get("price_quotes_v1") else ""
        snapshot_time = ""
        after = None
        stats = {"new": 0, "updated": 0, "gone": 0}
        first = True

        while True:
            page = self.hub.catalog_page(since=since, after=after)
            rows = page.get("products") or []
            if first:
                snapshot_time = page.get("server_time", "")
                step(2)
                first = False
            if rows:
                part = self.store.replace_products(rows)
                for k in stats:
                    stats[k] += part[k]

            after = page.get("next_after")
            if not after:
                self.store.set("catalog_since", snapshot_time)
                self.store.set("price_quotes_v1", "1")
                break

        stats["server"] = server
        return stats

    def find_customer(self, query: str) -> list[Customer]:
        return [
            Customer(
                id=c["id"], ms_id=c["ms_id"], name=c["name"],
                phone=c.get("phone", ""), card=c.get("card", ""),
                bonus_points=c.get("bonus_points", 0),
                accumulation_discount=c.get("accumulation_discount", 0.0),
                personal_discount=c.get("personal_discount", 0.0),
            )
            for c in self.hub.find_customers(query)
        ]

    def create_customer(self, name: str, phone: str, card: str = "") -> Customer:
        c = self.hub.create_customer(name, phone, card)
        return Customer(
            id=c["id"], ms_id=c["ms_id"], name=c["name"],
            phone=c.get("phone", ""), card=c.get("card", ""),
            bonus_points=c.get("bonus_points", 0),
            accumulation_discount=c.get("accumulation_discount", 0.0),
            personal_discount=c.get("personal_discount", 0.0),
        )

    def find_customer_by_code(self, code: str) -> Customer | None:
        """Skaner mijoz kartasini o'qiganda — FAQAT karta shtrix-kodi bo'yicha
        aynan shu mijozni topadi.

        Telefon yoki ism bilan qidirmaydi. Kod tovar shtrix-kodi bo'lmasa,
        u nakopitelniy karta kodi bo'lishi mumkin — server discount_card
        bilan ANIQ teng kelgan mijozни qaytaradi (bo'lmasa — None).
        """
        code = (code or "").strip()
        if not code:
            return None
        try:
            rows = self.hub.find_customers_by_card(code)
        except HubError:
            return None
        for c in rows:
            if c.get("card") == code:
                return Customer(
                    id=c["id"], ms_id=c["ms_id"], name=c["name"],
                    phone=c.get("phone", ""), card=c.get("card", ""),
                    bonus_points=c.get("bonus_points", 0),
                    accumulation_discount=c.get("accumulation_discount", 0.0),
                    personal_discount=c.get("personal_discount", 0.0),
                )
        return None
