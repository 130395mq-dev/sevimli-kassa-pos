"""
Hub bilan aloqa.

Qoida: **chek avval diskka, keyin serverga.** Onlayn holatda kassa
MoySklad yaratgan hujjatning haqiqiy ОТ-* raqamini kutib, qog'oz chekni
shu raqam bilan chiqaradi. Internet uzilsa chek lokal navbatda qoladi va
vaqtinchalik ekanini ochiq ko'rsatadi.

Takroriy yuborish xavfsiz: har chekning `local_uuid` si bor va server
o'sha kalit bo'yicha takrorni rad etadi.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .cart import Cart, Customer, PaymentPlan, Product
from .config import Config
from .store import Store
from . import device
from .version import VERSION

#: Hozir `submit` ichida serverga yuborilayotgan cheklar (local_uuid).
#: Fon oqimidagi `flush` bularni o'tkazib yuboradi — aks holda bitta chek
#: ikki marta ketma-ket yuborilardi (2026-09-16: server logida ~200 ms
#: farq bilan ikkita POST, ikkinchisi MoySklad'da «syncId takror»).
#: Ikki LiveBackend nusxasi (UI va fon) bitta jarayonda — modul darajasi.
_INFLIGHT: set[str] = set()
_INFLIGHT_LOCK = threading.Lock()

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
    """Server bilan gaplashib bo'lmadi yoki so'rovni rad etdi.

    `status` — server javobining HTTP kodi (bo'lsa). 400 = so'rov aynan
    rad etildi (masalan qaytarish asl chekdan oshdi) — qayta urinish
    yordam bermaydi; 409 = holat (smena yo'q) — keyin tuzalishi mumkin.
    """

    def __init__(self, message: str = "", status: int | None = None):
        super().__init__(message)
        self.status = status


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
                raise HubAuthError(detail or "Kassa tokeni noto'g'ri", status=e.code) from e
            if e.code == 409 and ("login" in path or "session/resume" in path):
                # Bu login boshqa kompyuterda ishlayapti — xabar serverdan
                raise HubBusyError(detail or "Bu login boshqa kassada ishlayapti", status=e.code) from e
            if e.code >= 500 or e.code in (408, 429):
                raise HubConnError(detail or f"Server vaqtincha band: {e.code}", status=e.code) from e
            raise HubError(detail or f"Server xatosi {e.code}", status=e.code) from e
        except urllib.error.URLError as e:
            raise HubConnError(f"Serverga ulanib bo'lmadi: {e.reason}") from e
        except TimeoutError as e:
            raise HubConnError("Server javob bermadi") from e

    # ------------------------------------------------------------ so'rovlar

    def hello(self, queue=None) -> dict:
        return self._call("GET", "hello", params=queue)

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

    def close_shift(self, counted_cash: int | None, closed_at: str = "",
                    local_uuid: str = "") -> dict:
        """Smenani yopadi.

        `closed_at` — internetsiz yopilgan smena uchun HAQIQIY yopilish
        vaqti; bo'sh bo'lsa server hozirgi vaqtni qo'yadi. `local_uuid`
        qaysi smena yopilayotganini aniqlaydi (takror yuborishda xato
        smena yopilib qolmasligi uchun).
        """
        return self._call("POST", "shift/close", {
            "counted_cash": counted_cash,
            "closed_at": closed_at,
            "local_uuid": local_uuid,
        })

    def shift_report(self) -> dict:
        return self._call("GET", "shift/report")

    def cash(self, kind: str, amount: int, comment: str = "", local_uuid: str = "",
             shift_id=None, created_at: str = "") -> dict:
        return self._call(
            "POST", "cash", {"kind": kind, "amount": amount, "comment": comment,
                             "local_uuid": local_uuid or str(uuid.uuid4()),
                             "shift_id": shift_id, "created_at": created_at}
        )

    def send_sale(self, payload: dict) -> dict:
        return self._call("POST", "sales", payload)

    def returnable_sales(self, query="", offset=0) -> list[dict]:
        return self._call("GET", "sales/returnable", params={"q": query, "offset": offset})["sales"]


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


def is_junk_receipt(payload: dict) -> bool:
    """Faqat tovar harakati, pul va ball bo'lmagan bo'sh yozuv.

    Nol summa o'zi yetarli emas: tekin tovar, chegirma yoki ball bilan
    to'langan haqiqiy chek saqlanadi. Noaniq/buzilgan yozuv ham saqlanadi.
    """
    if not isinstance(payload, dict):
        return False
    try:
        fields = ("gross_total", "discount_total", "net_total", "points_spent", "points_earned")
        if any(Decimal(str(payload.get(key) or 0)) != 0 for key in fields):
            return False
        payments = payload.get("payments", [])
        items = payload.get("items", [])
        payments = [] if payments is None else payments
        items = [] if items is None else items
        if not isinstance(payments, list) or not isinstance(items, list):
            return False
        for payment in payments:
            if not isinstance(payment, dict) or any(
                Decimal(str(payment.get(key) or 0)) != 0
                for key in ("amount", "tendered", "change")
            ):
                return False
        return all(
            isinstance(item, dict) and "quantity" in item
            and Decimal(str(item["quantity"])) == 0
            and Decimal(str(item.get("total") or 0)) == 0
            for item in items
        )
    except (InvalidOperation, ValueError, TypeError):
        return False


def return_payload(origin: dict, lines: list[dict], refund_method: str,
                   local_uuid: str, created_at: str) -> dict:
    """Qaytarish chekini serverga yuboriladigan ko'rinishga o'tkazadi.

    `lines` — qaytariladigan qatorlar: har biri {item, qty}.
    Pul asl to'lov emas, qaytariladigan summa: bitta usul bilan.
    """
    from .money import refund_total

    items = []
    total = 0
    for row in lines:
        item = row["item"]
        qty = row["qty"]
        # Pul float bilan hisoblanmaydi — savdodagi bilan bir xil yaxlitlash
        # (Decimal, ROUND_HALF_UP). Aks holda vaznli tovarda bir tiyin farq
        # chiqib, qaytarish summasi asl chek qatoridan farq qilardi.
        if "net_total" in origin and "refund_total" not in item:
            raise HubError("Qaytarish hisobini olish uchun serverni yangilang")
        line_total = refund_total(item, qty)
        total += line_total
        items.append({
            "origin_item_id": item.get("origin_item_id"),
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
        # Asl chek raqami — faqat kassa tarixida qayta chop etish uchun
        # (server e'tibor bermaydi, unga origin_id yetarli).
        "origin_number": str(origin.get("receipt_number") or origin.get("number") or ""),
        "created_at": created_at,
        "customer_id": None,  # server asl chekdan oladi
        "gross_total": total,
        "net_total": total,
        "items": items,
        "payments": [{"method": refund_method, "amount": total}] if total else [],
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
        found = self.store.by_barcode_qty(code)
        if found:
            product, pack_qty = found
            # Upakovka kodi (MoySklad «Упаковка», masalan 6 dona) — shuncha
            # dona qo'shiladi; oddiy kod — 1.
            return product, Decimal(str(pack_qty)) if pack_qty and pack_qty != 1 else Decimal(1)

        # 2) Katalogda yo'q — tarozi yorlig'imi? (prefiks + PLU + vazn)
        scan = parse(code)
        if scan.is_scale:
            product = self.store.by_plu(scan.plu)
            if not product:
                return None
            if scan.weight is not None:
                # Tarozi yorlig'i (29 + PLU + vazn) faqat tarozidan chiqadi,
                # demak PLU'si mos kelgan tovar — vaznli. Katalogda «vaznli»
                # belgisi bo'lmasa ham sotamiz: Sevimli MoySklad'ida hamma
                # tovar birligi «шт», server hech birini vaznli deb
                # belgilamaydi (2026-09: 1194 ta kilo tovar, is_weight=0
                # → «Tovar topilmadi»). Tovar tarozi PLU'si bilan
                # topiladi — kodi raqamli (00843) yoki plu to'ldirilgan.
                # Chek qatorida «kg» ko'rinishi va tortishlar birlashmasligi
                # uchun tovar nusxasi vaznli qilib qaytariladi.
                if not product.is_weight:
                    if product.plu is None and not (product.code or "").strip().isdigit():
                        # Kodi raqam emas — tarozi tovari emas, tasodif
                        return None
                    product = replace(product, is_weight=True)
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
        self.last_receipt_number = "MoySklad: kutilmoqda"
        self._send_now(local_uuid, payload)

    def _send_now(self, local_uuid: str, payload: dict) -> None:
        """Navbatga yozilgan chekni shu zahoti serverga yuboradi.

        Onlayn bo'lsa Отгрузка darhol yaratiladi va MoySklad bergan haqiqiy
        raqam qog'oz chekda chiqadi. So'rov yo'lda uzilsa chek lokal
        navbatda qoladi; local_uuid tufayli qayta yuborish xavfsiz.

        Yuborish davomida chek `_INFLIGHT` da turadi — fon `flush` uni
        ikkinchi marta yubormaydi.
        """
        with _INFLIGHT_LOCK:
            _INFLIGHT.add(local_uuid)
        try:
            try:
                resp = self.hub.send_sale(payload)
            except (HubConnError, HubAuthError) as e:
                self.store.note_outage(local_uuid, str(e))
                return
            except HubError as e:
                self.store.mark_failed(local_uuid, str(e))
                return
            except Exception as e:
                # Buzuq/kutilmagan javobda ham diskka yozilgan chek yo'qolmaydi
                # va kassir uni ikkinchi marta urib yubormaydi.
                self.store.note_outage(local_uuid, str(e))
                return

            check_no = resp.get("id") if isinstance(resp, dict) else None
            official = resp.get("receipt_number") if isinstance(resp, dict) else None
            self.store.mark_sent(local_uuid, check_no, official)
            if official:
                self.last_receipt_number = official
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.discard(local_uuid)

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
        # Bu oynada pul qaytariladi; yangi 0 summali qaytarish yaratilmaydi.
        # Eski cheklar esa cleanup vaqtida tovar harakati bilan tekshiriladi.
        if (not payload["items"] or is_junk_receipt(payload) or
                (payload["net_total"] == 0 and any("refund_total" not in row["item"] or not row["item"].get("origin_item_id") for row in lines))):
            raise HubError("Qaytarish summasi 0 — hech nima qaytarilmadi")
        self._bind_shift(payload)

        self.store.queue(local_uuid, payload, created_at)
        self.last_receipt_number = "MoySklad: kutilmoqda"
        self.last_return_uuid = local_uuid
        return payload["net_total"]

    def local_returned(self, origin_id) -> dict:
        """Shu chek uchun navbatда turgan (hali serverга yetmagan)
        qaytarishlar — tovar bo'yicha jami miqdor. Server buni hali
        bilmaydi; qaytadan qaytarib yuborilmasin uchun ayiramiz."""
        agg: dict = {}
        for pl in self.store.outbox_returns():
            if pl.get("origin_id") != origin_id:
                continue
            for it in pl.get("items", []):
                key = it.get("ms_product_id") or it.get("name")
                agg[key] = agg.get(key, 0) + float(it.get("quantity") or 0)
        return agg

    def returnable_sales(self, query="", offset=0) -> list[dict]:
        sales = self.hub.returnable_sales(query, offset)
        pending = self.store.outbox_returns()
        for sale in sales:
            for payload in pending:
                if payload.get("origin_id") != sale["id"]:
                    continue
                for returned in payload.get("items", []):
                    candidates = [it for it in sale["items"] if
                        (it.get("origin_item_id") == returned.get("origin_item_id")
                         if returned.get("origin_item_id") else
                         (it.get("ms_product_id") or it["name"]) ==
                         (returned.get("ms_product_id") or returned.get("name")))]
                    if len(candidates) != 1:
                        sale["return_error"] = "Mahalliy qaytarishni menejer tekshirishi kerak"
                        continue
                    item = candidates[0]
                    item["returned_qty"] = str(Decimal(str(item.get("returned_qty") or 0)) + Decimal(str(returned["quantity"])))
                    item["returned_total"] = int(item.get("returned_total") or 0) + int(returned.get("total") or 0)
        return sales

    def cash(self, kind: str, amount: int, comment: str = "") -> dict:
        """Kassaga pul kiritish / kassadan chiqarish.

        Chek bilan bir xil yo'l: avval diskka, keyin serverga. Internet
        yo'q bo'lsa amal navbatda qoladi — kassir ishini davom ettiradi va
        smenani ham yopa oladi. Ulanish tiklanganda amal o'z smenasiga
        yoziladi (`local_uuid` tufayli ikki marta yozilmaydi).

        Ilgari amal faqat serverга yuborilardi va tarmoq uzilsa
        «tasdiqlanmagan» bayrog'i qolib, smena umuman yopilmay qolardi.
        """
        self._adopt_stuck_cash()
        local_uuid = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "kind": kind, "amount": int(amount), "comment": comment,
            "local_uuid": local_uuid, "created_at": created_at,
            "shift_id": self.store.get("active_shift_id") or None,
        }
        self.store.queue_cash(local_uuid, payload, created_at)
        try:
            result = self.hub.cash(**payload)
        except HubConnError as e:
            # Internet yo'q — navbatда qoladi, xato ko'rsatilmaydi.
            self.store.note_cash_error(local_uuid, str(e))
            return {"queued": True, "offline": True}
        except HubError as e:
            # Server RAD etdi (masalan ochiq smena yo'q) — qayta urinmaymiz,
            # aks holda navbat to'silib qolardi. Kassir xatoni ko'radi.
            self.store.discard_cash(local_uuid, str(e))
            raise
        self.store.mark_cash_sent(local_uuid)
        return result

    def _adopt_stuck_cash(self) -> None:
        """Eski usulda tiqilib qolgan pul amalini navbatга ko'chiradi.

        1.17.17 gacha tarmoq uzilsa `pending_cash_operation` bayrog'i
        o'chmay qolardi va smena yopilmasdi. Yangilangan kassa shu
        amalni navbatга olib, bayroqni tozalaydi — eski tiqilish o'zi
        yechiladi.
        """
        raw = self.store.get("pending_cash_operation")
        if not raw:
            return
        try:
            old = json.loads(raw)
        except (ValueError, TypeError):
            self.store.set("pending_cash_operation", "")
            return
        key = str(old.get("local_uuid") or uuid.uuid4())
        old.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        self.store.queue_cash(key, old, old["created_at"])
        self.store.set("pending_cash_operation", "")
        logger.info("Tiqilib qolgan pul amali navbatga ko'chirildi: %s", key)

    def flush_cash(self) -> int:
        """Navbatdagi pul amallarini yuboradi. Yuborilgan sonini qaytaradi.

        Cheklardan KEYIN, smenani yopishdan OLDIN chaqiriladi — shunda
        amal o'zining ochiq smenasiga tushadi.
        """
        self._adopt_stuck_cash()
        sent = 0
        for row in self.store.pending_cash():
            payload = json.loads(row["payload"])
            try:
                self.hub.cash(**payload)
            except HubConnError as e:
                self.store.note_cash_error(row["local_uuid"], str(e))
                break          # internet yo'q — qolganini ham urinmaymiz
            except HubError as e:
                self.store.discard_cash(row["local_uuid"], str(e))
                logger.warning("Pul amali rad etildi: %s", e)
                continue
            self.store.mark_cash_sent(row["local_uuid"])
            sent += 1
        return sent

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
        if self.store.closed_shifts():
            # Oldingi smena hali serverda yopilmagan — yangisini ochsak
            # server uni eski smena deb qaytarardi.
            return None
        local = self.store.get_local_shift()
        if not local:
            return None
        if local.get("server_id") or not local.get("local_uuid"):
            # Serverда allaqachon bor (yoki onlayn ochilgan) — bu yerda
            # ish yo'q. Yopilishi kutilayotgan bo'lsa `sync_shift_close`
            # navbatlar bo'shagach yopadi.
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
        # Serverga ochildi. Navbatdagi cheklar shu ochiq smenaga tushadi.
        self.store.set("active_shift_id", str(sh["id"]))
        if local.get("closed_at"):
            # Smena internetsiz YOPILGAN ham edi — belgini saqlaymiz,
            # cheklar va pul amallari ketgandan keyin serverда yopamiz.
            local["server_id"] = sh["id"]
            self.store.set_local_shift(local)
        else:
            self.store.set_local_shift(None)
        logger.info("Internetsiz ochilgan smena serverга sinxronlandi: #%s",
                    sh.get("number"))
        return sh

    # ------------------------------------------------ smenani yopish

    def mark_shift_closed(self, closed_at: str, counted_cash=None) -> None:
        """Smenani MAHALLIY yopiq deb belgilaydi (internet yo'q paytda).

        Yopilgan smena alohida navbatga tushadi — kassir keyingi smenani
        ocha oladi, oldingisi esa internet qaytganda o'z vaqti bilan
        serverda yopiladi.

        Onlayn ochilgan smena uchun ham ishlaydi: o'shanda mahalliy yozuv
        yo'q edi, shu yerda server id si bilan yaratiladi.
        """
        local = self.store.get_local_shift()
        if not local:
            server_id = self.store.get("active_shift_id")
            local = {
                "local_uuid": "",
                "server_id": int(server_id) if server_id else None,
                "opened_at": "",
                "opening_cash": 0,
            }
        local["closed_at"] = closed_at
        local["counted_cash"] = counted_cash
        local["shift_tag"] = self.store.get("history_shift_tag") or ""
        self.store.add_closed_shift(local)
        self.store.set_local_shift(None)

    def sync_shifts(self) -> None:
        """Smenalarni server bilan moslaydi — QAT'IY TARTIBDA.

        Avval internetsiz yopilgan smenalar (eng eskisidan): serverda
        ochiladi, cheklari ketguncha kutiladi, keyin yopiladi. Shundan
        keyingina yangi smena ochiladi.

        Tartib muhim: serverda bir kassada bitta ochiq smena bo'ladi.
        Yangi smenani oldingisi yopilmasdan ochsak, server uni eski ochiq
        smena deb qaytaradi va ikkalasining cheklari aralashib ketardi.
        """
        for record in list(self.store.closed_shifts()):
            if not self._sync_one_closed(record):
                return          # internet yo'q yoki cheklari hali ketmagan
        self.sync_shift()

    def _sync_one_closed(self, record: dict) -> bool:
        """Bitta yopilgan smenani serverga o'tkazadi. Tugasa True."""
        if record.get("local_uuid") and not record.get("server_id"):
            try:
                sh = self.hub.open_shift(
                    record.get("cashier_id", 0),
                    int(record.get("opening_cash") or 0),
                    local_uuid=record["local_uuid"],
                    opened_at=record.get("opened_at", ""),
                )["shift"]
            except HubConnError:
                return False
            except HubError as e:
                logger.warning("Yopilgan smena ochilmadi: %s", e)
                return False
            record["server_id"] = sh["id"]
            self.store.set("active_shift_id", str(sh["id"]))
            self._save_closed(record)

        # Cheklari va pul amallari ketmaguncha yopmaymiz — aks holda
        # serverdagi hisobot kassadagidan kam chiqadi.
        tag = record.get("shift_tag", "")
        if tag and (self.store.pending_for_tag(tag)
                    or self.store.pending_cash_for_tag(tag)):
            return False

        try:
            self.hub.close_shift(
                record.get("counted_cash"),
                closed_at=record.get("closed_at", ""),
                local_uuid=record.get("local_uuid", ""),
            )
        except HubConnError:
            return False
        except HubError as e:
            # Masalan «allaqachon yopilgan» — qayta urinishning ma'nosi
            # yo'q, navbatdan chiqaramiz (aks holda har flushda takrorlanardi).
            logger.warning("Smena serverda yopilmadi: %s", e)
        self._drop_closed(record)
        if self.store.get("active_shift_id") == str(record.get("server_id") or ""):
            self.store.set("active_shift_id", "")
        logger.info("Internetsiz yopilgan smena serverga sinxronlandi")
        return True

    def _save_closed(self, record: dict) -> None:
        items = self.store.closed_shifts()
        for i, item in enumerate(items):
            if item.get("closed_at") == record.get("closed_at"):
                items[i] = record
                break
        self.store.set_closed_shifts(items)

    def _drop_closed(self, record: dict) -> None:
        items = [i for i in self.store.closed_shifts()
                 if i.get("closed_at") != record.get("closed_at")]
        self.store.set_closed_shifts(items)

    def finish_shift(self, counted_cash, local_text: str | None = None) -> dict:
        """Smenani yopadi. Internet bo'lsa serverда, bo'lmasa mahalliy.

        Nomi `close_shift` EMAS — o'sha nomni oyna o'zining tugma
        funksiyasi uchun ishlatadi (`backend.close_shift = close_shift`,
        pos/main.py). 1.18.0 da ikkalasi to'qnashib, yopish tugmasi
        jimgina ishlamay qolgan edi.

        `local_text` — internetsiz holat uchun tayyor hisobot matni. Uni
        oyna chizadi (chek kengligi va do'kon nomi o'shanda), bu yer
        faqat qaysi yo'ldan borishni hal qiladi.
        """
        try:
            return self.hub.close_shift(counted_cash)
        except HubConnError as e:
            if local_text is None:
                raise
            logger.info("Smena internetsiz yopilyapti (server yo'q: %s)", e)
        # Server RAD etgan bo'lsa (oddiy HubError) bu yerга yetib kelmaymiz —
        # kassirga sabab ko'rsatiladi. Faqat tarmoq uzilganda mahalliy yopamiz.
        closed_at = datetime.now(timezone.utc).isoformat()
        self.mark_shift_closed(closed_at, counted_cash)
        return {"receipt_text": local_text, "offline": True, "closed_at": closed_at}

    def discard_empty_receipts(self) -> int:
        """Eski bo'sh yozuvlarni ham ko'radi; tarmoq va retry limitiga bog'liq emas."""
        count = 0
        for row in self.store.unsent_rows():
            try:
                payload = json.loads(row["payload"])
            except (ValueError, TypeError):
                continue
            if is_junk_receipt(payload):
                self.store.discard(row["local_uuid"], "Bo'sh chek — tovar, pul va ball yo'q")
                count += 1
        return count

    def flush(self, limit: int = 50) -> int:
        """Navbatdagi cheklarni yuboradi. Yuborilganlar sonini qaytaradi.

        Avval mahalliy smena bo'lsa uni serverга ochamiz — aks holda
        cheklar «ochiq smena yo'q» bilan qaytadi.
        """
        # pending() retry limiti tugagan yozuvlarni olmaydi. Ular ham
        # unsent_count() orqali smenani yopishga to'sqinlik qilishi mumkin.
        self.discard_empty_receipts()
        self.sync_shifts()
        sent = 0
        for row in self.store.pending(limit):
            # Shu chek hozir `submit` ichida yuborilyapti — tegmaymiz.
            with _INFLIGHT_LOCK:
                if row["local_uuid"] in _INFLIGHT:
                    continue
            payload = json.loads(row["payload"])
            # Bo'sh (0 summali) chek — serverга umuman yubormaymiz. Aks holda
            # server uni rad etib turadi, kassa cheksiz qayta urinadi va
            # «navbatда 1 chek» xabari hech ketmaydi. Chetга chiqaramiz.
            if is_junk_receipt(payload):
                self.store.discard(row["local_uuid"], "Bo'sh (0 summali) chek — yuborilmadi")
                continue
            try:
                resp = self.hub.send_sale(payload)
            except (HubConnError, HubAuthError) as e:
                # Ulanish yoki token xatosi — sabab UMUMIY (internet yo'q
                # yoki kassa uzilgan). Qolganini urinishning ma'nosi yo'q,
                # to'xtaymiz.
                self.store.note_outage(row["local_uuid"], str(e))
                break
            except HubError as e:
                # A rejected genuine return remains visible and retryable.
                # Only proven empty receipts may be discarded automatically.
                if is_junk_receipt(payload):
                    self.store.discard(row["local_uuid"], str(e))
                else:
                    self.store.mark_failed(row["local_uuid"], str(e))
                continue
            else:
                check_no = resp.get("id") if isinstance(resp, dict) else None
                official = resp.get("receipt_number") if isinstance(resp, dict) else None
                self.store.mark_sent(row["local_uuid"], check_no, official)
                sent += 1
        # Cheklardan keyin pul amallari (smena hali ochiq), keyin yopish.
        self.flush_cash()
        self.sync_shifts()
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
