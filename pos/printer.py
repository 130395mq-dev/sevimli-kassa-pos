"""
Chekni printerga yuborish.

Chek — oddiy matn (`shared/receipt.py` tayyorlaydi). Termal (80mm/58mm)
printerlar matnni ESC/POS buyruqlari bilan to'g'ridan-to'g'ri qabul qiladi.

**Ikki yo'l:**
  1) RAW ESC/POS (Windows, `win32print`) — TANLANGAN printerga to'g'ridan-to'g'ri
     yuboradi. "Asosiy printer" ga bog'liq emas, Notepad ochilmaydi, hoshiya
     yo'q, oxirida qog'ozni o'zi kesadi. Bu asosiy va ishonchli yo'l.
  2) Zaxira — `win32print` bo'lmasa yoki xato bersa: matnni faylga yozib,
     Windows'ning oddiy chop etishiga beradi.

**Muhim:** chop etish muvaffaqiyatsiz bo'lsa ham chek yo'qolmaydi — matn
har doim faylga yoziladi (arxiv), kassir keyin qayta chiqara oladi.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# win32print bor-yo'qligini bir marta tekshiramiz (faqat Windows'da bo'ladi)
try:  # pragma: no cover - platformaga bog'liq
    import win32print  # type: ignore

    _HAS_WIN32 = True
except Exception:  # pragma: no cover
    win32print = None  # type: ignore
    _HAS_WIN32 = False


# ------------------------------------------------------------------ ESC/POS
ESC = b"\x1b"
GS = b"\x1d"
#: Dasturni boshlang'ich holatga keltirish (ESC @)
INIT = ESC + b"@"
#: Kod sahifasi PC866 (rus harflari ham chiqadi). Lotin — baribir ASCII.
CODEPAGE_866 = ESC + b"t\x11"
#: Xitoy/yapon (Kanji) rejimini O'CHIRADI — FS «.»
#:
#: MUHIM (2026-09-18): ko'p arzon termal printerlar (Xprinter, Rongta va h.k.)
#: zavoddan «Chinese mode» yoqilgan holda keladi yoki o'chib-yonganda shu
#: rejimga qaytadi. Unda 0x80—0xFF baytlari ikki baytli ieroglif deb
#: o'qiladi va kirill tovar nomlari chekda koreys/xitoy harflariga
#: aylanadi. FS «.» shu rejimni o'chiradi; CJK'ni bilmaydigan printer bu
#: buyruqni e'tiborsiz qoldiradi — zarari yo'q.
CANCEL_CJK = b"\x1c\x2e"
#: Xalqaro belgilar to'plami — АҚШ (ESC R 0). Ba'zi printerlarda boshqa
#: to'plam yoqilgan bo'lsa «#», «$» kabi belgilar boshqacha chiqadi.
INTL_USA = ESC + b"R\x00"
#: Qog'ozni qisman kesish (GS V 66 0) — ko'p printerlar tushunadi
CUT = GS + b"V\x42\x00"
#: Kesishdan oldin qog'oz chiqarish uchun bo'sh qatorlar
FEED = b"\n\n\n\n"

#: Markazga tekislash / chapga (logo markazда bo'lsin uchun)
ALIGN_CENTER = ESC + b"a\x01"
ALIGN_LEFT = ESC + b"a\x00"
#: Teskari (oq-qora) rejim — GS B n. Yoqilса: oq matn qora fonда.
REVERSE_ON = GS + b"B\x01"
REVERSE_OFF = GS + b"B\x00"

#: Chek pastидagi «rahmat» — uch tilда (oq-qora bar bo'lib chiqadi).
THANK_YOU = [
    "Xaridingiz uchun rahmat!",
    "Spasibo za pokupku!",
    "Thank you for your purchase!",
]


def _logo_bytes(paper: str) -> bytes:
    """Chek tepasидаги logo — oldindan tayyorlangan ESC/POS raster."""
    try:
        from .receipt_logo import LOGO_58, LOGO_80
        return LOGO_58 if str(paper) == "58" else LOGO_80
    except Exception:  # logo moduli yo'q bo'lsa — logosиз davom etadi
        return b""


def _autumn_bytes(paper: str) -> bytes:
    """Chek tepasidagi kuzgi barglar bezagi (logo ustiga)."""
    try:
        from .receipt_autumn import AUTUMN_58, AUTUMN_80
        return AUTUMN_58 if str(paper) == "58" else AUTUMN_80
    except Exception:
        return b""


def _thanks_bytes(paper: str) -> bytes:
    """Pastдаги «rahmat» bar — chiroyli shrift bilan chizilgan ESC/POS
    raster (oq matn, qora fon, uch til). Oldindan tayyorlangan."""
    try:
        from .receipt_thanks import THANKS_58, THANKS_80
        return THANKS_58 if str(paper) == "58" else THANKS_80
    except Exception:
        return b""


def _thank_you_bar(width: int) -> bytes:
    """Uch tilдаги rahmatни oq-qora (teskari) bar qilib chiqaradi.

    Har qator butun kenglikка probel bilan to'ldiriladi — shunда teskari
    rejimда butun qator qora bo'lib, o'rtasида oq matn turadi (uzun bar).
    """
    out = bytearray()
    out += ALIGN_LEFT
    # Tepа-past bo'sh (qora) qator — bar qalinroq ko'rinsin
    pad = " " * width
    lines = [pad] + [t.center(width)[:width] for t in THANK_YOU] + [pad]
    for ln in lines:
        out += REVERSE_ON + _encode(ln) + REVERSE_OFF + b"\r\n"
    return bytes(out)


def print_sale(text: str, printer: str = "", paper: str = "80",
               width: int = 48, name: str = "chek") -> tuple[bool, Path]:
    """Mijoz chekини chiroyli chop etadi: tepада logo, matn, pastда uch
    tilдаги oq-qora «rahmat» bar. RAW ESC/POS ishlamasа — oddiy matn.

    Fayl har holda saqlanadi (chop etilmasа ham chek qoladi).
    """
    # Arxiv/zaxira uchun matn versiyasi — rahmat oddiy matn bilan.
    plain = text + "\n" + "\n".join(_center_txt(t, width) for t in THANK_YOU) + "\n"
    path = save(plain, name)

    try:
        if sys.platform == "win32" and _HAS_WIN32:
            _print_sale_raw(text, printer, paper, width)
        elif sys.platform == "win32":
            _print_windows_fallback(path, printer)
        else:
            _print_unix(path, printer)
    except Exception as e:  # pragma: no cover
        logger.warning("Chek chop etilmadi (%s). Fayl: %s", e, path)
        return False, path
    return True, path


def _center_txt(text: str, w: int) -> str:
    return text.center(w)[:w]


def _printer_settings() -> tuple[int, str]:
    """(kod sahifasi raqami, kodlash) — config.json'dan. Standart: 17/cp866.

    Printer boshqa kod sahifasini kutsa, kassani qayta yig'masdan
    config.json'da `printer_codepage` va `printer_encoding` ni o'zgartirish
    kifoya.
    """
    try:
        from .config import load

        cfg = load()
        page = int(getattr(cfg, "printer_codepage", 17) or 17)
        enc = str(getattr(cfg, "printer_encoding", "") or "cp866")
    except Exception:  # noqa: BLE001 — chop etish hech qachon yiqilmasin
        return 17, "cp866"
    return page & 0xFF, enc


def head_bytes() -> bytes:
    """Har chekdan oldingi sozlash: boshlang'ich holat → CJK rejimini
    o'chirish → xalqaro to'plam → kod sahifasi."""
    page, _ = _printer_settings()
    return INIT + CANCEL_CJK + INTL_USA + ESC + b"t" + bytes([page])


def _print_sale_raw(text: str, printer: str, paper: str, width: int) -> None:  # pragma: no cover
    """RAW ESC/POS: logo + matn + oq-qora rahmat bar."""
    name = printer or default_printer()
    if not name:
        raise RuntimeError("Printer tanlanmagan va asosiy printer ham yo'q")

    autumn = _autumn_bytes(paper)
    logo = _logo_bytes(paper)
    head = head_bytes()
    if autumn or logo:
        head += ALIGN_CENTER
        if autumn:
            head += autumn + b"\n"
        if logo:
            head += logo + b"\n"
        head += ALIGN_LEFT

    # Pastдаги rahmat — chiroyli shrift (raster). Raster bo'lmasa, oddiy
    # oq-qora matn bar bilan almashtiramiz (zaxira).
    thanks = _thanks_bytes(paper)
    if thanks:
        thanks_block = ALIGN_CENTER + thanks + b"\n" + ALIGN_LEFT
    else:
        thanks_block = b"\n" + _thank_you_bar(width)

    data = head + _encode(text) + thanks_block + FEED + CUT

    handle = win32print.OpenPrinter(name)
    try:
        win32print.StartDocPrinter(handle, 1, ("Sevimli chek", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)


#: PC866 kod sahifasida yo'q belgilarni oddiy ASCII'ga almashtiramiz,
#: aks holda ular chekda "?" bo'lib chiqadi.
_PUNCT = {
    "—": "-", "–": "-",      # — –  tire
    "’": "'", "‘": "'",      # ' '  apostrof
    "“": '"', "”": '"',      # " "  qo'shtirnoq
    "«": '"', "»": '"',      # « »  qo'shtirnoq (rus/uz)
    "‹": "'", "›": "'",
    "…": "...",                    # …
    "•": "*", "·": "*",      # •  ·
    " ": " ",                      # ajratmaydigan probel
    "−": "-",                      # minus
}


def _encode(text: str) -> bytes:
    """Chek matnini printer tushunadigan baytlarga o'giradi (PC866)."""
    for bad, good in _PUNCT.items():
        text = text.replace(bad, good)
    _, enc = _printer_settings()
    try:
        return text.replace("\n", "\r\n").encode(enc, errors="replace")
    except LookupError:      # config.json'da noto'g'ri kodlash yozilgan
        return text.replace("\n", "\r\n").encode("cp866", errors="replace")


