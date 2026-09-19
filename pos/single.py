"""Bitta kompyuterda — bitta nusxa.

Nega kerak (2026-09-19): dastur og'ir (~50 MB) va ochilishi bir necha
soniya oladi. Kassir ekranda hech narsa ko'rmagach yana bosadi, yana
bosadi — va ikkinchi, uchinchi nusxa ochiladi. Ikkala nusxa bitta
`kassa.db` ga yozadi va har biri o'z smena holatini yuritadi; shu tufayli
chek boshqa smenaga tushib qolishi mumkin.

Ikkinchi nusxa ochilganda: birinchisining oynasi oldinga chiqariladi va
ikkinchisi jimgina yopiladi. Kassir uchun bu «bosdim — oyna chiqdi» bo'lib
ko'rinadi.

Windows'da nomlangan muteks ishlatiladi: dastur qanday tugasa ham (hatto
o'chib qolsa ham) operatsion tizim uni o'zi bo'shatadi, shuning uchun
«qolib ketgan qulf» muammosi bo'lmaydi. Boshqa tizimlarda (testlar
Linux'da ishlaydi) — fayl qulfi.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

#: Windows: CreateMutexW shu xatoni beradi — muteks allaqachon bor
_ERROR_ALREADY_EXISTS = 183

#: Qulf ushlab turiladigan joy. Modul darajasida — tozalanib ketmasin.
_holder = None


def _lock_path(name: str):
    from .config import config_dir

    return config_dir() / f"{name}.lock"


def _acquire_windows(name: str) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32           # type: ignore[attr-defined]
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    if not handle:
        return True                              # muteks yaratilmadi — to'smaymiz
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    global _holder
    _holder = handle
    return True


def _acquire_posix(name: str) -> bool:
    import fcntl

    path = _lock_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "w")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    global _holder
    _holder = handle
    return True


def acquire(name: str = "SevimliKassa") -> bool:
    """True — biz yagona nusxamiz. False — boshqa nusxa ishlab turibdi.

    Qulf olinmagan bo'lsa ham dastur yiqilmaydi: kutilmagan xatoda True
    qaytaramiz (ya'ni to'smaymiz) — qulf tufayli kassa ochilmay qolgandan
    ko'ra ikkita oyna kamroq zarar.
    """
    try:
        if sys.platform.startswith("win"):
            return _acquire_windows(name)
        return _acquire_posix(name)
    except Exception as e:  # noqa: BLE001
        logger.warning("Yagona nusxa qulfi ishlamadi: %s", e)
        return True


def release() -> None:
    """Qulfni bo'shatadi (asosan testlar uchun — odatda OS o'zi qiladi)."""
    global _holder
    holder, _holder = _holder, None
    if holder is None:
        return
    try:
        if sys.platform.startswith("win"):
            import ctypes

            ctypes.windll.kernel32.CloseHandle(holder)  # type: ignore[attr-defined]
        else:
            holder.close()
    except Exception:  # noqa: BLE001
        pass


def raise_existing_window(prefix: str = "Sevimli Kassa") -> bool:
    """Ishlab turgan nusxaning oynasini oldinga chiqaradi.

    Sarlavha «Sevimli Kassa — <nuqta> · <kassa>» ko'rinishida bo'lgani
    uchun aniq nom bilan emas, boshi bo'yicha qidiriladi. Faqat
    Windows'da ishlaydi; topilmasa yoki xato bo'lsa — False.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32            # type: ignore[attr-defined]
        found: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def check(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.startswith(prefix):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(check, 0)
        if not found:
            return False
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)               # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Oynani oldinga chiqarib bo'lmadi: %s", e)
        return False