def archive_dir() -> Path:
    from .config import config_dir

    path = config_dir() / "cheklar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(text: str, name: str = "chek") -> Path:
    """Chekni faylga yozadi va yo'lini qaytaradi (arxiv)."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = archive_dir() / f"{name}-{stamp}.txt"
    # Windows'da Notepad CRLF kutadi
    path.write_text(text.replace("\n", "\r\n"), encoding="utf-8-sig")
    return path


# ------------------------------------------------------------------ printerlar ro'yxati
def list_printers() -> list[str]:
    """O'rnatilgan printerlar nomlari. Sozlamalar oynasidagi ro'yxat uchun."""
    if _HAS_WIN32:
        try:  # pragma: no cover
            flags = (
                win32print.PRINTER_ENUM_LOCAL
                | win32print.PRINTER_ENUM_CONNECTIONS
            )
            return [p[2] for p in win32print.EnumPrinters(flags)]
        except Exception as e:  # pragma: no cover
            logger.warning("Printerlar ro'yxati olinmadi: %s", e)
            return []
    # Zaxira: PowerShell orqali (win32print bo'lmasa)
    if sys.platform == "win32":  # pragma: no cover
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Printer | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return [x.strip() for x in out.stdout.splitlines() if x.strip()]
        except Exception:
            return []
    return []


def default_printer() -> str:
    """Windows'ning asosiy printeri nomi (agar tanlanmagan bo'lsa)."""
    if _HAS_WIN32:
        try:  # pragma: no cover
            return win32print.GetDefaultPrinter() or ""
        except Exception:
            return ""
    return ""


# ------------------------------------------------------------------ chop etish
def print_text(text: str, printer: str = "", name: str = "chek") -> tuple[bool, Path]:
    """Chekni chop etadi. `(chop_etildimi, fayl_yoli)` qaytadi.

    Fayl har holda yoziladi — chop etish ishlamasa ham chek qoladi.
    """
    path = save(text, name)

    try:
        if sys.platform == "win32":
            if _HAS_WIN32:
                _print_raw(text, printer)
            else:
                _print_windows_fallback(path, printer)
        else:
            _print_unix(path, printer)
    except Exception as e:
        logger.warning("Chek chop etilmadi (%s). Fayl: %s", e, path)
        return False, path

    return True, path


def _print_raw(text: str, printer: str) -> None:  # pragma: no cover
    """RAW ESC/POS — tanlangan printerga to'g'ridan-to'g'ri yuboradi."""
    name = printer or default_printer()
    if not name:
        raise RuntimeError("Printer tanlanmagan va asosiy printer ham yo'q")

    data = head_bytes() + _encode(text) + FEED + CUT

    handle = win32print.OpenPrinter(name)
    try:
        win32print.StartDocPrinter(handle, 1, ("Sevimli chek", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)


def _print_windows_fallback(path: Path, printer: str) -> None:
    if printer:
        subprocess.run(
            ["cmd", "/c", "print", f"/D:{printer}", str(path)],
            check=True, capture_output=True, timeout=20,
        )
        return
    os.startfile(str(path), "print")  # type: ignore[attr-defined]


def _print_unix(path: Path, printer: str) -> None:
    cmd = ["lp"]
    if printer:
        cmd += ["-d", printer]
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True, timeout=20)
